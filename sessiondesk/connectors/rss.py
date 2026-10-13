"""RSS/Atom feeds as a connector: market news, squawk (fast headline wires), central banks, research.

The default lists below are public feeds. Users can add, remove or disable feeds in Settings;
their overrides live in settings["feeds"][group] = [{"name", "url", "enabled"}].
Squawk feeds are polled every few seconds with conditional GET, everything else every few minutes.
"""
from __future__ import annotations

import asyncio

from ..features.feeds import FeedFetcher
from .base import Connector

DEFAULT_FEEDS: dict[str, list[dict]] = {
    "squawk": [
        {"name": "investingLive", "url": "https://investinglive.com/feed/"},
        {"name": "FinancialJuice", "url": "https://www.financialjuice.com/feed.ashx?xy=rss"},
    ],
    "markets": [
        {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
        {"name": "WSJ Markets", "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"},
        {"name": "FT Markets", "url": "https://www.ft.com/markets?format=rss"},
        {"name": "Reuters (Google News)", "url": "https://news.google.com/rss/search?q=site:reuters.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en"},
        {"name": "Bloomberg (Google News)", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en"},
        {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
        {"name": "FXStreet", "url": "https://www.fxstreet.com/rss/news"},
        {"name": "OilPrice", "url": "https://oilprice.com/rss/main"},
        {"name": "Handelsblatt Finanzen", "url": "https://www.handelsblatt.com/contentexport/feed/finanzen"},
        {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar"},
    ],
    "central_banks": [
        {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
        {"name": "ECB", "url": "https://www.ecb.europa.eu/rss/press.html"},
        {"name": "Bank of England", "url": "https://www.bankofengland.co.uk/rss/news"},
        {"name": "Bank of Japan", "url": "https://www.boj.or.jp/en/rss/whatsnew.xml"},
    ],
    "research": [
        {"name": "Krueger Algorithms research", "url": "https://kruegeralgorithms.com/feed.xml"},
        {"name": "Quantocracy", "url": "https://quantocracy.com/feed/"},
        {"name": "Alpha Architect", "url": "https://alphaarchitect.com/feed/"},
        {"name": "Liberty Street Economics (NY Fed)", "url": "https://libertystreeteconomics.newyorkfed.org/feed/"},
        {"name": "FEDS Notes (Federal Reserve)", "url": "https://www.federalreserve.gov/feeds/feds_notes.xml"},
        {"name": "Damodaran Online", "url": "https://aswathdamodaran.blogspot.com/feeds/posts/default"},
        {"name": "arXiv q-fin", "url": "https://rss.arxiv.org/rss/q-fin"},
        {"name": "ECB Blog", "url": "https://www.ecb.europa.eu/rss/blog.html"},
    ],
}
GROUPS = tuple(DEFAULT_FEEDS)


class Rss(Connector):
    id = "rss"
    name = "RSS news & research feeds"
    tier = "free"
    kind = "news"
    capabilities = ("news", "research")
    homepage = ""
    description = "Public headline feeds: squawk wires (polled every few seconds), market news, central banks, research blogs. Edit the lists in Settings."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.fetcher = FeedFetcher(ctx.http)
        self.errors: dict[str, str] = {}

    def feeds(self, group: str) -> list[dict]:
        custom = (self.ctx.settings.get("feeds") or {}).get(group)
        feeds = custom if isinstance(custom, list) else DEFAULT_FEEDS.get(group, [])
        return [f for f in feeds if f.get("url") and f.get("enabled", True)]

    async def fetch_group(self, group: str) -> list[dict]:
        feeds = self.feeds(group)

        async def one(f):
            try:
                items = await self.fetcher.fetch(f["url"], f["name"])
                self.errors.pop(f["name"], None)
            except Exception as exc:
                self.errors[f["name"]] = f"{type(exc).__name__}: {exc}"
                return []
            for it in items:
                it["group"] = group
                it["provider"] = self.id
            return items
        results = await asyncio.gather(*(one(f) for f in feeds))
        return [it for items in results for it in items]

    async def news(self) -> list[dict]:
        a, b = await asyncio.gather(self.fetch_group("markets"), self.fetch_group("squawk"))
        return a + b

    async def test(self) -> dict:
        items = await self.fetch_group("squawk")
        return {"ok": bool(items), "detail": f"{len(items)} squawk headlines; feed errors: {len(self.errors)}"}
