"""Taxes and other balance bookings per account: what the broker withheld or refunded, month by month next to the
trading result before tax, plus deposits, withdrawals and fees - from the MetaTrader 5 export (bridge 1.20+).

An account whose export carries no bookings (older bridge, other exporters) gets an estimate instead: the balance
changes that are not trades, between the day-start balances SessionDesk recorded itself. With a German broker that
is mostly withholding tax and refunds, but fees, dividend adjustments or a payout look the same - it says so.
This page computes, it does not advise: the broker's annual tax statement is what counts.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .report import CASH_CLASS, balance_check

UTC = dt.timezone.utc


def _month(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m")


def months(deals: list[dict], cash: list[dict], year: int | None) -> list[dict]:
    """Per month of the year (None: of whatever the rows span): trading result before tax, taxes withheld / refunded,
    net tax, effective rate, deposits, withdrawals, fees (pure, tested)."""
    rows: dict[str, dict] = defaultdict(lambda: {"result": 0.0, "withheld": 0.0, "refunded": 0.0, "deposits": 0.0, "withdrawals": 0.0,
                                                 "fees": 0.0, "bookings": 0})
    for d in deals:
        t = d.get("time")
        if t and (year is None or dt.datetime.fromtimestamp(t, UTC).year == year):
            rows[_month(t)]["result"] += d.get("net") or 0
    for c in cash:
        t, v = c.get("time"), c.get("amount") or 0
        if not t or (year is not None and dt.datetime.fromtimestamp(t, UTC).year != year):
            continue
        r, kind = rows[_month(t)], CASH_CLASS.get(c.get("type"), "other")
        r["bookings"] += 1
        if kind == "tax":
            r["withheld" if v < 0 else "refunded"] += v
        elif kind == "flow":
            r["deposits" if v > 0 else "withdrawals"] += v
        elif kind == "result":
            r["result"] += v
            r["fees"] += v
    out = []
    for m in sorted(rows):
        r = rows[m]
        net_tax = r["withheld"] + r["refunded"]
        out.append({"month": m, **r, "net_tax": net_tax, "after_tax": r["result"] + net_tax,
                    "rate": -net_tax / r["result"] * 100 if r["result"] > 0 else None})
    return out


def estimate(deals: list[dict], balance_now: float, recorded: dict[str, float]) -> list[dict]:
    """Balance changes that are not trades between consecutive recorded day starts (and now), for exports without
    bookings (pure, tested). balance_check's difference on a day = every non-trade booking from that day to now."""
    chk = balance_check(deals, balance_now, recorded, tolerance=0.0)["rows"]
    out = []
    for i, r in enumerate(chk):
        later = chk[i + 1]["diff"] if i + 1 < len(chk) else 0.0
        out.append({"from": r["day"], "to": chk[i + 1]["day"] if i + 1 < len(chk) else "now", "non_trade": r["diff"] - later})
    return out


async def view(ctx, year: int | None = None) -> dict:
    year = year or dt.date.today().year
    stored = await ctx.db.run(ctx.db.day_starts)
    accounts = []
    for c in ctx.hub.candidates("account"):
        if not hasattr(c, "deals"):
            continue
        accs, deals = await c.account(), await c.deals()
        book = await c.cash() if hasattr(c, "cash") else {"rows": [], "covered": []}
        for a in accs or []:
            login = a.get("login")
            mine = [d for d in deals if d.get("account") == login]
            row = {"account": login, "currency": a.get("currency"), "server": a.get("server"), "covered": login in book["covered"]}
            if row["covered"]:
                cash = [x for x in book["rows"] if x.get("account") == login]
                row["months"] = months(mine, cash, year)
                row["bookings"] = sorted((x for x in cash if x.get("time") and dt.datetime.fromtimestamp(x["time"], UTC).year == year),
                                         key=lambda x: -x["time"])[:100]
                tot = {k: sum(m[k] for m in row["months"]) for k in ("result", "withheld", "refunded", "net_tax", "after_tax", "deposits",
                                                                      "withdrawals", "fees")}
                tot["rate"] = -tot["net_tax"] / tot["result"] * 100 if tot["result"] > 0 else None
                row["year"] = tot
                first = min((d["time"] for d in mine if d.get("time")), default=None)
                row["export_from"] = dt.datetime.fromtimestamp(first, UTC).date().isoformat() if first else None
            else:
                tail = str(login)[-3:]
                rec = {day: b for (acc, day), b in stored.items() if str(acc)[-3:] == tail}
                row["estimate"] = estimate(mine, a.get("balance") or 0.0, rec)
                row["estimate_total"] = sum(e["non_trade"] for e in row["estimate"])
            accounts.append(row)
    return {"year": year, "accounts": accounts,
            "note": "From the MetaTrader 5 export: taxes as the broker booked them (withheld on gains, refunded when losses are "
                    "offset), next to the trading result before tax (trades plus fees, interest and dividend adjustments). "
                    "Effective rate = net tax / result before tax. This is arithmetic, not tax advice - the broker's annual tax "
                    "statement counts. Accounts without bookings in their export show an estimate from SessionDesk's day-start "
                    "records: every balance change that is not a trade (tax, but also fees, dividend adjustments, payouts)."}
