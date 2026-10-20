"""Alerts you set yourself, on any number SessionDesk has:

  quote   a price or today's change          "AAPL price above 350", "^GDAXI change_pct below -2"
  hub     any Data hub series                "fred:BAMLH0A0HYM2 last above 5", "eia:... change below -5", "power:de-lu z above 3"
  stock   a stock's measures                 "SAP.DE rsi14 below 30", "NVDA from_high below -20", "AAPL dist200 below 0"
  basket  any member of one of your baskets  "basket <id>: rsi14 below 30" - fires once, naming the members that meet it

One-shot: an alert fires once when its condition is met on a check (every 15 s; hub and stock values change at their
own pace) and is then marked triggered; "re-arm" sets it active again. Values come from the same services as every
page (delayed on free data) - a notice, never an order. Stored in <data dir>/price_alerts.json (the name stays for
alerts created before other sources existed: those are quote/price alerts).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
OPS = {"above": lambda p, lvl: p >= lvl, "below": lambda p, lvl: p <= lvl}
FIELDS = {
    "quote": {"price": "price", "change_pct": "change today %"},
    "hub": {"last": "latest value", "change": "latest change", "z": "z of the latest change (unusual if |z| ≥ 3)"},
    "stock": {"rsi14": "RSI 14", "from_high": "% from 52-week high", "dist200": "% from 200-day average", "chg1d": "change today %",
              "chg5d": "change 5 days %", "chg20d": "change 20 days %", "chg60d": "change 60 days %", "vol20": "volatility 20 days %"},
}
FIELDS["basket"] = FIELDS["stock"]


def _path(ctx) -> Path:
    return ctx.data_dir / "price_alerts.json"


def load(ctx) -> list[dict]:
    try:
        alerts = json.loads(_path(ctx).read_text(encoding="utf-8")).get("alerts", [])
    except (OSError, ValueError):
        return []
    for a in alerts:                       # alerts from before sources existed are quote/price alerts
        a.setdefault("source", "quote")
        a.setdefault("field", "price")
    return alerts


def save(ctx, alerts: list[dict]) -> None:
    from ..settings import _write_private
    with _LOCK:
        _write_private(_path(ctx), {"alerts": alerts})


def create(ctx, symbol: str, op: str, level: float, note: str = "", source: str = "quote", field: str = "price") -> dict:
    source = source if source in FIELDS else "quote"
    symbol = (symbol or "").strip()
    if source in ("quote", "stock"):
        symbol = symbol.upper()
    if not symbol or op not in OPS:
        return {"error": "a target and 'above' or 'below' are required"}
    if field not in FIELDS[source]:
        return {"error": f"field must be one of: {', '.join(FIELDS[source])}"}
    try:
        level = float(level)
    except (TypeError, ValueError):
        return {"error": "the value must be a number"}
    alert = {"id": secrets.token_hex(6), "source": source, "symbol": symbol, "field": field, "op": op, "level": level,
             "note": (note or "").strip()[:200], "created": time.time(), "active": True, "triggered": None,
             "price_at_trigger": None, "matches": None}
    alerts = load(ctx) + [alert]
    save(ctx, alerts)
    return {"alert": alert, "alerts": alerts}


def update(ctx, alert_id: str, *, delete: bool = False, rearm: bool = False) -> dict:
    alerts = load(ctx)
    if delete:
        alerts = [a for a in alerts if a["id"] != alert_id]
    for a in alerts:
        if a["id"] == alert_id and rearm:
            a.update(active=True, triggered=None, price_at_trigger=None, matches=None)
    save(ctx, alerts)
    return {"alerts": alerts}


def check(alerts: list[dict], values: dict, now: float) -> list[dict]:
    """Pure: mark and return the alerts whose condition is met now (mutates the list entries).
    values: alert id -> number, or for basket alerts -> {member: number}."""
    fired = []
    for a in alerts:
        if not a.get("active"):
            continue
        v = values.get(a["id"])
        if v is None:
            continue
        if isinstance(v, dict):
            hits = {m: x for m, x in v.items() if x is not None and OPS[a["op"]](x, a["level"])}
            if hits:
                a.update(active=False, triggered=now, matches=sorted(hits, key=hits.get, reverse=a["op"] == "above")[:10],
                         price_at_trigger=hits[sorted(hits, key=hits.get, reverse=a["op"] == "above")[0]])
                fired.append(a)
        elif OPS[a["op"]](v, a["level"]):
            a.update(active=False, triggered=now, price_at_trigger=v)
            fired.append(a)
    return fired


async def _stock_metrics(ctx, symbol: str) -> dict:
    from .screener import metrics
    from .stocks import history
    h = await history(ctx, symbol, "1y")
    closes = [b["c"] for b in h.get("bars", [])] if "error" not in h else []
    return metrics(closes) or {}


async def values_for(ctx, alerts: list[dict], only_active: bool = True) -> dict:
    """Current value of every alert's target."""
    todo = [a for a in alerts if a.get("active") or not only_active]
    out: dict = {}
    quote_syms = sorted({a["symbol"] for a in todo if a["source"] == "quote"})
    if quote_syms:
        from .markets import get_quotes
        q = (await get_quotes(ctx, quote_syms, intraday=False)).get("quotes", {})
        for a in todo:
            if a["source"] == "quote":
                out[a["id"]] = (q.get(a["symbol"]) or {}).get(a["field"])
    from .datahub import assess
    series_kind = {s["id"]: s["kind"] for s in await ctx.db.run(ctx.db.series_list)} if any(a["source"] == "hub" for a in todo) else {}
    stock_cache: dict[str, dict] = {}
    for a in todo:
        if a["source"] == "hub":
            pts = await ctx.db.run(ctx.db.observations, a["symbol"], 400)
            if not pts:
                continue
            if a["field"] == "last":
                out[a["id"]] = pts[-1][1]
            else:
                r = assess(pts, series_kind.get(a["symbol"], "level"))
                out[a["id"]] = r.get(a["field"]) if r else None
        elif a["source"] in ("stock", "basket"):
            if a["source"] == "stock":
                members = [a["symbol"]]
            else:
                b = next((x for x in (ctx.settings.get("baskets") or []) if x.get("id") == a["symbol"]), None)
                members = [m["symbol"] for m in (b or {}).get("members", [])]
            vals = {}
            for m in members:
                if m not in stock_cache:
                    stock_cache[m] = await _stock_metrics(ctx, m)
                vals[m] = stock_cache[m].get(a["field"])
            out[a["id"]] = vals.get(a["symbol"]) if a["source"] == "stock" else vals
    return out


