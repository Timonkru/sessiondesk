"""Asset monitors: everything about one commodity on one page - prices, the futures curve (contango or
backwardation), spreads, inventories and flows from the Data hub, implied volatility, CFTC positioning, the
releases that move it and its headlines. Built from data SessionDesk already collects; the curve reads the
individual contract months from Yahoo (free, delayed).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import re
import time

from . import futures
from .futures import ttf_in_usd_mmbtu

MONTH_CODES = "FGHJKMNQUVXZ"
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# curve: (root, exchange suffix, months ahead of the front, day of month after which the front rolls, allowed months or None)
MONITORS = {
    "oil": {
        "name": "Crude oil", "prices": [("CL=F", "WTI"), ("BZ=F", "Brent"), ("RB=F", "Gasoline (RBOB, $/gal)"), ("HO=F", "Heating oil (ULSD, $/gal)"), ("USO", "USO (ETF)")],
        "curves": [("CL", ".NYM", 1, 20, None, "WTI"), ("BZ", ".NYM", 2, 25, None, "Brent")],
        "spreads": ["brent_wti", "crack_321"],
        "hub": ["eia:crude_oil_stocks_excl_spr", "eia:cushing_crude_stocks", "eia:gasoline_stocks", "eia:distillate_stocks",
                "eia:strategic_petroleum_reserve", "eia:crude_oil_stocks_incl_spr"],
        "iv": "iv:USO", "cot": ["WTI crude"], "tankers": True, "market": "energy",
        "news": r"\boil\b|crude|opec|brent|\bwti\b|refiner|tanker|hormuz",
        "calendar": r"crude|oil|opec|eia",
    },
    "gas": {
        "name": "Natural gas & power", "prices": [("NG=F", "US natural gas (Henry Hub)"), ("TTF=F", "EU natural gas (Dutch TTF)")],
        "curves": [("NG", ".NYM", 1, 25, None, "Henry Hub"), ("TTF", ".NYM", 1, 25, None, "TTF")],
        "spreads": ["ttf_hh"],
        "hub": ["eiagas:lower_48_total", "eiagas:lower_48_total:vs5y", "entsog:total", "entsog:lng_total", "entsog:norway",
                "entsog:turkstream", "power:de-lu", "power:fr", "power:it-north"],
        "hub_prefix": ["agsi:"], "iv": None, "cot": [], "tankers": False, "market": "energy",
        "news": r"natural gas|\blng\b|\bgas\b|\bttf\b|pipeline|power prices?|electricity",
        "calendar": r"natural gas|gas storage",
    },
    "gold": {
        "name": "Gold & precious metals", "prices": [("GC=F", "Gold"), ("SI=F", "Silver"), ("PL=F", "Platinum"), ("GLD", "GLD (ETF)"),
                                                     ("DX-Y.NYB", "US dollar index"), ("^TNX", "US 10y yield")],
        "curves": [("GC", ".CMX", 1, 25, (2, 4, 6, 8, 10, 12), "Gold")],
        "spreads": ["gold_silver"],
        "hub": ["fred:DFII10", "fred:T10YIE", "mkt:DX-Y.NYB", "iv:GLD"],
        "iv": "iv:GLD", "cot": ["Gold", "Silver"], "tankers": False, "market": "metals",
        "news": r"\bgold\b|bullion|silver|precious|central bank buying",
        "calendar": r"cpi|pce|fomc|federal funds|non-farm|payrolls",
    },
}


def contracts(root: str, suffix: str, today: dt.date, offset: int, roll_day: int, allowed=None, n: int = 12) -> list[tuple[str, str]]:
    """The next n contract months as (Yahoo symbol, label), front first (pure, tested)."""
    m = today.month + offset + (1 if today.day >= roll_day else 0)
    y = today.year
    out = []
    while len(out) < n:
        yy, mm = y + (m - 1) // 12, (m - 1) % 12 + 1
        if allowed is None or mm in allowed:
            out.append((f"{root}{MONTH_CODES[mm - 1]}{yy % 100:02d}{suffix}", f"{MONTH_NAMES[mm - 1]} {yy % 100:02d}"))
        m += 1
        if m > today.month + 40:
            break
    return out


def curve_shape(points: list[tuple[str, float | None]]) -> dict | None:
    """Front vs. later contracts in percent: negative = backwardation (later cheaper) (pure, tested).
    Months without a price stay in the list as None, so "6th month" is the 6th contract month, not the 6th price
    Yahoo happened to have (TTF on Yahoo misses most months)."""
    if not points or not points[0][1]:
        return None
    front = points[0][1]
    if sum(1 for _, v in points if v) < 2:
        return None
    at = lambda i: (points[i][1] / front - 1) * 100 if len(points) > i and points[i][1] else None   # noqa: E731
    last = [v for _, v in points if v][-1]
    return {"front": front, "m2": at(1), "m6": at(5), "m12": at(11), "state": "backwardation" if last < front else "contango",
            "months_priced": sum(1 for _, v in points if v), "months": len(points)}


def spreads(keys: list[str], q: dict) -> list[dict]:
    p = lambda s: (q.get(s) or {}).get("price")   # noqa: E731
    out = []
    for k in keys:
        if k == "brent_wti" and p("BZ=F") and p("CL=F"):
            out.append({"name": "Brent minus WTI ($/bbl)", "value": p("BZ=F") - p("CL=F")})
        if k == "crack_321" and p("RB=F") and p("HO=F") and p("CL=F"):
            out.append({"name": "3-2-1 crack spread ($/bbl, refining margin)", "value": (2 * p("RB=F") * 42 + p("HO=F") * 42 - 3 * p("CL=F")) / 3})
        if k == "ttf_hh" and p("TTF=F") and p("NG=F") and p("EURUSD=X"):
            # one unit first: TTF EUR/MWh -> $/MMBtu (the old ratio divided EUR/MWh by $/MMBtu, a number without meaning)
            ttf_usd = ttf_in_usd_mmbtu(p("TTF=F"), p("EURUSD=X"))
            out.append({"name": "TTF converted to $/MMBtu (EUR/MWh x EUR/USD / 3.412)", "value": ttf_usd})
            out.append({"name": "TTF minus Henry Hub ($/MMBtu, front contracts)", "value": ttf_usd - p("NG=F")})
            out.append({"name": "TTF / Henry Hub (both in $/MMBtu)", "value": ttf_usd / p("NG=F")})
        if k == "gold_silver" and p("GC=F") and p("SI=F"):
            out.append({"name": "Gold / silver ratio", "value": p("GC=F") / p("SI=F")})
    return out


def year_ago(points: list[tuple[str, float]]) -> float | None:
    """Value about one year before the last point (nearest observation 330-400 days back) (pure, tested)."""
    if not points:
        return None
    last = dt.date.fromisoformat(points[-1][0])
    best = None
    for d, v in points:
        age = (last - dt.date.fromisoformat(d)).days
        if 330 <= age <= 400 and (best is None or abs(age - 365) < best[0]):
            best = (abs(age - 365), v)
    return best[1] if best else None


async def monitor(ctx, key: str) -> dict:
    spec = MONITORS.get(key)
    if not spec:
        return {"error": "unknown monitor"}
    from .markets import get_quotes
    yahoo = ctx.hub.get("yahoo")
    today = dt.date.today()
    curve_syms = {c[5]: ([(m["symbol"], m["label"]) for m in futures.months(c[0], today, 12)] if c[0] in futures.CONTRACTS
                         else contracts(c[0], c[1], today, c[2], c[3], c[4], 12 if c[4] is None else 6)) for c in spec["curves"]}
    # energy: name the exchange's front contract instead of Yahoo's continuous symbol (futures.py), keep the key for spreads
    fronts = {s: futures.front(s, today) for s, _ in spec["prices"]}
    fetch = [(fronts[s]["symbol"] if fronts[s] else s) for s, _ in spec["prices"]] + (["EURUSD=X"] if "ttf_hh" in spec["spreads"] else [])

    async def curve_data():
        syms = [s for lst in curve_syms.values() for s, _ in lst]
        data = await yahoo.daily_series(syms, "5d")
        out = []
        for name, lst in curve_syms.items():
            pts = [(label, (data.get(s) or [[None, None]])[-1][1]) for s, label in lst]
            out.append({"name": name, "points": [(lb, v) for lb, v in pts if v], "shape": curve_shape(pts)})
        return {"curves": out}

    async def hub_rows():
        series = {s["id"]: s for s in await ctx.db.run(ctx.db.series_list)}
        ids = [i for i in spec["hub"] if i in series] + [i for i in series for p in spec.get("hub_prefix", []) if i.startswith(p)][:8]
        rows = []
        for sid in ids:
            pts = await ctx.db.run(ctx.db.observations, sid, 420)
            if not pts:
                continue
            ya = year_ago(pts)
            rows.append({"id": sid, "name": series[sid]["name"], "last": pts[-1][1], "day": pts[-1][0],
                         "change": pts[-1][1] - pts[-2][1] if len(pts) > 1 else None, "year_ago": ya,
                         "vs_year": (pts[-1][1] - ya) if ya is not None else None, "spark": [v for _, v in pts[-60:]]})
        return rows

    async def headlines():
        from .news import list_news
        d = await list_news(ctx, None, None, None, None, 200, spec["market"])
        rx = re.compile(spec["news"], re.I)
        return [n for n in d.get("items", []) if rx.search(n.get("title", ""))][:12]

    async def releases():
        if "calendar" not in ctx.extras:
            return []
        now = time.time()
        d = await ctx.extras["calendar"].events(now - 7 * 86400, now + 10 * 86400)
        rx = re.compile(spec["calendar"], re.I)
        # no impact filter: the FX calendar rates the EIA inventory reports "low" - for a commodity they are the main release
        return [e for e in d.get("events", []) if rx.search(e.get("title", "")) and e.get("currency") in ("USD", "EUR", "GBP")][-14:]

    async def positioning():
        if not spec["cot"]:
            return []
        from .macro import cot
        d = await cot(ctx)
        return [r for r in d.get("rows", []) if r.get("market") in spec["cot"]]

    async def tankers():
        if not spec["tankers"]:
            return None
        from .tankers import view
        d = await view(ctx)
        return d if d.get("configured") else None

    res = await asyncio.gather(get_quotes(ctx, fetch, intraday=True), curve_data(), hub_rows(),
                               headlines(), releases(), positioning(), tankers(), return_exceptions=True)
    ok = lambda x, d: d if isinstance(x, Exception) else x   # noqa: E731
    q, curves, hub, news, cal, cot_rows, tank = (ok(res[0], {}), ok(res[1], {"curves": []}), ok(res[2], []), ok(res[3], []),
                                                 ok(res[4], []), ok(res[5], []), ok(res[6], None))
    quotes = dict(q.get("quotes", {}))
    for s, fr in fronts.items():                    # the contract's quote under the key the spreads use
        if fr and fr["symbol"] in quotes:
            quotes[s] = {**quotes[fr["symbol"]], "contract": fr["label"], "expiry": fr["expiry"], "unit": fr["unit"],
                         "exchange": fr["contract"], "symbol": fr["symbol"]}
    missing = [s for s, _ in spec["prices"] if (quotes.get(s) or {}).get("price") is None]
    if missing:                                     # e.g. TTF=F has no intraday quote: fall back to the daily closes
        daily = await yahoo.daily_series(missing, "1mo")
        for s in missing:
            pts = daily.get(s) or []
            if len(pts) >= 2:
                quotes[s] = {"price": pts[-1][1], "prev_close": pts[-2][1], "change_pct": (pts[-1][1] / pts[-2][1] - 1) * 100,
                             "spark": [v for _, v in pts[-20:]], "source": "daily close"}
    iv_pts = await ctx.db.run(ctx.db.observations, spec["iv"], 400) if spec["iv"] else []
    return {"key": key, "name": spec["name"],
            "prices": [{"symbol": s, "label": lb, **(quotes.get(s) or {})} for s, lb in spec["prices"]],
            "asof": time.time(),
            "curves": curves["curves"], "spreads": spreads(spec["spreads"], quotes), "hub": hub, "news": news, "calendar": cal,
            "cot": cot_rows, "tankers": tank,
            "iv": {"id": spec["iv"], "last": iv_pts[-1][1], "n": len(iv_pts), "since": iv_pts[0][0]} if iv_pts else None,
            "note": "Futures curve from the individual contract months (Yahoo, delayed): a curve falling into the future = "
                    "backwardation (tight supply now), rising = contango. Inventories and flows are Data hub series with their "
                    "own history and alerts. Positioning: CFTC, Tuesday data published Friday."}
