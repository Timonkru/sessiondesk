"""Trade journal: every closed position with net result, initial risk and R, plus your note.

Initial risk:
  observed   money at risk to the stop when SessionDesk FIRST saw the position (a stop moved before that is
             invisible - so it is only a proxy)
  confirmed  what you enter yourself (e.g. from your entry log); always wins over the observed value
R = net / initial risk. Stats per setup use only trades with a known risk and say how many that is.
"""
from __future__ import annotations

import statistics
import time
from collections import defaultdict

_last_deal_sync = {"ts": 0.0}


def position_key(p: dict) -> str | None:
    return str(p.get("position_id") or p.get("ticket") or "") or None


async def sync(ctx, overview: dict) -> None:
    """Record first-seen risk of open positions; every 60 s fold closed positions from the deal history in."""
    now = time.time()
    for p in overview.get("positions", []):
        key = position_key(p)
        if not key or not p.get("fresh", True):
            continue
        await ctx.db.run(ctx.db.journal_upsert, {
            "account": p.get("account"), "position_id": key, "symbol": p.get("symbol"), "side": p.get("side"),
            "magic": p.get("magic"), "opened": p.get("open_time"), "closed": None, "net": None,
            "risk_observed": p.get("risk_to_stop") or None,
            "context": f"first seen {time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}, stop {p.get('sl') or 'none'}"})
    if now - _last_deal_sync["ts"] < 60:
        return
    _last_deal_sync["ts"] = now
    mt5 = ctx.hub.get("mt5")
    if not mt5 or not mt5.active():
        return
    try:
        deals = await mt5.deals()
    except Exception:
        return
    for row in closed_positions(deals):
        await ctx.db.run(ctx.db.journal_upsert, row)


def closed_positions(deals: list[dict]) -> list[dict]:
    pos: dict[tuple, dict] = {}
    for d in sorted(deals, key=lambda x: x.get("time") or 0):
        key = (d.get("account"), str(d.get("position_id")))
        r = pos.setdefault(key, {"account": key[0], "position_id": key[1], "symbol": d.get("symbol"), "side": None, "magic": None,
                                 "opened": None, "closed": None, "net": 0.0, "has_exit": False})
        r["net"] += d.get("net") or 0.0
        if d.get("entry") == "0":
            if r["opened"] is None:
                r["opened"], r["magic"] = d.get("time"), d.get("magic") or "0"
                r["side"] = "LONG" if d.get("type") == "BUY" else "SHORT"
        elif d.get("entry") in ("1", "2", "3"):
            r["has_exit"] = True
            r["closed"] = d.get("time")
    return [r for r in pos.values() if r["has_exit"] and r["opened"]]


def r_multiple(row: dict) -> float | None:
    risk = row.get("risk_confirmed") or row.get("risk_observed")
    if not risk or risk <= 0 or row.get("net") is None:
        return None
    return row["net"] / risk


def stats(rows: list[dict], names: dict) -> list[dict]:
    """Per account and setup: accounts can hold different currencies, so their money is never added up."""
    per: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r.get("closed"):
            per[(r.get("account"), str(r.get("magic") or "0"))].append(r)
    out = []
    for (account, magic), trades in per.items():
        rs = [x for x in (r_multiple(t) for t in trades) if x is not None]
        out.append({"account": account, "setup": "manual" if magic == "0" else names.get(magic, f"magic {magic}"), "magic": magic,
                    "trades": len(trades), "net": sum(t.get("net") or 0 for t in trades),
                    "with_risk": len(rs), "avg_r": statistics.mean(rs) if rs else None,
                    "se_r": statistics.stdev(rs) / len(rs) ** 0.5 if len(rs) > 2 else None,
                    "win_rate": sum((t.get("net") or 0) > 0 for t in trades) / len(trades)})
    return sorted(out, key=lambda x: -x["trades"])


def curves(closed: list[dict], days: int) -> dict:
    """Per account: cumulative net after each closed trade, and net per day (per week beyond 90 days)."""
    out: dict[str, dict] = {}
    weekly = days > 90
    for r in sorted(closed, key=lambda x: x.get("closed") or 0):
        acc = out.setdefault(r.get("account") or "?", {"cum": [], "periods": defaultdict(float), "total": 0.0})
        acc["total"] += r.get("net") or 0
        acc["cum"].append({"t": r["closed"], "v": round(acc["total"], 2)})
        d = time.localtime(r["closed"])
        key = time.strftime("%G-W%V", d) if weekly else time.strftime("%Y-%m-%d", d)
        acc["periods"][key] += r.get("net") or 0
    return {a: {"cum": v["cum"], "periods": [{"label": k, "net": round(n, 2)} for k, n in sorted(v["periods"].items())],
                "total": v["total"], "period": "week" if weekly else "day"} for a, v in out.items()}


