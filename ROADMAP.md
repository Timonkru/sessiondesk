# Roadmap

Status 13 Oct 2026: v0.1 - all pages working on free data, 43 offline tests green, bridge compiles
(0 errors, 0 warnings). Open items in priority order.

## Verify what exists

- [ ] Activate CI: move `ci/tests.yml` to `.github/workflows/tests.yml` (the GitHub web editor can do it,
      or locally after `gh auth refresh -s workflow` - the current CLI token lacks the workflow scope).

- [ ] Run each keyed connector once with a real key (Finnhub, FMP, Polygon, Alpha Vantage,
      Trading Economics, Alpaca) and flip `verified = True` only after it worked.
- [ ] First real AI call per provider (Anthropic SDK path incl. `fallbacks="default"`, OpenAI,
      Gemini, Ollama); check streaming, usage numbers and cost estimate.
- [ ] Attach `SessionDeskBridge` to a demo account chart: check positions, risk to stop, EA list,
      deals, and that calendar actual values arrive within seconds of a release.
- [ ] Watch one high-impact release live end to end (warning toasts, burst mode, release bar).
- [ ] Test the app inside GitHub Codespaces (port forwarding + host check).

## Speed

- [ ] Prefetch the watchlist profiles in the background after start (cold fundamentals take 3-6 s).
- [ ] Websocket quotes for keyed providers (Finnhub/Polygon/Alpaca streams) instead of polling.
- [ ] Measure page timings and show them in Help (cold vs warm).

## Features

- [ ] Telegram channel connector (user's own api_id/hash) for squawk channels.
- [ ] Databento and Interactive Brokers connectors (planned entries exist in `registry.py`).
- [ ] SEC XBRL company facts for long fundamental history (P/E history, margins over 10 years).
- [ ] Estimated leveraged-ETF rebalancing flow on big days (AUM x L x (L-1) x return).
- [ ] Extensions folder: private local modules that add pages/routes without entering the repo.
- [ ] Optional AI triage of headlines (batch, cheap model) on top of the rule-based impact tags.
- [ ] Publish a compiled `.ex5` with each GitHub release.

## Known limits

- Yahoo Finance and the Forex Factory feed are unofficial, personal-use endpoints; they can change
  or rate-limit without notice.
- Free calendars carry no actual values; the print arrives via the MT5 bridge, a keyed calendar or
  as a squawk headline.
- Fundamentals from Yahoo are sometimes wrong; multiples outside plausible ranges are flagged and ignored.
