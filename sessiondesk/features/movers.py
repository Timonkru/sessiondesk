"""Unusual-move scanner with explanations.

Every few minutes: today's change for every member of the selected indices + the watchlist.
A move counts as unusual when it is large in percent AND large relative to the stock's own
volatility (z = log return / 60-day daily sigma) - a 3 % day is nothing for a small-cap biotech
and a lot for a utility. Very large moves alert regardless.

The explanation is computed, not guessed:
  market   - the benchmark's move times the stock's beta = the part the whole market explains
  sector   - same with the sector ETF (US)
  residual - what is left = stock-specific
  earnings - did the company report yesterday after the close or this morning?
  headlines- the newest ticker headlines from the active news connectors
The AI (optional) only turns these facts into a sentence; it is told not to invent causes.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
import re
import statistics
import time

from ..connectors.base import stable_id
from . import universe

SECTOR_ETFS = sorted(set(universe.SECTOR_ETF.values()))


def log_returns(closes: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:]) if a and b and a > 0 and b > 0]


def sigma(closes: list[float], n: int = 60) -> float | None:
    r = log_returns(closes[:-1])[-n:]          # drop the (possibly live) last close
    return statistics.stdev(r) if len(r) >= 20 else None


def beta(stock: list[float], bench: list[float], n: int = 60) -> float | None:
    a, b = log_returns(stock[:-1])[-n:], log_returns(bench[:-1])[-n:]
    k = min(len(a), len(b))
    if k < 20:
        return None
    a, b = a[-k:], b[-k:]
    mb = sum(b) / k
    var = sum((x - mb) ** 2 for x in b)
    if var <= 0:
        return None
    ma = sum(a) / k
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / var


NAME_NOISE = {"inc", "corp", "corporation", "company", "co", "plc", "group", "holdings", "the", "communications", "technologies",
              "international", "financial", "systems", "&", "and"}


def mentions(title: str, symbol: str, name: str) -> bool:
    """Ticker feeds attach generic articles ("5 dividend stocks ...") to every symbol they mention in passing.
    Keep a headline only if it names the company (first significant word of its name) or the ticker."""
    base = symbol.split(".")[0].split("-")[0]
    if len(base) >= 2 and re.search(r"(?<![A-Za-z&])" + re.escape(base) + r"(?![A-Za-z&])", title):
        return True
    words = [w for w in re.split(r"[\s,.]+", name or "") if w and w.lower() not in NAME_NOISE]
    key = words[0] if words else ""
    return len(key) >= 3 and re.search(r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])", title, re.I) is not None


def is_unusual(pct: float, z: float | None, rules: dict, watch: bool) -> bool:
    if abs(pct) >= rules.get("always_abs_pct", 8.0):
        return True
    if z is None:
        return False
    if watch:
        return abs(pct) >= rules.get("watchlist_abs_pct", 2.0) and abs(z) >= rules.get("watchlist_abs_z", 2.0)
    return abs(pct) >= rules.get("min_abs_pct", 3.0) and abs(z) >= rules.get("min_abs_z", 2.5)


def explain(row: dict) -> str:
    """Rule-based one-paragraph explanation from the computed facts (no AI needed)."""
    s = row["symbol"]
    parts = [f"{s} {row['pct']:+.1f}%" + (f" ({row['z']:+.1f} sigma of its normal daily move)" if row.get("z") is not None else "") + "."]
    ctx = []
    if row.get("bench_pct") is not None:
        ctx.append(f"{row['bench_name']} {row['bench_pct']:+.1f}%")
    if row.get("sector_pct") is not None:
        ctx.append(f"sector {row['sector_etf']} {row['sector_pct']:+.1f}%")
    if ctx:
        parts.append("Context: " + ", ".join(ctx) + ".")
    if row.get("explained_pct") is not None:
        share = row.get("specific_share")
        if share is not None:
            if share >= 0.7:
                parts.append(f"Market/sector explain only {row['explained_pct']:+.1f} pts (beta {row['beta']:.2f}): the move is mostly stock-specific.")
            elif share <= 0.3:
                parts.append(f"Market/sector explain {row['explained_pct']:+.1f} pts (beta {row['beta']:.2f}): mostly a market/sector move.")
            else:
                parts.append(f"Market/sector explain {row['explained_pct']:+.1f} pts (beta {row['beta']:.2f}); the rest is stock-specific.")
    if row.get("earnings"):
        parts.append(f"Earnings: reported {row['earnings']}.")
    heads = row.get("headlines") or []
    if heads:
        parts.append("Latest headlines: " + " | ".join(h["title"] for h in heads[:3]))
    elif row.get("headlines") is not None:
        extra = f" ({row['headlines_unrelated']} generic articles mention the ticker in passing)" if row.get("headlines_unrelated") else ""
        parts.append("No headline naming the company yet" + extra + " - the cause may not be public or not in the connected feeds.")
    return " ".join(parts)


async def _vol_table(ctx, symbols: list[str]) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        closes = await yahoo.daily_closes(symbols, "3mo")
        if not closes:
            return {"error": "no history returned"}
        return {"closes": closes}
    key = "vol:" + stable_id(*sorted(symbols))
    return await ctx.cache.get(key, 12 * 3600, build, disk=True, swr=True)


async def _earnings_recent(ctx) -> dict[str, str]:
    """{symbol: 'after the close on Mon 13 Oct' | 'before the open today'} for yesterday/today."""
    nas = ctx.hub.get("nasdaq")
    if not nas or not nas.active():
        return {}
    today = dt.date.today()
    prev = today - dt.timedelta(days=3 if today.weekday() == 0 else 1)

    async def build():
        rows = await nas.earnings(prev, (today - prev).days + 1)
        return {"rows": rows}
    data = await ctx.cache.get(f"earn:{today.isoformat()}", 3 * 3600, build, disk=True)
    out = {}
    for r in data.get("rows", []):
        day = dt.date.fromisoformat(r["date"])
        if day == prev and r["timing"] in ("after close", "n/a"):
            out[r["symbol"]] = f"after the close on {day.strftime('%a %d %b')}"
        elif day == today and r["timing"] in ("pre-market", "n/a"):
            out[r["symbol"]] = "before the open today"
        elif day == today and r["timing"] == "after close":
            out.setdefault(r["symbol"], "after the close today (scheduled)")
    return out


async def scan(ctx, *, publish: bool = True) -> dict:
    rules = ctx.settings.get("alerts") or {}
    watch = [s.strip() for s in ctx.settings.get("watchlist") or [] if s.strip()]
    unis = [u for u in ctx.settings.get("universes") or [] if u in universe.UNIVERSES]
    member_of: dict[str, str] = {}
    for u in unis:
        for m in universe.members(u):
            member_of.setdefault(m["symbol"], u)
    benches = {u: universe.BENCHMARK[u] for u in unis}
    symbols = list(dict.fromkeys(list(member_of) + watch + list(benches.values()) + ["^GSPC"] + SECTOR_ETFS))
    yahoo = ctx.hub.get("yahoo")
    if not yahoo or not yahoo.active():
        return {"error": "the movers scan needs the Yahoo connector enabled"}
    quotes, vol = await asyncio.gather(yahoo.quotes(symbols, intraday=False), _vol_table(ctx, symbols))
    closes = vol.get("closes", {})
    rows = []
    for sym, q in quotes.items():
        if sym in benches.values() or sym in SECTOR_ETFS or sym == "^GSPC" or q.get("change_pct") is None:
            continue
        pct = q["change_pct"]
        sg = sigma(closes.get(sym, []))
        z = math.log(1 + pct / 100) / sg if sg else None
        u = member_of.get(sym)
        bench_sym = benches.get(u) or ("^GDAXI" if sym.endswith(".DE") else "^GSPC")
        m = universe.lookup(sym)
        etf = universe.sector_etf(sym, m["sector"] if m else None)
        rows.append({"symbol": sym, "name": (m or {}).get("name", ""), "pct": pct, "z": z, "price": q.get("price"),
                     "time": q.get("time"), "universe": universe.UNIVERSES.get(u) if u else "watchlist",
                     "watch": sym in watch, "bench": bench_sym, "sector_etf": etf, "sector": (m or {}).get("sector")})
    flagged = [r for r in rows if is_unusual(r["pct"], r["z"], rules, r["watch"])]
    flagged.sort(key=lambda r: -abs(r["z"] if r["z"] is not None else r["pct"] / 2))
    flagged = flagged[:25]
    earnings = await _earnings_recent(ctx)
    names = {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^GDAXI": "DAX"}

    async def enrich(r):
        bq = quotes.get(r["bench"], {})
        r["bench_name"] = names.get(r["bench"], r["bench"])
        r["bench_pct"] = bq.get("change_pct")
        ref_sym, ref_pct = r["bench"], r["bench_pct"]
        if r["sector_etf"] and quotes.get(r["sector_etf"], {}).get("change_pct") is not None:
            r["sector_pct"] = quotes[r["sector_etf"]]["change_pct"]
            ref_sym, ref_pct = r["sector_etf"], r["sector_pct"]
        b = beta(closes.get(r["symbol"], []), closes.get(ref_sym, []))
        if b is not None and ref_pct is not None:
            r["beta"] = b
            r["explained_pct"] = b * ref_pct
            r["specific_share"] = min(1.0, abs(r["pct"] - b * ref_pct) / abs(r["pct"])) if r["pct"] else None
        r["earnings"] = earnings.get(r["symbol"])
        try:
            res = await ctx.hub.first("symbol_news", "symbol_news", r["symbol"])
            fresh = [h for h in res.get("data", []) if h.get("published", 0) >= time.time() - 36 * 3600]
            named = [h for h in fresh if mentions(h["title"], r["symbol"], r["name"])]
            r["headlines_unrelated"] = len(fresh) - len(named)
            r["headlines"] = [{"title": h["title"], "url": h.get("url"), "source": h.get("source"),
                               "published": h.get("published")} for h in named[:5]]
        except Exception:
            r["headlines"] = None
        r["explanation"] = explain(r)
        return r
    flagged = list(await asyncio.gather(*(enrich(r) for r in flagged)))

    new_alerts = []
    for r in flagged:
        day = dt.datetime.fromtimestamp(r.get("time") or time.time(), dt.timezone.utc).date().isoformat()
        alert = {"id": stable_id("move", r["symbol"], day, "up" if r["pct"] > 0 else "down"), "ts": time.time(), "kind": "move",
                 "symbol": r["symbol"], "title": f"{r['symbol']} {r['pct']:+.1f}%" + (f" · {r['z']:+.1f}σ" if r["z"] is not None else ""),
                 "body": r["explanation"], "data": r}
        if ctx.db and await ctx.db.run(ctx.db.add_alert, alert):
            new_alerts.append(alert)
            if publish:
                ctx.broker.publish("alert", {"alert": alert})
    top = sorted(rows, key=lambda r: r["pct"])
    return {"flagged": flagged, "new": [a["id"] for a in new_alerts], "scanned": len(rows),
            "gainers": top[::-1][:15], "losers": top[:15], "asof": time.time(),
            "rules": rules, "universes": [universe.UNIVERSES[u] for u in unis]}
