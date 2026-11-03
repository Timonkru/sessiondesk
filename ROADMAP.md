# Roadmap

Status 1 Nov 2026: v0.1 with about 35 pages on free data, 216 offline tests green (Linux and Windows, Python 3.10
and 3.12), bridge v1.20 (deals, taxes, deposits, dividends). Since the 16 Oct status: Data hub with early warnings,
Commodities & energy (EIA, Energy-Charts, ENTSOG, AGSI+), Tankers (AIS), Sectors, Baskets, Earnings reported,
BTC short-term holder zone alert, world clock, reports and taxes, AI pre-session briefing and weekly review,
Earnings nowcast. Open items in priority order.

## 1. Verify what exists (highest leverage: most keyed paths have never touched a real key)

- [ ] Run each keyed connector once with a real key and flip `verified = True` only after it worked:
      Finnhub, FMP, Alpha Vantage, Alpaca, Polygon, Trading Economics, Quiver. One FMP free key alone unlocks the
      consensus history, revenue beat rates and a calendar with actual values - the biggest single step.
- [ ] SEC EDGAR: enter the contact email (Settings → Connectors). Without it the Form 4 insider series stay empty
      (the Archives host answers 403).
- [ ] Earnings desk: first AI reading with a real key; watch a full reporting day on the maintainer's own instance.
- [ ] First real AI call per provider (OpenAI, Gemini, OpenRouter, Ollama); Anthropic is verified.
- [ ] Earnings nowcast on the maintainer's own instance (so far only on a scratch instance).
- [ ] Watch one high-impact release live end to end (warning toasts, burst mode, release bar).
- [ ] Test the app inside GitHub Codespaces (port forwarding + host check).

## 2. Earnings nowcast: what the out-of-sample test said

The free attention proxies (Wikipedia pageviews, Google Trends, TSA) were tested on 71 consumer stocks and 1,679
reports 2016-2022 before the page was built: information coefficient against the EPS beat +0.03 (t 1.0), against the
price reaction 0.0. The proxies track revenue growth that is already known from the previous quarter and add nothing
to its acceleration. The page therefore stays labelled "unvalidated" and makes no buy or sell statements.

- [ ] Put that verdict into `<data dir>/earnings_proxies.json` (`"validation"`) so the banner says what was found.
- [ ] Re-test once a consensus history exists (FMP key): the test above had to use the EPS beat as a stand-in target
      because no historical revenue consensus is available for free.
- [ ] Steam players and App Store ranks start their history with the first collector run; a nowcast on them needs
      about two years of data.

## 3. Speed

- [ ] Prefetch the watchlist profiles in the background after start (cold fundamentals take 3-6 s).
- [ ] Websocket quotes for keyed providers (Finnhub/Polygon/Alpaca streams) instead of polling.
- [ ] The Earnings nowcast page takes 40-60 s on its first load (SEC facts, Yahoo estimates per company); prefetch
      in the background like the proxies.
- [ ] Measure page timings and show them in Help (cold vs warm).

## 4. Features

- [ ] SEC XBRL company facts beyond quarterly revenue: margins, P/E history over 10 years (the connector already
      reads `companyfacts`).
- [ ] Telegram channel connector (user's own api_id/hash) for squawk channels.
- [ ] Databento and Interactive Brokers connectors (planned entries exist in `registry.py`).
- [ ] Estimated leveraged-ETF rebalancing flow on big days (AUM x L x (L-1) x return).
- [ ] Optional AI triage of headlines (batch, cheap model) on top of the rule-based impact tags.
- [ ] Paid alternative data (Placer, Similarweb, Second Measure) would each need an adapter; none is written and
      none is tested - see docs/CONNECTORS.md.
- [ ] Publish a compiled `.ex5` with each GitHub release.

## Known limits

- Yahoo Finance, the Forex Factory feed, CNBC quotes, the checkonchain chart and the Nasdaq earnings calendar are
  unofficial endpoints; they can change or rate-limit without notice.
- Free calendars carry no actual values; the print arrives via the MT5 bridge, a keyed calendar or as a squawk
  headline.
- Fundamentals from Yahoo are sometimes wrong; multiples outside plausible ranges are flagged and ignored. Yahoo's
  "current quarter" revenue estimate does not always match the company's fiscal quarter from the SEC; the nowcast
  page skips the comparison when the year-ago figures differ by more than 3 %.
- Yahoo's continuous futures jump when Yahoo rolls to the next contract; the board shows the exchange front
  contract instead, and the Data hub does not warn on those series.
- Wikipedia article renames cut the pageview history at the rename; Indeed Hiring Lab publishes job categories,
  not companies.
