"""Cross-asset overview and the shared quote service.

get_quotes() asks the preferred quote connectors in order and lets each one fill only the symbols
the previous one could not deliver (a US-only paid feed + Yahoo for indices, FX and Europe).
Every quote carries the connector it came from.
"""
from __future__ import annotations

OVERVIEW: list[tuple[str, list[tuple[str, str]]]] = [
    ("Americas", [("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100"), ("^DJI", "Dow Jones"), ("^RUT", "Russell 2000"),
                  ("^GSPTSE", "Canada TSX"), ("^MXX", "Mexico IPC"), ("^BVSP", "Brazil Bovespa"), ("^MERV", "Argentina Merval")]),
    ("Europe", [("^GDAXI", "DAX"), ("^STOXX50E", "Euro Stoxx 50"), ("^STOXX", "Stoxx 600"), ("^FTSE", "FTSE 100"),
                ("^FCHI", "CAC 40"), ("^SSMI", "SMI"), ("FTSEMIB.MI", "FTSE MIB"), ("^IBEX", "IBEX 35"), ("^AEX", "AEX"),
                ("^OMX", "OMX Stockholm 30"), ("^BFX", "BEL 20"), ("^ATX", "ATX")]),
    ("Asia-Pacific", [("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("000001.SS", "Shanghai Composite"), ("399001.SZ", "Shenzhen Component"),
                      ("^KS11", "Kospi"), ("^TWII", "Taiwan TAIEX"), ("^NSEI", "India Nifty 50"), ("^BSESN", "India Sensex"),
                      ("^AXJO", "ASX 200"), ("^NZ50", "NZX 50"), ("^STI", "Singapore STI"), ("^JKSE", "Jakarta Composite")]),
    ("Middle East & Africa", [("^TA125.TA", "Tel Aviv 125"), ("XU100.IS", "Borsa Istanbul 100"), ("^J203.JO", "South Africa All Share")]),
    ("Futures", [("ES=F", "S&P 500 fut"), ("NQ=F", "Nasdaq fut"), ("YM=F", "Dow fut"), ("RTY=F", "Russell fut")]),
    ("Rates", [("^IRX", "US 3m"), ("^FVX", "US 5y"), ("^TNX", "US 10y"), ("^TYX", "US 30y")]),
    ("FX", [("DX-Y.NYB", "Dollar index"), ("EURUSD=X", "EUR/USD"), ("USDJPY=X", "USD/JPY"), ("GBPUSD=X", "GBP/USD"),
            ("USDCHF=X", "USD/CHF"), ("AUDUSD=X", "AUD/USD"), ("USDCNY=X", "USD/CNY")]),
    ("Commodities", [("GC=F", "Gold"), ("SI=F", "Silver"), ("CL=F", "WTI crude"), ("BZ=F", "Brent"),
                     ("NG=F", "Natural gas"), ("HG=F", "Copper")]),
    ("Crypto", [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ether"), ("SOL-USD", "Solana")]),
    ("Volatility", [("^VIX", "VIX"), ("^VIX9D", "VIX 9-day"), ("^VIX3M", "VIX 3-month"), ("^VVIX", "VVIX"), ("^MOVE", "MOVE")]),
    ("US sectors", [("XLK", "Technology"), ("XLC", "Communication"), ("XLY", "Discretionary"), ("XLF", "Financials"),
                    ("XLV", "Health care"), ("XLI", "Industrials"), ("XLE", "Energy"), ("XLB", "Materials"),
                    ("XLP", "Staples"), ("XLU", "Utilities"), ("XLRE", "Real estate")]),
]
YIELD_SYMBOLS = {"^IRX", "^FVX", "^TNX", "^TYX"}


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
    symbols = [s for _, items in groups for s, _ in items]

    async def build():
        return await get_quotes(ctx, symbols, intraday=True)
    data = await ctx.cache.get("overview:quotes", 20, build)
    if "error" in data:
        return data
    quotes = data.get("quotes", {})
    out = []
    for title, items in groups:
        rows = []
        for sym, label in items:
            q = quotes.get(sym)
            row = {"symbol": sym, "label": label, **(q or {})}
            if sym in YIELD_SYMBOLS and q and q.get("change") is not None:
                row["change_bp"] = q["change"] * 100          # yields: show the move in basis points
            rows.append(row)
        out.append({"title": title, "rows": rows})
    return {"groups": out, "asof": data.get("asof"), "stale": data.get("stale"), "missing": data.get("missing", [])}