def day_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def start_balances(closed: list[dict], balance_now: float | None, days: list[str], stored: dict | None = None) -> dict:
    """Balance at the start of each day: the stored day start where SessionDesk saw it, otherwise today's balance minus
    the net of every trade closed on or after that day. Deposits, withdrawals and fees outside trades are not in the
    journal, so the reconstruction is an approximation (pure, tested)."""
    out = {}
    for d in days:
        if stored and stored.get(d):
            out[d] = stored[d]
        elif balance_now is not None:
            out[d] = balance_now - sum(r.get("net") or 0 for r in closed if r.get("closed") and day_key(r["closed"]) >= d)
    return out


def with_pct(cv: dict, rows: list[dict], balances: dict) -> None:
    """Adds percent of the day's start balance to curves (cumulative, per period) and to each trade (mutates)."""
    for acc, c in cv.items():
        sb = balances.get(acc) or {}
        first = sb.get(min(sb)) if sb else None
        for p in c["cum"]:
            p["pct"] = p["v"] / first * 100 if first else None
        for per in c["periods"]:
            base = sb.get(per["label"])
            if base is None and "-W" in per["label"]:              # weekly bars: the first traded day of that week
                week_days = sorted(d for d in sb if time.strftime("%G-W%V", time.strptime(d, "%Y-%m-%d")) == per["label"])
                base = sb.get(week_days[0]) if week_days else None
            per["pct"] = per["net"] / base * 100 if base else None
        c["base"] = first
    for r in rows:
        base = (balances.get(r.get("account")) or {}).get(day_key(r["closed"])) if r.get("closed") else None
        r["pct"] = (r.get("net") or 0) / base * 100 if base else None


async def _balances(ctx, closed_all: list) -> tuple:
    accounts = {}
    try:
        from . import broker
        accounts = {a.get("login"): a for a in (await broker.overview(ctx)).get("accounts", [])}
    except Exception:
        pass
    stored = await ctx.db.run(ctx.db.day_starts)
    out = {}
    for acc in {r.get("account") for r in closed_all}:
        own = [r for r in closed_all if r.get("account") == acc]
        days = sorted({day_key(r["closed"]) for r in own if r.get("closed")})
        bal = (accounts.get(acc) or {}).get("balance")
        out[acc] = start_balances(own, bal, days, {d: v for (a, d), v in stored.items() if a == acc})
    return out, accounts


def _groupby(rows: list, key: str) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        out[r.get(key) or "?"].append(r)
    return out


