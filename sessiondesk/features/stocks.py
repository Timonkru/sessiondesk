"""Single-stock detail: quote + profile + key stats, price history, merged news, filings, earnings."""
from __future__ import annotations

import asyncio
import time

from . import universe
from .valuation import profile

PROFILE_FIELDS = ("name", "sector", "industry", "country", "website", "employees", "summary", "exchange", "currency",
                  "market_cap", "enterprise_value", "shares", "beta", "avg_volume", "high_52w", "low_52w",
                  "dividend_yield", "earnings_ts", "earnings_start", "earnings_end", "ex_dividend", "type",
                  "pe_forward", "pe_trailing", "ev_ebitda", "ps", "pb", "short_pct_float", "short_ratio", "shares_short",
                  "shares_short_prior", "short_date", "float_shares", "held_insiders", "held_institutions",
                  "target_mean", "recommendation", "analysts", "revenue_growth", "operating_margin", "net_margin")


async def history(ctx, symbol: str, range_: str = "1y") -> dict:
    async def build():
        res = await ctx.hub.first("history", "history", symbol, range_)
        if "error" in res:
            return res
        return {**res["data"], "source": res["source"]}
    ttl = 30 if range_ in ("1d", "5d") else 900
    return await ctx.cache.get(f"hist:{symbol}:{range_}", ttl, build)


async def summary(ctx, symbol: str, profile_wait: float = 1.5) -> dict:
    """Quote and intraday path come fast; the fundamentals profile (yfinance, ~3-6 s when cold) is awaited
    only briefly - if it is not ready, the page renders without it and asks again (profile_pending)."""
    prof_task = asyncio.ensure_future(profile(ctx, symbol))
    day = await history(ctx, symbol, "1d")
    try:
        prof = await asyncio.wait_for(asyncio.shield(prof_task), timeout=profile_wait)
    except asyncio.TimeoutError:
        prof = {"error": "pending", "pending": True}
    if "error" in day and "error" in prof:
        return {"error": f"no data for {symbol}: {day['error']}"}
    quote = {}
    if "error" not in day:
        bars = day.get("bars") or []
        prev = None
        async def build_quote():
            from .markets import get_quotes
            res = await get_quotes(ctx, [symbol], intraday=False)
            one = (res.get("quotes") or {}).get(symbol)
            return one if one else {"error": res.get("error") or "no quote"}
        q = await ctx.cache.get(f"q:{symbol}", 20, build_quote)
        if "error" not in q:
            quote = q
            prev = q.get("prev_close")
        quote.update({"time": day.get("time") or quote.get("time"),     # spark gives the bar start, the chart meta the last trade
                      "day_high": day.get("day_high"), "day_low": day.get("day_low"), "volume": day.get("volume"),
                      "currency": day.get("currency"), "exchange": day.get("exchange"),
                      "intraday": [{"t": b["t"], "c": b["c"]} for b in bars], "prev_close": prev or quote.get("prev_close")})
    info = {} if "error" in prof else {k: prof.get(k) for k in PROFILE_FIELDS if prof.get(k) is not None}
    if not info.get("name") and "error" not in day:
        info["name"] = day.get("name")
    member = universe.lookup(symbol)
    kind = (info.get("type") or ("" if "error" in day else day.get("type")) or "").upper()
    return {"symbol": symbol, "type": kind, "quote": quote, "profile": info, "index": universe.UNIVERSES.get(member["universe"]) if member else None,
            "sector_etf": universe.sector_etf(symbol, info.get("sector")), "peers": universe.peers(symbol, 8),
            "profile_error": None if prof.get("pending") else prof.get("error"), "profile_pending": bool(prof.get("pending")),
            "asof": time.time()}


async def news(ctx, symbol: str) -> dict:
    async def build():
        results = await ctx.hub.gather("symbol_news", "symbol_news", symbol)
        items, errors = [], {}
        for src, res in results.items():
            if isinstance(res, dict) and "error" in res:
                errors[src] = res["error"]
            elif isinstance(res, list):
                items += res
        seen, merged = set(), []
        for it in sorted(items, key=lambda x: -x.get("published", 0)):
            key = it["title"].lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
        # The local archive often holds headlines that name the company without the ticker feed.
        if ctx.db:
            archived = await ctx.db.run(ctx.db.query_news, None, None, None, symbol, 30)
            for it in archived:
                if it["title"].lower()[:80] not in seen:
                    merged.append(it)
        merged.sort(key=lambda x: -x.get("published", 0))
        return {"items": merged[:80], "errors": errors, "sources": [s for s in results if s not in errors]}
    return await ctx.cache.get(f"snews:{symbol}", 180, build)


async def filings(ctx, symbol: str) -> dict:
    sec = ctx.hub.get("sec")
    if not sec or not sec.active():
        return {"items": [], "note": "Add a contact email to the SEC EDGAR connector (Settings -> Connectors) to see US filings."}

    async def build():
        return {"items": await sec.filings(symbol)}
    return await ctx.cache.get(f"filings:{symbol}", 1800, build)


async def search(ctx, q: str) -> dict:
    q = q.strip()
    if not q:
        return {"items": []}
    local = []
    ql = q.lower()
    for u in universe.UNIVERSES:
        for m in universe.members(u):
            if m["symbol"].lower() == ql or m["symbol"].lower().startswith(ql) or ql in m["name"].lower():
                local.append({"symbol": m["symbol"], "name": m["name"], "exchange": universe.UNIVERSES[u], "type": "EQUITY",
                              "sector": m["sector"]})
    local = sorted(local, key=lambda m: (m["symbol"].lower() != ql, not m["symbol"].lower().startswith(ql), len(m["symbol"])))[:6]

    async def build():
        res = await ctx.hub.first("search", "search", q)
        return {"items": res.get("data", [])} if "error" not in res else res
    remote = await ctx.cache.get(f"search:{ql}", 3600, build)
    seen = {m["symbol"] for m in local}
    items = local + [r for r in remote.get("items", []) if r["symbol"] not in seen]
    return {"items": items[:12]}
