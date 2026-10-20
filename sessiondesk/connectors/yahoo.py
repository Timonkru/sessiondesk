"""Yahoo Finance - the free default for quotes, history, search, fundamentals and per-ticker news.

Unofficial endpoints (the same ones the yfinance library uses). Fine for personal use; for
anything commercial or latency-critical, connect a licensed provider - the hub prefers keyed
connectors automatically.

  quotes    v8 spark, 20 symbols per call, calls run in parallel     ~0.7 s for 20, ~1.5 s for 500
  history   v8 chart
  search    v1 search
  profile   yfinance Ticker.info + cash-flow statement (needs Yahoo's crumb, yfinance handles it)
  news      per-ticker RSS
"""
from __future__ import annotations

import asyncio
import math
import time

from .base import Connector, ConnectorError, stable_id

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
SPARK = "https://query1.finance.yahoo.com/v8/finance/spark"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"

RANGES = {"1d": "5m", "5d": "15m", "1mo": "1h", "3mo": "1d", "6mo": "1d", "1y": "1d", "2y": "1d",
          "5y": "1wk", "10y": "1mo", "max": "1mo", "ytd": "1d"}


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class Yahoo(Connector):
    id = "yahoo"
    name = "Yahoo Finance"
    tier = "free"
    capabilities = ("quotes", "history", "search", "profile", "symbol_news")
    homepage = "https://finance.yahoo.com"
    description = "Quotes (delayed by exchange rules), history, search, fundamentals, per-ticker headlines. Unofficial API, personal use."

    def __init__(self, ctx):
        super().__init__(ctx)
        self._sem = asyncio.Semaphore(6)

    async def test(self) -> dict:
        q = await self.quotes(["^GSPC"])
        ok = bool(q.get("^GSPC", {}).get("price"))
        return {"ok": ok, "detail": f"S&P 500 = {q['^GSPC']['price']:.2f}" if ok else "no data"}

    # ------------------------------------------------------------ quotes
    async def _spark(self, chunk: list[str], range_: str, interval: str) -> dict:
        async with self._sem:
            resp = await self.ctx.http.get(SPARK, params={"symbols": ",".join(chunk), "range": range_, "interval": interval},
                                           headers=UA, timeout=12)
        if resp.status_code != 200:
            raise ConnectorError(f"Yahoo spark HTTP {resp.status_code}")
        return resp.json()

    async def quotes(self, symbols: list[str], *, intraday: bool = True) -> dict:
        """{symbol: Quote}. intraday=True adds a 5-minute 'spark' path of today's session."""
        symbols = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
        range_, interval = ("1d", "5m") if intraday else ("5d", "1d")
        chunks = [symbols[i:i + 20] for i in range(0, len(symbols), 20)]
        results = await asyncio.gather(*(self._spark(c, range_, interval) for c in chunks), return_exceptions=True)
        out: dict[str, dict] = {}
        for res in results:
            if isinstance(res, Exception):
                continue
            for sym, d in res.items():
                q = parse_spark(sym, d, intraday=intraday)
                if q:
                    out[sym] = q
        if symbols and not out and any(isinstance(r, Exception) for r in results):
            raise ConnectorError(str(next(r for r in results if isinstance(r, Exception))))
        return out

    async def daily_closes(self, symbols: list[str], range_: str = "3mo") -> dict[str, list[float]]:
        """{symbol: [daily closes]} for volatility / beta estimates (spark, 20 per call)."""
        chunks = [symbols[i:i + 20] for i in range(0, len(symbols), 20)]
        results = await asyncio.gather(*(self._spark(c, range_, "1d") for c in chunks), return_exceptions=True)
        out = {}
        for res in results:
            if isinstance(res, Exception):
                continue
            for sym, d in res.items():
                closes = [c for c in (d.get("close") or []) if _num(c) is not None]
                if closes:
                    out[sym] = [float(c) for c in closes]
        return out

    async def daily_series(self, symbols: list[str], range_: str = "2y") -> dict[str, list[tuple[str, float]]]:
        """{symbol: [(YYYY-MM-DD, close)]} - dated daily closes (spark, 20 per call), for the data hub."""
        import datetime as _dt
        chunks = [symbols[i:i + 20] for i in range(0, len(symbols), 20)]
        results = await asyncio.gather(*(self._spark(c, range_, "1d") for c in chunks), return_exceptions=True)
        out = {}
        for res in results:
            if isinstance(res, Exception):
                continue
            for sym, d in res.items():
                pts = [(_dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), float(c))
                       for t, c in zip(d.get("timestamp") or [], d.get("close") or []) if t and _num(c) is not None]
                if pts:
                    out[sym] = list(dict(pts).items())             # one value per day (the latest wins)
        return out

    # ------------------------------------------------------------ history
    async def history(self, symbol: str, range_: str = "1y", interval: str | None = None) -> dict:
        if range_.endswith("-d"):                      # "10y-d" = daily bars over the whole range (statistics)
            range_, interval = range_[:-2], "1d"
        interval = interval or RANGES.get(range_, "1d")
        async with self._sem:
            resp = await self.ctx.http.get(CHART + symbol, params={"range": range_, "interval": interval,
                                                                   "includePrePost": "false", "events": "div,splits"},
                                           headers=UA, timeout=12)
        if resp.status_code == 404:
            raise ConnectorError(f"unknown symbol {symbol}")
        if resp.status_code != 200:
            raise ConnectorError(f"Yahoo chart HTTP {resp.status_code}")
        return parse_chart(resp.json())

    async def search(self, q: str) -> list[dict]:
        async with self._sem:
            resp = await self.ctx.http.get(SEARCH, params={"q": q, "quotesCount": 10, "newsCount": 0}, headers=UA, timeout=8)
        if resp.status_code != 200:
            raise ConnectorError(f"Yahoo search HTTP {resp.status_code}")
        out = []
        for item in resp.json().get("quotes", []):
            if not item.get("symbol"):
                continue
            out.append({"symbol": item["symbol"], "name": (item.get("longname") or item.get("shortname") or "").strip(),
                        "exchange": item.get("exchDisp") or item.get("exchange"), "type": item.get("quoteType"),
                        "sector": item.get("sectorDisp") or item.get("sector")})
        return out

    # ------------------------------------------------------------ fundamentals
    async def profile(self, symbol: str) -> dict:
        return await asyncio.to_thread(_yf_profile, symbol)

    # ------------------------------------------------------------ news
    async def symbol_news(self, symbol: str) -> list[dict]:
        from ..features.feeds import parse_feed
        resp = await self.ctx.http.get(RSS, params={"s": symbol, "region": "US", "lang": "en-US"}, headers=UA, timeout=10)
        if resp.status_code != 200:
            raise ConnectorError(f"Yahoo RSS HTTP {resp.status_code}")
        items = await asyncio.to_thread(parse_feed, resp.content, "Yahoo Finance")
        for item in items:
            item["symbols"] = [symbol]
            item["provider"] = self.id
        return items


