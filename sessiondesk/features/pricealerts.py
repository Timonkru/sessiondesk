"""Price alerts you set yourself: "tell me when AAPL trades above 350" / "... when ^GDAXI falls below 23000".

One-shot: an alert fires once when its condition is met on a check (every 15 s) and is then marked
triggered; "re-arm" sets it active again. Prices come from the same quote service as every page (broker
quotes where a connector provides them, otherwise the free delayed feed), so the alert is as fast and
as delayed as that source - it is a notice, not an order.
Stored in <data dir>/price_alerts.json.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
OPS = {"above": lambda p, lvl: p >= lvl, "below": lambda p, lvl: p <= lvl}


def _path(ctx) -> Path:
    return ctx.data_dir / "price_alerts.json"


def load(ctx) -> list[dict]:
    try:
        return json.loads(_path(ctx).read_text(encoding="utf-8")).get("alerts", [])
    except (OSError, ValueError):
        return []


def save(ctx, alerts: list[dict]) -> None:
    from ..settings import _write_private
    with _LOCK:
        _write_private(_path(ctx), {"alerts": alerts})


def create(ctx, symbol: str, op: str, level: float, note: str = "") -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol or op not in OPS:
        return {"error": "symbol and 'above' or 'below' are required"}
    try:
        level = float(level)
    except (TypeError, ValueError):
        return {"error": "the price must be a number"}
    alert = {"id": secrets.token_hex(6), "symbol": symbol, "op": op, "level": level, "note": (note or "").strip()[:200],
             "created": time.time(), "active": True, "triggered": None, "price_at_trigger": None}
    alerts = load(ctx) + [alert]
    save(ctx, alerts)
    return {"alert": alert, "alerts": alerts}


def update(ctx, alert_id: str, *, delete: bool = False, rearm: bool = False) -> dict:
    alerts = load(ctx)
    if delete:
        alerts = [a for a in alerts if a["id"] != alert_id]
    for a in alerts:
        if a["id"] == alert_id and rearm:
            a.update(active=True, triggered=None, price_at_trigger=None)
    save(ctx, alerts)
    return {"alerts": alerts}


def check(alerts: list[dict], quotes: dict[str, dict], now: float) -> list[dict]:
    """Pure: mark and return the alerts whose condition is met now (mutates the list entries)."""
    fired = []
    for a in alerts:
        if not a.get("active"):
            continue
        q = quotes.get(a["symbol"]) or {}
        price = q.get("price")
        if price is None:
            continue
        if OPS[a["op"]](price, a["level"]):
            a.update(active=False, triggered=now, price_at_trigger=price)
            fired.append(a)
    return fired


async def run_check(ctx) -> list[dict]:
    alerts = load(ctx)
    symbols = sorted({a["symbol"] for a in alerts if a.get("active")})
    if not symbols:
        return []
    from .markets import get_quotes
    res = await get_quotes(ctx, symbols, intraday=False)
    fired = check(alerts, res.get("quotes", {}), time.time())
    if fired:
        # re-read before saving: an alert created during the quote call must not be lost
        current = {a["id"]: a for a in load(ctx)}
        for a in fired:
            if a["id"] in current:
                current[a["id"]].update(active=False, triggered=a["triggered"], price_at_trigger=a["price_at_trigger"])
        save(ctx, list(current.values()))
        for a in fired:
            word = "above" if a["op"] == "above" else "below"
            ctx.broker.publish("price_alert", {"alert": {
                "id": a["id"], "symbol": a["symbol"], "title": f"{a['symbol']} {word} {a['level']:g}",
                "body": f"traded at {a['price_at_trigger']:g}" + (f" - {a['note']}" if a["note"] else ""), "data": a}})
    return fired


async def listing(ctx) -> dict:
    alerts = load(ctx)
    symbols = sorted({a["symbol"] for a in alerts})
    quotes = {}
    if symbols:
        from .markets import get_quotes
        quotes = (await get_quotes(ctx, symbols, intraday=False)).get("quotes", {})
    rows = []
    for a in sorted(alerts, key=lambda x: (not x.get("active"), -(x.get("triggered") or x.get("created") or 0))):
        price = (quotes.get(a["symbol"]) or {}).get("price")
        rows.append({**a, "price": price, "distance_pct": (a["level"] / price - 1) * 100 if price else None})
    return {"alerts": rows, "note": "One-shot alerts, checked every 15 seconds against the same quotes the pages show "
                                   "(delayed on free data). They notify; they never trade."}
