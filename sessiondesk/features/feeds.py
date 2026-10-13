"""RSS/Atom plumbing shared by news, squawk and research: parse, normalize, conditional GET.

Conditional GET (ETag / Last-Modified) matters for the fast squawk loop: an unchanged feed costs
one tiny 304 instead of a full download, which is what makes polling every few seconds polite.
"""
from __future__ import annotations

import calendar
import html
import re
import time

from ..connectors.base import stable_id

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def clean(text: str | None, limit: int = 600) -> str:
    text = html.unescape(TAG.sub(" ", text or ""))
    text = WS.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_feed(content: bytes, source: str) -> list[dict]:
    import feedparser
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        title = clean(e.get("title"), 300)
        if not title:
            continue
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        # Undated entries (some feeds omit dates) would otherwise sort above every dated headline.
        published = calendar.timegm(stamp) if stamp else time.time() - 86400
        link = e.get("link") or ""
        summary = clean(e.get("summary") or e.get("description"), 600)
        if summary.lower().startswith(title.lower()[:40]):
            summary = summary[len(title):].strip(" -–:")
        out.append({"id": stable_id(link, title), "title": title, "url": link, "source": source,
                    "published": int(published), "summary": summary,
                    "author": clean(e.get("author"), 80) or None, "undated": not stamp})
    return out


class FeedFetcher:
    """Remembers validators per URL so repeated polls are conditional, and backs off when a feed
    rate-limits (HTTP 429/503): Retry-After if given, else 2 min doubling up to 30 min. While a feed
    is backing off, the last items are served from memory instead of hitting the server again."""

    def __init__(self, http, user_agent: str = "SessionDesk/0.1 (+https://github.com/Timonkru/sessiondesk)"):
        self.http = http
        self.ua = user_agent
        self._validators: dict[str, dict] = {}
        self._last: dict[str, list[dict]] = {}
        self._blocked_until: dict[str, float] = {}
        self._backoff: dict[str, float] = {}

    async def fetch(self, url: str, source: str, timeout: float = 15.0) -> list[dict]:
        now = time.time()
        if self._blocked_until.get(url, 0) > now:
            if url in self._last:
                return self._last[url]
            raise RuntimeError(f"{source}: rate limited, next try in {int(self._blocked_until[url] - now)} s")
        headers = {"User-Agent": self.ua, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
        headers.update(self._validators.get(url, {}))
        resp = await self.http.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        if resp.status_code == 304:
            return self._last.get(url, [])
        if resp.status_code in (429, 503):
            wait = _retry_after(resp.headers.get("retry-after")) or min(1800.0, self._backoff.get(url, 60.0) * 2)
            self._backoff[url] = wait
            self._blocked_until[url] = now + wait
            raise RuntimeError(f"{source}: HTTP {resp.status_code} (rate limited) - pausing {int(wait)} s")
        if resp.status_code != 200:
            raise RuntimeError(f"{source}: HTTP {resp.status_code}")
        self._backoff.pop(url, None)
        validators = {}
        if resp.headers.get("etag"):
            validators["If-None-Match"] = resp.headers["etag"]
        if resp.headers.get("last-modified"):
            validators["If-Modified-Since"] = resp.headers["last-modified"]
        self._validators[url] = validators
        import asyncio
        items = await asyncio.to_thread(parse_feed, resp.content, source)
        self._last[url] = items
        return items


def _retry_after(value: str | None) -> float | None:
    try:
        return max(30.0, min(3600.0, float(value)))
    except (TypeError, ValueError):
        return None
