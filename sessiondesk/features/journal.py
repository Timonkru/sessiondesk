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
    cv = curves(closed, days)
    for a, c in cv.items():
        c["currency"] = currency.get(a)
    hidden = len(closed_all) - len(closed)
    return {"trades": closed, "open": [r for r in rows if not r.get("closed")], "stats": st, "curves": cv,
            "copies_hidden": hidden, "copy_magics": sorted(copies),
            "note": "R needs an initial risk: 'observed' = money to the stop when SessionDesk first saw the position (a proxy), "
                    "'confirmed' = entered by you. Averages with fewer than ~30 trades are anecdotal. Accounts are never added "
                    "together (they can hold different currencies)."
                    + (f" {hidden} copied trades (copy_magics in Settings) are hidden so nothing counts twice." if hidden else "")}
