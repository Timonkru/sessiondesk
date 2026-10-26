"""Futures contract months: which contract is the front, when it expires, what unit it trades in.

Why: Yahoo's continuous symbols (NG=F, TTF=F, BZ=F ...) roll on Yahoo's own schedule. Measured 26.10.2026: NG=F already
pointed to December (3.017 $/MMBtu) while the November contract still traded until 28.10. (2.519) - so the
Commodities page showed Henry Hub +14 % "today" (December price vs. November close the day before), the board
-1.5 %, and TTF=F was still November. Here the front month follows the exchange's expiry rule, and every price
names its contract, so two pages can no longer show two different contracts as "the" gas price. Same day,
same defect: BZ=F jumped to January (Brent "-5.7 %" against -1.5 % in the December contract), RB=F and HO=F
to December.

Expiry rules are the exchanges' published last-trading-day rules on weekdays only; exchange holidays are not
modelled, so an expiry next to a holiday can be one day off.
"""
from __future__ import annotations

import datetime as dt

MONTH_CODES = "FGHJKMNQUVXZ"
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# root: (Yahoo suffix, expiry rule, unit, exchange / contract description). Rules:
#   ("before_1st", n)   n business days before the 1st of the delivery month (NG, TTF)
#   ("last_bd", k)      last business day of the k-th month before the delivery month (Brent k=2, RBOB/ULSD k=1)
#   ("wti",)            3 business days before the 25th of the month before delivery (before the business day
#                       preceding the 25th if the 25th is a weekend day)
CONTRACTS = {
    "NG": (".NYM", ("before_1st", 3), "$/MMBtu", "NYMEX Henry Hub natural gas"),
    "TTF": (".NYM", ("before_1st", 2), "EUR/MWh", "Dutch TTF natural gas (NYMEX, settles on ICE Endex TTF)"),
    "BZ": (".NYM", ("last_bd", 2), "$/bbl", "Brent crude (NYMEX, settles on ICE Brent)"),
    "CL": (".NYM", ("wti",), "$/bbl", "NYMEX WTI light sweet crude"),
    "RB": (".NYM", ("last_bd", 1), "$/gal", "NYMEX RBOB gasoline"),
    "HO": (".NYM", ("last_bd", 1), "$/gal", "NYMEX NY Harbor ULSD (heating oil)"),
}
CONTINUOUS = {"NG=F": "NG", "TTF=F": "TTF", "BZ=F": "BZ", "CL=F": "CL", "RB=F": "RB", "HO=F": "HO"}
MWH_PER_MMBTU = 0.29307107          # 1 MMBtu = 0.293 MWh, i.e. 1 MWh = 3.412 MMBtu


def business_days_before(day: dt.date, n: int) -> dt.date:
    """The weekday n business days before `day` (weekends skipped, holidays not) (pure, tested)."""
    d = day
    while n > 0:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def expiry(root: str, year: int, month: int) -> dt.date:
    """Last trading day of the contract for delivery month year-month (pure, tested)."""
    rule = CONTRACTS[root][1]
    first = dt.date(year, month, 1)
    if rule[0] == "before_1st":
        return business_days_before(first, rule[1])
    if rule[0] == "last_bd":
        y, m = (year, month - rule[1]) if month > rule[1] else (year - 1, month - rule[1] + 12)
        return business_days_before(dt.date(y + (m // 12), m % 12 + 1, 1), 1)          # last weekday of month m
    prev = first - dt.timedelta(days=1)                                                # WTI
    d25 = dt.date(prev.year, prev.month, 25)
    anchor = d25 if d25.weekday() < 5 else business_days_before(d25, 1)
    return business_days_before(anchor, 3)


def months(root: str, today: dt.date, n: int = 12) -> list[dict]:
    """The next n tradable contract months, front first: {symbol, label, expiry, unit, contract} (pure, tested)."""
    suffix, _, unit, desc = CONTRACTS[root]
    out = []
    y, m = today.year, today.month
    while len(out) < n:
        expiry_day = expiry(root, y, m)
        if expiry_day >= today:
            out.append({"symbol": f"{root}{MONTH_CODES[m - 1]}{y % 100:02d}{suffix}", "label": f"{MONTH_NAMES[m - 1]} {y % 100:02d}",
                        "expiry": expiry_day.isoformat(), "unit": unit, "contract": desc, "root": root})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def front(symbol: str, today: dt.date | None = None) -> dict | None:
    """Front contract for a continuous Yahoo symbol we resolve ourselves (energy, see CONTINUOUS), else None."""
    root = CONTINUOUS.get(symbol)
    return months(root, today or dt.date.today(), 2)[0] if root else None


def ttf_in_usd_mmbtu(ttf_eur_mwh: float, eurusd: float) -> float:
    """TTF from EUR/MWh into $/MMBtu, the Henry Hub unit (pure, tested)."""
    return ttf_eur_mwh * eurusd * MWH_PER_MMBTU
