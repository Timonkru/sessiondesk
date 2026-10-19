# Extensions: your own pages

SessionDesk is meant to be finished out of the box and still bend to your own way of trading. Besides
your own scripts (see [JOBS.md](JOBS.md)) you can add **pages**: a small Python module in your data
folder becomes an entry in the navigation. Nothing of it enters the repository, so private trading
logic stays on your machine.

## Where

```
~/.sessiondesk/extensions/
    my_page.py                  # a single file ...
    desk/                       # ... or a folder with extension.py (helpers next to it)
        extension.py
        helper.py
```

Files and folders starting with `_` or `.` are skipped. Names: lower case letters, digits, `-` and `_`.
After adding or editing a file: **Settings → Extensions → Save & reload** (or the "reload code" link on
the page). Switch loading off there with "load extensions".

**Trust:** an extension runs inside SessionDesk with your user rights. Only put your own code there.

## The module

```python
TITLE = "My desk"            # navigation label (default: file name)
DESCRIPTION = "one line"     # optional, under the page title
REFRESH = 30                 # optional, seconds between automatic refreshes; 0 = manual only

async def page(ctx) -> dict: # or a plain def (runs in a worker thread)
    return {"blocks": [...]}

async def action(ctx, payload) -> dict:   # optional, called by an "input" block
    return {"message": "saved"}

async def today(ctx) -> dict:             # optional: blocks shown at the top of the Today page
    return {"blocks": [...]}               # keep it quick (20 s limit): answer from your cache, refresh in the background
```

A Today block that is still loading can carry `"retry_in": 15`; the Today page then asks again after that
many seconds. If you start background work with `asyncio.ensure_future`, keep a reference to the task
(asyncio holds tasks only weakly).

`page()` gets the same context object the built-in pages use: `ctx.settings`, `ctx.cache`
(`await ctx.cache.get(key, ttl_seconds, async_builder)` caches and de-duplicates), `ctx.http`
(shared async HTTP client), `ctx.hub` (connectors) and `ctx.data_dir`. Built-in feature functions can be
imported, e.g. `from sessiondesk.features.markets import get_quotes`. A call may take up to 90 seconds;
slow work belongs in the cache with a sensible TTL.

To reuse code that lives in another Python environment, run it as a subprocess
(`asyncio.create_subprocess_exec(<other python>, <script>, ...)`) and print JSON - that keeps both
environments apart.

## Blocks

Every value is shown as plain text, never as HTML. The page's AI context is the same block data, so the
assistant answers about what your page shows.

| Type | Fields |
|---|---|
| `kv` | `title`, `items: [[label, value], ...]` |
| `table` | `title`, `columns: [{"key", "label", "num"}]`, `rows: [{...}]`, `empty`, `note`; a row with `"_level": "high"` marks its first cell |
| `list` | `title`, `items: [text, or {"text", "level": "high" / "warn" / "ok" / "muted", "detail"}]`, `empty` |
| `text` | `title`, `text` (simple markdown: `**bold**`, bullet lines, `#` headings) |
| `note` | `text` |
| `input` | `title`, `action`, `placeholder` - Enter sends `{"action", "text"}` to `action()` and reloads the page |

Any block with `"cols": 2` goes to the right column on wide screens.

## Example

[`examples/extensions/watch_gap.py`](../examples/extensions/watch_gap.py) lists the watchlist sorted by
today's move. Copy it into the folder, reload, done.

## Rules that still apply

Extensions are your code, but SessionDesk's own rules are worth keeping: read-only towards brokers (no
order path), keys in `secrets.json` or environment variables rather than in the file, and no numbers
on the page that the code did not compute.
