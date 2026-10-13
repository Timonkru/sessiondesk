"""Macro panel: yield curve, Fed-funds path from futures, volatility structure, positioning, risk appetite.

Descriptive context, not timing tools - each block states its source and sample.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math

MONTH_CODES = "FGHJKMNQUVXZ"
CURVE = [("1m", "DGS1MO"), ("3m", "DGS3MO"), ("6m", "DGS6MO"), ("1y", "DGS1"), ("2y", "DGS2"), ("3y", "DGS3"),
         ("5y", "DGS5"), ("7y", "DGS7"), ("10y", "DGS10"), ("20y", "DGS20"), ("30y", "DGS30")]
EXTRA_SERIES = [("10y real (TIPS)", "DFII10"), ("10y breakeven inflation", "T10YIE"), ("High-yield spread", "BAMLH0A0HYM2"),
                ("Fed funds effective", "DFF")]
RISK_RATIOS = [("High yield vs Treasuries", "HYG", "IEF"), ("Cyclicals vs staples", "XLY", "XLP"),
               ("Small vs large caps", "IWM", "SPY"), ("Copper vs gold", "HG=F", "GC=F"),
               ("High beta vs low vol", "SPHB", "SPLV"), ("Emerging vs developed", "EEM", "EFA"),
               ("Semis vs market", "SOXX", "SPY"), ("Equal vs cap weight", "RSP", "SPY")]


def ff_contracts(today: dt.date, n: int = 10) -> list[tuple[str, str]]:
    out = []
    for k in range(n):
        m, y = (today.month - 1 + k) % 12, today.year + (today.month - 1 + k) // 12
        out.append((f"ZQ{MONTH_CODES[m]}{str(y)[2:]}.CBT", dt.date(y, m + 1, 1).strftime("%b %y")))
    return out


async def rates(ctx) -> dict:
    fred = ctx.hub.get("fred")

    async def build():
        ids = [s for _, s in CURVE + EXTRA_SERIES]
        res = await asyncio.gather(*(fred.series(i) for i in ids), return_exceptions=True)
        series = {i: r["points"] for i, r in zip(ids, res) if not isinstance(r, Exception) and r.get("points")}
        if not series:
            return {"error": "FRED returned no data"}

        def point(sid, back=0):
            pts = series.get(sid) or []
            return pts[-1 - back] if len(pts) > back else None
        curve = []
        for label, sid in CURVE:
            now, wk = point(sid), point(sid, 5)
            if now:
                curve.append({"tenor": label, "date": now[0], "yield": now[1], "chg_1w_bp": (now[1] - wk[1]) * 100 if wk else None})
        extras = []
        for label, sid in EXTRA_SERIES:
            now, wk = point(sid), point(sid, 5)
            if now:
                extras.append({"label": label, "id": sid, "date": now[0], "value": now[1], "chg_1w": now[1] - wk[1] if wk else None})
        by = {c["tenor"]: c["yield"] for c in curve}
        spreads = {f"{a}/{b}": (by[b] - by[a]) * 100 for a, b in (("3m", "10y"), ("2y", "10y"), ("5y", "30y")) if a in by and b in by}
        return {"curve": curve, "extras": extras, "spreads_bp": spreads, "source": "FRED (daily, previous close)"}
    return await ctx.cache.get("macro:rates", 3600, build, disk=True)


async def fed_path(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        strip = ff_contracts(dt.date.today())
        quotes = await yahoo.quotes([s for s, _ in strip], intraday=False)
        rows = []
        for sym, label in strip:
            q = quotes.get(sym)
            if q and q.get("price"):
                rows.append({"month": label, "implied": 100 - q["price"],
                             "chg_bp": -(q["change"] or 0) * 100 if q.get("change") is not None else None})
        if not rows:
            return {"error": "no Fed funds futures quotes"}
        base = rows[0]["implied"]
        for r in rows:
            r["vs_now_bp"] = (r["implied"] - base) * 100
            r["moves_25bp"] = r["vs_now_bp"] / 25
        return {"path": rows, "source": "CBOT 30-day Fed funds futures via Yahoo (delayed). Implied = 100 - price; "
                                        "monthly averages, so a mid-month meeting shows up split across two months."}
    return await ctx.cache.get("macro:fedpath", 900, build)


async def vol(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        terms = [("9d", "^VIX9D"), ("30d", "^VIX"), ("3m", "^VIX3M"), ("6m", "^VIX6M"), ("VVIX", "^VVIX"), ("MOVE", "^MOVE")]
        quotes, closes = await asyncio.gather(yahoo.quotes([t for _, t in terms], intraday=False),
                                              yahoo.daily_closes(["^GSPC"], "3mo"))
        curve = [{"term": label, "symbol": t, "value": quotes[t]["price"], "change": quotes[t].get("change")}
                 for label, t in terms if t in quotes]
        out = {"curve": curve}
        spx = closes.get("^GSPC", [])
        if len(spx) > 21:
            r = [math.log(b / a) for a, b in zip(spx, spx[1:])]
            for n in (10, 20):
                tail = r[-n:]
                mean = sum(tail) / n
                out[f"realized_{n}d"] = math.sqrt(sum((x - mean) ** 2 for x in tail) / (n - 1)) * math.sqrt(252) * 100
        by = {c["term"]: c["value"] for c in curve}
        if "30d" in by and "realized_20d" in out:
            out["risk_premium"] = by["30d"] - out["realized_20d"]
        if "30d" in by and "3m" in by:
            out["slope"] = by["3m"] - by["30d"]
            out["state"] = "contango (calm)" if out["slope"] > 0 else "backwardation (stress)"
        return out
    return await ctx.cache.get("macro:vol", 300, build)


async def risk_ratios(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        syms = sorted({s for _, a, b in RISK_RATIOS for s in (a, b)})
        closes = await yahoo.daily_closes(syms, "3mo")
        rows = []
        for label, a, b in RISK_RATIOS:
            ca, cb = closes.get(a, []), closes.get(b, [])
            k = min(len(ca), len(cb))
            if k < 22:
                continue
            ratio = [x / y for x, y in zip(ca[-k:], cb[-k:]) if y]
            rows.append({"label": label, "pair": f"{a}/{b}", "d1": (ratio[-1] / ratio[-2] - 1) * 100,
                         "d5": (ratio[-1] / ratio[-6] - 1) * 100, "d20": (ratio[-1] / ratio[-21] - 1) * 100})
        if not rows:
            return {"error": "no ratio data"}
        return {"rows": rows, "risk_on_5d": sum(r["d5"] > 0 for r in rows), "n": len(rows),
                "note": "Ratio up = the risk-on side outperforms. Aligned on the last common closes; descriptive only."}
    return await ctx.cache.get("macro:risk", 900, build)


async def cot(ctx) -> dict:
    conn = ctx.hub.get("cftc")

    async def build():
        return {"rows": await conn.cot(), "source": "CFTC Commitments of Traders (Tuesday positions, published Friday)"}
    return await ctx.cache.get("macro:cot", 6 * 3600, build, disk=True)