async def _labels(ctx) -> dict:
    """Readable names for baskets and Data hub series (alerts store their ids)."""
    out = {("basket", b["id"]): b["name"] for b in (ctx.settings.get("baskets") or [])}
    for s in await ctx.db.run(ctx.db.series_list):
        out[("hub", s["id"])] = s["name"]
    return out


def title(a: dict) -> str:
    field = FIELDS.get(a["source"], {}).get(a["field"], a["field"])
    word = "above" if a["op"] == "above" else "below"
    target = a.get("label") or a["symbol"]
    if a["source"] == "quote" and a["field"] == "price":
        return f"{target} {word} {a['level']:g}"
    if a["source"] == "basket":
        return f"basket {target}: a member's {field} {word} {a['level']:g}"
    return f"{target} {field} {word} {a['level']:g}"


async def run_check(ctx) -> list[dict]:
    alerts = load(ctx)
    if not any(a.get("active") for a in alerts):
        return []
    values = await values_for(ctx, alerts)
    fired = check(alerts, values, time.time())
    if fired:
        # re-read before saving: an alert created during the value calls must not be lost
        current = {a["id"]: a for a in load(ctx)}
        for a in fired:
            if a["id"] in current:
                current[a["id"]].update(active=False, triggered=a["triggered"], price_at_trigger=a["price_at_trigger"],
                                        matches=a.get("matches"))
        save(ctx, list(current.values()))
        names = await _labels(ctx)
        for a in fired:
            a["label"] = names.get((a["source"], a["symbol"]), a["symbol"])
            if a["source"] == "basket":
                body = "now: " + ", ".join(a.get("matches") or [])
            else:
                body = f"now {a['price_at_trigger']:g}"
            ctx.broker.publish("price_alert", {"alert": {
                "id": a["id"], "symbol": a["symbol"], "title": title(a),
                "body": body + (f" - {a['note']}" if a["note"] else ""), "data": a}})
    return fired


async def listing(ctx) -> dict:
    alerts = load(ctx)
    values = await values_for(ctx, alerts, only_active=False) if alerts else {}
    names = await _labels(ctx)
    rows = []
    for a in sorted(alerts, key=lambda x: (not x.get("active"), -(x.get("triggered") or x.get("created") or 0))):
        v = values.get(a["id"])
        if isinstance(v, dict):                      # basket: show the member closest to the condition
            known = {m: x for m, x in v.items() if x is not None}
            best = (max if a["op"] == "above" else min)(known, key=known.get) if known else None
            v_show, near = (known[best], best) if best else (None, None)
        else:
            v_show, near = v, None
        label = names.get((a["source"], a["symbol"]), a["symbol"])
        price = v_show if a["source"] == "quote" and a["field"] == "price" else None
        rows.append({**a, "label": label, "title": title({**a, "label": label}), "value": v_show, "nearest": near, "price": price,
                     "distance_pct": (a["level"] / price - 1) * 100 if price else None})
    return {"alerts": rows, "fields": FIELDS,
            "note": "One-shot alerts, checked every 15 seconds against the same values the pages show (delayed on free data; "
                    "Data hub series update at their own pace, stock measures from daily closes). They notify; they never trade."}
