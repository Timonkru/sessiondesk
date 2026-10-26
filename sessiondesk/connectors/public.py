"""Free public sources that need no account.

  fred        FRED graph CSV (no key)                    macro series: yields, inflation, spreads
  ffcal       Forex Factory weekly calendar JSON          scheduled releases with impact level (no actuals)
  cftc        CFTC Commitments of Traders (Socrata)       weekly positioning
  sec         SEC EDGAR submissions                        US filings; SEC asks for a contact email in the User-Agent
  nasdaq      Nasdaq earnings calendar                     who reports on which day, consensus EPS
  treasury    U.S. Treasury daily par yield curve (CSV)    official end-of-day curve, a day ahead of FRED
  cnbc        CNBC quote service (unofficial JSON)         government bond yields around the clock (2y/10y/30y ...)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import urllib.parse

from .base import Connector, ConnectorError, Field, stable_id

import httpx

PLAIN_UA = {"User-Agent": "SessionDesk/0.1"}
# FRED silently stalls (no response, read timeout) for user agents it does not know - measured 11.10.2026:
# "SessionDesk/0.1" and browser strings hang, the HTTP library's own agent answers in ~0.5 s.
FRED_UA = {"User-Agent": f"python-httpx/{httpx.__version__}"}


# ------------------------------------------------------------------ FRED
class Fred(Connector):
    id = "fred"
    name = "FRED (St. Louis Fed)"
    tier = "free"
    capabilities = ("series",)
    homepage = "https://fred.stlouisfed.org"
    description = "Official US macro and rates series, daily close (no intraday). No key needed."

    async def test(self) -> dict:
        s = await self.series("DGS10")
        return {"ok": bool(s["points"]), "detail": f"10y = {s['points'][-1][1]}% ({s['points'][-1][0]})"}

    async def series(self, series_id: str) -> dict:
        resp = await self.ctx.http.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id},
                                       headers=FRED_UA, timeout=20)
        if resp.status_code != 200:
            raise ConnectorError(f"FRED HTTP {resp.status_code}")
        return {"id": series_id, "points": parse_fred_csv(resp.text)}


# ------------------------------------------------------------------ U.S. Treasury
TREASURY_CSV = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
TREASURY_TENORS = {"1 Mo": "1m", "3 Mo": "3m", "6 Mo": "6m", "1 Yr": "1y", "2 Yr": "2y", "3 Yr": "3y", "5 Yr": "5y",
                   "7 Yr": "7y", "10 Yr": "10y", "20 Yr": "20y", "30 Yr": "30y"}


class Treasury(Connector):
    id = "treasury"
    name = "U.S. Treasury yield curve"
    tier = "free"
    capabilities = ("curve",)
    homepage = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"
    description = ("Official daily par yield curve, published after the US close the same day - FRED's DGS series repeat "
                   "it one to two business days later. No key needed.")

    async def test(self) -> dict:
        c = await self.curve()
        last = c["days"][-1]
        return {"ok": True, "detail": f"{last['date']}: 10y = {last['yields'].get('10y')}%"}

    async def curve(self, year: int | None = None) -> dict:
        """{"days": [{"date": YYYY-MM-DD, "yields": {tenor: %}}], oldest first}; early January adds the year before.
        Shared by the Macro curve and the rates-by-country table: one download per 30 minutes."""
        cache = getattr(self.ctx, "cache", None)
        if cache is None or year:
            return await self._curve(year)
        async def build():
            return await self._curve(None)
        data = await cache.get("treasury:curve", 1800, build)
        if "error" in data:
            raise ConnectorError(data["error"])
        return data

    async def _curve(self, year: int | None) -> dict:
        today = dt.date.today()
        years = [year] if year else ([today.year - 1, today.year] if today.month == 1 else [today.year])
        days = []
        for y in years:
            resp = await self.ctx.http.get(TREASURY_CSV.format(year=y), params={"type": "daily_treasury_yield_curve",
                                           "field_tdr_date_value": str(y), "page": "", "_format": "csv"},
                                           headers=PLAIN_UA, timeout=30, follow_redirects=True)
            if resp.status_code != 200:
                raise ConnectorError(f"Treasury HTTP {resp.status_code}")
            days += parse_treasury_csv(resp.text)
        if not days:
            raise ConnectorError("Treasury: empty yield curve file")
        return {"days": sorted(days, key=lambda d: d["date"])}


def parse_treasury_csv(text: str) -> list[dict]:
    """Treasury par yield curve CSV (MM/DD/YYYY, one column per tenor) -> [{"date", "yields"}] (pure, tested)."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = dt.datetime.strptime(row.get("Date", ""), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        ylds = {}
        for col, tenor in TREASURY_TENORS.items():
            try:
                ylds[tenor] = float(row.get(col) or "")
            except ValueError:
                continue
        if ylds:
            out.append({"date": day, "yields": ylds})
    return out


