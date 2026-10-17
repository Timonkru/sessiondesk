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

## What is inside

| Page | What it does |
|---|---|
| **Today** | Your trading day on one page: accounts with a prop-rule meter (daily loss, own stop, open slots), rule flags, your own session schedule with release collisions marked, next releases and forced flows, an AI briefing written from computed facts, what changed since you last looked, one-line notes. Schedule and rules live in your local settings. |
| **Markets** | Indices, index futures, US yields (moves in basis points), FX, commodities, crypto, volatility, US sectors - each with today's path. Next high-impact releases, unusual moves and the squawk wire beside it. |
| **Levels** | Ladder of the nearest levels above and below each price: levels from your own text files (e.g. options-derived levels), round numbers, previous day and overnight range. Alerts when a price crosses a level; stale level files are ignored. |
| **Indices & breadth** | S&P 500, Nasdaq-100, DAX 40, Dow 30: share of members up, above their 50/200-day averages, at new highs/lows, a breadth line next to the index with a divergence flag; who moves the index (Dow in points, cap-weighted indices by weight x move, with a check against the index move); bottom-up forward P/E with its own daily history; the weekly FactSet forward P/E for the S&P 500. |
| **Stock** | Quote and chart (1 day to max) and twelve tabs: overview, financial statements, earnings history with price reactions, estimates and analysts, valuation (multiples against the peer median with plausibility checks, a reverse DCF you can steer: *what growth does today's price assume?*), ownership and short interest, options (expected move, put/call, max pain), performance and risk, peers, dividends, news, SEC filings. Indices, FX, futures and crypto get the tabs that fit them. |
| **Watchlist & movers** | Your watchlist plus a scan of the S&P 500, Nasdaq-100 and DAX 40 every few minutes. A move is flagged when it is large in percent **and** relative to the stock's own volatility. Each alert is explained from computed facts: how much the market and sector explain (beta), what is stock-specific, earnings timing, headlines that name the company. |
| **News** | Live headlines with transparent rule-based impact triage (central banks, top-tier data, geopolitics, tariffs, market structure) and full-text search over everything received since install. With a broker connected, headlines that touch your open markets (central banks, data, yields, commodities, named companies) are marked and pushed, also below high impact. |
| **Calendar** | Economic calendar merged from all active sources, countdown to the next release, warnings 30/5/1 minutes before, and "burst mode" around high-impact events: the actual value is pushed as soon as a source has it (MetaTrader 5 bridge, TradingEconomics, Finnhub, FMP, or the squawk headline). Earnings calendar. |
| **Forced flows** | Dates on which someone must trade regardless of price: index rebalances (S&P, Nasdaq-100, MSCI, FTSE, STOXX/DAX, Russell), option and VIX expiries, futures roll, month/quarter end, Tokyo fix - computed from published rules, each with a link to verify. |
| **Research** | Feeds from research blogs and central banks, a clean reader view (text only, no trackers), a reading list, AI summaries. |
| **Macro** | Treasury curve and spreads, Fed funds path from futures, VIX term structure vs realized volatility, risk-appetite ratios, put/call ratios (SPY, QQQ), CFTC positioning. |
| **Accounts & EAs** | Read-only: balances, open positions with money at risk to the stop, which EA runs on which chart, closed trades per EA (magic number), book risk (correlated positions, scenario moves), currency strength, contract specs. |
| **Jobs** | Run your own scripts (`.bat`, `.cmd`, `.ps1`, `.py`, `.sh`, any command) by click, on a schedule or as a service; live output; copy a job's output file to the clipboard; workflows that chain jobs. |
| **Journal** | Closed positions with net result, initial risk and R multiple, a note per trade, statistics per setup (EA) in R. |
| **Your own pages** | A Python file in `~/.sessiondesk/extensions/` becomes a page in the navigation: tables, lists, key figures and an input line, rendered safely and with AI support. Private logic stays on your machine. See [docs/EXTENSIONS.md](docs/EXTENSIONS.md). |
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
Settings, keys, cache, the news archive and job logs live in `~/.sessiondesk/` (override with
`SESSIONDESK_HOME`).

## Free core and bring-your-own-key connectors

| Connector | Tier | Gives you |
|---|---|---|
| Yahoo Finance | free | quotes, history, search, fundamentals, ticker headlines (unofficial API, personal use) |
| RSS feeds | free | squawk wires, market news, central banks, research blogs (edit the lists in Settings) |
| Forex Factory calendar | free | scheduled releases with impact, forecast, previous |
| FRED | free | Treasury curve, inflation breakevens, credit spreads |
| CFTC | free | Commitments of Traders |
| SEC EDGAR | free (contact email) | US filings |
| Nasdaq earnings | free | earnings dates and consensus |
| MetaTrader 5 bridge | free | accounts, positions, running EAs, deals, **calendar with actual values within ~2 s** |
| Finnhub | your key (free tier) | fast news, company news, earnings; economic calendar on paid plans |
| Financial Modeling Prep | your key (free tier) | fundamentals, vendor DCF, calendar with actuals |
| Polygon.io | your key (paid) | real-time US snapshots, aggregates, news |
| Alpha Vantage | your key (free tier) | news with sentiment |
| Trading Economics | your key (paid) | economic calendar with actuals |
| Alpaca | your key (free account) | read-only account and positions, Benzinga news, IEX quotes |
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

Built by [Krueger Algorithms](https://kruegeralgorithms.com).
