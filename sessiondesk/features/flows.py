"""Forced-flow calendar: dates on which someone MUST trade, whatever the price.

Index funds rebalance on index-review days, option dealers' hedges roll off at expiry, balanced
funds rebalance at month end, Japanese importers buy dollars at the Tokyo fix. These dates come from
published index-provider and exchange rules, so they can be computed in advance.

Two honest limits, shown in the UI:
  - A rule computes the date; providers occasionally move a date (holidays, special reviews).
    Each row links to the provider's own calendar - verify before relying on it.
  - "Forced" does not mean "tradable". Most calendar flows show no edge after costs once tested;
    the calendar tells you when liquidity and closing auctions are unusual, nothing more.
"""
from __future__ import annotations

import calendar as cal
import datetime as dt
from functools import lru_cache


# ------------------------------------------------------------------ business days
@lru_cache(maxsize=None)
def _holidays(market: str, year: int) -> frozenset:
    try:
        import holidays
    except ImportError:
        return frozenset()
    try:
        code = {"US": "NYSE", "EU": "XETR", "UK": "XLON", "JP": "XJPX"}.get(market)
        if not code:
            return frozenset()
        h = holidays.financial_holidays(code, years=year)
        return frozenset(h.keys())
    except Exception:
        return frozenset()


def is_business_day(day: dt.date, market: str) -> bool:
    return day.weekday() < 5 and day not in _holidays(market, day.year)


def prev_business_day(day: dt.date, market: str) -> dt.date:
    while not is_business_day(day, market):
        day -= dt.timedelta(days=1)
    return day


def last_business_day(year: int, month: int, market: str) -> dt.date:
    return prev_business_day(dt.date(year, month, cal.monthrange(year, month)[1]), market)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def third_friday(year: int, month: int) -> dt.date:
    return nth_weekday(year, month, 4, 3)


def expiry_friday(year: int, month: int) -> dt.date:
    """US monthly expiration: third Friday, or the business day before if it is a holiday."""
    return prev_business_day(third_friday(year, month), "US")


def vix_expiry(year: int, month: int) -> dt.date:
    """VIX settles on the Wednesday 30 days before the next month's SPX expiration Friday."""
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    day = third_friday(ny, nm) - dt.timedelta(days=30)
    return day if is_business_day(day, "US") else prev_business_day(day - dt.timedelta(days=1), "US")


def gotobi_days(year: int, month: int) -> list[dt.date]:
    """Tokyo fix days: the 5th, 10th, 15th, 20th, 25th and month end; weekend/holiday -> previous business day."""
    days = [dt.date(year, month, d) for d in (5, 10, 15, 20, 25)] + [dt.date(year, month, cal.monthrange(year, month)[1])]
    return sorted({prev_business_day(d, "JP") for d in days})


# ------------------------------------------------------------------ rules
def _ev(day, time_, name, markets, mechanism, size, verify, certainty="rule", kind="index"):
    return {"date": day.isoformat(), "time": time_, "name": name, "markets": markets, "mechanism": mechanism,
            "size": size, "verify": verify, "certainty": certainty, "kind": kind}


