"""Sector performance by region, from sector ETFs (free daily closes): 1 day, 1 week, 1 month, 3 months,
year to date and 1 year, absolute and relative to the region's broad market. ETFs carry fees and tracking
differences, so this is the sector picture, not the exact index return.
"""
from __future__ import annotations

import datetime as dt
import time

REGIONS = {
    "us": {"name": "United States - S&P 500 sectors (SPDR ETFs)", "benchmark": ("SPY", "S&P 500 (SPY)"), "sectors": [
        ("XLK", "Technology"), ("XLC", "Communication"), ("XLY", "Consumer discretionary"), ("XLF", "Financials"),
        ("XLV", "Health care"), ("XLI", "Industrials"), ("XLE", "Energy"), ("XLB", "Materials"), ("XLP", "Consumer staples"),
        ("XLU", "Utilities"), ("XLRE", "Real estate")]},
    "eu": {"name": "Europe - STOXX 600 sectors (iShares ETFs, Xetra)", "benchmark": ("^STOXX", "STOXX 600"), "sectors": [
        ("EXV1.DE", "Banks"), ("EXH5.DE", "Insurance"), ("EXH2.DE", "Financial services"), ("EXV3.DE", "Technology"),
        ("EXV4.DE", "Health care"), ("EXH1.DE", "Oil & gas"), ("EXV6.DE", "Basic resources"), ("EXV7.DE", "Chemicals"),
        ("EXH4.DE", "Industrial goods"), ("EXV8.DE", "Construction"), ("EXV5.DE", "Autos"), ("EXH3.DE", "Food & beverage"),
        ("EXH7.DE", "Personal & household"), ("EXH8.DE", "Retail"), ("EXV9.DE", "Travel & leisure"), ("EXH6.DE", "Media"),
        ("EXV2.DE", "Telecom"), ("EXH9.DE", "Utilities"), ("EXI5.DE", "Real estate")]},
}
PERIODS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "1y": 252}


def returns(points: list[tuple[str, float]], today: dt.date | None = None) -> dict:
    """Period returns in percent from dated closes (pure, tested)."""
    out = {}
    v = [p[1] for p in points]
    for name, k in PERIODS.items():
        out[name] = (v[-1] / v[-1 - k] - 1) * 100 if len(v) > k and v[-1 - k] else None
    year = str((today or dt.date.today()).year)
    prev = [val for d, val in points if d < year + "-01-01"]
    out["ytd"] = (v[-1] / prev[-1] - 1) * 100 if prev and prev[-1] else None
    return out


async def performance(ctx, region: str) -> dict:
    spec = REGIONS.get(region)
    if not spec:
        return {"error": "unknown region"}
    yahoo = ctx.hub.get("yahoo")

    async def build():
        syms = [s for s, _ in spec["sectors"]] + [spec["benchmark"][0]]
        data = await yahoo.daily_series(syms, "2y")
        if not data:
            return {"error": "no sector data"}
        bench = returns(data.get(spec["benchmark"][0], []))
        rows = []
        for sym, name in spec["sectors"]:
            pts = data.get(sym)
            if not pts:
                continue
            r = returns(pts)
            rows.append({"symbol": sym, "name": name, "last": pts[-1][1], "day": pts[-1][0], **r,
                         **{f"rel_{k}": (r[k] - bench[k]) if r.get(k) is not None and bench.get(k) is not None else None for k in r},
                         "spark": [v for _, v in pts[-60:]]})
        return {"region": region, "name": spec["name"], "benchmark": {"symbol": spec["benchmark"][0], "name": spec["benchmark"][1], **bench},
                "rows": rows, "asof": time.time()}
    return await ctx.cache.get(f"sectors:{region}", 900, build)
