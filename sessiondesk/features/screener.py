"""Screener over the bundled index universes (S&P 500, Nasdaq-100, DAX 40, Dow 30).

Price measures come from the year of daily closes the Indices page already keeps (refreshed hourly, today's
value live) - the screener adds no load on the free sources. Fundamentals (market cap, forward P/E, dividend
yield) are shown where a company profile is already cached; they are not fetched for 500 names at once.
A screen describes the current state of each stock. It is not a signal: test any rule before trading it.
"""
from __future__ import annotations

import math
import statistics
import time

from . import universe
from .indices import INDEX_SYMBOL, member_closes


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI on daily closes."""
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[:n], closes[1:n + 1]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    for a, b in zip(closes[n:-1], closes[n + 1:]):
        d = b - a
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
    if avg_l == 0:
        return 100.0 if avg_g > 0 else 50.0
    return 100 - 100 / (1 + avg_g / avg_l)


def metrics(c: list[float]) -> dict | None:
    if len(c) < 30 or not c[-1]:
        return None
    last = c[-1]

    def chg(k):
        return (last / c[-1 - k] - 1) * 100 if len(c) > k and c[-1 - k] else None
    hi, lo = max(c[-252:]), min(c[-252:])
    sma50 = statistics.mean(c[-50:]) if len(c) >= 50 else None
    sma200 = statistics.mean(c[-200:]) if len(c) >= 200 else None
    rets = [b / a - 1 for a, b in zip(c[-21:-1], c[-20:]) if a]
    return {"last": last, "chg1d": chg(1), "chg5d": chg(5), "chg20d": chg(20), "chg60d": chg(60),
            "chg1y": chg(min(251, len(c) - 1)) if len(c) >= 200 else None,
            "from_high": (last / hi - 1) * 100 if hi else None, "from_low": (last / lo - 1) * 100 if lo else None,
            "dist50": (last / sma50 - 1) * 100 if sma50 else None, "dist200": (last / sma200 - 1) * 100 if sma200 else None,
            "above50": last > sma50 if sma50 else None, "above200": last > sma200 if sma200 else None,
            "rsi14": rsi(c[-120:]), "vol20": statistics.pstdev(rets) * math.sqrt(252) * 100 if len(rets) >= 10 else None}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


async def screen(ctx, key: str) -> dict:
    if key not in INDEX_SYMBOL:
        return {"error": "unknown universe"}
    data = await member_closes(ctx, key)
    if "error" in data:
        return data
    rows = []
    with_profile = 0
    for m in universe.members(key):
        sym = m["symbol"]
        met = metrics(data["closes"].get(sym) or [])
        if not met:
            continue
        prof = ctx.cache.peek(f"profile:v2:{sym}", disk=True) or {}
        if prof and "error" not in prof:
            with_profile += 1
        else:
            prof = {}
        pe = _num(prof.get("pe_forward"))
        rows.append({"symbol": sym, "name": m.get("name") or prof.get("name") or "", "sector": m.get("sector") or prof.get("sector") or "",
                     "industry": m.get("industry") or "",
                     **met, "market_cap": _num(prof.get("market_cap")), "pe_fwd": pe if pe is not None and 0 < pe < 400 else None,
                     "div_yield": (_num(prof.get("dividend_yield")) or 0) * 100 if prof.get("dividend_yield") is not None else None})
    return {"key": key, "name": universe.UNIVERSES[key], "rows": rows, "asof": time.time(), "with_profile": with_profile,
            "closes_asof": data.get("closes_asof"), "closes_stale": data.get("closes_stale"),
            "note": "Price measures from one year of daily closes (free data, refreshed hourly, today's value live). "
                    f"Market cap, forward P/E and dividend yield only where a company profile is cached ({with_profile} of {len(rows)}); "
                    "open a stock or the Indices page to fill more. A screen describes; it is not a signal."}
