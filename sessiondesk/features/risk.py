"""Open-book risk, currency strength and the reaction history of calendar events.

Book risk
  correlation  sign-adjusted correlation of the markets you hold (long A + short B on correlated markets
               is a hedge, two longs a doubled bet), from 30 days of hourly returns
  scenario     P/L if a driver market (default NQ, DAX) moves by the shock (default -1 %): each position's
               money per 1 % move x its beta to the driver. Stops are ignored - it is a sensitivity, not a forecast.
Currency strength
  day change of each major against all others, from broker FX quotes (fresh) or free quotes
Event reaction history
  for each upcoming event the exporter delivered history for: actual vs forecast of the last releases and
  how index futures / FX moved from one hour before to two hours after each release
"""
from __future__ import annotations

import asyncio
import math
import statistics
import time

from . import assets

REACTION_ASSETS = {"USD": ["NQ", "DOW", "EURUSD", "GOLD"], "EUR": ["DAX", "EURUSD"], "GBP": ["FTSE", "GBPUSD"],
                   "JPY": ["NIKKEI", "USDJPY"], "CHF": ["SMI", "USDCHF"], "CNY": ["HK50"], "CAD": ["USDCAD", "OIL"],
                   "AUD": ["AUDUSD"], "NZD": ["NZDUSD"]}
FX_MAJORS = ("USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD")


