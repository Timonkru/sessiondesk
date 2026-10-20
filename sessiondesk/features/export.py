"""Read-only data access for spreadsheets and scripts on this computer: Excel / LibreOffice =WEBSERVICE(),
Power Query "From Web", curl, Python. Served under /api/v1/ and authorised with a stable API key that the user
creates (and can replace) in Settings, so a formula keeps working across restarts.

Google Sheets cannot use it: Sheets fetches from Google's servers, which cannot reach 127.0.0.1 - on purpose,
SessionDesk is never exposed to the internet.
"""
from __future__ import annotations

import csv
import io

QUOTE_FIELDS = ("price", "change", "change_pct", "prev_close", "time")
STOCK_FIELDS = ("symbol", "name", "group_label", "industry", "last", "chg1d", "chg5d", "chg20d", "chg60d", "chg1y", "from_high",
                "dist200", "rsi14", "vol20", "market_cap", "pe_fwd", "div_yield")


def to_csv(rows: list[dict], fields: tuple | list) -> str:
    """CSV with a header row; dots as decimal separator (pure, tested)."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(fields)
    def cell(v):
        if v is None:
            return ""
        return round(v, 6) if isinstance(v, float) else v
    for r in rows:
        w.writerow([cell(r.get(f)) for f in fields])
    return out.getvalue()


async def quotes(ctx, symbols: list[str]) -> list[dict]:
    from .markets import get_quotes
    d = await get_quotes(ctx, symbols, intraday=False)
    q = d.get("quotes", d) if isinstance(d, dict) else {}
    out = []
    for s in symbols:
        x = q.get(s) or {}
        out.append({"symbol": s, **{f: x.get(f) for f in QUOTE_FIELDS}})
    return out


async def value(ctx, symbol: str, field: str) -> str:
    """One value as plain text, for =WEBSERVICE(). symbol "hub:<series id>" reads the Data hub (field last / date)."""
    if symbol.startswith("hub:"):
        pts = await ctx.db.run(ctx.db.observations, symbol[4:], 2)
        if not pts:
            return ""
        return pts[-1][0] if field in ("date", "day") else str(pts[-1][1])
    row = (await quotes(ctx, [symbol]))[0]
    v = row.get(field if field in QUOTE_FIELDS else "price")
    return "" if v is None else str(v)


async def history(ctx, symbol: str, range_: str = "1y") -> list[dict]:
    from .stocks import history as hist
    r = range_ if range_ in ("1mo", "3mo", "6mo", "1y", "2y", "5y", "10y") else "1y"
    h = await hist(ctx, symbol, r + "-d")                 # always daily bars ("1mo" alone would be hourly)
    import datetime as dt
    return [{"date": dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).date().isoformat(), "open": b.get("o"), "high": b.get("h"),
             "low": b.get("l"), "close": b.get("c"), "volume": b.get("v")} for b in h.get("bars", [])] if "error" not in h else []
