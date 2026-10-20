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

## Default feed lists

- Squawk: investingLive, FinancialJuice.
- Markets: CNBC, WSJ, FT, Reuters and Bloomberg via Google News, BBC, FXStreet, OilPrice,
  Handelsblatt, Nikkei Asia.
- Central banks: Federal Reserve, ECB, Bank of England, Bank of Japan.
- Research: Krueger Algorithms research, Quantocracy, Alpha Architect, Liberty Street Economics,
  FEDS Notes, Damodaran Online, arXiv q-fin, ECB Blog.

Replace any list in **Settings → Feeds** (one `Name | URL` per line; empty box = built-in list).
