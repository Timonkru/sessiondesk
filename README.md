# SessionDesk

A local-first market desk that runs in your browser. Markets, single stocks with valuation,
unusual-move alerts that explain themselves, high-impact release warnings with the print pushed
the moment it lands, a forced-flow calendar, a research reader, your own scripts as jobs, and a
read-only view of your MetaTrader accounts and Expert Advisors.

It works out of the box on free data. Everything that costs money - real-time feeds, calendars
with actual values, fundamentals APIs, and the AI - is a connector you switch on with **your own
key**. Nothing is sent anywhere except to the sources you enable.

> SessionDesk is a research and monitoring tool. It never places, changes or closes orders, and it
> is not investment advice. Free data can be delayed or wrong; every panel names its source.

**Made by [Krueger Algorithms](https://kruegeralgorithms.com/en)**: market research with published methods, and
tools for prop traders (risk guardian, position sizer, trade copier, correlation check) on the
[MQL5 Market](https://www.mql5.com/en/users/sg_mephisot/seller). SessionDesk is free and open source.

## What is inside

| Page | What it does |
|---|---|
| **Today** | Your trading day on one page: accounts with a prop-rule meter (daily loss, own stop, open slots), rule flags, your own session schedule with release collisions marked, next releases and forced flows, an AI briefing written from computed facts, what changed since you last looked, one-line notes. Schedule and rules live in your local settings. |
| **My desk** | Your own screens: tiles from every part of SessionDesk - quotes with today's path, a chart, Data hub series (several rebased on one chart), news by market, the next releases, your alerts, a basket, movers of any index or region, the sector heat map, tanker counts. Several layouts as tabs; Edit adds, moves, resizes and removes tiles; each tile refreshes itself. Saved locally. |
| **Markets** | The Overview: indices by region (Americas, Europe, Asia-Pacific, Middle East & Africa), index futures, US yields (moves in basis points), FX, commodities, crypto, volatility, US sectors - each with today's path. Your watchlist (add / remove here) and the live squawk wire beside it. |
| **Levels** | Ladder of the nearest levels above and below each price: levels from your own text files (e.g. options-derived levels), round numbers, previous day and overnight range. Alerts when a price crosses a level; stale level files are ignored. Your own price alerts ("AAPL at or above 350"), set here or from an instrument page, one-shot, with phone push. |
| **Alerts** | One-shot alerts on any number SessionDesk has: a price or today's change, any Data hub series (latest value, latest change, or an unusual move as z), a stock's measures (RSI, distance to the 52-week high or the 200-day average, recent changes, volatility), or any member of one of your baskets ("a member's RSI at or below 30" - the alert names the members). Toast, browser notification and phone push; re-arm with one click. |
| **Countries** | One page per economy (US, Canada, euro area, Germany, France, Italy, Spain, Netherlands, UK, Switzerland, Japan, China & Hong Kong, Australia): main index and its currency, today's participation of the index members with best and worst, inflation, unemployment and GDP, the government curve and policy rate, the upcoming and recent releases for its currency, and the news of its market - all from the same sources as the other pages, each block linking there. |
| **Indices** | Part of the Markets tree (Markets › Indices › region › index › stock, with a breadcrumb on every level). All indices by region; the fifteen with a bundled member list (S&P 500, Nasdaq-100, Dow 30, S&P/TSX 60, DAX 40, FTSE 100, CAC 40, SMI, Euro Stoxx 50, FTSE MIB, IBEX 35, AEX, Nikkei 225, Hang Seng, S&P/ASX 200) open to two tabs: **Members** (the shared stock table, summarised by sector) and **Breadth, drivers & valuation** (share of members up, above their 50/200-day averages, at new highs/lows, a breadth line next to the index with a divergence flag; who moves the index - Dow in points, cap-weighted indices by weight x move, with a check against the index move; bottom-up forward P/E with its own history; FactSet for the S&P 500). |
| **Sectors** | US sectors (SPDR ETFs) and European sectors (STOXX 600 sector ETFs) as a heat map over 1 day to 1 year and YTD, optionally relative to the broad market. A sector opens to its ETF against the market, top and bottom movers and its industries; an industry opens to its stocks (Markets › Sectors › region › sector › industry). |
| **Baskets** | Your own baskets ("NVDA 30, MSFT 25, AVGO"; missing weights share the rest): a buy-and-hold line against a benchmark, period returns, each member's contribution. Every basket also becomes a Data hub series. |
| **Stock** | Quote and chart (1 day to max, candles with volume and 20/50 averages or line) and twelve tabs: overview, financial statements, earnings history with price reactions, estimates and analysts, valuation (multiples against the peer median with plausibility checks, a reverse DCF you can steer: *what growth does today's price assume?*), ownership and short interest, options (expected move, put/call, max pain), performance and risk, peers, people & indices (board, executives with pay, index memberships with estimated weight and rank), a network view (indices, peers, people, holders around the company), dividends, news, SEC filings. Board, executive and index changes of your watchlist and held stocks are raised as alerts. Indices, FX, futures and crypto get the tabs that fit them; spot FX shows implied volatility from the currency ETF's options (FXE, FXY, ...) and volume from the CME futures, each labelled as a proxy. Volume of the last complete session against its average on every instrument. |
| **Movers** | A scan of the indices you pick (any of the fifteen with a member list) plus your watchlist every few minutes. A move is flagged when it is large in percent **and** relative to the stock's own volatility. Each alert is explained from computed facts: how much the market and sector explain (beta), what is stock-specific, earnings timing, headlines that name the company. |
| **Stocks** | Every stock of the bundled indices (about 1,380, each once) in the shared stock table - the same table as on the index and sector pages: today's and 5/20/60-day/1-year moves, distance to the 52-week high and the 200-day average, RSI, volatility, and (where cached) market cap, forward P/E and yield; presets, sector and industry filters, min/max filters, a summary by sector or industry, CSV. Replaces the former Screener. |
| **News** | Live headlines with transparent rule-based impact triage (central banks, top-tier data, geopolitics, tariffs, market structure), a market filter (US, Europe, UK, Japan, China, rates, FX, oil/gas/power, metals, agriculture, crypto, tech) and full-text search over everything received since install. With a broker connected, headlines that touch your open markets (central banks, data, yields, commodities, named companies) are marked and pushed, also below high impact. |
| **Calendar** | One timeline of everything scheduled: releases, earnings that matter (watchlist, big indices, large caps), forced flows and your own session schedule. Behind it the economic calendar merged from all active sources, countdown to the next release, warnings 30/5/1 minutes before, and "burst mode" around high-impact events: the actual value is pushed as soon as a source has it (MetaTrader 5 bridge, TradingEconomics, Finnhub, FMP, or the squawk headline). Earnings calendar (US listings) filterable by market cap and importance - high: your watchlist or a mega cap (≥ 200 B USD); medium: Dow 30, Nasdaq-100, DAX 40 or Euro Stoxx 50 member, or ≥ 50 B - and sortable by date or size. The header shows a world clock for New York and London with the NYSE / LSE regular session open or closed (exchange holidays not included). |
| **Forced flows** | Dates on which someone must trade regardless of price: index rebalances (S&P, Nasdaq-100, MSCI, FTSE, STOXX/DAX, Russell), option and VIX expiries, futures roll, month/quarter end, Tokyo fix - computed from published rules, each with a link to verify. |
| **Research** | Recommended items with the reason (they touch your open positions, name a watchlist company, or match topics you saved). Feeds from research blogs and central banks, filterable by market, a clean reader view (text only, no trackers), a reading list, AI summaries. |
| **Macro** | Five tabs: rates (government yields and policy rates for the US, the euro area, the UK and Japan from FRED, the ECB, the Bank of England and Japan's Ministry of Finance, with 2s10s and how far the 2-year yield sits above the policy rate; Treasury curve and spreads, Fed funds path from futures), inflation & growth (CPI, core PCE, jobs, claims, retail sales, GDPNow), credit & liquidity (high-yield and investment-grade spreads, financial conditions, Fed balance sheet, reverse repo, TGA, euro area spreads to Germany), volatility & risk (VIX term structure vs realized, put/call, risk-appetite ratios), positioning (CFTC). |
| **Data hub** | Every series SessionDesk collects, with its history, in one local database: the market board, FRED macro / credit / liquidity, EIA weekly oil stocks (commercial crude, Cushing, SPR, products; history back to 1982) and US gas storage by region (since 2010), European day-ahead power prices, EU gas imports by route and LNG send-out by country (ENTSOG), EU gas storage per country (GIE AGSI+, free key), your baskets, 30-day implied volatility of major ETFs and your watchlist stocks (one value per US session, from live option quotes; the Options tab then shows where today's IV stands in its own record), headlines per theme from your own news archive. Chart, CSV export and a link to the original source per series; tick up to six series to compare them on one chart (rebased to 100, standardized or raw, 1 year to max). **Early warnings** when a series moves unusually against its own history (robust z-score, "largest since ..."), pushed like any other alert. Describes, does not predict. |
| **Commodities & energy** | Energy, metals and agriculture futures (incl. corn, wheat, TTF gas) with 1 day to 1 year and YTD; European day-ahead power prices for 12 bidding zones (daily base, against 30-day and 1-year averages; Energy-Charts / SMARD, CC BY 4.0); EU gas imports by route (Norway, TurkStream, Algeria, Libya, TAP, UK) and LNG send-out by country from ENTSOG, daily, free; EU gas storage fill level, injection and withdrawal for the EU, Germany, Italy, France, the Netherlands and Austria from GIE AGSI+ (free key); crude, product and gas inventories from the EIA weekly reports; the free-key and paid sources that can be connected for power generation and flows, crop data, warehouse stocks and tanker positions. |
| **Tankers (AIS)** | Tankers at nine oil chokepoints (Hormuz, Bab el-Mandeb, Suez, Bosporus, Danish straits, Gulf of Finland, Singapore, Cape of Good Hope, Panama) from live AIS via aisstream.io with your own free key: tankers now (moving vs. slow or at anchor), tankers per day as a Data hub series with early warnings, the ships with destination and draught. Shore-based receivers: coverage far from land is partial and ships can switch AIS off, so compare a chokepoint with its own history. |
| **Accounts & EAs** | Read-only: balances, open positions with money at risk to the stop, which EA runs on which chart, closed trades per EA (magic number), book risk (correlated positions, scenario moves), currency strength, contract specs. |
| **Portfolio** | What the open book is exposed to, per account (accounts are never added together): gross exposure as leverage and net exposure in % of equity, split by asset class, region, currency (FX pairs on both legs) and sector, the largest positions, risk to the stops and positions without one; plus whether positions move together (correlation) and what a move in a driver market would do. Read-only. |
| **Jobs** | Run your own scripts (`.bat`, `.cmd`, `.ps1`, `.py`, `.sh`, any command) by click, on a schedule or as a service; live output; copy a job's output file to the clipboard; workflows that chain jobs. |
| **Journal** | Equity curve and P/L per day (per week beyond 90 days) for each account, closed positions with net result, initial risk and R multiple, a note per trade, statistics per account and setup (EA) in R. Accounts are never added together; trade-copier copies (Settings → copy_magics) are hidden so nothing counts twice. |
| **Your own pages** | A Python file in `~/.sessiondesk/extensions/` becomes a page in the navigation: tables, lists, key figures and an input line, rendered safely and with AI support. Private logic stays on your machine. See [docs/EXTENSIONS.md](docs/EXTENSIONS.md). |
| **CSV export** | Every table has a CSV button (top right on hover) that downloads exactly what it shows; Data hub series export their full history. |
| **Tabs and windows** | "+ Tab" (or Ctrl+click a menu entry) keeps pages open side by side; "⧉ Window" opens the current page in its own window, e.g. for a second screen. |
| **System** | Is everything doing its job? Background loops, each source's last success and error, feeds, calendar sources, broker export age, jobs, extensions, level files - condensed into one problem list; a counter in the navigation shows when something needs a look. |
| **Phone push** | Optional: high-impact headlines, release warnings and values, position changes, headlines on your open markets, failed jobs - to your phone via ntfy (free app) or your own Telegram bot. Quiet hours, hourly limit, no duplicates. Off until you enter your own topic or bot. |
| **AI everywhere** | Type a question in the search bar on any page and the assistant answers about what that page shows. Explain an alert, summarize an article, or ask the built-in help how to set something up. |

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/Timonkru/sessiondesk.git
cd sessiondesk
python -m venv .venv
```

Activate the environment (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS/Linux), then:

```bash
pip install -e .
sessiondesk
```

Your browser opens at <http://127.0.0.1:8765>. Options: `--port 9000`, `--no-browser`, `--app` (own
window without browser bars). Starting it again while it runs simply reopens the window.

Windows desktop shortcut (starts minimized in the background, opens the app window; close the
minimized console to stop it):

```bash
powershell -ExecutionPolicy Bypass -File scripts\windows_shortcut.ps1
```

Run it in the background from Windows login (no window; alerts, phone push and jobs keep working; the
desktop shortcut then just opens the window). Stop it on the System page or with `sessiondesk --stop`;
`-Remove` takes the autostart entry out again:

```bash
powershell -ExecutionPolicy Bypass -File scripts\windows_autostart.ps1
```

Elsewhere: `sessiondesk --background` (log in `~/.sessiondesk/logs/server.log`), e.g. from a login item or
a systemd user service.

Settings, keys, cache, the news archive and job logs live in `~/.sessiondesk/` (override with
`SESSIONDESK_HOME`).

## Command bar

Type in the search bar (or press `/`). Besides names and symbols it understands short commands; the
first line of the list shows where a command goes, Enter runs it.

| Type | Goes to |
|---|---|
| `AAPL DES` / `OV` | overview of the instrument (`GP` / `CHART` too) |
| `AAPL FA` · `EE` · `ANR` · `RV` · `HDS` | financial statements · earnings history · estimates & analysts · valuation · ownership |
| `AAPL OPT` (`OMON`, `OVDV`) · `PERF` · `COMP` · `MGMT` · `SPLC` · `DVD` · `CN` · `FIL` | options · performance & risk · peers · people & indices · network · dividends · news · SEC filings |
| `AAPL HUB` | the instrument's series in the Data hub |
| `DAX MEMBERS`, `NKY BREADTH`, `SPX DRIVERS` | an index's members or its breadth, drivers & valuation (`SPX`, `NDX`, `INDU`, `TSX`, `DAX`, `UKX`, `CAC`, `SMI`, `SX5E`, `MIB`, `IBEX`, `AEX`, `NKY`, `HSI`, `AS51`) |
| `TOP` · `WEI` · `ECO` · `FLOW` · `IDX` · `SECT` · `EQS` · `MOST` · `BSKT` · `HUB` · `ECST` · `CMDTY` · `TANK` · `ALRT` · `DESK` · `PORT` · `JRNL` | news · markets · calendar · forced flows · indices · sectors · stocks · movers · baskets · data hub · macro · commodities · tankers · alerts · my desk · portfolio · journal |

Words that are also common tickers (MOV, MAC, CAL, RES ...) stay stock searches.

## Spreadsheets and scripts

Excel or LibreOffice on the same computer can pull values straight from SessionDesk. Create a key under
**Settings → Spreadsheets & scripts** (shown once; a new key replaces the old one), then for example:

```
=WEBSERVICE("http://127.0.0.1:8765/api/v1/value?symbol=AAPL&field=price&key=YOUR_KEY")
=WEBSERVICE("http://127.0.0.1:8765/api/v1/value?symbol=hub:fred:DGS10&key=YOUR_KEY")
```

Power Query (Data → From Web) or scripts read CSV: `/api/v1/quotes.csv?symbols=AAPL,SAP.DE`,
`/api/v1/history.csv?symbol=AAPL&range=1y` (daily bars), `/api/v1/series.csv?id=<Data hub id>`,
`/api/v1/stocks.csv?scope=index:dax40` (all measures of an index's members). Fields for `value`: `price`,
`change`, `change_pct`, `prev_close`, `time`; `hub:<id>` gives a Data hub series' latest value (`field=date` its date).
The key opens these read-only addresses and nothing else. Google Sheets cannot use them: Sheets fetches
from Google's servers, which cannot reach a SessionDesk on your computer - on purpose.

## Free core and bring-your-own-key connectors

| Connector | Tier | Gives you |
|---|---|---|
| Yahoo Finance | free | quotes, history, search, fundamentals, ticker headlines (unofficial API, personal use) |
| RSS feeds | free | squawk wires, market news, central banks, research blogs (edit the lists in Settings) |
| Forex Factory calendar | free | scheduled releases with impact, forecast, previous |
| FRED | free | Treasury curve, inflation breakevens, credit spreads |
| CFTC | free | Commitments of Traders |
| EIA | free | weekly petroleum stocks and natural gas storage, with history |
| Energy-Charts (Fraunhofer ISE) | free | European day-ahead power prices (data Bundesnetzagentur / SMARD.de, CC BY 4.0) |
| ENTSOG Transparency Platform | free | daily physical gas flows at the EU entry points: imports by route, LNG send-out by country (operator-reported; the Emden landing points publish no flows) |
| SEC EDGAR | free (contact email) | US filings |
| Nasdaq earnings | free | earnings dates and consensus |
| MetaTrader 5 bridge | free | accounts, positions, running EAs, deals, **calendar with actual values within ~2 s** |
| Finnhub | your key (free tier) | fast news, company news, earnings; economic calendar on paid plans |
| Financial Modeling Prep | your key (free tier) | fundamentals, vendor DCF, calendar with actuals |
| aisstream.io | your key (free) | live AIS ship positions for the tanker monitor |
| Polygon.io | your key (paid) | real-time US snapshots, aggregates, news |
| Alpha Vantage | your key (free tier) | news with sentiment |
| Trading Economics | your key (paid) | economic calendar with actuals |
| Alpaca | your key (free account) | read-only account and positions, Benzinga news, IEX quotes |
| GIE AGSI+ | your key (free account) | EU gas storage per country: fill level, injection, withdrawal, with history |
| Anthropic / OpenAI / Gemini / OpenRouter | your key | the AI assistant |
| Ollama / any OpenAI-compatible server | free, local | the AI assistant without sending data anywhere |

Add keys in **Settings → Connectors** (press *Test connection*) or as environment variables
(see `.env.example`). Paid sources are preferred automatically when active. Connectors marked
*not verified* follow the vendor documentation but have not been run with a live key yet - the
test button tells you immediately. Planned: Databento, Interactive Brokers, cTrader, NinjaTrader,
Benzinga, Telegram channels, Tiingo, EODHD. See [docs/CONNECTORS.md](docs/CONNECTORS.md).

## AI: the code computes, the model words

Every number the assistant may use is computed by SessionDesk and handed over as JSON - the data
of the page you are on. The system prompt forbids figures that are not in that data, buy/sell
instructions, price targets and direction calls. The default provider is Anthropic Claude
(`claude-opus-5-5`); choose any provider and model in **Settings → AI**, cap the daily number of
calls, and watch token usage. See [docs/AI.md](docs/AI.md).

## MetaTrader 5

Copy `bridge/SessionDeskBridge.mq5` into `MQL5/Experts`, compile it in MetaEditor and attach it to
**one** chart per terminal. It only writes files to the common data folder; it contains no order
code. See [docs/MT5_BRIDGE.md](docs/MT5_BRIDGE.md).

## Jobs: your own routines

Register any script once and run it from the desk - or import an existing `jobs.json` read-only.
Schedules, services, workflows and clipboard outputs are described in [docs/JOBS.md](docs/JOBS.md).

## Security model

- Listens on `127.0.0.1` only (unless you pass `--host`).
- Every API call needs a per-start session token that only the page served by SessionDesk knows,
  so other websites in your browser cannot call it; the Host header must be local (DNS-rebinding
  protection).
- Keys are stored in `~/.sessiondesk/secrets.json` (or taken from the environment) and are never
  sent back to the browser - the UI only shows the last four characters.
- Jobs run with your user rights, exactly like starting the script yourself.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

Tests run offline (mocked HTTP). Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Roadmap: [ROADMAP.md](ROADMAP.md). Index member lists are refreshed with
`python scripts/update_universes.py` (needs pandas and lxml).

## License

MIT - see [LICENSE](LICENSE). Data from third-party sources stays subject to their terms; Yahoo
Finance and the Forex Factory feed are unofficial endpoints meant for personal use.

Built by [Krueger Algorithms](https://kruegeralgorithms.com/en). Research write-ups with their methods are on the website;
the MetaTrader tools for prop traders are on the [MQL5 Market](https://www.mql5.com/en/users/sg_mephisot/seller).
