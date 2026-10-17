# Working on SessionDesk (instructions for coding agents)

The maintainer (Timon) talks **German**: answers, reports and commit messages in German. Everything
inside the code is **English**: identifiers, comments, docstrings, UI strings, log/error texts,
README and docs. Be direct, no sugar-coating; end every report with an honest caveat (what was not
tested, what is assumed).

## Setup and checks

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Windows: .venv\Scripts\pip install -e ".[dev]"
python -m pytest                          # offline, must stay green on Linux and Windows
sessiondesk --no-browser --port 8765      # run the app (console script; `python -m sessiondesk` also works from the repo root)
```

Never claim a result that was not just produced: "tests green" only after running them, UI
"works" only after loading the page and checking the browser console.

## Map

- `sessiondesk/app.py` - FastAPI routes, security guard, background loops
- `sessiondesk/features/` - one module per page (markets, stocks, valuation, movers, news, calendar,
  flows, research, macro, broker, jobs)
- `sessiondesk/connectors/` - outside systems; `registry.py` lists them; `base.py` defines shapes
- `sessiondesk/extensions.py` - loader for the user's own pages (`<data dir>/extensions/`, docs/EXTENSIONS.md)
- `sessiondesk/push.py` - optional phone push (ntfy / own Telegram bot); topic and tokens are secrets
- `sessiondesk/ai/` - providers (official Anthropic SDK, OpenAI-compatible, Gemini, Ollama) + assist rules
- `sessiondesk/static/` - browser UI, vanilla ES modules, no build step; `lib/ui.js` helpers
- `bridge/SessionDeskBridge.mq5` - read-only MetaTrader 5 exporter
- `docs/` - user docs; the in-app AI support answers from README + docs, keep them accurate
- `ROADMAP.md` - what is open, in priority order

## Hard rules

1. **No order path, ever.** Broker/EA connectors are read-only. Do not add order placement,
   modification or closing - not even behind a flag - without an explicit decision by the maintainer.
2. **Keys never in the repo.** Keys live in `~/.sessiondesk/secrets.json` or env vars; the API returns
   only `describe()` (set/source/last four chars). Tests must assert that secrets do not leak.
3. **Code computes, the model words.** AI prompts get JSON computed by SessionDesk and must forbid
   invented numbers, trade instructions, price targets and direction calls (`ai/assist.py` GUARD).
4. **Untrusted text goes into the DOM via `textContent` only** (`h()` in `static/lib/ui.js`). No
   `innerHTML` with feed, article or AI text.
5. **Honest connectors.** A connector written from vendor docs stays `verified = False` until a live
   call succeeded. Free sources are labelled as such; unofficial endpoints are named in the docs.
6. **Be polite to free sources.** Cache by stable keys, back off on 429/503 (see `features/feeds.py`,
   `cache.py` `retry=`). Never poll faster than the source allows.
7. **Tests run offline.** Use `tests/conftest.py` (httpx.MockTransport); no real network, no yfinance
   calls in tests.
8. **Private material stays out.** This repo is public. Do not add personal account numbers, private
   trading-system logic, setup definitions or paths from the maintainer's machine.
9. **Scope.** Change what was asked; offer extra improvements as a question instead of slipping them in.

## Verifying UI changes

Run the app, open the page, check the browser console for errors, exercise the changed control, and
look at a narrow window (the layout switches to one column below 760 px). Static files are served
with `Cache-Control: no-cache`; Python changes need a server restart (the page reloads itself after
a restart because the session token changes).
