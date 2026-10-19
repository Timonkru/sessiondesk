"""Research area: article feeds, a clean reader view, a reading list.

The reader fetches the article and keeps only the text blocks (headings, paragraphs, lists,
quotes, code) - no scripts, no styles, no trackers - and the UI renders them as plain text.
Paywalled or script-rendered pages yield only a teaser; the page says so and links the original.
"""
from __future__ import annotations

import ipaddress
import re
import time
from urllib.parse import urlparse

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"}
DROP = ("script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe", "button", "figure")
BLOCKS = {"h1": "h", "h2": "h", "h3": "h", "h4": "h", "p": "p", "li": "li", "blockquote": "quote", "pre": "code"}
MAX_BYTES = 4_000_000


def safe_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    host = u.hostname.lower()
    if host in ("localhost", "0.0.0.0") or host.endswith(".local") or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return True


def extract(html: str, url: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    def meta(*names):
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None
    title = meta("og:title", "twitter:title") or (soup.title.string.strip() if soup.title and soup.title.string else url)
    author = meta("author", "article:author", "parsely-author")
    published = meta("article:published_time", "date", "pubdate", "dc.date")
    site = meta("og:site_name") or urlparse(url).hostname
    for tag in soup(DROP):
        tag.decompose()
    root = soup.find("article") or soup.find("main")
    if root is None or len(root.get_text(" ", strip=True)) < 400:
        best, best_len = soup.body or soup, 0
        for cand in soup.find_all(["div", "section"]):
            n = sum(len(p.get_text(" ", strip=True)) for p in cand.find_all("p", recursive=False))
            if n > best_len:
                best, best_len = cand, n
        root = best if best_len > 200 else (root or soup.body or soup)
    blocks, seen = [], set()
    for el in root.find_all(list(BLOCKS)):
        if el.name in ("p", "li") and el.find_parent(["blockquote", "pre"]):
            continue
        if el.name == "li" and el.find_parent("li"):
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el.name != "pre" else el.get_text()
        if not text or (el.name != "pre" and len(text) < 2) or text in seen:
            continue
        seen.add(text)
        blocks.append({"type": BLOCKS[el.name], "text": text[:8000]})
    words = sum(len(b["text"].split()) for b in blocks)
    return {"url": url, "title": title, "author": author, "published": published, "site": site, "blocks": blocks[:600],
            "words": words, "minutes": max(1, round(words / 230)),
            "teaser_only": words < 180,
            "note": "Only a teaser came through (paywall or a page that renders with JavaScript) - open the original." if words < 180 else None}


async def read_article(ctx, url: str) -> dict:
    if not safe_url(url):
        return {"error": "only public http(s) addresses can be opened in the reader"}

    async def build():
        resp = await ctx.http.get(url, headers=BROWSER_UA, timeout=20, follow_redirects=True)
        if resp.status_code >= 400:
            return {"error": f"the site answered HTTP {resp.status_code}"}
        ctype = resp.headers.get("content-type", "")
        if "pdf" in ctype or str(resp.url).lower().endswith(".pdf"):
            return _pdf(resp.content[:MAX_BYTES * 5], str(resp.url))
        import asyncio
        return await asyncio.to_thread(extract, resp.text[:MAX_BYTES], str(resp.url))
    return await ctx.cache.get(f"reader:{url}", 24 * 3600, build, disk=True)


def _pdf(content: bytes, url: str) -> dict:
    try:
        import io

        from pypdf import PdfReader
    except ImportError:
        return {"url": url, "title": url.rsplit("/", 1)[-1], "blocks": [], "pdf": True, "words": 0, "minutes": 0,
                "teaser_only": True, "note": "PDF - install 'pypdf' to read it here, or open the original."}
    reader = PdfReader(io.BytesIO(content))
    blocks = []
    for page in reader.pages[:60]:
        for para in re.split(r"\n\s*\n", page.extract_text() or ""):
            text = re.sub(r"\s+", " ", para).strip()
            if len(text) > 1:
                blocks.append({"type": "p", "text": text})
    words = sum(len(b["text"].split()) for b in blocks)
    return {"url": url, "title": (reader.metadata.title if reader.metadata and reader.metadata.title else url.rsplit("/", 1)[-1]),
            "blocks": blocks, "pdf": True, "words": words, "minutes": max(1, round(words / 230)), "teaser_only": words < 180,
            "note": None}


def recommend(items: list[dict], held: dict[str, set], watch: set[str], saved_titles: list[str], now: float,
              max_age_days: float = 14, limit: int = 8) -> list[dict]:
    """Research items ranked by what concerns you: open positions (market themes), watchlist names, topics of the
    articles you saved; newer counts more. Every pick says why. Pure, tested."""
    from .assets import themes_of
    from .news import match_held
    saved_themes: dict[str, int] = {}
    for t in saved_titles:
        for th in themes_of(t) - {"risk"}:
            saved_themes[th] = saved_themes.get(th, 0) + 1
    out = []
    for it in items:
        age_days = (now - (it.get("published") or now)) / 86400
        if age_days > max_age_days:
            continue
        text = {"title": f"{it.get('title', '')} {(it.get('summary') or '')[:300]}", "symbols": it.get("symbols") or []}
        why, score = [], 0.0
        touched = match_held(text, held) if held else []
        if touched:
            score += 3
            why.append("touches your open " + ", ".join(touched))
        names = sorted(set(it.get("symbols") or []) & watch)
        if names:
            score += 2
            why.append("names " + ", ".join(names) + " (watchlist)")
        topics = sorted((themes_of(text["title"]) - {"risk"}) & set(saved_themes))
        if topics:
            score += 1
            why.append("topic you saved before: " + ", ".join(topics))
        if score:
            out.append({**it, "score": score - age_days / 7, "why": why})
    return sorted(out, key=lambda x: -x["score"])[:limit]


async def feed(ctx, q: str | None = None, limit: int = 120) -> dict:
    rows = await ctx.db.run(ctx.db.query_news, "research", q, None, None, limit)
    rss = ctx.hub.get("rss")
    sources = [f["name"] for f in rss.feeds("research")] if rss else []
    saved = await ctx.db.run(ctx.db.saved)
    out = {"items": rows, "sources": sources, "saved": saved, "asof": time.time()}
    if not q:
        from .news import held
        held_map = await held(ctx)
        watch = {s.upper() for s in (ctx.settings.get("watchlist") or [])}
        out["recommended"] = recommend(rows, held_map, watch, [s.get("title") or "" for s in saved], time.time())
    return out
