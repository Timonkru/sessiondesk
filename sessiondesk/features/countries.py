"""Country pages: one page per economy that brings together what SessionDesk already has about it - the main index and
the breadth of its members, the currency, the latest macro prints, the government curve and policy rate, the
upcoming releases for its currency, and the news of its market. Nothing new is fetched for a country page; it
reads the same caches as the Markets, Indices, Macro and Calendar pages.
"""
from __future__ import annotations

import asyncio
import time

# key: name, region, index symbols (first = main), member universe, FX symbol (+ what it shows), currency,
#      macro row (Macro > Inflation & growth), rates row (Macro > Rates), news market, central bank
COUNTRIES = {
    "us": dict(name="United States", region="Americas", indices=["^GSPC", "^NDX", "^DJI", "^RUT"], universe="sp500",
               fx=("DX-Y.NYB", "US dollar index"), ccy="USD", macro="United States", rates="United States", market="us", bank="Federal Reserve"),
    "ca": dict(name="Canada", region="Americas", indices=["^GSPTSE", "XIU.TO"], universe="tsx60", fx=("CAD=X", "USD/CAD"), ccy="CAD",
               macro=None, rates=None, market=None, bank="Bank of Canada"),
    "ea": dict(name="Euro area", region="Europe", indices=["^STOXX50E", "^STOXX"], universe="stoxx50", fx=("EURUSD=X", "EUR/USD"), ccy="EUR",
               macro="Euro area", rates="Euro area (AAA)", market="europe", bank="European Central Bank"),
    "de": dict(name="Germany", region="Europe", indices=["^GDAXI"], universe="dax40", fx=("EURUSD=X", "EUR/USD"), ccy="EUR",
               macro="Germany", rates="Euro area (AAA)", market="europe", bank="European Central Bank"),
    "fr": dict(name="France", region="Europe", indices=["^FCHI"], universe="cac40", fx=("EURUSD=X", "EUR/USD"), ccy="EUR",
               macro="France", rates="Euro area (AAA)", market="europe", bank="European Central Bank"),
    "it": dict(name="Italy", region="Europe", indices=["FTSEMIB.MI"], universe="ftsemib", fx=("EURUSD=X", "EUR/USD"), ccy="EUR",
               macro="Italy", rates="Euro area (AAA)", market="europe", bank="European Central Bank"),
    "es": dict(name="Spain", region="Europe", indices=["^IBEX"], universe="ibex35", fx=("EURUSD=X", "EUR/USD"), ccy="EUR",
               macro="Spain", rates="Euro area (AAA)", market="europe", bank="European Central Bank"),
    "nl": dict(name="Netherlands", region="Europe", indices=["^AEX"], universe="aex25", fx=("EURUSD=X", "EUR/USD"), ccy="EUR",
               macro=None, rates="Euro area (AAA)", market="europe", bank="European Central Bank"),
    "uk": dict(name="United Kingdom", region="Europe", indices=["^FTSE"], universe="ftse100", fx=("GBPUSD=X", "GBP/USD"), ccy="GBP",
               macro="United Kingdom", rates="United Kingdom", market="uk", bank="Bank of England"),
    "ch": dict(name="Switzerland", region="Europe", indices=["^SSMI"], universe="smi", fx=("CHF=X", "USD/CHF"), ccy="CHF",
               macro=None, rates=None, market=None, bank="Swiss National Bank"),
    "jp": dict(name="Japan", region="Asia-Pacific", indices=["^N225"], universe="nikkei225", fx=("JPY=X", "USD/JPY"), ccy="JPY",
               macro="Japan", rates="Japan", market="japan", bank="Bank of Japan"),
    "cn": dict(name="China & Hong Kong", region="Asia-Pacific", indices=["^HSI", "000001.SS", "399001.SZ"], universe="hsi",
               fx=("CNY=X", "USD/CNY"), ccy="CNY", macro=None, rates=None, market="china", bank="People's Bank of China"),
    "au": dict(name="Australia", region="Asia-Pacific", indices=["^AXJO"], universe="asx200", fx=("AUDUSD=X", "AUD/USD"), ccy="AUD",
               macro=None, rates=None, market=None, bank="Reserve Bank of Australia"),
}


