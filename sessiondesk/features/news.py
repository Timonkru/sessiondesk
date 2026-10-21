"""Headline intake: poll feeds and news connectors, tag, classify impact, archive, push.

Impact is rule-based and transparent (the matched rule travels with the item). It flags what
usually moves index futures within minutes - central-bank decisions, top-tier data prints,
geopolitical shocks, tariffs, market-structure events. It is a triage aid, not a signal.
"""
from __future__ import annotations

import re
import time

from . import assets, universe

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


_URL = re.compile(r"https?://\S+|www\.\S+")


def is_junk(title: str | None) -> bool:
    """Posts that are only a link (or a few characters once links are removed) carry no headline."""
    rest = _URL.sub("", title or "").strip(" \t\n-–—|:·•")
    return len(rest) < 8


def prepare(items: list[dict], group: str) -> list[dict]:
    out = []
    for it in items:
        if is_junk(it.get("title")):
            continue
        it = dict(it)
        it.setdefault("group", group)
        it["impact"], it["tags"] = classify(it)
        it["symbols"] = tag_symbols(it)
        out.append(it)
    return out


# ------------------------------------------------------------------ headlines that touch open positions
# Market filter for News and Research: the theme rules from assets.THEMES plus extra words per market.
MARKETS = [
    ("us", "US stocks", {"us_stocks", "fed", "us_macro", "tech"}, None),
    ("europe", "Europe", {"eu_stocks", "ecb", "eu_macro"}, r"\beurope(an)?\b|\bgerman|\bfrance\b|\bfrench\b|\bital(y|ian)\b|\bspain\b|\bspanish\b|\beu\b"),
    ("uk", "UK", {"boe", "uk_macro"}, r"\bbritain\b|\bbritish\b|\buk\b|\bpound\b|\blondon\b"),
    ("japan", "Japan", {"boj", "japan"}, r"\bjapan"),
    ("china", "China & Hong Kong", {"china", "pboc"}, r"\bchina\b|\bchinese\b|hong kong"),
    ("rates", "Rates & bonds", {"yields", "fed", "ecb", "boe", "boj"}, r"\bbonds?\b|\byields?\b|\bcredit\b|\bspreads?\b"),
    ("fx", "FX & dollar", {"usd"}, r"\bforex\b|\bfx\b|currenc|\beuro\b|\byen\b|sterling|\byuan\b|\bfranc\b|\bdollar\b"),
    ("energy", "Oil, gas & power", {"oil"}, r"natural gas|\blng\b|\bpower (prices?|grid)|electricity|refiner|pipeline|\bcoal\b|uranium|tanker"),
    ("metals", "Gold & metals", {"gold"}, r"\bsilver\b|copper|platinum|palladium|alumin(i)?um|iron ore|lithium|\bnickel\b|\bmetals?\b"),
    ("agri", "Agriculture", set(), r"\bcorn\b|wheat|soybeans?|\bcoffee\b|cocoa|\bsugar\b|cotton|cattle|\bhogs?\b|\bgrains?\b|\bcrops?\b|harvest|fertili[sz]er|wasde|\busda\b"),
    ("crypto", "Crypto", {"crypto"}, None),
    ("tech", "Tech & AI", {"tech"}, r"\bai\b|artificial intelligence|\bchips?\b|software|data cent(er|re)s?"),
]
_MARKET_RX = {k: re.compile(x, re.IGNORECASE) for k, _, _, x in MARKETS if x}


def markets_of(text: str) -> list[str]:
    """Market keys whose themes or extra words appear in the text (title, for research also the summary)."""
    themes = assets.themes_of(text)
    return [k for k, _, th, _ in MARKETS if themes & th or (k in _MARKET_RX and _MARKET_RX[k].search(text or ""))]


def market_list() -> list[dict]:
    return [{"key": k, "label": label} for k, label, _, _ in MARKETS]


