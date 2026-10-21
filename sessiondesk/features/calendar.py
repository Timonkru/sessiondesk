"""Economic calendar: merge sources, warn before high-impact releases, push the print the moment it lands.

Sources, merged by currency + time + title similarity:
  ffcal              schedule + impact + forecast/previous (free, no actuals)
  mt5                MetaQuotes calendar incl. ACTUAL values, written by the bridge within ~2 s
  tradingeconomics / finnhub / fmp   calendars with actuals (user keys)

Release path ("burst mode"): from burst_before seconds ahead of a high-impact event until
burst_after seconds past it, the desk polls every burst_seconds:
  1. the calendar sources that carry actuals -> push "release" with actual vs forecast + surprise
  2. the squawk feeds (conditional GET)      -> push the first matching headline
Whichever arrives first wins; both are labelled with their source. Outside these windows nothing
polls fast, so the free feeds are not hammered.
"""
from __future__ import annotations

import asyncio
import re
import time


ACTUAL_SOURCES = ("mt5", "tradingeconomics", "finnhub", "fmp")
IMPACT_RANK = {"holiday": 0, "low": 1, "medium": 2, "high": 3}
SYNONYMS = [(r"consumer price index", "cpi"), (r"producer price index", "ppi"), (r"gross domestic product", "gdp"),
            (r"non-?farm (employment change|payrolls)", "nonfarm payrolls"), (r"personal consumption expenditures?", "pce"),
            (r"interest rate decision", "rate decision"), (r"federal funds rate", "rate decision"),
            (r"main refinancing rate", "rate decision"), (r"official bank rate", "rate decision"),
            (r"\bmom\b", "m/m"), (r"\byoy\b", "y/y"), (r"\bqoq\b", "q/q"),
            # MetaTrader names events in the terminal's language; the German words that decide core/period
            (r"\bkern", "core "), (r"\(monat\)", " m/m"), (r"\(jahr\)", " y/y"), (r"\(quartal\)", " q/q")]
STOP = {"m/m", "y/y", "q/q", "the", "of", "and", "s", "a", "in", "rate", "change", "flash", "prelim", "final", "sa", "nsa", "mom", "yoy"}
KEY_TERMS = ["cpi", "ppi", "pce", "gdp", "nonfarm", "payrolls", "unemployment", "retail sales", "ism", "pmi", "jolts",
             "jobless claims", "rate decision", "fomc", "ecb", "boe", "boj", "snb", "rba", "boc", "employment", "inflation",
             "trade balance", "industrial production", "ifo", "zew", "sentiment", "housing", "durable goods"]
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def norm_title(title: str) -> str:
    t = title.lower()
    for rx, rep in SYNONYMS:
        t = re.sub(rx, rep, t)
    return re.sub(r"[^a-z0-9/ ]+", " ", t)


def tokens(title: str) -> set[str]:
    return {w for w in norm_title(title).split() if w not in STOP}


def same_event(a: dict, b: dict) -> bool:
    if a.get("currency") != b.get("currency") or abs(a["ts"] - b["ts"]) > 120:
        return False
    ta, tb = tokens(a["title"]), tokens(b["title"])
    if not ta or not tb:
        return False
    if ("core" in ta) != ("core" in tb):
        return False
    pa, pb = period(a["title"]), period(b["title"])
    if pa and pb and pa != pb:                 # CPI m/m and CPI y/y print at the same second - keep them apart
        return False
    return len(ta & tb) / len(ta | tb) >= 0.5 or same_numbers(a, b) or same_speaker(a, b)


def same_numbers(a: dict, b: dict) -> bool:
    """Titles in two languages (MT5 uses the terminal's language, Forex Factory English) share no words; the same
    currency and second plus the same previous value identify the event. Forecasts differ between the two consensus
    sources, so they only have to agree when the previous value is small and could be a coincidence (pure, tested)."""
    pa, pb, fa, fb = (to_number(x.get(k)) for k in ("previous", "forecast") for x in (a, b))
    if pa is None or pb is None or abs(pa - pb) > max(0.0051, 0.006 * max(abs(pa), abs(pb))):     # -8.557 vs -8.6
        return False
    return max(abs(pa), abs(pb)) >= 1 or (fa is not None and fb is not None and abs(fa - fb) <= 0.1001)