def returns_from_bars(bars: list[dict]) -> dict[int, float]:
    """{hour_ts: hourly log return} keyed by the bar's hour so different markets can be aligned."""
    out = {}
    for a, b in zip(bars, bars[1:]):
        if a["c"] > 0 and b["c"] > 0:
            out[int(b["t"] // 3600)] = math.log(b["c"] / a["c"])
    return out


def corr_beta(x: dict[int, float], y: dict[int, float]) -> tuple[float | None, float | None, int]:
    """(correlation, beta of x on y, n) over common hours."""
    keys = sorted(set(x) & set(y))
    n = len(keys)
    if n < 30:
        return None, None, n
    xs, ys = [x[k] for k in keys], [y[k] for k in keys]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx <= 0 or vy <= 0:
        return None, None, n
    return cov / math.sqrt(vx * vy), cov / vy, n


async def _hourly(ctx, tickers: list[str], range_: str = "1mo") -> dict[str, list[dict]]:
    yahoo = ctx.hub.get("yahoo")

    async def one(t):
        async def build():
            return await yahoo.history(t, range_, "60m")
        res = await ctx.cache.get(f"h60:{t}:{range_}", 1800, build)
        return t, res.get("bars", []) if "error" not in res else []
    pairs = await asyncio.gather(*(one(t) for t in tickers))
    return dict(pairs)


async def book(ctx, positions: list[dict], accounts: list[dict]) -> dict:
    if not positions:
        return {"positions": [], "note": "No open positions."}
    rows = []
    for p in positions:
        asset = assets.asset_of(p.get("symbol", ""), ctx.settings)
        rows.append({"account": p.get("account"), "symbol": p.get("symbol"), "side": p.get("side"), "volume": p.get("volume"),
                     "asset": asset, "ticker": assets.yahoo_ticker(asset), "sign": 1 if p.get("side") == "LONG" else -1,
                     "money_per_pct": p.get("money_per_pct"), "risk_to_stop": p.get("risk_to_stop")})
    drivers = [d for d in (ctx.settings.get("scenario_drivers") or ["NQ", "DAX"]) if assets.yahoo_ticker(d)]
    shock = float(ctx.settings.get("scenario_shock_pct") or -1.0)
    tickers = sorted({r["ticker"] for r in rows if r["ticker"]} | {assets.yahoo_ticker(d) for d in drivers})
    bars = await _hourly(ctx, tickers)
    rets = {t: returns_from_bars(b) for t, b in bars.items()}
    # correlation between distinct held markets, sign-adjusted per pair of positions
    held = []
    for r in rows:
        key = (r["asset"], r["sign"])
        if r["ticker"] and key not in held:
            held.append(key)
    matrix = []
    for a, sa in held:
        line = []
        for b, sb in held:
            if a == b:
                c = 1.0
            else:
                c, _beta, _n = corr_beta(rets.get(assets.yahoo_ticker(a), {}), rets.get(assets.yahoo_ticker(b), {}))
            line.append(None if c is None else c * sa * sb)
        matrix.append({"asset": a, "side": "LONG" if sa > 0 else "SHORT", "values": line})
    # scenarios per account and driver
    equity = {a.get("login"): a.get("equity") for a in accounts}
    scenarios = []
    for acct in sorted({r["account"] for r in rows}):
        own = [r for r in rows if r["account"] == acct]
        for d in drivers:
            dt_ = assets.yahoo_ticker(d)
            parts, missing = [], 0
            for r in own:
                if r["money_per_pct"] is None or not r["ticker"]:
                    missing += 1
                    continue
                if r["asset"] == d:
                    beta, n = 1.0, None
                else:
                    _c, beta, n = corr_beta(rets.get(r["ticker"], {}), rets.get(dt_, {}))
                if beta is None:
                    missing += 1
                    continue
                parts.append({"symbol": r["symbol"], "beta": beta, "n": n, "pnl": r["sign"] * r["money_per_pct"] * beta * shock})
            total = sum(p["pnl"] for p in parts) if parts else None
            eq = equity.get(acct)
            scenarios.append({"account": acct, "driver": d, "shock": shock, "total": total,
                              "total_pct": total / eq * 100 if total is not None and eq else None,
                              "parts": parts, "incomplete": missing})
    return {"positions": rows, "matrix": matrix, "scenarios": scenarios, "drivers": drivers,
            "note": "Correlation from about 30 days of hourly returns (free data; broker CFDs can differ). Positive "
                    "sign-adjusted value = the two positions win and lose together. Scenario = sensitivity, stops ignored."}


async def currency_strength(ctx, broker_quotes: dict | None = None) -> dict:
    score: dict[str, list[float]] = {c: [] for c in FX_MAJORS}
    source = "broker"
    seen = set()
    for sym, q in (broker_quotes or {}).items():
        core = "".join(ch for ch in sym.upper() if ch.isalpha())[:6]
        base, quote = core[:3], core[3:]
        if len(core) != 6 or base not in score or quote not in score or core in seen or not q.get("change_pct"):
            continue
        seen.add(core)
        score[base].append(q["change_pct"])
        score[quote].append(-q["change_pct"])
    if len(seen) < 6:
        source = "free quotes (delayed)"
        pairs = [f"{a}{b}=X" for i, a in enumerate(FX_MAJORS) for b in FX_MAJORS[i + 1:]]
        from .markets import get_quotes
        res = await get_quotes(ctx, pairs, intraday=False)
        score = {c: [] for c in FX_MAJORS}
        for t, q in (res.get("quotes") or {}).items():
            base, quote = t[:3], t[3:6]
            if q.get("change_pct") is None:
                continue
            score[base].append(q["change_pct"])
            score[quote].append(-q["change_pct"])
    rows = [{"currency": c, "strength": sum(v) / len(v), "pairs": len(v)} for c, v in score.items() if v]
    return {"rows": sorted(rows, key=lambda r: -r["strength"]), "source": source,
            "note": "Average % change of each currency against the others today (vs previous close)."}


async def event_history(ctx) -> dict:
    mt5 = ctx.hub.get("mt5")
    if not mt5 or not mt5.active():
        return {"events": {}, "note": "Needs the MetaTrader 5 bridge (it exports the last releases of upcoming events)."}
    events = await mt5.calhist()
    if not events:
        return {"events": {}, "note": "The bridge has not exported calendar history yet."}
    want = sorted({a for ev in events.values() for a in REACTION_ASSETS.get(ev["currency"], ["NQ"])})
    tickers = {assets.yahoo_ticker(a): a for a in want if assets.yahoo_ticker(a)}
    bars = await _hourly(ctx, list(tickers), "2y")
    out = {}
    for key, ev in events.items():
        markets = REACTION_ASSETS.get(ev["currency"], ["NQ"])
        rels = []
        for r in ev["releases"][:8]:
            moves = {}
            for a in markets:
                b = bars.get(assets.yahoo_ticker(a), [])
                before = [x for x in b if x["t"] <= r["ts"] - 3600]
                after = [x for x in b if r["ts"] < x["t"] <= r["ts"] + 2 * 3600]
                if before and after and r["ts"] - before[-1]["t"] < 6 * 3600:
                    moves[a] = (after[-1]["c"] / before[-1]["c"] - 1) * 100
            rels.append({**r, "moves": moves})
        avg = {a: statistics.mean(abs(x["moves"][a]) for x in rels if a in x["moves"]) for a in markets
               if any(a in x["moves"] for x in rels)}
        out[key] = {"currency": ev["currency"], "name": ev["name"], "unit": ev["unit"], "markets": markets,
                    "releases": rels, "avg_abs_move": avg}
    return {"events": out, "note": "Move = close of the hour before the release to the close two hours after (wide on "
                                   "purpose: hourly bars, DST shifts). Free hourly data reaches back about two years."}


async def specs(ctx) -> dict:
    mt5 = ctx.hub.get("mt5")
    if not mt5 or not mt5.active():
        return {"rows": []}
    return {"rows": await mt5.specs(), "asof": time.time()}