def held_map(positions: list[dict], settings=None) -> dict[str, set[str]]:
    """Open positions -> {market or ticker: headline themes it reacts to}. Index/FX/commodity CFDs map to a market
    (DAX, GOLD, EURUSD ...) and its themes; single-stock CFDs (NVDA.US, SAP.DE) are matched by ticker only."""
    out: dict[str, set[str]] = {}
    for p in positions:
        sym = p.get("symbol") or ""
        asset = assets.asset_of(sym, settings)
        if asset:
            out.setdefault(asset, set()).update(assets.themes_for_asset(asset))
        elif sym:
            out.setdefault(re.split(r"[._#]", sym)[0].upper(), set())
    return out


BROAD_THEMES = {"geopolitics", "tariffs"}       # touch nearly every market; high-impact cases are pushed by the impact rules


def match_held(item: dict, held: dict[str, set[str]], strict: bool = False) -> list[str]:
    """Open markets a headline is about. strict (used for pushes): specific themes or the ticker only."""
    # "risk" (sell-off, record high ...) alone is market noise; it must come with a more specific theme
    themes = assets.themes_of(item.get("title", "")) - {"risk"} - (BROAD_THEMES if strict else set())
    syms = set(item.get("symbols") or [])
    return [name for name, th in held.items() if name in syms or (themes & th)]


async def held(ctx) -> dict[str, set[str]]:
    async def build():
        from . import broker
        b = await broker.overview(ctx)
        live = [p for p in b.get("positions", []) if p.get("fresh", True)]
        return {"held": {k: sorted(v) for k, v in held_map(live, ctx.settings).items()}}
    try:
        res = await ctx.cache.get("news:held", 30, build)
    except Exception:
        return {}
    return {k: set(v) for k, v in (res.get("held") or {}).items()}


async def for_positions(ctx, hours: int = 12, q: str | None = None, strict: bool = False) -> dict:
    hmap = await held(ctx)
    if not hmap:
        return {"held": [], "items": [], "note": "No open positions (or no broker connected)."}
    rows = await ctx.db.run(ctx.db.query_news, None, q, None, None, 600, int(time.time() - hours * 3600))
    items = []
    for it in rows:
        m = match_held(it, hmap, strict)
        if m:
            items.append({**it, "held": m})
    return {"held": sorted(hmap), "items": items[:150], "hours": hours, "strict": strict,
            "note": "Matched by market themes (central bank, data, yields, oil ...) and by company names/tickers in the headline. "
                    "A match means the topic is relevant to the position, not that the headline moves it."}


async def ingest(ctx, items: list[dict], group: str, *, push: bool) -> list[dict]:
    """Archive; push new squawk headlines, any new high-impact headline, and medium-impact ones that touch an open position."""
    fresh_cut = time.time() - 6 * 3600            # first poll after start must not replay yesterday as "new"
    prepared = prepare(items, group)
    new = await ctx.db.run(ctx.db.add_news, prepared)
    pushed = []
    hmap = await held(ctx) if push and new else {}
    for it in new:
        if not push or it.get("published", 0) < fresh_cut:
            continue
        touches = match_held(it, hmap) if hmap else []
        specific = match_held(it, hmap, strict=True) if hmap else []
        if group == "squawk" or it["impact"] == "high" or (specific and it["impact"] == "medium"):
            ctx.broker.publish("news", {"item": {**{k: it.get(k) for k in ("id", "title", "url", "source", "published",
                                                                          "impact", "tags", "symbols", "group")}, "held": touches,
                                                 "markets": markets_of(it.get("title", ""))}})
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


async def list_news(ctx, group: str | None, q: str | None, impact: str | None, symbol: str | None, limit: int,
                    market: str | None = None) -> dict:
    pool = min(limit * 8, 3000) if market else limit            # the market match runs on titles, so read a larger pool
    rows = [r for r in await ctx.db.run(ctx.db.query_news, group, q, impact, symbol, pool) if not is_junk(r.get("title"))]
    for r in rows:
        r["markets"] = markets_of(r.get("title", ""))
    if market:
        rows = [r for r in rows if market in r["markets"]][:limit]
    rss = ctx.hub.get("rss")
    return {"items": rows, "feed_errors": dict(rss.errors) if rss else {}, "fts": ctx.db.fts, "markets": market_list(),
            "streams": (ctx.extras.get("newsstream") or {})}
