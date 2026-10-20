"""Commodities & energy: futures prices by group (free daily closes), plus the free fundamental data the hub collects
(EIA oil stocks and gas storage), plus the sources that can be connected for more (free keys or paid).
"""
from __future__ import annotations

import time

from .sectors import returns

GROUPS = [
    ("Energy", [("CL=F", "WTI crude"), ("BZ=F", "Brent crude"), ("NG=F", "US natural gas (Henry Hub)"), ("TTF=F", "EU natural gas (Dutch TTF)"),
                ("RB=F", "Gasoline (RBOB)"), ("HO=F", "Heating oil / diesel"), ("URA", "Uranium miners (ETF)")]),
    ("Metals", [("GC=F", "Gold"), ("SI=F", "Silver"), ("PL=F", "Platinum"), ("PA=F", "Palladium"), ("HG=F", "Copper"), ("ALI=F", "Aluminium")]),
    ("Agriculture", [("ZC=F", "Corn"), ("ZW=F", "Wheat"), ("ZS=F", "Soybeans"), ("KC=F", "Coffee"), ("CC=F", "Cocoa"), ("SB=F", "Sugar"),
                     ("CT=F", "Cotton"), ("OJ=F", "Orange juice"), ("LE=F", "Live cattle"), ("HE=F", "Lean hogs")]),
]
FUNDAMENTAL_CATEGORIES = ("Oil (EIA weekly)", "Gas (EIA weekly)")
MORE_SOURCES = [
    ("ENTSO-E Transparency", "free key", "European power: day-ahead prices, load, generation by fuel, cross-border flows"),
    ("GIE AGSI+", "free key", "European gas storage per country and site (fill level, injection, withdrawal)"),
    ("ENTSOG Transparency", "free", "European gas pipeline flows per entry/exit point"),
    ("USDA NASS / WASDE", "free key", "US crop progress, stocks, supply and demand estimates"),
    ("CME / COMEX warehouse stocks", "free (daily files)", "registered and eligible gold, silver, copper stocks"),
    ("aisstream.io", "free key", "tanker positions (AIS) at chokepoints - Hormuz, Suez, Bab el-Mandeb, Baltic ports"),
    ("Kpler / Vortexa", "paid", "crude and product flows from tracked cargoes"),
    ("LME", "paid", "base metal warehouse stocks and prices"),
]


async def board(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        syms = [s for _, items in GROUPS for s, _ in items]
        data = await yahoo.daily_series(syms, "2y")
        out = []
        for g, items in GROUPS:
            rows = []
            for sym, name in items:
                pts = data.get(sym)
                if pts:
                    rows.append({"symbol": sym, "name": name, "last": pts[-1][1], "day": pts[-1][0], **returns(pts),
                                 "spark": [v for _, v in pts[-60:]]})
            out.append({"group": g, "rows": rows})
        return {"groups": out, "asof": time.time()}
    prices = await ctx.cache.get("commodities:board", 900, build)
    fundamentals = []
    for s in await ctx.db.run(ctx.db.series_list):
        if s["category"] in FUNDAMENTAL_CATEGORIES:
            pts = await ctx.db.run(ctx.db.observations, s["id"], 60)
            if pts:
                fundamentals.append({**s, "last": pts[-1][1], "day": pts[-1][0], "prev": pts[-2][1] if len(pts) > 1 else None,
                                     "change": pts[-1][1] - pts[-2][1] if len(pts) > 1 else None})
    return {**prices, "fundamentals": fundamentals, "more_sources": [{"name": n, "access": a, "what": w} for n, a, w in MORE_SOURCES],
            "note": "Front-month futures (rolling contracts jump at expiry) and one uranium ETF, free daily closes. Inventories from the "
                    "EIA weekly reports; their history in SessionDesk starts with the first collection."}
