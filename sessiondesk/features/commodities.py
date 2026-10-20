"""Commodities & energy: futures prices by group (free daily closes), plus the free fundamental data the hub collects
(EIA oil stocks and gas storage, European power prices, EU gas imports by route from ENTSOG, EU gas storage from
GIE AGSI+ with the user's free key), plus the sources that can be connected for more (free keys or paid).
"""
from __future__ import annotations

import time

from .datahub import AGSI_CATEGORY, AGSI_SCOPES, ENTSOG_CATEGORY, ENTSOG_LNG, ENTSOG_ROUTES, source_url
from .sectors import returns

GROUPS = [
    ("Energy", [("CL=F", "WTI crude"), ("BZ=F", "Brent crude"), ("NG=F", "US natural gas (Henry Hub)"), ("TTF=F", "EU natural gas (Dutch TTF)"),
                ("RB=F", "Gasoline (RBOB)"), ("HO=F", "Heating oil / diesel"), ("URA", "Uranium miners (ETF)")]),
    ("Metals", [("GC=F", "Gold"), ("SI=F", "Silver"), ("PL=F", "Platinum"), ("PA=F", "Palladium"), ("HG=F", "Copper"), ("ALI=F", "Aluminium")]),
    ("Agriculture", [("ZC=F", "Corn"), ("ZW=F", "Wheat"), ("ZS=F", "Soybeans"), ("KC=F", "Coffee"), ("CC=F", "Cocoa"), ("SB=F", "Sugar"),
                     ("CT=F", "Cotton"), ("OJ=F", "Orange juice"), ("LE=F", "Live cattle"), ("HE=F", "Lean hogs")]),
]
FUNDAMENTAL_CATEGORIES = ("Oil (EIA weekly)", "Gas (EIA weekly)")
POWER_CATEGORY = "Power (day-ahead)"
# display order of the ENTSOG table: total, pipeline routes, LNG total, LNG by country
FLOW_ORDER = (["entsog:total"] + ["entsog:" + k for k, _, _ in ENTSOG_ROUTES] + ["entsog:lng_total"]
              + ["entsog:lng_" + c.lower() for c, _, _ in ENTSOG_LNG])
MORE_SOURCES = [
    ("ENTSO-E Transparency", "free key", "European power: load, generation by fuel, cross-border flows (day-ahead prices are already in via Energy-Charts)"),
    ("USDA NASS / WASDE", "free key", "US crop progress, stocks, supply and demand estimates"),
    ("CME / COMEX warehouse stocks", "free (daily files)", "registered and eligible gold, silver, copper stocks"),
    ("aisstream.io", "free key", "tanker positions (AIS) at chokepoints - Hormuz, Suez, Bab el-Mandeb, Baltic ports"),
    ("Kpler / Vortexa", "paid", "crude and product flows from tracked cargoes"),
    ("LME", "paid", "base metal warehouse stocks and prices"),
]


def _year_ago(pts: list[tuple[str, float]]) -> float | None:
    """Value on the last day at or before the same calendar day one year earlier (pure)."""
    import datetime as dt
    if not pts:
        return None
    target = (dt.date.fromisoformat(pts[-1][0]) - dt.timedelta(days=365)).isoformat()
    older = [v for d, v in pts if d <= target]
    return older[-1] if older and pts[0][0] <= target else None


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
    fundamentals, power, flows = [], [], []
    storage: dict[str, dict] = {}
    for s in await ctx.db.run(ctx.db.series_list):
        if s["category"] == ENTSOG_CATEGORY:
            pts = await ctx.db.run(ctx.db.observations, s["id"], 400)
            if pts:
                vals = [v for _, v in pts]
                flows.append({**s, "url": source_url(s["id"]), "last": vals[-1], "day": pts[-1][0],
                              "prev": vals[-2] if len(vals) > 1 else None,
                              "avg30": sum(vals[-31:-1]) / len(vals[-31:-1]) if len(vals) > 30 else None,
                              "year_ago": _year_ago(pts), "spark": vals[-60:]})
            continue
        if s["category"] == AGSI_CATEGORY:
            code, field = s["id"].split(":")[1:3]
            pts = await ctx.db.run(ctx.db.observations, s["id"], 400)
            if pts:
                row = storage.setdefault(code, {"code": code, "url": source_url(s["id"])})
                row[field] = pts[-1][1]
                if field == "full":
                    row.update({"id": s["id"], "day": pts[-1][0], "full_prev": pts[-2][1] if len(pts) > 1 else None,
                                "full_year_ago": _year_ago(pts), "spark": [v for _, v in pts[-60:]]})
            continue
        if s["category"] == POWER_CATEGORY:
            pts = await ctx.db.run(ctx.db.observations, s["id"], 400)
            if pts:
                vals = [v for _, v in pts]
                power.append({**s, "url": source_url(s["id"]), "last": vals[-1], "day": pts[-1][0],
                              "prev": vals[-2] if len(vals) > 1 else None,
                              "avg30": sum(vals[-31:-1]) / len(vals[-31:-1]) if len(vals) > 30 else None,
                              "avg365": sum(vals[-366:-1]) / len(vals[-366:-1]) if len(vals) > 300 else None,
                              "spark": vals[-60:]})
            continue
        if s["category"] in FUNDAMENTAL_CATEGORIES:
            pts = await ctx.db.run(ctx.db.observations, s["id"], 60)
            if pts:
                fundamentals.append({**s, "url": source_url(s["id"]), "last": pts[-1][1], "day": pts[-1][0], "prev": pts[-2][1] if len(pts) > 1 else None,
                                     "change": pts[-1][1] - pts[-2][1] if len(pts) > 1 else None})
    order = {sid: i for i, sid in enumerate(FLOW_ORDER)}
    flows.sort(key=lambda r: order.get(r["id"], len(order)))
    names = dict(AGSI_SCOPES)
    gas_storage = [{**storage[c.lower()], "name": names[c]} for c, _ in AGSI_SCOPES if c.lower() in storage and "full" in storage[c.lower()]]
    agsi = ctx.hub.get("agsi")
    agsi_state = {"configured": bool(agsi and agsi.configured()), "active": bool(agsi and agsi.active()),
                  "verified": bool(agsi and agsi.verified)}
    return {**prices, "fundamentals": fundamentals, "power": power, "gas_flows": flows, "gas_storage": gas_storage, "agsi": agsi_state,
            "more_sources": [{"name": n, "access": a, "what": w} for n, a, w in MORE_SOURCES],
            "note": "Front-month futures (rolling contracts jump at expiry) and one uranium ETF, free daily closes. Inventories from the "
                    "EIA weekly reports; their history in SessionDesk starts with the first collection."}