# ------------------------------------------------------------------ CNBC (bond yields around the clock)
CNBC_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"


class Cnbc(Connector):
    id = "cnbc"
    name = "CNBC quotes (bond yields)"
    tier = "free"
    capabilities = ("yields",)
    homepage = "https://www.cnbc.com/bonds/"
    description = ("Government bond yields that trade around the clock (US 2y/5y/10y/30y, Bund, Gilt) - the Cboe yield "
                   "indices on Yahoo only move during US hours. Unofficial JSON endpoint behind cnbc.com, no key; "
                   "may change without notice.")

    async def test(self) -> dict:
        q = await self.quotes(["US10Y"])
        return {"ok": bool(q), "detail": f"US 10y = {q['US10Y']['price']}%" if q else "no data"}

    async def quotes(self, symbols: list[str]) -> dict:
        resp = await self.ctx.http.get(CNBC_URL, params={"symbols": "|".join(symbols), "requestMethod": "itv", "noform": "1",
                                                         "partnerId": "2", "fund": "1", "exthrs": "1", "output": "json"},
                                       headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code != 200:
            raise ConnectorError(f"CNBC HTTP {resp.status_code}")
        return parse_cnbc(resp.json())


def _cnbc_num(text) -> float | None:
    try:
        return float(str(text).replace("%", "").replace(",", "").replace("+", "").strip())
    except ValueError:
        return None


def parse_cnbc(data: dict) -> dict:
    """CNBC restQuote JSON -> {symbol: Quote}; yields in percent, change in percentage points (pure, tested)."""
    rows = ((data or {}).get("FormattedQuoteResult") or {}).get("FormattedQuote") or []
    if isinstance(rows, dict):
        rows = [rows]
    out = {}
    for q in rows:
        price, prev = _cnbc_num(q.get("last")), _cnbc_num(q.get("previous_day_closing"))
        if price is None:
            continue
        try:
            ts = dt.datetime.strptime(q.get("last_time", ""), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
        except ValueError:
            ts = None
        change = price - prev if prev is not None else None
        out[q["symbol"]] = {"symbol": q["symbol"], "name": q.get("name"), "price": price, "prev_close": prev, "change": change,
                            "change_pct": change / prev * 100 if change is not None and prev else None, "time": ts}
    return out


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        try:
            out.append((row[0], float(row[1])))
        except ValueError:          # FRED writes "." for missing days
            continue
    return out


# ------------------------------------------------------------------ Forex Factory calendar
FF_IMPACT = {"High": "high", "Medium": "medium", "Low": "low", "Holiday": "holiday", "Non-Economic": "low"}


class FFCalendar(Connector):
    id = "ffcal"
    name = "Forex Factory calendar"
    tier = "free"
    kind = "calendar"
    capabilities = ("calendar",)
    homepage = "https://www.forexfactory.com/calendar"
    description = ("Scheduled releases this and next week with impact level, forecast and previous. "
                   "No actual values - those come from MT5, TradingEconomics or the squawk feeds. Refreshed every 15 min.")

    async def test(self) -> dict:
        ev = await self.calendar()
        return {"ok": bool(ev), "detail": f"{len(ev)} events this/next week"}

    async def calendar(self, start: float | None = None, end: float | None = None) -> list[dict]:
        events = []
        for week in ("thisweek", "nextweek"):
            resp = await self.ctx.http.get(f"https://nfs.faireconomy.media/ff_calendar_{week}.json",
                                           headers=PLAIN_UA, timeout=12)
            if resp.status_code == 404 and week == "nextweek":
                continue                     # published only later in the week
            if resp.status_code != 200:
                if events:
                    break
                raise ConnectorError(f"Forex Factory HTTP {resp.status_code}")
            events += parse_ff(resp.json())
        if start is not None:
            events = [e for e in events if e["ts"] >= start]
        if end is not None:
            events = [e for e in events if e["ts"] <= end]
        return events


def parse_ff(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        try:
            when = dt.datetime.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        ts = when.timestamp()
        out.append({"id": stable_id("ff", r.get("country"), r.get("title"), int(ts)), "ts": ts,
                    "currency": r.get("country", ""), "title": r.get("title", ""),
                    "impact": FF_IMPACT.get(r.get("impact"), "low"),
                    "forecast": r.get("forecast") or None, "previous": r.get("previous") or None,
                    "actual": r.get("actual") or None, "source": "ffcal"})
    return out


# ------------------------------------------------------------------ CFTC COT
COT_FINANCIAL = {"E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE": "S&P 500",
                 "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE": "Nasdaq 100",
                 "DJIA Consolidated - CHICAGO BOARD OF TRADE": "Dow",
                 "RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE": "Russell 2000",
                 "EURO FX - CHICAGO MERCANTILE EXCHANGE": "Euro",
                 "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE": "Yen",
                 "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE": "Pound",
                 "UST 10Y NOTE - CHICAGO BOARD OF TRADE": "UST 10y",
                 "VIX FUTURES - CBOE FUTURES EXCHANGE": "VIX"}
COT_COMMODITY = {"GOLD - COMMODITY EXCHANGE INC.": "Gold", "SILVER - COMMODITY EXCHANGE INC.": "Silver",
                 "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE": "WTI crude",
                 "COPPER- #1 - COMMODITY EXCHANGE INC.": "Copper"}


class Cftc(Connector):
    id = "cftc"
    name = "CFTC Commitments of Traders"
    tier = "free"
    capabilities = ("cot",)
    homepage = "https://publicreporting.cftc.gov"
    description = "Weekly futures positioning (Tuesday data, published Friday). Leveraged funds / managed money net and 1-year percentile."

    async def _query(self, dataset: str, fields: str, names: dict) -> list[dict]:
        since = (dt.date.today() - dt.timedelta(days=380)).isoformat()
        quoted = ",".join("'" + n.replace("'", "''") + "'" for n in names)
        params = {"$select": f"market_and_exchange_names,report_date_as_yyyy_mm_dd,{fields}",
                  "$where": f"report_date_as_yyyy_mm_dd > '{since}' AND market_and_exchange_names in({quoted})",
                  "$limit": "5000"}
        url = f"https://publicreporting.cftc.gov/resource/{dataset}.json?" + urllib.parse.urlencode(params)
        resp = await self.ctx.http.get(url, headers=PLAIN_UA, timeout=30)
        if resp.status_code != 200:
            raise ConnectorError(f"CFTC HTTP {resp.status_code}")
        return resp.json()

    async def cot(self) -> list[dict]:
        fin = await self._query("gpe5-46if", "lev_money_positions_long,lev_money_positions_short", COT_FINANCIAL)
        com = await self._query("72hh-3qpy", "m_money_positions_long_all,m_money_positions_short_all", COT_COMMODITY)
        return (cot_rows(fin, COT_FINANCIAL, "lev_money_positions_long", "lev_money_positions_short", "leveraged funds")
                + cot_rows(com, COT_COMMODITY, "m_money_positions_long_all", "m_money_positions_short_all", "managed money"))

    async def test(self) -> dict:
        rows = await self.cot()
        return {"ok": bool(rows), "detail": f"{len(rows)} markets, latest {max(r['date'] for r in rows) if rows else '-'}"}


def cot_rows(raw: list[dict], names: dict, long_key: str, short_key: str, group: str) -> list[dict]:
    out = []
    for full, label in names.items():
        series = sorted((r["report_date_as_yyyy_mm_dd"][:10], float(r[long_key]) - float(r[short_key]))
                        for r in raw if r.get("market_and_exchange_names") == full and long_key in r and short_key in r)
        if len(series) < 8:
            continue
        nets = [n for _, n in series]
        last = nets[-1]
        pct = (sum(n < last for n in nets) + (sum(n == last for n in nets) - 1) / 2) / (len(nets) - 1) * 100
        out.append({"market": label, "group": group, "date": series[-1][0], "net": last,
                    "week_change": last - nets[-2], "weeks": len(nets), "percentile": pct})
    return out


# ------------------------------------------------------------------ SEC EDGAR
class Sec(Connector):
    id = "sec"
    name = "SEC EDGAR"
    tier = "free"
    capabilities = ("filings",)
    fields = (Field("contact_email", "Contact email", secret=False,
                    help="SEC requires every client to identify itself with a contact email in the User-Agent."),)
    homepage = "https://www.sec.gov/edgar"
    description = "US company filings (8-K, 10-Q, 10-K, insider Form 4). Official, free, 10 requests/s limit."

    def _ua(self) -> dict:
        return {"User-Agent": f"SessionDesk/0.1 {self.option('contact_email')}"}

    async def _cik_map(self) -> dict:
        async def build():
            resp = await self.ctx.http.get("https://www.sec.gov/files/company_tickers.json", headers=self._ua(), timeout=20)
            if resp.status_code != 200:
                raise ConnectorError(f"SEC HTTP {resp.status_code}")
            return {"map": {v["ticker"].upper(): int(v["cik_str"]) for v in resp.json().values()}}
        res = await self.ctx.cache.get("sec:tickers", 7 * 86400, build, disk=True)
        if "error" in res:
            raise ConnectorError(res["error"])
        return res["map"]

    async def filings(self, symbol: str, limit: int = 40) -> list[dict]:
        cik = (await self._cik_map()).get(symbol.upper().replace(".", "-"))
        if not cik:
            return []
        resp = await self.ctx.http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=self._ua(), timeout=20)
        if resp.status_code != 200:
            raise ConnectorError(f"SEC HTTP {resp.status_code}")
        return parse_sec_submissions(resp.json(), cik, limit)

    async def test(self) -> dict:
        rows = await self.filings("AAPL", 3)
        return {"ok": bool(rows), "detail": f"AAPL latest {rows[0]['form']} {rows[0]['date']}" if rows else "no filings"}


SEC_FORMS = {"8-K": "material event", "10-Q": "quarterly report", "10-K": "annual report", "4": "insider transaction",
             "S-1": "registration", "DEF 14A": "proxy", "SC 13D": "5%+ stake (activist)", "SC 13G": "5%+ stake (passive)",
             "6-K": "foreign issuer report", "20-F": "foreign annual report", "13F-HR": "institutional holdings"}


def parse_sec_submissions(data: dict, cik: int, limit: int) -> list[dict]:
    recent = (data.get("filings") or {}).get("recent") or {}
    out = []
    for i, form in enumerate(recent.get("form", [])[: limit * 3]):
        acc = recent["accessionNumber"][i]
        doc = recent.get("primaryDocument", [""] * (i + 1))[i]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}" if doc else \
              f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
        out.append({"form": form, "kind": SEC_FORMS.get(form, ""), "date": recent["filingDate"][i],
                    "description": recent.get("primaryDocDescription", [""] * (i + 1))[i] or "",
                    "items": recent.get("items", [""] * (i + 1))[i] or "", "url": url})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ Nasdaq earnings
class NasdaqEarnings(Connector):
    id = "nasdaq"
    name = "Nasdaq earnings calendar"
    tier = "free"
    capabilities = ("earnings",)
    homepage = "https://www.nasdaq.com/market-activity/earnings"
    description = "Who reports on which day (US listings), timing (pre/post market) and consensus EPS."

    async def earnings_day(self, day: dt.date) -> list[dict]:
        resp = await self.ctx.http.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": day.isoformat()},
                                       headers={"User-Agent": "Mozilla/5.0 SessionDesk", "Accept": "application/json"}, timeout=12)
        if resp.status_code != 200:
            raise ConnectorError(f"Nasdaq HTTP {resp.status_code}")
        return parse_nasdaq_earnings(resp.json(), day)

    async def earnings(self, start: dt.date, days: int = 7) -> list[dict]:
        import asyncio
        dates = [start + dt.timedelta(days=i) for i in range(days)]
        dates = [d for d in dates if d.weekday() < 5]
        res = await asyncio.gather(*(self.earnings_day(d) for d in dates), return_exceptions=True)
        out = []
        for r in res:
            if isinstance(r, list):
                out += r
        return out

    async def test(self) -> dict:
        rows = await self.earnings(dt.date.today(), 5)
        return {"ok": True, "detail": f"{len(rows)} reports in the next 5 days"}


