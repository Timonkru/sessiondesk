"""BTC near the short-term holder realized price (STH-RP): an alert when the price comes within ± band dollars of it,
or jumps across it between two checks.

One alert per visit: after firing, the zone has to be left by band + rearm dollars before it can fire again, so a price
hovering at the edge does not alert on every check. The STH-RP is a daily value (features/onchain.py); when the newest
one is older than max_age_days the alert pauses and says so instead of measuring the price against an old level.
The state lives in <data dir>/sth_zone_state.json: a restart neither repeats an alert nor fires for a price that was
already inside the zone (the first check after install only records where the price is).
A notice, never an order; the level describes where recent buyers sit on average, it is not a tested signal.
"""
from __future__ import annotations

import datetime as dt
import json
import time

DEFAULTS = {"enabled": True, "band": 200.0, "rearm": 50.0, "max_age_days": 3, "symbol": "BTC-USD"}
PRIMARY, SECOND = "onchain:sth_rp", "onchain:sth_rp_bgeo"


def config(settings) -> dict:
    out = {**DEFAULTS, **(settings.get("sth_zone") or {})}
    out["band"] = max(1.0, float(out["band"]))
    out["rearm"] = max(0.0, float(out["rearm"]))
    return out


def step(state: dict | None, price: float, level: float, band: float, rearm: float) -> tuple[dict, dict | None]:
    """One check (pure, tested). state {"inside": bool, "side": "above"|"below"} -> (new state, event or None).
    Event {"type": "enter"|"cross", "from": side}: entering the zone, or crossing the level between two checks."""
    diff = price - level
    side = "above" if diff >= 0 else "below"
    near = abs(diff) <= band
    if not state:                                  # first check: record, do not alert for where the price already is
        return {"inside": near, "side": side}, None
    crossed = state.get("side") not in (None, side)
    if not state.get("inside") and (near or crossed):
        return {"inside": True, "side": side}, {"type": "cross" if crossed else "enter", "from": state.get("side")}
    if state.get("inside") and abs(diff) > band + rearm:
        return {"inside": False, "side": side}, None
    return {**state, "side": side}, None


def _state_path(ctx):
    return ctx.data_dir / "sth_zone_state.json"


def load_state(ctx) -> dict:
    try:
        return json.loads(_state_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(ctx, state: dict) -> None:
    try:
        _state_path(ctx).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


async def level(ctx) -> dict:
    """Newest STH-RP with its date, age and source, plus the second source on its latest common day."""
    from .datahub import source_url
    a = await ctx.db.run(ctx.db.observations, PRIMARY, 400)
    b = await ctx.db.run(ctx.db.observations, SECOND, 400)
    use, sid = (a, PRIMARY) if a and (not b or a[-1][0] >= b[-1][0]) else (b, SECOND)
    if not use:
        return {"error": "no STH realized price collected yet - Data hub → collect now, or wait for the next run"}
    day, value = use[-1]
    age = (dt.date.today() - dt.date.fromisoformat(day)).days
    out = {"value": value, "day": day, "age_days": age, "series": sid, "url": source_url(sid),
           "prev": use[-2][1] if len(use) > 1 else None}
    if a and b:
        common = sorted(set(d for d, _ in a) & set(d for d, _ in b))
        if common:
            d = common[-1]
            va, vb = dict(a)[d], dict(b)[d]
            out["check"] = {"day": d, "checkonchain": va, "bgeometrics": vb, "diff": va - vb}
    return out


async def btc_price(ctx, symbol: str) -> dict | None:
    from .markets import get_quotes

    async def build():
        return await get_quotes(ctx, [symbol], intraday=False)
    data = await ctx.cache.get("sth:quote:" + symbol, 15, build)
    return (data.get("quotes") or {}).get(symbol)


async def status(ctx) -> dict:
    cfg = config(ctx.settings)
    lv = await level(ctx)
    q = await btc_price(ctx, cfg["symbol"])
    st = load_state(ctx)
    out = {"config": cfg, "level": lv, "price": (q or {}).get("price"), "price_time": (q or {}).get("time"), "state": st,
           "note": "STH realized price = average cost basis of coins moved within 155 days (daily value). Alert once when "
                   f"BTC comes within ± band of it or crosses it; again only after leaving the zone by band + {cfg['rearm']:g} $. "
                   "Paused when the level is older than max_age_days. Describes where recent buyers sit; not a tested signal."}
    if "error" not in lv and out["price"] is not None:
        out["diff"] = out["price"] - lv["value"]
        out["zone"] = [lv["value"] - cfg["band"], lv["value"] + cfg["band"]]
        out["paused"] = lv["age_days"] > cfg["max_age_days"]
    return out


async def run_check(ctx) -> dict | None:
    """Background check (every 30 s). Returns the alert it published, if any."""
    cfg = config(ctx.settings)
    if not cfg["enabled"]:
        return None
    lv = await level(ctx)
    if "error" in lv or lv["age_days"] > cfg["max_age_days"]:
        return None
    q = await btc_price(ctx, cfg["symbol"])
    if not q or q.get("price") is None:
        return None
    price = float(q["price"])
    state, event = step(load_state(ctx), price, lv["value"], cfg["band"], cfg["rearm"])
    save_state(ctx, state)
    if not event:
        return None
    now = time.time()
    diff = price - lv["value"]
    how = (f"crossed the short-term holder cost basis from {event['from']}" if event["type"] == "cross"
           else f"within {cfg['band']:g} $ of the short-term holder cost basis ({diff:+,.0f} $)")
    alert = {"id": f"sth:{lv['day']}:{int(now)}", "ts": now, "kind": "sth", "symbol": cfg["symbol"],
             "title": f"BTC {price:,.0f} {how}",
             "body": f"STH realized price {lv['value']:,.0f} $ ({lv['day']}, {lv['series'].split(':')[1]}); zone "
                     f"{lv['value'] - cfg['band']:,.0f} to {lv['value'] + cfg['band']:,.0f} $.",
             "data": {"source": "sth", "triggered": now, "price": price, "level": lv["value"], "day": lv["day"], **event}}
    if ctx.db:
        await ctx.db.run(ctx.db.add_alert, alert)
    ctx.broker.publish("price_alert", {"alert": alert})       # same path as your own alerts: toast, sound, phone push
    return alert