def events_between(start: dt.date, end: dt.date) -> list[dict]:
    out: list[dict] = []
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    for y, m in months:
        quarterly = m in (3, 6, 9, 12)
        fri = expiry_friday(y, m)
        if quarterly:
            out.append(_ev(fri, "US open (SOQ) and close", "Quarterly expiration (\"triple witching\")",
                           ["US indices", "index futures", "single stocks"],
                           "Index futures, index options and stock options expire together. Dealer hedges tied to expiring "
                           "options are unwound; open interest is largest of the quarter. Closing auctions are unusually heavy.",
                           "high", "https://www.cboe.com/about/hours/us-options/", kind="expiry"))
            out.append(_ev(fri, "US close 16:00 ET", "S&P 500 / S&P Dow Jones quarterly rebalance",
                           ["S&P 500", "S&P 400/600", "Dow"],
                           "Constituent changes and share/float updates take effect after the close; index funds execute in "
                           "the closing auction. Changes are announced about two weeks earlier (usually a Friday evening).",
                           "high", "https://www.spglobal.com/spdji/en/governance/methodology-and-regulations/"))
            out.append(_ev(fri, "US close 16:00 ET", "Nasdaq-100 quarterly rebalance" + (" + annual reconstitution" if m == 12 else ""),
                           ["Nasdaq-100", "QQQ"],
                           "Quarterly weight rebalance; in December the annual reconstitution (members added/removed, "
                           "announced about a week earlier). Effective before the open on the following Monday.",
                           "high" if m == 12 else "medium", "https://indexes.nasdaqomx.com/"))
            out.append(_ev(fri, "Xetra close 17:30 CET", "DAX / STOXX quarterly review effective",
                           ["DAX", "MDAX", "Euro Stoxx 50", "STOXX Europe 600"],
                           "Deutsche Boerse and STOXX index changes take effect after the close of the third Friday; "
                           "passive funds trade the closing auction. Euro Stoxx 50 composition is reviewed in September.",
                           "medium", "https://www.stoxx.com/rulebooks"))
            out.append(_ev(fri, "LSE close 16:30 UK", "FTSE UK quarterly review effective",
                           ["FTSE 100", "FTSE 250"],
                           "Index changes decided at the quarterly review take effect after the close of the third Friday; "
                           "trackers trade the closing auction. The review is published about two weeks earlier.",
                           "medium", "https://www.lseg.com/en/ftse-russell/index-resources/index-notices"))
            roll = fri - dt.timedelta(days=8)
            out.append(_ev(prev_business_day(roll, "US"), "all day", "Equity index futures roll date",
                           ["ES", "NQ", "YM", "RTY"],
                           "Liquidity moves from the expiring to the next quarterly contract; calendar-spread volume peaks. "
                           "Charts on continuous contracts can jump by the basis.",
                           "low", "https://www.cmegroup.com/trading/equity-index/rolldates.html", kind="expiry"))
        else:
            out.append(_ev(fri, "US close", "Monthly options expiration (OPEX)", ["US indices", "single stocks"],
                           "Standard monthly options expire; hedges of large open-interest strikes roll off, which can "
                           "release or create pinning around big strikes into the close.",
                           "medium", "https://www.cboe.com/about/hours/us-options/", kind="expiry"))
        out.append(_ev(vix_expiry(y, m), "US open (SOQ)", "VIX futures/options settlement", ["VIX", "SPX options"],
                       "VIX derivatives settle on a special opening quotation of SPX options; hedges around the settlement "
                       "concentrate in the open.", "low", "https://www.cboe.com/tradable_products/vix/", kind="expiry"))
        if m in (2, 5, 8, 11):
            day = last_business_day(y, m, "US")
            big = m in (5, 11)
            out.append(_ev(day, "close of each market", "MSCI " + ("semi-annual" if big else "quarterly") + " index review effective",
                           ["MSCI ACWI / EM / World", "global equities"],
                           "MSCI changes take effect as of the close of the last business day of February, May, August and "
                           "November; May and November are the larger semi-annual reviews. Announced about two weeks earlier.",
                           "high" if big else "medium", "https://www.msci.com/index-review"))
        if m == 6:
            day = nth_weekday(y, 6, 4, 4)
            out.append(_ev(prev_business_day(day, "US"), "US close 16:00 ET", "Russell US annual reconstitution",
                           ["Russell 1000/2000/3000", "IWM"],
                           "Rank day is 30 April; preliminary lists follow in May; the reconstitution takes effect after the "
                           "close of the fourth Friday of June - often one of the highest-volume closes of the year. FTSE "
                           "Russell announced semi-annual reconstitution from 2026; check the December date with the provider.",
                           "high", "https://www.lseg.com/en/ftse-russell/russell-reconstitution"))
        if m in (3, 9):
            day = last_business_day(y, m, "JP")
            out.append(_ev(day, "Tokyo close", "Japan fiscal " + ("year" if m == 3 else "half-year") + " end + Nikkei 225 periodic review",
                           ["Nikkei 225", "TOPIX", "USD/JPY"],
                           "Japanese institutions close their books (window dressing, repatriation). The Nikkei 225 periodic "
                           "review is implemented around the start of April and October - verify the exact day.",
                           "medium", "https://indexes.nikkei.co.jp/en/nkave/archives/news", certainty="approximate"))
        me = last_business_day(y, m, "US")
        out.append(_ev(me, "US close; FX 16:00 London fix", "Month end" + (" / quarter end" if quarterly else "") + " rebalancing",
                       ["global equities", "bonds", "FX majors"],
                       "Balanced and pension funds rebalance back to target weights after big equity/bond moves; bond "
                       "indices extend duration; FX hedges are reset at the WM/Reuters 4 pm London fix.",
                       "medium" if quarterly else "low", "https://www.lseg.com/en/ftse-russell/benchmarks/wmr-fx-benchmarks",
                       certainty="rule", kind="calendar"))
        for d in gotobi_days(y, m):
            out.append(_ev(d, "09:55 JST", "Tokyo fix (gotobi day)", ["USD/JPY"],
                           "Japanese importers settle dollar purchases at the 09:55 Tokyo fixing on the 5th/10th/15th/20th/25th "
                           "and month end; the effect is debated and small.", "low", "https://www.mufg.jp/english/",
                           kind="fx"))
    out = [e for e in out if start.isoformat() <= e["date"] <= end.isoformat()]
    out.sort(key=lambda e: (e["date"], {"high": 0, "medium": 1, "low": 2}[e["size"]]))
    return out


async def flows(ctx, days: int = 120) -> dict:
    today = dt.date.today()
    return {"events": events_between(today, today + dt.timedelta(days=days)),
            "always": [
                {"name": "Leveraged & inverse ETF rebalancing", "when": "every trading day, last 30 min (US)",
                 "mechanism": "Daily-reset leveraged ETFs must buy into up days and sell into down days near the close; "
                              "the size grows with the day's move (approx. AUM x L x (L-1) x return)."},
                {"name": "Closing auctions", "when": "every trading day",
                 "mechanism": "Passive funds benchmark to the close; a growing share of daily volume trades in the auction."},
            ],
            "note": "Dates are computed from published rules. Providers can move dates - verify with the linked source. "
                    "A forced flow is a liquidity event, not a trade signal."}
