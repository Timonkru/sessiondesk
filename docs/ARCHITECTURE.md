# Architecture

```
browser (static/, vanilla JS modules, no build step)
   |  fetch /api/*  (header X-SD-Token)         EventSource /api/stream (push)
   v
sessiondesk/app.py  FastAPI: routes, security guard, background loops
   |
   +-- features/   one module per page: turns connector data into what the page shows
   |     markets  stocks  deep  valuation  movers  news  calendar  flows  research  macro  broker  jobs
   |     today  levels  risk  journal  indices  assets  universe  feeds  system  proxies  nowcast
   +-- connectors/ one class per outside system, normalized shapes (see base.py)
   |     yahoo  rss  public (fred, treasury, cnbc, ffcal, cftc, sec, nasdaq)  mt5  keyed (finnhub, fmp, polygon,
   |     alphavantage, tradingeconomics, alpaca, agsi, quiver)  registry.py (the list + planned entries)
   +-- ai/         providers.py (Anthropic SDK, OpenAI-compatible, Gemini, Ollama) + assist.py (rules, prompts)
   +-- push.py     phone push (ntfy / own Telegram bot): broker listener -> queue -> sender, off by default
   +-- extensions.py  the user's own pages from <data dir>/extensions/
   +-- cache.py    async stale-while-revalidate cache, single-flight, disk persistence, failure backoff
   +-- events.py   in-process pub/sub -> Server-Sent Events
   +-- db.py       SQLite: news archive (FTS5), alerts, reading list, AI usage
   +-- settings.py settings.json + secrets.json in the data directory (env vars win)
```

## Why it is fast

- **Stale-while-revalidate:** a page never waits for a source it has seen before. Expired data is
  returned instantly and refreshed in the background; concurrent requests share one fetch.
- **Batching:** Yahoo quotes come 20 symbols per call and the calls run in parallel (the 558-stock
  movers scan takes about 3 s).
- **Push, not poll:** alerts, squawk headlines, release warnings and job output arrive over one
  SSE connection.
- **Per-page loading:** only the open page loads data; slow parts (fundamentals, peers) render
  when ready instead of blocking the page.

## Background loops (`app.background`)

| Loop | Interval | Notes |
|---|---|---|
| squawk feeds | 30 s | conditional GET; rate-limited feeds back off automatically |
| market news, central banks, keyed news | 2 min | |
| research feeds | 60 min | |
| movers scan | 5 min, market hours | the first scan after a start sends one digest instead of a toast per stock |
| calendar warnings / burst mode | 10 s, 3 s around high-impact events | |
| jobs scheduler | 20 s | autostart services, daily and interval schedules |

## Rules the code follows

- Connectors never raise into pages: failures become `{"error": ...}` or a stale value with a reason.
- Every number shown carries its source; free data is labelled as such.
- Broker and EA connections are read-only. There is no order path anywhere.
- The AI only words facts the code computed (see AI.md).
- Calendar sources are fetched once per source and UTC day and filtered locally; keying the cache
  by the requested window once triggered HTTP 429 from Forex Factory.