async def day_view(ctx, day: str) -> dict:
    """Everything about one trading day: per account the result in money and percent, the trades with times, duration,
    R and notes, the intraday path, by setup and symbol, and the high-impact releases of that day."""
    import datetime as _dt
    try:
        start = time.mktime(time.strptime(day, "%Y-%m-%d"))
    except ValueError:
        return {"error": "day must be YYYY-MM-DD"}
    rows = await ctx.db.run(ctx.db.journal, start - 86400 * 400, 5000)
    names = {str(k): v for k, v in (ctx.settings.get("magic_names") or {}).items()}
    copies = {str(m) for m in (ctx.settings.get("copy_magics") or [])}
    closed_all = [r for r in rows if r.get("closed")]
    balances, accounts = await _balances(ctx, closed_all)
    todays = sorted([r for r in closed_all if day_key(r["closed"]) == day], key=lambda r: r["closed"])
    for r in todays:
        r["setup"] = "manual" if str(r.get("magic") or "0") == "0" else names.get(str(r.get("magic")), f"magic {r.get('magic')}")
        r["r"] = r_multiple(r)
        r["copy"] = str(r.get("magic") or "0") in copies
        r["minutes"] = (r["closed"] - r["opened"]) / 60 if r.get("opened") else None
        base = (balances.get(r["account"]) or {}).get(day)
        r["pct"] = (r.get("net") or 0) / base * 100 if base else None
    per_acc = []
    for acc in sorted({r["account"] for r in todays}, key=str):
        own = [r for r in todays if r["account"] == acc]
        base = (balances.get(acc) or {}).get(day)
        net = sum(r.get("net") or 0 for r in own)
        cum, path = 0.0, []
        for r in own:
            cum += r.get("net") or 0
            path.append({"t": r["closed"], "v": round(cum, 2), "pct": cum / base * 100 if base else None})
        rs = [r["r"] for r in own if r["r"] is not None]

        def group(key):
            return sorted(({"name": k, "trades": len(v), "net": sum(x.get("net") or 0 for x in v),
                            "pct": sum(x.get("net") or 0 for x in v) / base * 100 if base else None}
                           for k, v in _groupby(own, key).items()), key=lambda g: g["net"])
        per_acc.append({"account": acc, "currency": (accounts.get(acc) or {}).get("currency"), "start_balance": base,
                        "net": net, "pct": net / base * 100 if base else None, "trades": len(own),
                        "wins": sum(1 for r in own if (r.get("net") or 0) > 0), "avg_r": statistics.mean(rs) if rs else None,
                        "sum_r": sum(rs) if rs else None, "path": path,
                        "by_setup": group("setup"), "by_symbol": group("symbol"), "copies": sum(1 for r in own if r["copy"])})
    events = []
    if "calendar" in ctx.extras:
        try:
            d = await ctx.extras["calendar"].events(start, start + 86400)
            events = [e for e in d.get("events", []) if e.get("impact") == "high"]
        except Exception:
            events = []
    traded = sorted({day_key(r["closed"]) for r in closed_all})
    before = [d for d in traded if d < day]
    after = [d for d in traded if d > day]
    return {"day": day, "weekday": _dt.date.fromisoformat(day).strftime("%A"), "accounts": per_acc, "trades": todays, "events": events,
            "prev": before[-1] if before else None, "next": after[0] if after else None,
            "note": "Percent = of the account's balance at the start of that day: stored by SessionDesk from 2026-10-18 on, before "
                    "that reconstructed from today's balance minus later trade results (deposits, withdrawals and fees outside "
                    "trades are not included). Copied trades are the copy account's real result and are marked."}


async def view(ctx, days: int = 30, include_copies: bool = False) -> dict:
    rows = await ctx.db.run(ctx.db.journal, time.time() - days * 86400, 1000)
    names = {str(k): v for k, v in (ctx.settings.get("magic_names") or {}).items()}
    copies = {str(m) for m in (ctx.settings.get("copy_magics") or [])}
    for r in rows:
        r["setup"] = "manual" if str(r.get("magic") or "0") == "0" else names.get(str(r.get("magic")), f"magic {r.get('magic')}")
        r["r"] = r_multiple(r)
        r["risk_source"] = "confirmed" if r.get("risk_confirmed") else "observed" if r.get("risk_observed") else None
        r["copy"] = str(r.get("magic") or "0") in copies
    closed_all = [r for r in rows if r.get("closed")]
    closed = closed_all if include_copies else [r for r in closed_all if not r["copy"]]
    currency = {}
    try:
        from . import broker
        currency = {a.get("login"): a.get("currency") for a in (await broker.overview(ctx)).get("accounts", [])}
    except Exception:
        pass
    st = stats(closed, names)
    for x in st:
        x["currency"] = currency.get(x["account"])
    # The curve is the account's real P/L: copied trades are that account's own trades, so they always count there.
    # Only the per-setup statistics hide them (the same decisions already count on the master account).
    cv = curves(closed_all, days)
    for a, c in cv.items():
        c["currency"] = currency.get(a)
    history = [r for r in await ctx.db.run(ctx.db.journal, time.time() - (days + 400) * 86400, 5000) if r.get("closed")]
    balances, _accounts = await _balances(ctx, history)
    with_pct(cv, closed, balances)
    hidden = len(closed_all) - len(closed)
    return {"trades": closed, "open": [r for r in rows if not r.get("closed")], "stats": st, "curves": cv,
            "copies_hidden": hidden, "copy_magics": sorted(copies),
            "note": "R needs an initial risk: 'observed' = money to the stop when SessionDesk first saw the position (a proxy), "
                    "'confirmed' = entered by you. Averages with fewer than ~30 trades are anecdotal. Accounts are never added "
                    "together (they can hold different currencies)."
                    + (f" {hidden} copied trades (copy_magics in Settings) are left out of the trade list and setup statistics so "
                       "nothing counts twice; the equity curves include them, because they are the copy account's real P/L." if hidden else "")}