SPEECH_WORDS = {"speaks", "spricht", "speech", "rede", "testifies", "president", "präsident", "governor", "gouverneur", "member",
                "german", "chair", "board", "executive", "vorstandsmitglied", "deputy", "conference", "press"}


def same_speaker(a: dict, b: dict) -> bool:
    """Speeches carry no numbers: the same currency and time plus the same surname (a capitalised word of four or more
    letters that is not a title) mark the same speech, whatever the language (pure, tested)."""
    if any(x.get(k) not in (None, "") for x in (a, b) for k in ("forecast", "previous", "actual")):
        return False
    names = lambda t: {w for w in re.findall(r"\b[A-ZÄÖÜ][a-zäöüß]{3,}\b", t) if w.lower() not in SPEECH_WORDS}  # noqa: E731
    return bool(names(a["title"]) & names(b["title"]))


def same_words(a: dict, b: dict) -> bool:
    ta, tb = tokens(a["title"]), tokens(b["title"])
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def period(title: str) -> str:
    t = norm_title(title)
    return next((p for p in ("m/m", "y/y", "q/q") if p in t), "")


def to_number(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = NUM.search(str(text).replace(",", ""))
    return float(m.group()) if m else None


def merge(sources: dict[str, list[dict]]) -> list[dict]:
    """One row per real-world event; keeps every source's view, prefers sources with actuals."""
    order = ["mt5", "tradingeconomics", "finnhub", "fmp", "ffcal"]
    rows: list[dict] = []
    for src in sorted(sources, key=lambda s: order.index(s) if s in order else 99):
        for ev in sources[src]:
            hit = next((r for r in rows if same_event(r, ev)), None)
            if hit is None:
                rows.append({**ev, "sources": [src]})
                continue
            hit["sources"].append(src)
            if src == "ffcal" and "mt5" in hit["sources"] and not same_words(hit, ev):
                hit["title"] = ev["title"]            # matched by the numbers: the English title, like every other row
            if IMPACT_RANK.get(ev.get("impact"), 0) > IMPACT_RANK.get(hit.get("impact"), 0):
                hit["impact"] = ev["impact"]          # Forex Factory's impact grading usually wins here
            for key in ("actual", "forecast", "previous", "actual_value", "forecast_value"):
                if hit.get(key) in (None, "") and ev.get(key) not in (None, ""):
                    hit[key] = ev[key]
    for r in rows:
        a = r.get("actual_value") if r.get("actual_value") is not None else to_number(r.get("actual"))
        f = r.get("forecast_value") if r.get("forecast_value") is not None else to_number(r.get("forecast"))
        r["surprise"] = (a - f) if a is not None and f is not None else None
    rows.sort(key=lambda r: r["ts"])
    return rows


def headline_matches(event: dict, title: str) -> bool:
    t = norm_title(title)
    evn = norm_title(event["title"])
    keys = [k for k in KEY_TERMS if k in evn]
    if not keys:
        keys = [w for w in tokens(event["title"]) if len(w) > 3][:2]
    return bool(keys) and any(k in t for k in keys)


class CalendarService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.warned: set[tuple[str, int]] = set()
        self.released: set[str] = set()
        self.headlined: set[str] = set()
        self.last_errors: dict[str, str] = {}

    async def _source(self, conn, start: float, end: float, ttl: float) -> list[dict]:
        """One cached fetch per source and UTC day (window: 2 days back .. 9 days ahead), filtered locally.
        Keying the cache by the caller's window made every page and loop fetch separately - Forex Factory
        answered with HTTP 429 (found 12.10.2026). Failures back off for 15 minutes."""
        if conn.id == "mt5":                     # local file: always read fresh
            try:
                return await conn.calendar(start, end)
            except Exception as exc:
                self.last_errors[conn.id] = str(exc)
                return []
        day0 = int(time.time() // 86400) * 86400
        lo, hi = day0 - 2 * 86400, day0 + 9 * 86400

        async def build():
            return {"events": await conn.calendar(lo, hi)}
        res = await self.ctx.cache.get(f"cal:{conn.id}:{day0}", ttl, build, disk=conn.id == "ffcal", retry=900)
        if "error" in res:
            self.last_errors[conn.id] = res["error"]
            return []
        if res.get("stale_reason"):
            self.last_errors[conn.id] = "using the last good copy - " + res["stale_reason"]
        else:
            self.last_errors.pop(conn.id, None)
        return [e for e in res.get("events", []) if start <= e["ts"] <= end]

    async def events(self, start: float | None = None, end: float | None = None, *, fast: bool = False) -> dict:
        now = time.time()
        start = start if start is not None else now - 12 * 3600
        end = end if end is not None else now + 7 * 86400
        conns = self.ctx.hub.candidates("calendar")

        async def one(c):
            ttl = 900 if c.id == "ffcal" else (5 if fast else 120)
            evs = await self._source(c, start, end, ttl)
            return c.id, [e for e in evs if start <= e["ts"] <= end]
        pairs = await asyncio.gather(*(one(c) for c in conns))
        merged = merge(dict(pairs))
        return {"events": merged, "sources": [c.id for c in conns], "errors": dict(self.last_errors),
                "has_actuals": any(c.id in ACTUAL_SOURCES for c in conns)}

    def _watched(self, ev: dict) -> bool:
        cfg = self.ctx.settings.get("events") or {}
        return ev.get("impact") in cfg.get("impact", ["high"]) and (not cfg.get("currencies") or ev.get("currency") in cfg["currencies"])

    async def loop(self) -> None:
        """Warnings + burst-mode release capture. Runs for the app's lifetime."""
        while True:
            cfg = self.ctx.settings.get("events") or {}
            burst_before, burst_after = cfg.get("burst_before", 60), cfg.get("burst_after", 240)
            try:
                now = time.time()
                data = await self.events(now - burst_after - 60, now + 2 * 86400)
                watched = [e for e in data["events"] if self._watched(e)]
                for ev in watched:
                    left = ev["ts"] - now
                    for m in cfg.get("warn_minutes", [30, 5, 1]):
                        key = (ev["id"], m)
                        if 0 < left <= m * 60 and key not in self.warned:
                            self.warned.add(key)
                            # also mark the longer warnings as done, so a late start doesn't fire three at once
                            for m2 in cfg.get("warn_minutes", []):
                                if m2 > m:
                                    self.warned.add((ev["id"], m2))
                            self.ctx.broker.publish("event_warning", {"event": _slim(ev), "minutes": m, "seconds_left": left})
                hot = [e for e in watched if -burst_after <= e["ts"] - now <= burst_before]
                if hot:
                    await self._burst(hot)
                    await asyncio.sleep(cfg.get("burst_seconds", 3))
                else:
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
            except Exception as exc:          # never let the loop die
                self.last_errors["loop"] = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(10)

    async def _burst(self, hot: list[dict]) -> None:
        now = time.time()
        fresh = await self.events(now - 3600, now + 3600, fast=True)
        for ev in fresh["events"]:
            if any(same_event(ev, h) for h in hot) and ev.get("actual") not in (None, "") and ev["id"] not in self.released:
                self.released.add(ev["id"])
                self.ctx.broker.publish("release", {"event": _slim(ev), "source": ",".join(s for s in ev["sources"] if s in ACTUAL_SOURCES)})
        rss = self.ctx.hub.get("rss")
        if not rss or not rss.active():
            return
        for feed in rss.feeds("squawk"):
            try:
                # Shared fetcher: conditional GET state and rate-limit backoff are common with the news poller.
                items = await rss.fetcher.fetch(feed["url"], feed["name"], timeout=5)
            except Exception:
                continue
            for it in items[:15]:
                for ev in hot:
                    if it["published"] < ev["ts"] - 90 or ev["id"] in self.headlined:
                        continue
                    if headline_matches(ev, it["title"]):
                        self.headlined.add(ev["id"])
                        self.ctx.broker.publish("release_headline", {"event": _slim(ev), "headline": {
                            "title": it["title"], "source": it["source"], "url": it.get("url"), "published": it["published"]}})


def _slim(ev: dict) -> dict:
    return {k: ev.get(k) for k in ("id", "ts", "currency", "title", "impact", "actual", "forecast", "previous", "surprise", "sources")}
