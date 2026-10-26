"""Cross-asset overview and the shared quote service.

get_quotes() asks the preferred quote connectors in order and lets each one fill only the symbols
the previous one could not deliver (a US-only paid feed + Yahoo for indices, FX and Europe).
Every quote carries the connector it came from.
"""
from __future__ import annotations

from .movers import traded_today

OVERVIEW: list[tuple[str, list[tuple[str, str]]]] = [
    ("Americas", [("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100"), ("^DJI", "Dow Jones"), ("^RUT", "Russell 2000"),
                  ("^GSPTSE", "Canada TSX"), ("XIU.TO", "Canada TSX 60 (XIU ETF)"), ("^MXX", "Mexico IPC"), ("^BVSP", "Brazil Bovespa"), ("^MERV", "Argentina Merval")]),
    ("Europe", [("^GDAXI", "DAX"), ("^STOXX50E", "Euro Stoxx 50"), ("^STOXX", "Stoxx 600"), ("^FTSE", "FTSE 100"),
                ("^FCHI", "CAC 40"), ("^SSMI", "SMI"), ("FTSEMIB.MI", "FTSE MIB"), ("^IBEX", "IBEX 35"), ("^AEX", "AEX"),
                ("^OMX", "OMX Stockholm 30"), ("^BFX", "BEL 20"), ("^ATX", "ATX")]),
    ("Asia-Pacific", [("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("000001.SS", "Shanghai Composite"), ("399001.SZ", "Shenzhen Component"),
                      ("^KS11", "Kospi"), ("^TWII", "Taiwan TAIEX"), ("^NSEI", "India Nifty 50"), ("^BSESN", "India Sensex"),
                      ("^AXJO", "ASX 200"), ("^NZ50", "NZX 50"), ("^STI", "Singapore STI"), ("^JKSE", "Jakarta Composite")]),
    ("Middle East & Africa", [("^TA125.TA", "Tel Aviv 125"), ("XU100.IS", "Borsa Istanbul 100"), ("^J203.JO", "South Africa All Share")]),
    ("Futures", [("ES=F", "S&P 500 fut"), ("NQ=F", "Nasdaq fut"), ("YM=F", "Dow fut"), ("RTY=F", "Russell fut")]),
    ("Rates", [("US3M", "US 3m"), ("US2Y", "US 2y"), ("US5Y", "US 5y"), ("US10Y", "US 10y"), ("US30Y", "US 30y"),
               ("DE2Y-DE", "Germany 2y"), ("DE10Y-DE", "Germany 10y"), ("GB10Y-GB", "UK 10y")]),
    ("FX", [("DX-Y.NYB", "Dollar index"), ("EURUSD=X", "EUR/USD"), ("USDJPY=X", "USD/JPY"), ("GBPUSD=X", "GBP/USD"),
            ("USDCHF=X", "USD/CHF"), ("AUDUSD=X", "AUD/USD"), ("USDCNY=X", "USD/CNY")]),
    ("Commodities", [("GC=F", "Gold"), ("SI=F", "Silver"), ("CL=F", "WTI crude"), ("BZ=F", "Brent"),
                     ("NG=F", "US gas Henry Hub ($/MMBtu)"), ("TTF=F", "EU gas TTF (EUR/MWh)"), ("HG=F", "Copper")]),
    ("Crypto", [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ether"), ("SOL-USD", "Solana")]),
    ("Volatility", [("^VIX", "VIX"), ("^VIX9D", "VIX 9-day"), ("^VIX3M", "VIX 3-month"), ("^VVIX", "VVIX"), ("^MOVE", "MOVE")]),
    ("US sectors", [("XLK", "Technology"), ("XLC", "Communication"), ("XLY", "Discretionary"), ("XLF", "Financials"),
                    ("XLV", "Health care"), ("XLI", "Industrials"), ("XLE", "Energy"), ("XLB", "Materials"),
                    ("XLP", "Staples"), ("XLU", "Utilities"), ("XLRE", "Real estate")]),
]
# Bond yields come from CNBC, which quotes them around the clock; the Cboe indices on Yahoo (^TNX ...) only move in
# US hours, so a European morning showed Friday's close as "today". Cboe stays the fallback and the chart link.
CNBC_YIELDS = {"US3M": "^IRX", "US2Y": None, "US5Y": "^FVX", "US10Y": "^TNX", "US30Y": "^TYX",
               "DE2Y-DE": None, "DE10Y-DE": None, "GB10Y-GB": None, "FR10Y-FR": None, "IT10Y-IT": None, "ES10Y-ES": None}
YIELD_SYMBOLS = {"^IRX", "^FVX", "^TNX", "^TYX"} | set(CNBC_YIELDS)


async def yield_quotes(ctx, symbols: list[str]) -> dict:
    """{symbol: Quote} for CNBC yield symbols; Cboe via Yahoo where CNBC fails. Each quote names its source."""
    want = [s for s in symbols if s in CNBC_YIELDS]
    if not want:
        return {}
    cnbc = ctx.hub.get("cnbc")

    async def build():
        got = await cnbc.quotes(want) if cnbc and cnbc.active() else {}
        return {"quotes": got} if got else {"error": "CNBC returned no yields"}
    data = await ctx.cache.get("yields:" + ",".join(want), 30, build)
    out = {s: {**q, "source": "cnbc"} for s, q in (data.get("quotes") or {}).items()}
    fallback = {CNBC_YIELDS[s]: s for s in want if s not in out and CNBC_YIELDS.get(s)}
    if fallback:
        res = await get_quotes(ctx, list(fallback), intraday=True)
        for ysym, q in (res.get("quotes") or {}).items():
            out[fallback[ysym]] = {**q, "source": q.get("source", "yahoo") + " (Cboe, US hours only)"}
    return out


async def get_quotes(ctx, symbols: list[str], *, intraday: bool = True) -> dict:
    symbols = list(dict.fromkeys(s for s in symbols if s))
    out: dict[str, dict] = {}
    errors = []
    for conn in ctx.hub.candidates("quotes"):
        missing = [s for s in symbols if s not in out]
        if not missing:
            break
        try:
            if conn.id == "yahoo":
                got = await conn.quotes(missing, intraday=intraday)
            else:
                got = await conn.quotes(missing)
        except Exception as exc:
            errors.append(f"{conn.id}: {exc}")
            continue
        for sym, q in (got or {}).items():
            if sym in missing and q.get("price") is not None:
                q["source"] = conn.id
                out[sym] = q
    if errors and not out:
        return {"error": "; ".join(errors)}
    return {"quotes": out, "missing": [s for s in symbols if s not in out], "errors": errors}


async def overview(ctx) -> dict:
    groups = ctx.settings.get("overview_groups") or OVERVIEW
    from . import futures
    fronts = {s: futures.front(s) for _, items in groups for s, _ in items}     # energy: the exchange's front contract
    symbols = [(fronts[s]["symbol"] if fronts[s] else s) for _, items in groups for s, _ in items if s not in CNBC_YIELDS]

    async def build():
        return await get_quotes(ctx, symbols, intraday=True)
    data = await ctx.cache.get("overview:quotes", 20, build)
    if "error" in data:
        return data
    quotes = dict(data.get("quotes", {}))
    try:
        quotes.update(await yield_quotes(ctx, [s for _, items in groups for s, _ in items]))
    except Exception:                                   # yields missing must not take the board down
        pass
    out = []
    for title, items in groups:
        rows = []
        for sym, label in items:
            fr = fronts.get(sym)
            q = quotes.get(fr["symbol"] if fr else sym)
            row = {"symbol": sym, "label": label, **(q or {}), "chart": CNBC_YIELDS.get(sym) or (None if sym in CNBC_YIELDS else sym)}
            if fr:
                row.update({"symbol": fr["symbol"], "chart": fr["symbol"], "label": f"{label} {fr['label']}"})
            if q:   # False = the last quote is from an earlier session (market not open yet, or the feed is still delayed)
                row["traded_today"] = traded_today(q.get("time"))
            if sym in YIELD_SYMBOLS and q and q.get("change") is not None:
                row["change_bp"] = q["change"] * 100          # yields: show the move in basis points
            rows.append(row)
        out.append({"title": title, "rows": rows})
    return {"groups": out, "asof": data.get("asof"), "stale": data.get("stale"), "missing": data.get("missing", [])}