def parse_nasdaq_earnings(payload: dict, day: dt.date) -> list[dict]:
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    timing = {"time-pre-market": "pre-market", "time-after-hours": "after close", "time-not-supplied": "n/a"}
    out = []
    for r in rows:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        out.append({"symbol": sym, "name": r.get("name", ""), "date": day.isoformat(),
                    "timing": timing.get(r.get("time"), r.get("time") or "n/a"),
                    "eps_forecast": r.get("epsForecast") or None, "estimates": r.get("noOfEsts") or None,
                    "market_cap": r.get("marketCap") or None, "last_year_eps": r.get("lastYearEPS") or None,
                    "eps_actual": nasdaq_actual(r)})
    return out


def nasdaq_actual(row: dict) -> str | None:
    """Nasdaq's reported EPS - only once it carries a surprise. Until Nasdaq has the new figure, its "eps" field holds
    the year-ago quarter (LRCX on 2026-10-21: "$1.26" = the Oct 2025 quarter, surprise "N/A"), which would read as a
    miss of 40 % (pure, tested)."""
    eps, surprise = (row.get("eps") or "").strip(), str(row.get("surprise") or "").strip()
    if not eps or eps.upper() == "N/A" or not surprise or surprise.upper() == "N/A":
        return None
    return eps


def _json_dumps(x) -> str:
    return json.dumps(x, default=str)
