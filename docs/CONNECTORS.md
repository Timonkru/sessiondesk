# Connectors

A connector wraps one outside system. Free ones work immediately; keyed and paid ones need the
user's own key, entered in **Settings → Connectors** or set as an environment variable
(`SESSIONDESK_<ID>_<FIELD>`, for example `SESSIONDESK_FINNHUB_API_KEY`; AI keys also accept the
vendors' standard names such as `ANTHROPIC_API_KEY`).

## Routing

`Hub.candidates(capability)` returns the active connectors in this order:

1. the user's explicit preference (`settings.preferences.<capability>`),
2. for news and calendars: paid, then free-key, then free,
3. for quotes and history: paid, then the free Yahoo feed (20 symbols per call, global coverage),
   then free-key APIs that cost one rate-limited call per symbol.

Quotes are filled: each connector only supplies the symbols the previous one could not deliver.
News and calendars are merged across all active sources and de-duplicated.

## Capabilities and normalized shapes

| Capability | Method | Returns |
|---|---|---|
| quotes | `quotes(symbols)` | `{symbol: {symbol, price, prev_close, change, change_pct, time}}` |
| history | `history(symbol, range)` | `{symbol, bars: [{t, o, h, l, c, v}], ...}` |
| search | `search(q)` | `[{symbol, name, exchange, type}]` |
| profile | `profile(symbol)` | fundamentals dict (see PROFILE_KEYS in `connectors/yahoo.py`) |
| news, symbol_news | `news()`, `symbol_news(symbol)` | `[{id, title, url, source, published, summary, symbols}]` |
| calendar | `calendar(start, end)` | `[{id, ts, currency, title, impact, actual, forecast, previous, source}]` |
| earnings | `earnings(start_date, days)` | `[{symbol, date, timing, eps_forecast, ...}]` |
| account, positions, eas | read-only broker views | see `connectors/mt5.py` |

## Adding a connector

1. Subclass `Connector` in `sessiondesk/connectors/` and set `id`, `name`, `tier`, `kind`,
   `capabilities`, `fields`, `homepage`, `description`.
2. Implement the capability methods and `test()` (the cheapest real call).
3. Keep `verified = False` until it has run against a live key.
4. Add the class to `ALL` in `connectors/registry.py`.
5. Add an offline test with a canned payload (see `tests/conftest.py`).

## Energy fundamentals (Data hub collectors)

These feed the Data hub and the Commodities & energy page. They run in the background (every few hours) and
load their history once on the first run.

| Source | Key | What | Notes |
|---|---|---|---|
| EIA | none | US weekly oil stocks and gas storage | history pages scraped once per series |
| Energy-Charts | none | day-ahead power prices, 12 bidding zones | CC BY 4.0, Bundesnetzagentur / SMARD.de |
| ENTSOG Transparency Platform | none | daily physical gas flows at the EU entry points (`api/v1/operationalData`), summed per route and per LNG country | each source is counted once where it enters the EU (TurkStream at Strandzha 2, TAP at Kipoi); Kotlovka (transit to Kaliningrad) is left out; the Emden landing points publish no flows, so the Norway route is incomplete; recent days are provisional and are reloaded for two weeks |
| GIE AGSI+ (`agsi`) | free key, header `x-key` | gas storage fill level, injection, withdrawal for the EU, DE, IT, FR, NL, AT | create the key at agsi.gie.eu, enter it under Settings → Connectors; at most 60 calls per minute, SessionDesk pauses between pages; without a key the collector does nothing and the page says "key needed" |

## Company proxies and the Earnings nowcast

`features/proxies.py` collects, every three hours, free numbers per company into the Data hub (group "Company
proxies"). Which company gets which proxy is the user's own file `<data dir>/earnings_proxies.json`; SessionDesk writes
it with four neutral examples on first use. Format:

```json
{"companies": {
  "DAL":  {"wikipedia": ["Delta Air Lines"], "tsa": true, "primary": "tsa"},
  "EA":   {"steam": [1172470, 2807960], "primary": "steam"},
  "DUOL": {"apps": [570060128], "primary": "apps_grossing"},
  "NFLX": {"wikipedia": ["Netflix"], "indeed": {"country": "US", "sector": "Media & Communications"}, "primary": "wiki"}
}}
```

`primary` is the proxy the nowcast regression uses. Fix it before looking at any fit; picking the best-fitting proxy
afterwards is overfitting. The verdict of an out-of-sample test can be added as `"validation": {"status": ..., "text": ...}`
and replaces the "unvalidated" banner.

| Source | Key | Series | Notes |
|---|---|---|---|
| Wikimedia pageviews REST API | none | `wiki:<ticker>` daily views, summed over the listed articles | from 2015-07; only days all listed articles have; use the current title (a renamed article starts its history at the rename) |
| TSA checkpoint travel numbers | none | `tsa:us` travellers per day | tsa.gov page per year from 2019 (HTML table, unofficial parsing) |
| Steam Web API `GetNumberOfCurrentPlayers` | none | `steam:<ticker>` concurrent players, summed | a snapshot per run, the day keeps its highest snapshot; Steam publishes no history, so the series starts with the first run |
| Apple iTunes RSS charts | none | `apps:<ticker>:grossing`, `apps:<ticker>:free` best rank | US top 100 only; no point on days outside it; history starts with the first run |
| Indeed Hiring Lab (GitHub CSV) | none | `indeed:<country>:<category>` postings index | job categories, not companies or industries; daily, from 2020-02, a few days behind; fetched once a day |
| SEC EDGAR Form 4 | contact email | `form4:<ticker>:net` open-market purchases minus sales per month | codes P and S only; the Archives host answers 403 without a contact email; history grows from the newest 60 filings |
| SEC EDGAR XBRL company facts | none | (no series) fiscal quarters and revenue for the nowcast | US filers only; Q4 = fiscal year minus Q1-Q3; when the tagged revenue stops early the page says so instead of guessing the quarter |
| FMP `/stable/earnings`, Finnhub `/stock/earnings` + earnings calendar | your key | (no series) consensus history | revenue and EPS estimate vs actual per quarter; without a key the page says "key needed" and takes Yahoo's current-quarter revenue estimate and EPS history |

Google Trends is not included: there is no official API, the unofficial one rate-limits after a few calls and rescales
every request, so a stored history would not be comparable. These proxies never take part in the Data hub's pushed
early warnings (`datahub.NO_WARN_PREFIX`); the nowcast page has its own alert, off by default.

Paid alternative data: **Quiver Quantitative** has an adapter (`connectors/keyed.py`, `verified = False` until a key
is entered and "Test connection" succeeds). Placer.ai (foot traffic), Similarweb (web traffic) and Second Measure /
Bloomberg Second Measure (card spend) would each need their own adapter; none is written.

## Default feed lists

- Squawk: investingLive, FinancialJuice.
- Markets: CNBC, WSJ, FT, Reuters and Bloomberg via Google News, BBC, FXStreet, OilPrice,
  Handelsblatt, Nikkei Asia.
- Central banks: Federal Reserve, ECB, Bank of England, Bank of Japan.
- Research: Krueger Algorithms research, Quantocracy, Alpha Architect, Liberty Street Economics,
  FEDS Notes, Damodaran Online, arXiv q-fin, ECB Blog.

Replace any list in **Settings → Feeds** (one `Name | URL` per line; empty box = built-in list).
