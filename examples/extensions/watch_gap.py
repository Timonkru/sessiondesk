"""Example SessionDesk extension: your watchlist sorted by today's move, with a note line.

Copy this file to ~/.sessiondesk/extensions/ (or <data dir>/extensions/), then Settings -> Extensions -> "Save & reload",
or restart SessionDesk. It shows up in the navigation as "Watchlist by move". See docs/EXTENSIONS.md.
"""
from sessiondesk.features.markets import get_quotes

TITLE = "Watchlist by move"
DESCRIPTION = "example extension: the watchlist sorted by today's change"
REFRESH = 30


async def page(ctx) -> dict:
    symbols = list(ctx.settings.get("watchlist") or [])
    res = await get_quotes(ctx, symbols, intraday=False)
    rows = sorted(({"symbol": s, "price": q.get("price"), "change": q.get("change_pct")} for s, q in res.get("quotes", {}).items()),
                  key=lambda r: r["change"] if r["change"] is not None else 0)
    return {"blocks": [
        {"type": "kv", "title": "Summary", "items": [["Symbols", len(symbols)], ["With a quote", len(rows)],
                                                    ["Up", sum(1 for r in rows if (r["change"] or 0) > 0)]]},
        {"type": "table", "title": "Today", "columns": [
            {"key": "symbol", "label": "Symbol"}, {"key": "price", "label": "Price", "num": True}, {"key": "chg", "label": "Change", "num": True}],
         "rows": [{**r, "chg": "–" if r["change"] is None else f"{r['change']:+.2f}%",
                   "_level": "high" if r["change"] is not None and abs(r["change"]) >= 3 else None} for r in rows],
         "empty": "No quotes - is the watchlist empty?"},
        {"type": "note", "text": "Rows marked like a warning moved 3 % or more. Edit this file to make the page your own."},
    ]}