# ---------------------------------------------------------------- parsers (pure, tested)
def parse_spark(symbol: str, d: dict, *, intraday: bool) -> dict | None:
    closes = [(_num(c), t) for c, t in zip(d.get("close") or [], d.get("timestamp") or [])]
    closes = [(c, t) for c, t in closes if c is not None]
    if not closes:
        return None
    price, ts = closes[-1]
    if intraday:
        prev = _num(d.get("chartPreviousClose")) or _num(d.get("previousClose"))
    else:
        prev = closes[-2][0] if len(closes) >= 2 else None
    q = {"symbol": symbol, "price": price, "prev_close": prev, "time": ts,
         "change": price - prev if prev else None,
         "change_pct": (price / prev - 1) * 100 if prev else None}
    if intraday:
        step = max(1, len(closes) // 60)          # keep the path light: <= ~60 points
        q["spark"] = [round(c, 6) for c, _ in closes[::step]]
    return q


def parse_chart(payload: dict) -> dict:
    res = (payload.get("chart") or {}).get("result") or []
    if not res:
        err = ((payload.get("chart") or {}).get("error") or {}).get("description", "no data")
        raise ConnectorError(f"Yahoo chart: {err}")
    r = res[0]
    meta = r.get("meta", {})
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        c = _num((q.get("close") or [None])[i] if i < len(q.get("close") or []) else None)
        if c is None:
            continue
        def g(k):
            arr = q.get(k) or []
            return _num(arr[i]) if i < len(arr) else None
        bars.append({"t": int(t), "o": g("open") or c, "h": g("high") or c, "l": g("low") or c, "c": c, "v": g("volume") or 0})
    return {
        "symbol": meta.get("symbol"), "currency": meta.get("currency"), "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "name": meta.get("longName") or meta.get("shortName"), "type": meta.get("instrumentType"),
        "price": _num(meta.get("regularMarketPrice")), "time": meta.get("regularMarketTime"),
        "change_pct": _num(meta.get("regularMarketChangePercent")),
        "day_high": _num(meta.get("regularMarketDayHigh")), "day_low": _num(meta.get("regularMarketDayLow")),
        "volume": _num(meta.get("regularMarketVolume")),
        "high_52w": _num(meta.get("fiftyTwoWeekHigh")), "low_52w": _num(meta.get("fiftyTwoWeekLow")),
        "timezone": meta.get("exchangeTimezoneName"), "bars": bars,
    }


PROFILE_KEYS = {
    # identity
    "longName": "name", "shortName": "short_name", "sector": "sector", "industry": "industry", "country": "country",
    "website": "website", "fullTimeEmployees": "employees", "longBusinessSummary": "summary", "currency": "currency",
    "financialCurrency": "financial_currency", "exchange": "exchange", "quoteType": "type",
    # size / price
    "marketCap": "market_cap", "enterpriseValue": "enterprise_value", "sharesOutstanding": "shares",
    "currentPrice": "price", "regularMarketPrice": "market_price", "previousClose": "prev_close",
    "fiftyTwoWeekHigh": "high_52w", "fiftyTwoWeekLow": "low_52w", "averageVolume": "avg_volume", "beta": "beta",
    # valuation
    "trailingPE": "pe_trailing", "forwardPE": "pe_forward", "pegRatio": "peg", "trailingPegRatio": "peg_trailing",
    "priceToBook": "pb", "priceToSalesTrailing12Months": "ps", "enterpriseToEbitda": "ev_ebitda",
    "enterpriseToRevenue": "ev_revenue", "trailingEps": "eps_trailing", "forwardEps": "eps_forward",
    # quality / growth
    "grossMargins": "gross_margin", "operatingMargins": "operating_margin", "profitMargins": "net_margin",
    "returnOnEquity": "roe", "returnOnAssets": "roa", "revenueGrowth": "revenue_growth", "earningsGrowth": "earnings_growth",
    "totalRevenue": "revenue", "ebitda": "ebitda", "freeCashflow": "fcf_info", "operatingCashflow": "ocf",
    "totalCash": "cash", "totalDebt": "debt", "debtToEquity": "debt_to_equity", "currentRatio": "current_ratio",
    # income
    "dividendRate": "dividend_rate", "payoutRatio": "payout_ratio",
    # street
    "targetMeanPrice": "target_mean", "targetHighPrice": "target_high", "targetLowPrice": "target_low",
    "numberOfAnalystOpinions": "analysts", "recommendationKey": "recommendation", "recommendationMean": "recommendation_mean",
    # short interest / float
    "sharesShort": "shares_short", "sharesShortPriorMonth": "shares_short_prior", "shortPercentOfFloat": "short_pct_float",
    "shortRatio": "short_ratio", "dateShortInterest": "short_date", "floatShares": "float_shares",
    "heldPercentInsiders": "held_insiders", "heldPercentInstitutions": "held_institutions",
    # dates
    "earningsTimestamp": "earnings_ts", "earningsTimestampStart": "earnings_start", "earningsTimestampEnd": "earnings_end",
    "exDividendDate": "ex_dividend",
}


def _yf_profile(symbol: str) -> dict:
    import yfinance as yf  # imported lazily: heavy, and only needed here
    t = yf.Ticker(symbol)
    info = t.info or {}
    if not info or (len(info) <= 2 and "trailingPegRatio" in info):
        raise ConnectorError(f"no profile data for {symbol}")
    out = {v: info.get(k) for k, v in PROFILE_KEYS.items() if info.get(k) is not None}
    # Yahoo's dividendYield switched from fraction to percent in 2025 and is ambiguous below 1 -> derive it
    # from the annual dividend rate and the price instead (always a fraction here).
    px = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    rate = _num(info.get("dividendRate"))
    if px and rate is not None:
        out["dividend_yield"] = rate / px
    out["symbol"] = symbol
    out["fcf_history"] = []
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            row = next((r for r in ("Free Cash Flow", "FreeCashFlow") if r in cf.index), None)
            if row:
                for col, val in cf.loc[row].items():
                    v = _num(val)
                    if v is not None:
                        out["fcf_history"].append({"year": str(getattr(col, "year", col)), "fcf": v})
    except Exception:
        pass
    out["fetched"] = time.time()
    return out


def news_id(url: str, title: str) -> str:
    return stable_id(url or "", title or "")
