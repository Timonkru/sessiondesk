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


TG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def parse_telegram(page: str, source: str, channel: str) -> list[dict]:
    """Public web preview of a Telegram channel (t.me/s/<channel>): no login, the last ~20 posts.
    Squawk channels post one-line headlines seconds after the wire - often well before RSS feeds."""
    import datetime as dt
    out = []
    for block in page.split('class="tgme_widget_message_wrap')[1:]:
        post = re.search(r'data-post="([^"]+)"', block)
        when = re.search(r'datetime="([^"]+)"', block)
        body = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        if not (post and body):
            continue
        text = html.unescape(re.sub(r"<br\s*/?>", " ", body.group(1)))
        text = " ".join(re.sub(r"<[^>]+>", "", text).split())
        text = re.sub(r"\s*\(@\w+\)\s*$", "", text)            # channel signature "(@Channel)"
        text = re.sub(r"\s*\|\s*\w{1,4}\s*$", "", text)          # ... or "|XX"
        text = re.sub(r"\s*\$[A-Z]{2,}\b", "", text).strip()       # topic tags like "$MACRO"
        if not text:
            continue
        published = time.time()
        if when:
            try:
                published = dt.datetime.fromisoformat(when.group(1).replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        link = f"https://t.me/{post.group(1)}"
        out.append({"id": stable_id(link), "title": text[:300], "url": link, "source": source,
                    "published": int(published), "summary": "", "author": None, "undated": not when})
    out.reverse()                                              # newest first, like RSS
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
        """RSS/Atom URL, or "tg:<channel>" for a public Telegram channel."""
        now = time.time()
        if self._blocked_until.get(url, 0) > now:
            if url in self._last:
                return self._last[url]
            raise RuntimeError(f"{source}: rate limited, next try in {int(self._blocked_until[url] - now)} s")
        telegram = url.startswith("tg:")
        if telegram:
            fetch_url = "https://t.me/s/" + url[3:].strip().lstrip("@")
            headers = {"User-Agent": TG_UA}
        else:
            fetch_url = url
            headers = {"User-Agent": self.ua, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
            headers.update(self._validators.get(url, {}))
        resp = await self.http.get(fetch_url, headers=headers, timeout=timeout, follow_redirects=True)
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
        if telegram:
            items = parse_telegram(resp.text, source, url[3:])
            self._last[url] = items
            return items
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
