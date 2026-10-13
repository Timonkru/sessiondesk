"""Headline intake: poll feeds and news connectors, tag, classify impact, archive, push.

Impact is rule-based and transparent (the matched rule travels with the item). It flags what
usually moves index futures within minutes - central-bank decisions, top-tier data prints,
geopolitical shocks, tariffs, market-structure events. It is a triage aid, not a signal.
"""
from __future__ import annotations

import re
import time

from . import universe

HIGH_RULES = [
    ("central bank decision", r"\b(fed|fomc|ecb|boe|boj|snb|rba|boc|pboc|bank of (england|japan|canada))\b.*\b(raise[sd]?|hike[sd]?|cut[s]?|hold[s]?|keeps?|leaves?|unchanged|decision|surprise)\b"),
    ("rate decision", r"\brate decision\b|\binterest rate decision\b|\bpolicy rate\b.*\b(to|at)\b \d"),
    ("top-tier data print", r"\b(cpi|core cpi|pce|core pce|non-?farm|payrolls|nfp|gdp|unemployment rate|ism (manufacturing|services)|retail sales|ppi|jobless claims|jolts)\b.*(\d|actual|expected|forecast|est\.?)"),
    ("geopolitical shock", r"\b(invasion|invade[sd]?|missile|airstrike|air strike|attack(s|ed)? on|declares? war|nuclear|ceasefire|truce|martial law|coup)\b"),
    ("tariffs / sanctions", r"\b(tariff|tariffs|sanctions?|export (ban|controls?)|trade war)\b"),
    ("market structure", r"\b(circuit breaker|trading halt|halts trading|flash crash|exchange outage|limit down|limit up)\b"),
    ("credit event", r"\b(default(s|ed)?|bankrupt(cy)?|chapter 11|bail-?out|bank run|downgrade[sd]? .*(sovereign|united states|u\.s\.|treasur))\b"),
    ("fx intervention", r"\b(intervention|intervene[sd]?)\b.*\b(yen|yuan|franc|currency|fx)\b|\b(mof|ministry of finance)\b.*\b(yen)\b"),
    ("government", r"\b(government shutdown|debt ceiling|impeach|snap election|resigns?|resignation)\b"),
]
MEDIUM_RULES = [
    ("central bank speaker", r"\b(powell|lagarde|bailey|ueda|waller|williams|jefferson|schnabel|nagel|fed'?s|ecb'?s)\b"),
    ("guidance / earnings", r"\b(guidance|outlook|profit warning|beats?|misses?|earnings|revenue|eps)\b"),
    ("energy", r"\b(opec\+?|crude inventor|eia|oil output|production cut)\b"),
    ("auction / treasury", r"\b(auction|refunding|treasury yields?|bund yields?|gilt yields?)\b"),
    ("data", r"\b(pmi|ifo|zew|sentiment|housing starts|durable goods|trade balance|industrial production)\b"),
]
_HIGH = [(name, re.compile(rx, re.I)) for name, rx in HIGH_RULES]
_MED = [(name, re.compile(rx, re.I)) for name, rx in MEDIUM_RULES]

CASHTAG = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
EXCHANGE_TAG = re.compile(r"\((?:NASDAQ|NYSE|NYSEARCA|AMEX|OTC|XETRA|ETR)\s*:\s*([A-Z0-9.\-]{1,8})\)", re.I)
NAME_STOP = {"target", "visa", "ball", "gap", "best", "fox", "news", "match", "block", "general", "first", "global",
             "international", "american", "united", "national", "public", "energy", "southern", "eaton", "linde"}
_SUFFIX = re.compile(r"[,.]?\s+(inc|corp|corporation|co|company|plc|ltd|limited|holdings?|group|ag|se|n\.?v|s\.?a|the)\.?$", re.I)


def _simplify(name: str) -> str:
    name = name.strip()
    for _ in range(3):
        name = _SUFFIX.sub("", name).strip()
    return name


def _name_index() -> list[tuple[re.Pattern, str]]:
    out = []
    for u in universe.UNIVERSES:
        for m in universe.members(u):
            n = _simplify(m["name"])
            if len(n) >= 4 and n.lower() not in NAME_STOP:
                out.append((re.compile(r"\b" + re.escape(n) + r"\b"), m["symbol"]))
    return out


_NAMES: list | None = None


def tag_symbols(item: dict) -> list[str]:
    global _NAMES
    if _NAMES is None:
        _NAMES = _name_index()
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    found = list(item.get("symbols") or [])
    found += CASHTAG.findall(text) + [s.upper() for s in EXCHANGE_TAG.findall(text)]
    title = item.get("title", "")
    for rx, sym in _NAMES:
        if rx.search(title):
            found.append(sym)
    return list(dict.fromkeys(found))[:8]


def classify(item: dict) -> tuple[str, list[str]]:
    text = item.get("title", "")
    for name, rx in _HIGH:
        if rx.search(text):
            return "high", [name]
    for name, rx in _MED:
        if rx.search(text):
            return "medium", [name]
    return "normal", []


def prepare(items: list[dict], group: str) -> list[dict]:
    out = []
    for it in items:
        it = dict(it)
        it.setdefault("group", group)
        it["impact"], it["tags"] = classify(it)
        it["symbols"] = tag_symbols(it)
        out.append(it)
    return out


async def ingest(ctx, items: list[dict], group: str, *, push: bool) -> list[dict]:
    """Archive; push new squawk headlines and any new high-impact headline."""
    fresh_cut = time.time() - 6 * 3600            # first poll after start must not replay yesterday as "new"
    prepared = prepare(items, group)
    new = await ctx.db.run(ctx.db.add_news, prepared)
    pushed = []
    for it in new:
        if not push or it.get("published", 0) < fresh_cut:
            continue
        if group == "squawk" or it["impact"] == "high":
            ctx.broker.publish("news", {"item": {k: it.get(k) for k in ("id", "title", "url", "source", "published",
                                                                       "impact", "tags", "symbols", "group")}})
            pushed.append(it)
    return pushed


async def poll_group(ctx, group: str, *, push: bool = True) -> int:
    rss = ctx.hub.get("rss")
    if not rss or not rss.active():
        return 0
    items = await rss.fetch_group(group)
    return len(await ingest(ctx, items, group, push=push))


async def poll_keyed(ctx, *, push: bool = True) -> int:
    """General news from keyed connectors (Finnhub, Polygon, Alpaca/Benzinga)."""
    n = 0
    results = await ctx.hub.gather("news", "news")
    for src, res in results.items():
        if src == "rss" or not isinstance(res, list):
            continue
        n += len(await ingest(ctx, res, "markets", push=push))
    return n


async def list_news(ctx, group: str | None, q: str | None, impact: str | None, symbol: str | None, limit: int) -> dict:
    rows = await ctx.db.run(ctx.db.query_news, group, q, impact, symbol, limit)
    rss = ctx.hub.get("rss")
    return {"items": rows, "feed_errors": dict(rss.errors) if rss else {}, "fts": ctx.db.fts}