def breadth(rows: list[dict]) -> dict | None:
    """Today's participation from the stock-list rows of one index (pure, tested)."""
    moved = [r for r in rows if r.get("chg1d") is not None]
    if not moved:
        return None
    above = [r for r in rows if r.get("dist200") is not None]
    s = sorted(moved, key=lambda r: r["chg1d"])
    pick = lambda xs: [{"symbol": r["symbol"], "name": r.get("name"), "chg1d": r["chg1d"]} for r in xs]   # noqa: E731
    unchanged = sum(1 for r in moved if r["chg1d"] == 0)
    return {"n": len(moved), "up": sum(1 for r in moved if r["chg1d"] > 0), "before_open": unchanged / len(moved) > 0.8,
            "above200": sum(1 for r in above if r["dist200"] > 0) / len(above) * 100 if above else None,
            "near_high": sum(1 for r in rows if r.get("from_high") is not None and r["from_high"] > -2),
            "best": pick(s[-5:][::-1]), "worst": pick(s[:5])}


async def overview(ctx) -> dict:
    """The landing grid: every country with its main index, currency and 10-year yield."""
    from .markets import get_quotes
    from .rates_world import world
    syms = [c["indices"][0] for c in COUNTRIES.values()] + [c["fx"][0] for c in COUNTRIES.values()]
    q, w = await asyncio.gather(get_quotes(ctx, sorted(set(syms)), intraday=False), world(ctx))
    quotes = q.get("quotes", {})
    rates = {r["country"]: r for r in w.get("rows", [])}
    rows = []
    for key, c in COUNTRIES.items():
        idx, fx = quotes.get(c["indices"][0]) or {}, quotes.get(c["fx"][0]) or {}
        r = rates.get(c["rates"] or "") or {}
        rows.append({"key": key, "name": c["name"], "region": c["region"], "index": c["indices"][0], "index_price": idx.get("price"),
                     "index_chg": idx.get("change_pct"), "fx": c["fx"][1], "fx_symbol": c["fx"][0], "fx_price": fx.get("price"),
                     "fx_chg": fx.get("change_pct"), "y10": r.get("10y"), "policy": r.get("policy"), "bank": c["bank"]})
    return {"rows": rows}


async def page(ctx, key: str) -> dict:
    c = COUNTRIES.get(key)
    if not c:
        return {"error": "unknown country"}
    from . import universe
    from .macro import international
    from .markets import get_quotes
    from .news import list_news
    from .rates_world import world
    from .stocklist import stocks

    async def cal():
        now = time.time()
        d = await ctx.extras["calendar"].events(now - 3 * 86400, now + 10 * 86400) if "calendar" in ctx.extras else {"events": []}
        ev = [e for e in d.get("events", []) if e.get("currency") == c["ccy"] and e.get("impact") in ("high", "medium")]
        return {"next": [e for e in ev if e["ts"] >= now][:12], "recent": [e for e in ev if e["ts"] < now and e.get("actual") is not None][-8:][::-1]}

    tasks = [get_quotes(ctx, c["indices"] + [c["fx"][0]], intraday=True), international(ctx), world(ctx), cal(),
             list_news(ctx, None, None, None, None, 120, c["market"]) if c["market"] else asyncio.sleep(0, result={"items": []}),
             stocks(ctx, f"index:{c['universe']}") if c["universe"] in universe.UNIVERSES else asyncio.sleep(0, result={"rows": []})]
    q, intl, w, calendar, news_d, members = await asyncio.gather(*tasks, return_exceptions=True)
    ok = lambda x, default: default if isinstance(x, Exception) or (isinstance(x, dict) and "error" in x) else x   # noqa: E731
    q, intl, w, calendar, news_d, members = (ok(q, {}), ok(intl, {}), ok(w, {}), ok(calendar, {"next": [], "recent": []}),
                                             ok(news_d, {"items": []}), ok(members, {"rows": []}))
    quotes = q.get("quotes", {})
    rates_row = next((r for r in w.get("rows", []) if r["country"] == c["rates"]), None) if c["rates"] else None
    macro_row = (intl.get("table") or {}).get(c["macro"]) if c["macro"] else None
    return {"key": key, **{k: c[k] for k in ("name", "region", "ccy", "bank", "market")},
            "universe": c["universe"] if c["universe"] in universe.UNIVERSES else None,
            "universe_name": universe.UNIVERSES.get(c["universe"]),
            "indices": [{"symbol": s, **(quotes.get(s) or {})} for s in c["indices"]],
            "fx": {"symbol": c["fx"][0], "label": c["fx"][1], **(quotes.get(c["fx"][0]) or {})},
            "breadth": breadth(members.get("rows", [])), "macro": macro_row, "macro_labels": intl.get("indicators"),
            "rates": rates_row, "calendar": calendar, "news": news_d.get("items", [])[:12],
            "note": "Everything on this page comes from the same sources as the Markets, Indices, Macro and Calendar pages; "
                    "each block links there. Countries without a free macro or rates source show only what exists."}
