"""Today: the trading day on one page.

  accounts    equity, P/L since the day start, risk at the stops vs the budget, prop-rule meter
  rule flags  breaches of your own risk rules in the open book
  schedule    your own times (relative to a cash open or absolute) with countdown, holiday-aware,
              and a warning when a high-impact release falls within +-15 minutes
  briefing    AI pre-session briefing / weekly review from computed facts (see ai/assist.py)

Prop rules (settings["prop_rules"]): {"*": {...}, "<account or its last digits>": {...}}
  daily_loss_pct   loss limit from the day-start balance (e.g. 5 for a 5 % daily limit)
  own_stop_pct     your personal tighter day stop (optional)
  max_loss_pct     overall loss limit from initial_balance
  initial_balance  account size the overall limit refers to
  risk_per_trade_pct, max_slots   used for rule flags and "full-risk losers left"
  day_reset_tz     timezone of the day boundary (default Europe/Prague = the CE(S)T midnight most prop firms use)
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

from . import flows

DEFAULT_SESSIONS = {
    "EU": {"open": "09:00", "close": "17:30", "tz": "Europe/Berlin", "calendar": "EU", "markets": "DAX / Euro Stoxx"},
    "US": {"open": "09:30", "close": "16:00", "tz": "America/New_York", "calendar": "US", "markets": "S&P / Nasdaq / Dow"},
}


# ------------------------------------------------------------------ schedule (pure, tested)
def _at(day: dt.date, hhmm: str, tz: str) -> dt.datetime:
    hh, mm = (int(x) for x in hhmm.split(":")[:2])
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=ZoneInfo(tz))


def schedule_for(day: dt.date, sessions: dict, entries: list[dict]) -> list[dict]:
    """Cash open/close of each session plus the user's entries, for one calendar day (holidays skipped).
    Entry: {"label", "session": "EU", "offset_min": 30} (relative to that session's open) or
           {"label", "time": "12:15", "tz": "Europe/Berlin", "session": "EU"} (absolute; session = holiday calendar)."""
    out = []
    for name, s in sessions.items():
        local_day = day
        if not flows.is_business_day(local_day, s.get("calendar", "US")):
            continue
        open_ = _at(local_day, s["open"], s["tz"])
        close = _at(local_day, s["close"], s["tz"])
        out.append({"when": open_, "session": name, "label": "cash open", "markets": s.get("markets", ""), "kind": "session"})
        out.append({"when": close, "session": name, "label": "cash close", "markets": s.get("markets", ""), "kind": "session"})
        for e in entries:
            if e.get("session") != name:
                continue
            if e.get("time"):
                when = _at(local_day, e["time"], e.get("tz") or s["tz"])
            else:
                when = open_ + dt.timedelta(minutes=float(e.get("offset_min", 0)))
            if e.get("only_in_session", True) and not (open_ - dt.timedelta(minutes=60) <= when <= close):
                continue
            out.append({"when": when, "session": name, "label": e.get("label", ""), "markets": e.get("markets") or s.get("markets", ""),
                        "kind": "entry", "note": e.get("note", "")})
    return sorted(out, key=lambda x: x["when"])


def mark_collisions(items: list[dict], events: list[dict], window_min: float = 15) -> list[dict]:
    for it in items:
        ts = it["when"].timestamp()
        it["collisions"] = [f"{e['currency']} {e['title']}" for e in events
                            if e.get("impact") == "high" and abs(e["ts"] - ts) <= window_min * 60]
    return items


# ------------------------------------------------------------------ prop rules (pure, tested)
def rules_for(login: str, rules: dict) -> dict:
    base = dict(rules.get("*", {}))
    for key, val in rules.items():
        if key != "*" and login and (login == key or login.endswith(str(key)[-3:])):
            base.update(val)
    return base


def trading_day(now: float, tz: str = "Europe/Prague") -> str:
    return dt.datetime.fromtimestamp(now, ZoneInfo(tz)).date().isoformat()


def prop_meter(acc: dict, rule: dict, day_start: float | None) -> dict:
    equity = acc.get("equity")
    out = {"login": acc.get("login"), "equity": equity, "currency": acc.get("currency"), "rules": rule}
    if equity is None:
        return out
    extra = acc.get("extra") or {}

    def fx(key):
        try:
            return float(extra[key])
        except (KeyError, TypeError, ValueError):
            return None
    start = fx("day_start_balance") or day_start
    out["day_start"] = start
    out["day_start_source"] = "exporter" if fx("day_start_balance") else "first seen today" if day_start else None
    per_trade = rule.get("risk_per_trade_pct")
    mult = fx("risk_multiplier")
    out["risk_multiplier"] = mult
    if start:
        out["day_pnl"] = equity - start
        out["day_pct"] = (equity - start) / start * 100
        for key in ("daily_loss_pct", "own_stop_pct"):
            if rule.get(key):
                room = rule[key] + out["day_pct"]
                out[key.replace("_pct", "_room_pct")] = room
                out[key.replace("_pct", "_room")] = room / 100 * start
        tightest = min([out[k] for k in ("own_stop_room_pct", "daily_loss_room_pct") if k in out], default=None)
        if tightest is not None and per_trade:
            out["losers_left"] = max(0.0, tightest) / (per_trade * (mult if mult and mult > 0 else 1))
    if rule.get("initial_balance") and rule.get("max_loss_pct"):
        floor = rule["initial_balance"] * (1 - rule["max_loss_pct"] / 100)
        out["max_loss_room"] = equity - floor
        out["max_loss_room_pct"] = (equity - floor) / rule["initial_balance"] * 100
    high = fx("all_time_high") or fx("equity_high")
    if high:
        out["from_high_pct"] = (equity - high) / high * 100
    return out


def rule_flags(accounts: list[dict], positions: list[dict], rules: dict) -> list[dict]:
    flags = []
    by_acc: dict[str, list[dict]] = {}
    for p in positions:
        by_acc.setdefault(p.get("account"), []).append(p)
    for acc in accounts:
        login = acc.get("login")
        rule = rules_for(login or "", rules)
        own = by_acc.get(login, [])
        eq = acc.get("equity")
        per_trade, slots = rule.get("risk_per_trade_pct"), rule.get("max_slots")
        for p in own:
            if not p.get("sl"):
                flags.append({"level": "high", "account": login, "text": f"{p['symbol']} {p['side']} has no stop"})
            elif per_trade and eq and p.get("risk_to_stop") and p["risk_to_stop"] / eq * 100 > per_trade * 1.05:
                flags.append({"level": "high", "account": login,
                              "text": f"{p['symbol']} risks {p['risk_to_stop'] / eq * 100:.2f}% (budget {per_trade}%)"})
            if p.get("manual"):
                flags.append({"level": "info", "account": login, "text": f"{p['symbol']} {p['side']} was opened by hand"})
        if slots and len(own) > slots:
            flags.append({"level": "high", "account": login, "text": f"{len(own)} open positions (max {slots})"})
        book = sum(p.get("risk_to_stop") or 0 for p in own)
        if per_trade and slots and eq and book / eq * 100 > per_trade * slots * 1.05:
            flags.append({"level": "high", "account": login, "text": f"book risk {book / eq * 100:.2f}% (budget {per_trade * slots:.2f}%)"})
    return flags


# ------------------------------------------------------------------ assembly
async def snapshot(ctx) -> dict:
    from . import broker as broker_view
    now = time.time()
    rules = ctx.settings.get("prop_rules") or {}
    b = await broker_view.overview(ctx)
    accounts, positions = b.get("accounts", []), [p for p in b.get("positions", []) if p.get("fresh", True)]
    meters = []
    for acc in accounts:
        rule = rules_for(acc.get("login") or "", rules)
        day = trading_day(now, rule.get("day_reset_tz", "Europe/Prague"))
        ds = await ctx.db.run(ctx.db.day_start, acc.get("login"), day, acc.get("balance"), acc.get("equity")) if acc.get("fresh") else {}
        # Day figures from an export that is hours or days old would describe another day: equity only.
        m = prop_meter(acc, rule, (ds or {}).get("balance")) if acc.get("fresh") else             {"login": acc.get("login"), "equity": acc.get("equity"), "currency": acc.get("currency"), "rules": rule}
        m["fresh"] = acc.get("fresh")
        m["age"] = acc.get("age")
        m["risk_to_stops"], m["risk_pct"] = acc.get("risk_to_stops"), acc.get("risk_pct")
        m["positions"] = sum(1 for p in positions if p.get("account") == acc.get("login"))
        m["trade_allowed"] = acc.get("trade_allowed")
        meters.append(m)
    cal = await ctx.extras["calendar"].events(now - 3600, now + 36 * 3600)
    events = [e for e in cal.get("events", []) if e.get("impact") in ("high", "medium")]
    sessions = ctx.settings.get("sessions") or DEFAULT_SESSIONS
    entries = ctx.settings.get("schedule") or []
    today = dt.date.today()
    sched = schedule_for(today, sessions, entries) + schedule_for(today + dt.timedelta(days=1), sessions, entries)
    sched = [s for s in sched if s["when"].timestamp() >= now - 1800][:30]
    mark_collisions(sched, events)
    flows_soon = [f for f in flows.events_between(today, today + dt.timedelta(days=5)) if f["size"] != "low"]
    return {"accounts": meters, "flags": rule_flags(accounts, positions, rules), "positions": positions,
            "schedule": [{**s, "when": s["when"].timestamp(), "in_sec": s["when"].timestamp() - now} for s in sched],
            "events": [e for e in events if e["ts"] >= now - 3600][:20], "flows": flows_soon,
            "connected": b.get("connected", False), "asof": now}


async def briefing_facts(ctx, kind: str = "briefing") -> dict:
    """Facts for the AI: everything computed by SessionDesk, compact."""
    if kind == "review":
        from .review import build_facts
        return await build_facts(ctx)
    from .briefing import build_facts
    return await build_facts(ctx)
