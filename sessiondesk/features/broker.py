"""Read-only broker view: accounts, open positions with money at risk, running EAs, closed trades per EA.

Data comes from broker connectors (MT5 bridge, Alpaca). Nothing here can place, change or close an order.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict


def ea_performance(deals: list[dict], since: float, names: dict | None = None) -> list[dict]:
    """Closed trades per setup. One trade = one position id; its net is the sum of ALL its deals (entry
    commission included), it counts in the window of its last exit. The setup is the magic number of the
    OPENING deal - a manual close of an EA trade carries magic 0 and must not turn it into a manual trade."""
    positions: dict[tuple, dict] = {}
    for d in deals:
        key = (d.get("account"), d.get("position_id"))
        pos = positions.setdefault(key, {"magic": None, "net": 0.0, "closed_at": None, "has_exit": False})
        pos["net"] += d.get("net") or 0.0
        if d.get("entry") == "0" and pos["magic"] is None:            # DEAL_ENTRY_IN
            pos["magic"] = d.get("magic") or "0"
        if d.get("entry") in ("1", "2", "3"):                          # OUT, INOUT, OUT_BY
            pos["has_exit"] = True
            pos["closed_at"] = max(pos["closed_at"] or 0, d.get("time") or 0)
            if pos["magic"] is None:
                pos["fallback_magic"] = d.get("magic") or "0"
    per: dict[tuple, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "net": 0.0})
    for (account, _pid), pos in positions.items():
        if not pos["has_exit"] or (pos["closed_at"] or 0) < since:
            continue
        magic = pos["magic"] or pos.get("fallback_magic") or "0"
        row = per[(account, magic)]
        row["trades"] += 1
        row["net"] += pos["net"]
        row["wins"] += pos["net"] > 0
    out = []
    for (account, magic), r in per.items():
        label = "manual" if magic == "0" else (names or {}).get(str(magic)) or f"EA magic {magic}"
        out.append({"account": account, "magic": magic, "label": label,
                    "trades": r["trades"], "net": r["net"], "win_rate": r["wins"] / r["trades"] if r["trades"] else None})
    return sorted(out, key=lambda r: (r["account"], -abs(r["net"])))


async def overview(ctx) -> dict:
    conns = [c for c in ctx.hub.candidates("account")]
    if not conns:
        return {"connected": False, "note": "No broker connected. MetaTrader 5: put bridge/SessionDeskBridge.mq5 on one chart. "
                                              "Alpaca: add your keys under Connectors. Both are read-only."}

    async def safe(coro):
        try:
            return await coro
        except Exception as exc:
            return {"error": str(exc)}
    accounts, positions, eas, deals = [], [], [], []
    for c in conns:
        res = await asyncio.gather(safe(c.account()), safe(c.positions()),
                                   safe(c.eas()) if hasattr(c, "eas") else asyncio.sleep(0, result=[]),
                                   safe(c.deals()) if hasattr(c, "deals") else asyncio.sleep(0, result=[]))
        for target, r in zip((accounts, positions, eas, deals), res):
            if isinstance(r, list):
                for row in r:
                    row.setdefault("connector", c.id)
                target.extend(r)
    now = time.time()
    risk: dict[str, float] = defaultdict(float)
    unknown: set[str] = set()
    for p in positions:
        if p.get("risk_to_stop"):
            risk[p["account"]] += p["risk_to_stop"]
        elif not p.get("sl"):
            unknown.add(p["account"])
    for a in accounts:
        r = risk.get(a["login"])
        a["risk_to_stops"] = r
        a["risk_pct"] = r / a["equity"] * 100 if r and a.get("equity") else None
        a["positions_without_stop"] = a["login"] in unknown
    names = {str(k): v for k, v in (ctx.settings.get("magic_names") or {}).items()}
    for p in positions:
        if p.get("magic") not in (None, "", "0"):
            p["setup"] = names.get(str(p["magic"]))
    return {"connected": True, "accounts": accounts, "positions": positions, "eas": eas,
            "performance_7d": ea_performance(deals, now - 7 * 86400, names),
            "performance_30d": ea_performance(deals, now - 30 * 86400, names), "asof": now}
