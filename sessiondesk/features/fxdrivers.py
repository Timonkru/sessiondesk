"""FX drivers for a currency pair: what moves it, on one tab of the pair's page - the rate differential (2y and 10y)
and the carry from the policy rates, positioning (CFTC), today's currency strength, the releases of both currencies
and their headlines. Reads the same sources as Macro, Calendar and News; nothing new is fetched.
"""
from __future__ import annotations

import asyncio
import re
import time

RATES_ROW = {"USD": "United States", "EUR": "Euro area (AAA)", "GBP": "United Kingdom", "JPY": "Japan"}
COT_NAME = {"EUR": "Euro", "JPY": "Yen", "GBP": "Pound"}
NEWS_WORDS = {
    "USD": r"\bdollar\b|\bfed\b|powell|treasur|\bus (cpi|jobs|payrolls|economy)", "EUR": r"\beuro\b|\becb\b|lagarde|euro ?zone|euro area",
    "JPY": r"\byen\b|\bboj\b|\bueda\b|japan", "GBP": r"\bpound\b|sterling|\bboe\b|bank of england|bailey|\buk\b",
    "CHF": r"\bfranc\b|\bsnb\b|swiss", "AUD": r"aussie|\brba\b|australia", "CAD": r"loonie|bank of canada|\bboc\b|canad",
    "NZD": r"\bkiwi\b|\brbnz\b|new zealand", "CNY": r"\byuan\b|\bpboc\b|china",
}


def legs(symbol: str) -> tuple[str, str] | None:
    """'EURUSD=X' -> (EUR, USD), 'JPY=X' -> (USD, JPY), 'DX-Y.NYB' -> (USD, basket) (pure, tested)."""
    from .deep import fx_pair
    pair = fx_pair(symbol)
    if pair == "DXY":
        return "USD", "basket"
    if not pair:
        s = (symbol or "").upper()
        if s.endswith("=X"):
            core = s[:-2]
            pair = core if len(core) == 6 else ("USD" + core if len(core) == 3 else None)
    return (pair[:3], pair[3:]) if pair and len(pair) == 6 else None


def differential(base_row: dict | None, quote_row: dict | None) -> dict:
    """Base minus quote in basis points for policy, 2y and 10y (pure, tested)."""
    out = {}
    for k in ("policy", "2y", "10y"):
        a, b = (base_row or {}).get(k), (quote_row or {}).get(k)
        out[k] = (a - b) * 100 if a is not None and b is not None else None
    return out


async def drivers(ctx, symbol: str) -> dict:
    lg = legs(symbol)
    if not lg:
        return {"error": "not a currency pair"}
    base, quote = lg
    from .macro import cot
    from .news import list_news
    from .rates_world import world
    from .risk import currency_strength

    async def cal():
        if "calendar" not in ctx.extras:
            return {"next": [], "recent": []}
        now = time.time()
        d = await ctx.extras["calendar"].events(now - 3 * 86400, now + 8 * 86400)
        ev = [e for e in d.get("events", []) if e.get("currency") in (base, quote) and e.get("impact") in ("high", "medium")]
        return {"next": [e for e in ev if e["ts"] >= now][:16], "recent": [e for e in ev if e["ts"] < now and e.get("actual") is not None][-10:][::-1]}

    w, c, strength, calendar, news = await asyncio.gather(world(ctx), cot(ctx), currency_strength(ctx), cal(),
                                                          list_news(ctx, None, None, None, None, 300, None), return_exceptions=True)
    ok = lambda x, d: d if isinstance(x, Exception) or (isinstance(x, dict) and "error" in x) else x   # noqa: E731
    w, c, strength, calendar, news = ok(w, {}), ok(c, {}), ok(strength, {}), ok(calendar, {"next": [], "recent": []}), ok(news, {})
    rows = {r["country"]: r for r in w.get("rows", [])}
    b_row, q_row = rows.get(RATES_ROW.get(base, "")), rows.get(RATES_ROW.get(quote, ""))
    rx = re.compile("|".join(NEWS_WORDS[x] for x in (base, quote) if x in NEWS_WORDS) or r"$^", re.I)
    heads = [n for n in news.get("items", []) if rx.search(n.get("title", ""))][:14]
    cot_rows = [r for r in c.get("rows", []) if r.get("market") in {COT_NAME.get(base), COT_NAME.get(quote)}]
    st = {r["currency"]: r for r in strength.get("rows", [])}
    ranked = [r["currency"] for r in strength.get("rows", [])]
    return {"symbol": symbol, "base": base, "quote": quote,
            "rates": {"base": b_row, "quote": q_row, "diff": differential(b_row, q_row)},
            "carry_pct": differential(b_row, q_row)["policy"] / 100 if differential(b_row, q_row)["policy"] is not None else None,
            "cot": cot_rows, "strength": {x: {**st[x], "rank": ranked.index(x) + 1, "of": len(ranked)} for x in (base, quote) if x in st},
            "strength_source": strength.get("source"), "calendar": calendar, "news": heads,
            "note": "Differential = base currency minus quote currency, in basis points; a widening gap in favour of the base "
                    "currency has historically supported the pair, but the link is loose and changes over time. Carry = policy-rate "
                    "difference per year, before costs - your broker's swap is what you actually earn or pay. Positioning: CFTC "
                    "futures (leveraged funds), Tuesday data. Rates only where a free official curve exists (USD, EUR, GBP, JPY)."}
