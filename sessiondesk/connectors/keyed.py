"""Connectors that need the user's own key (free tier or paid plan at the vendor).

All of these are written against the vendors' public API documentation and are marked
verified=False until someone runs them with a real key - the Connectors page shows that, and
"Test connection" makes the cheapest real call so the user sees immediately whether it works.

  finnhub           news (general + company), earnings calendar, quotes (US), economic calendar (premium)
  fmp               Financial Modeling Prep: fundamentals, DCF, economic calendar, news
  polygon           Polygon.io / Massive: snapshots, aggregates, news
  alphavantage      news with sentiment, quotes (25 calls/day on the free key)
  tradingeconomics  economic calendar WITH actual values (fast release output)
  alpaca            broker, READ-ONLY: account + positions; plus Benzinga news and IEX quotes
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

from .base import Connector, ConnectorError, Field, stable_id

COUNTRY_CCY = {"United States": "USD", "Euro Area": "EUR", "Germany": "EUR", "France": "EUR", "Italy": "EUR", "Spain": "EUR",
               "United Kingdom": "GBP", "Japan": "JPY", "China": "CNY", "Switzerland": "CHF", "Canada": "CAD",
               "Australia": "AUD", "New Zealand": "NZD", "US": "USD", "EU": "EUR", "UK": "GBP", "JP": "JPY", "CN": "CNY",
               "CH": "CHF", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR"}
IMPACT = {3: "high", 2: "medium", 1: "low", "high": "high", "medium": "medium", "low": "low",
          "High": "high", "Medium": "medium", "Low": "low"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _iso_ts(text: str | None) -> float | None:
    if not text:
        return None
    text = text.replace(" ", "T").replace("Z", "+00:00")
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.timestamp()


# ================================================================== Finnhub
class Finnhub(Connector):
    id = "finnhub"
    name = "Finnhub"
    tier = "free-key"
    kind = "news"
    capabilities = ("quotes", "news", "symbol_news", "earnings", "calendar", "profile_extra")
    fields = (Field("api_key", "API key", help="finnhub.io -> Dashboard. Free key: news, US quotes, earnings. Economic calendar needs a paid plan."),)
    homepage = "https://finnhub.io"
    description = "Fast general and company news, US real-time quotes, earnings calendar; economic calendar on paid plans."
    verified = False
    BASE = "https://finnhub.io/api/v1"

    async def _get(self, path: str, **params):
        return await self.get_json(self.BASE + path, params=params, headers={"X-Finnhub-Token": self.secret("api_key") or ""})

    async def test(self) -> dict:
        q = await self._get("/quote", symbol="AAPL")
        return {"ok": bool(q.get("c")), "detail": f"AAPL {q.get('c')}"}

    async def quotes(self, symbols: list[str]) -> dict:
        us = [s for s in symbols if s.replace("-", "").isalpha() and "." not in s][:30]   # free tier: US tickers

        async def one(sym):
            try:
                q = await self._get("/quote", symbol=sym)
            except ConnectorError:
                return None
            if not q.get("c"):
                return None
            return {"symbol": sym, "price": q["c"], "prev_close": q.get("pc"), "change": q.get("d"),
                    "change_pct": q.get("dp"), "time": q.get("t")}
        res = await asyncio.gather(*(one(s) for s in us))
        return {q["symbol"]: q for q in res if q}

    def _news(self, rows: list[dict]) -> list[dict]:
        return [{"id": stable_id("finnhub", r.get("id"), r.get("url")), "title": r.get("headline", ""), "url": r.get("url"),
                 "source": r.get("source") or "Finnhub", "published": int(r.get("datetime") or time.time()),
                 "summary": r.get("summary") or "", "symbols": [s for s in (r.get("related") or "").split(",") if s],
                 "provider": self.id} for r in rows if r.get("headline")]

    async def news(self) -> list[dict]:
        return self._news(await self._get("/news", category="general"))

    async def symbol_news(self, symbol: str) -> list[dict]:
        today = dt.date.today()
        return self._news(await self._get("/company-news", symbol=symbol, **{"from": (today - dt.timedelta(days=7)).isoformat(),
                                                                              "to": today.isoformat()}))

    async def earnings(self, start: dt.date, days: int = 7) -> list[dict]:
        data = await self._get("/calendar/earnings", **{"from": start.isoformat(), "to": (start + dt.timedelta(days=days)).isoformat()})
        timing = {"bmo": "pre-market", "amc": "after close", "dmh": "during market"}
        return [{"symbol": r.get("symbol"), "date": r.get("date"), "timing": timing.get(r.get("hour"), "n/a"),
                 "eps_forecast": r.get("epsEstimate"), "eps_actual": r.get("epsActual"),
                 "revenue_forecast": r.get("revenueEstimate"), "revenue_actual": r.get("revenueActual")}
                for r in data.get("earningsCalendar", [])]

    async def calendar(self, start: float | None = None, end: float | None = None) -> list[dict]:
        d0 = dt.datetime.fromtimestamp(start or time.time() - 86400, dt.timezone.utc).date()
        d1 = dt.datetime.fromtimestamp(end or time.time() + 7 * 86400, dt.timezone.utc).date()
        data = await self._get("/calendar/economic", **{"from": d0.isoformat(), "to": d1.isoformat()})
        out = []
        for r in data.get("economicCalendar", []):
            ts = _iso_ts(r.get("time"))
            if ts is None:
                continue
            unit = r.get("unit") or ""
            out.append({"id": stable_id("finnhub", r.get("country"), r.get("event"), ts), "ts": ts,
                        "currency": COUNTRY_CCY.get(r.get("country"), r.get("country") or ""), "country": r.get("country"),
                        "title": r.get("event", ""), "impact": IMPACT.get(r.get("impact"), "low"),
                        "actual": None if r.get("actual") is None else f"{r['actual']}{unit}",
                        "forecast": None if r.get("estimate") is None else f"{r['estimate']}{unit}",
                        "previous": None if r.get("prev") is None else f"{r['prev']}{unit}",
                        "actual_value": _f(r.get("actual")), "forecast_value": _f(r.get("estimate")), "source": self.id})
        return out


# ================================================================== Financial Modeling Prep
class FMP(Connector):
    id = "fmp"
    name = "Financial Modeling Prep"
    tier = "free-key"
    capabilities = ("profile_extra", "symbol_news", "calendar", "earnings", "dcf")
    fields = (Field("api_key", "API key", help="financialmodelingprep.com -> Dashboard. Free key covers profiles and ratios for US stocks."),)
    homepage = "https://financialmodelingprep.com"
    description = "Fundamentals, TTM ratios, vendor DCF, economic calendar with actuals, stock news."
    verified = False
    BASE = "https://financialmodelingprep.com/stable"

    async def _get(self, path: str, **params):
        params["apikey"] = self.secret("api_key") or ""
        return await self.get_json(self.BASE + path, params=params)

    async def test(self) -> dict:
        p = await self._get("/profile", symbol="AAPL")
        return {"ok": bool(p), "detail": (p[0].get("companyName") if p else "empty")}

    async def profile_extra(self, symbol: str) -> dict:
        prof, ratios, dcf = await asyncio.gather(self._get("/profile", symbol=symbol), self._get("/ratios-ttm", symbol=symbol),
                                                 self._get("/discounted-cash-flow", symbol=symbol), return_exceptions=True)
        out = {}
        if isinstance(prof, list) and prof:
            p = prof[0]
            out.update({"name": p.get("companyName"), "sector": p.get("sector"), "industry": p.get("industry"),
                        "market_cap": p.get("marketCap"), "beta": p.get("beta"), "website": p.get("website"),
                        "summary": p.get("description"), "employees": _f(p.get("fullTimeEmployees"))})
        if isinstance(ratios, list) and ratios:
            r = ratios[0]
            out["ratios_ttm"] = {k: v for k, v in r.items() if isinstance(v, (int, float))}
        if isinstance(dcf, list) and dcf:
            out["vendor_dcf"] = {"value": _f(dcf[0].get("dcf")), "price": _f(dcf[0].get("Stock Price")), "date": dcf[0].get("date")}
        if not out:
            raise ConnectorError("FMP returned nothing for " + symbol)
        return out

    async def symbol_news(self, symbol: str) -> list[dict]:
        rows = await self._get("/news/stock", symbols=symbol, limit=30)
        return [{"id": stable_id("fmp", r.get("url")), "title": r.get("title", ""), "url": r.get("url"),
                 "source": r.get("publisher") or r.get("site") or "FMP", "published": int(_iso_ts(r.get("publishedDate")) or time.time()),
                 "summary": (r.get("text") or "")[:600], "symbols": [symbol], "provider": self.id} for r in rows or []]

    async def calendar(self, start: float | None = None, end: float | None = None) -> list[dict]:
        d0 = dt.datetime.fromtimestamp(start or time.time() - 86400, dt.timezone.utc).date()
        d1 = dt.datetime.fromtimestamp(end or time.time() + 7 * 86400, dt.timezone.utc).date()
        rows = await self._get("/economic-calendar", **{"from": d0.isoformat(), "to": d1.isoformat()})
        out = []
        for r in rows or []:
            ts = _iso_ts(r.get("date"))
            if ts is None:
                continue
            unit = r.get("unit") or ""
            out.append({"id": stable_id("fmp", r.get("country"), r.get("event"), ts), "ts": ts,
                        "currency": r.get("currency") or COUNTRY_CCY.get(r.get("country"), ""), "country": r.get("country"),
                        "title": r.get("event", ""), "impact": IMPACT.get(r.get("impact"), "low"),
                        "actual": None if r.get("actual") is None else f"{r['actual']}{unit}",
                        "forecast": None if r.get("estimate") is None else f"{r['estimate']}{unit}",
                        "previous": None if r.get("previous") is None else f"{r['previous']}{unit}",
                        "actual_value": _f(r.get("actual")), "forecast_value": _f(r.get("estimate")), "source": self.id})
        return out

    async def earnings(self, start: dt.date, days: int = 7) -> list[dict]:
        rows = await self._get("/earnings-calendar", **{"from": start.isoformat(), "to": (start + dt.timedelta(days=days)).isoformat()})
        return [{"symbol": r.get("symbol"), "date": r.get("date"), "timing": "n/a", "eps_forecast": r.get("epsEstimated"),
                 "eps_actual": r.get("epsActual"), "revenue_forecast": r.get("revenueEstimated")} for r in rows or []]


# ================================================================== Polygon / Massive
class Polygon(Connector):
    id = "polygon"
    name = "Polygon.io (Massive)"
    tier = "paid"
    capabilities = ("quotes", "history", "symbol_news", "news")
    fields = (Field("api_key", "API key", help="polygon.io dashboard. Snapshots (live quotes) need a paid stocks plan; aggregates and news work on the free key."),)
    homepage = "https://polygon.io"
    description = "US stocks: real-time snapshots (paid), minute/day aggregates, ticker news."
    verified = False
    BASE = "https://api.polygon.io"

    async def _get(self, path: str, **params):
        params["apiKey"] = self.secret("api_key") or ""
        return await self.get_json(self.BASE + path, params=params)

    async def test(self) -> dict:
        d = await self._get("/v2/aggs/ticker/AAPL/prev")
        r = (d.get("results") or [{}])[0]
        return {"ok": bool(r.get("c")), "detail": f"AAPL prev close {r.get('c')}"}

    async def quotes(self, symbols: list[str]) -> dict:
        us = [s for s in symbols if s.replace("-", "").isalpha()]
        if not us:
            return {}
        d = await self._get("/v2/snapshot/locale/us/markets/stocks/tickers", tickers=",".join(us[:250]))
        out = {}
        for t in d.get("tickers", []):
            price = _f((t.get("lastTrade") or {}).get("p")) or _f((t.get("day") or {}).get("c"))
            prev = _f((t.get("prevDay") or {}).get("c"))
            if price:
                out[t["ticker"]] = {"symbol": t["ticker"], "price": price, "prev_close": prev,
                                    "change": _f(t.get("todaysChange")), "change_pct": _f(t.get("todaysChangePerc")),
                                    "time": (t.get("updated") or 0) / 1e9 or None}
        return out

    async def history(self, symbol: str, range_: str = "1y", interval: str | None = None) -> dict:
        days = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827, "10y": 3653}.get(range_.removesuffix("-d"), 366)
        end = dt.date.today()
        d = await self._get(f"/v2/aggs/ticker/{symbol}/range/1/day/{(end - dt.timedelta(days=days)).isoformat()}/{end.isoformat()}",
                            adjusted="true", sort="asc", limit=50000)
        bars = [{"t": int(r["t"] / 1000), "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r.get("v", 0)} for r in d.get("results", [])]
        if not bars:
            raise ConnectorError(f"Polygon: no bars for {symbol}")
        return {"symbol": symbol, "bars": bars, "price": bars[-1]["c"], "currency": "USD"}

    def _news(self, rows) -> list[dict]:
        return [{"id": stable_id("polygon", r.get("id")), "title": r.get("title", ""), "url": r.get("article_url"),
                 "source": (r.get("publisher") or {}).get("name", "Polygon"), "published": int(_iso_ts(r.get("published_utc")) or time.time()),
                 "summary": r.get("description") or "", "symbols": r.get("tickers") or [], "provider": self.id} for r in rows]

    async def symbol_news(self, symbol: str) -> list[dict]:
        return self._news((await self._get("/v2/reference/news", ticker=symbol, limit=30, order="desc")).get("results", []))

    async def news(self) -> list[dict]:
        return self._news((await self._get("/v2/reference/news", limit=50, order="desc")).get("results", []))


# ================================================================== Alpha Vantage
class AlphaVantage(Connector):
    id = "alphavantage"
    name = "Alpha Vantage"
    tier = "free-key"
    capabilities = ("symbol_news",)
    fields = (Field("api_key", "API key", help="alphavantage.co/support/#api-key - free key = 25 calls per day."),)
    homepage = "https://www.alphavantage.co"
    description = "Ticker news with sentiment scores. The free key allows only 25 calls a day, so SessionDesk uses it for news only."
    verified = False

    async def _get(self, **params):
        params["apikey"] = self.secret("api_key") or ""
        d = await self.get_json("https://www.alphavantage.co/query", params=params)
        if isinstance(d, dict) and (d.get("Note") or d.get("Information")):
            raise ConnectorError("Alpha Vantage: " + (d.get("Note") or d.get("Information"))[:120])
        return d

    async def test(self) -> dict:
        d = await self._get(function="GLOBAL_QUOTE", symbol="IBM")
        q = d.get("Global Quote") or {}
        return {"ok": bool(q.get("05. price")), "detail": f"IBM {q.get('05. price')}"}

    async def symbol_news(self, symbol: str) -> list[dict]:
        d = await self._get(function="NEWS_SENTIMENT", tickers=symbol, limit=30)
        out = []
        for r in d.get("feed", []):
            ts = None
            try:
                ts = dt.datetime.strptime(r.get("time_published", ""), "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
            except ValueError:
                pass
            out.append({"id": stable_id("av", r.get("url")), "title": r.get("title", ""), "url": r.get("url"),
                        "source": r.get("source") or "Alpha Vantage", "published": int(ts or time.time()),
                        "summary": r.get("summary") or "", "symbols": [t.get("ticker") for t in r.get("ticker_sentiment", [])],
                        "sentiment": r.get("overall_sentiment_label"), "provider": self.id})
        return out


# ================================================================== TradingEconomics
class TradingEconomics(Connector):
    id = "tradingeconomics"
    name = "Trading Economics"
    tier = "paid"
    kind = "calendar"
    capabilities = ("calendar",)
    fields = (Field("api_key", "API key", help="tradingeconomics.com/api - format 'key:secret'. 'guest:guest' returns a small sample for testing."),)
    homepage = "https://tradingeconomics.com/api"
    description = "Economic calendar with actual values as they print - the cleanest paid source for fast release output."
    verified = False

    async def test(self) -> dict:
        ev = await self.calendar(time.time() - 3 * 86400, time.time() + 3 * 86400)
        return {"ok": True, "detail": f"{len(ev)} events"}

    async def calendar(self, start: float | None = None, end: float | None = None) -> list[dict]:
        d0 = dt.datetime.fromtimestamp(start or time.time() - 86400, dt.timezone.utc).date()
        d1 = dt.datetime.fromtimestamp(end or time.time() + 7 * 86400, dt.timezone.utc).date()
        rows = await self.get_json(f"https://api.tradingeconomics.com/calendar/country/All/{d0.isoformat()}/{d1.isoformat()}",
                                   params={"c": self.secret("api_key") or "", "f": "json"})
        out = []
        for r in rows or []:
            ts = _iso_ts(r.get("Date"))
            if ts is None:
                continue
            out.append({"id": stable_id("te", r.get("CalendarId")), "ts": ts,
                        "currency": r.get("Currency") or COUNTRY_CCY.get(r.get("Country"), ""), "country": r.get("Country"),
                        "title": r.get("Event", ""), "impact": IMPACT.get(r.get("Importance"), "low"),
                        "actual": r.get("Actual") or None, "forecast": r.get("Forecast") or r.get("TEForecast") or None,
                        "previous": r.get("Revised") or r.get("Previous") or None,
                        "actual_value": _f(str(r.get("Actual") or "").rstrip("%KMBT")),
                        "forecast_value": _f(str(r.get("Forecast") or "").rstrip("%KMBT")), "source": self.id})
        return out


# ================================================================== Alpaca (read-only)
class Alpaca(Connector):
    id = "alpaca"
    name = "Alpaca (read-only)"
    tier = "free-key"
    kind = "broker"
    capabilities = ("account", "positions", "news", "symbol_news", "quotes")
    fields = (Field("key_id", "API key ID"), Field("secret_key", "API secret key"),
              Field("mode", "Account", secret=False, required=False, help="paper or live (default paper). Read-only either way.",
                    placeholder="paper"))
    homepage = "https://alpaca.markets"
    description = ("READ-ONLY broker view (account, positions) plus real-time Benzinga news and IEX quotes with a free account. "
                   "SessionDesk never places, changes or cancels orders.")
    verified = False

    def _headers(self) -> dict:
        return {"APCA-API-KEY-ID": self.secret("key_id") or "", "APCA-API-SECRET-KEY": self.secret("secret_key") or ""}

    def _base(self) -> str:
        return "https://api.alpaca.markets" if self.option("mode") == "live" else "https://paper-api.alpaca.markets"

    async def test(self) -> dict:
        a = await self.get_json(self._base() + "/v2/account", headers=self._headers())
        return {"ok": bool(a.get("status")), "detail": f"account {a.get('status')}, {a.get('currency')}"}

    async def account(self) -> list[dict]:
        a = await self.get_json(self._base() + "/v2/account", headers=self._headers())
        return [{"login": "alpaca-" + (self.option("mode") or "paper"), "currency": a.get("currency"), "equity": _f(a.get("equity")),
                 "balance": _f(a.get("cash")), "profit": (_f(a.get("equity")) or 0) - (_f(a.get("last_equity")) or 0),
                 "trade_allowed": not a.get("trading_blocked"), "connected": True, "fresh": True, "age": 0}]

    async def positions(self) -> list[dict]:
        rows = await self.get_json(self._base() + "/v2/positions", headers=self._headers())
        return [{"account": "alpaca-" + (self.option("mode") or "paper"), "symbol": r.get("symbol"),
                 "side": "LONG" if r.get("side") == "long" else "SHORT", "volume": _f(r.get("qty")),
                 "open_price": _f(r.get("avg_entry_price")), "price": _f(r.get("current_price")),
                 "profit": _f(r.get("unrealized_pl")), "sl": None, "risk_to_stop": None, "magic": None, "manual": True,
                 "fresh": True, "age": 0} for r in rows or []]

    def _news(self, rows) -> list[dict]:
        return [{"id": stable_id("alpaca", r.get("id")), "title": r.get("headline", ""), "url": r.get("url"),
                 "source": r.get("source") or "Benzinga", "published": int(_iso_ts(r.get("created_at")) or time.time()),
                 "summary": r.get("summary") or "", "symbols": r.get("symbols") or [], "provider": self.id} for r in rows]

    async def news(self) -> list[dict]:
        d = await self.get_json("https://data.alpaca.markets/v1beta1/news", params={"limit": 50, "sort": "desc"}, headers=self._headers())
        return self._news(d.get("news", []))

    async def symbol_news(self, symbol: str) -> list[dict]:
        d = await self.get_json("https://data.alpaca.markets/v1beta1/news", params={"symbols": symbol, "limit": 30, "sort": "desc"},
                                headers=self._headers())
        return self._news(d.get("news", []))

    async def quotes(self, symbols: list[str]) -> dict:
        us = [s for s in symbols if s.replace("-", "").isalpha()]
        if not us:
            return {}
        d = await self.get_json("https://data.alpaca.markets/v2/stocks/snapshots", params={"symbols": ",".join(us[:200])},
                                headers=self._headers())
        out = {}
        for sym, s in (d or {}).items():
            price = _f((s.get("latestTrade") or {}).get("p")) or _f((s.get("dailyBar") or {}).get("c"))
            prev = _f((s.get("prevDailyBar") or {}).get("c"))
            if price:
                out[sym] = {"symbol": sym, "price": price, "prev_close": prev, "change": price - prev if prev else None,
                            "change_pct": (price / prev - 1) * 100 if prev else None,
                            "time": _iso_ts((s.get("latestTrade") or {}).get("t"))}
        return out
