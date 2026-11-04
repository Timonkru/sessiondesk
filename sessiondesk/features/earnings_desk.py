"""Earnings desk: exact times, the report documents, the call, and a flash summary out of SEC filings.

- Times: every time carries its kind. 'actual' = SEC's acceptance time of the results 8-K. 'announced' = the company or a
  data vendor named it before the fact. 'historical' = the median of the company's last eight results filings, with
  the spread. Nothing is shown as more exact than it is.
- Consensus: frozen before the report. Yahoo rolls its 'current quarter' to the next quarter once a company has reported
  and Nasdaq drops the year-ago EPS, so nothing is fetched for a report whose window has opened. No snapshot means no
  hit or miss, not a late one.
- Flash: the collector polls EDGAR's current-filings feed only while a report is due (one request covers all companies),
  reads Exhibit 99 with features/earnings_parse.py and compares only on a confirmed basis.
- Coverage: EDGAR filers only. A foreign filer gets a link to its 6-K without extraction; anything else is 'not covered'.

A beat is not a trading statement: about 72 % of reports beat (2016-2022, n = 1,679, consumer stocks of the S&P 500), so
a beat alone says little, and this page never turns one into a direction.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import statistics
import time
from urllib.parse import urlsplit

from ..connectors.base import ConnectorError
from ..connectors.public import parse_earnings_filings
from . import earnings_parse as ep

ET = ep.ET
BASE_RATE = "About 72 % of reports beat the EPS consensus (2016-2022, n = 1,679), so a beat alone says little. Figures, not a trade signal."
NOT_COVERED = "Not covered: no SEC EDGAR filings for this company. Non-US reports would need each company's own site or a paid feed."
FOREIGN = "Foreign filer: reports on Form 6-K without a results item, so there is no flash. The latest 6-K is linked."
HOT_POLL_SECONDS = 30
FALLBACK_HOT = 300
FALLBACK_LATE = 1800
FREEZE_DAYS = 2
MAX_TERMS_PER_DAY = 80
CATCH_UP_SECONDS = 3600    # read this long after SEC accepted it: the app was off or missed it, so old news, not a flash
META_MAX_AGE = 20 * 3600
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------ pure helpers (tested)
def et_minutes(ts: float) -> int:
    t = dt.datetime.fromtimestamp(ts, ET)
    return t.hour * 60 + t.minute


def clock(minutes: float) -> str:
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"


def at_et(day: str, minutes: float) -> float:
    d = dt.date.fromisoformat(day)
    return dt.datetime(d.year, d.month, d.day, int(minutes) // 60, int(minutes) % 60, tzinfo=ET).timestamp()


def session_of(minutes: float) -> str:
    return "before the open" if minutes < 9 * 60 + 30 else "after the close" if minutes >= 16 * 60 else "during the session"


def typical_time(results: list[dict], before: str, n: int = 8) -> dict | None:
    """When the company's results filings were accepted (Eastern time, so daylight saving does not shift them), from
    the last n before the given day: median and spread (pure, tested)."""
    rows = sorted((r for r in results if r.get("accepted") and (r.get("filed") or "") < before), key=lambda r: r["accepted"], reverse=True)[:n]
    if not rows:
        return None
    mins = [et_minutes(r["accepted"]) for r in rows]
    med = statistics.median(mins)
    return {"n": len(mins), "median": med, "earliest": min(mins), "latest": max(mins), "median_et": clock(med), "earliest_et": clock(min(mins)),
            "latest_et": clock(max(mins)), "session": session_of(med), "days": [r["filed"] for r in rows]}


def window(day: str, timing: str | None, typical: dict | None) -> tuple[float, float]:
    """The hours a report can land: from the calendar's session, widened to where this company has filed before."""
    start, end = {"after close": (15 * 60 + 30, 19 * 60), "pre-market": (5 * 60 + 30, 10 * 60 + 30)}.get(timing or "", (5 * 60 + 30, 19 * 60))
    if typical and typical["n"] >= 3:
        start, end = min(start, typical["earliest"] - 30), max(end, typical["latest"] + 60)
    return at_et(day, max(start, 0)), at_et(day, min(end, 23 * 60 + 59))


def phase(day: str, timing: str | None, typical: dict | None, now: float) -> str | None:
    """'hot' inside the window, 'late' until noon of the next day (an 8-K can follow the wire by hours), else None (pure, tested)."""
    start, end = window(day, timing, typical)
    if start <= now <= end:
        return "hot"
    late_end = at_et((dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat(), 12 * 60)
    return "late" if end < now <= late_end else None


def term_filings(meta: dict, day: str) -> dict:
    """The filings that belong to one report day: results 8-K within 3 days, then the first 10-Q/10-K filed from 5 days
    before to 75 days after it (pure, tested)."""
    d = dt.date.fromisoformat(day)

    def gap(r):
        return (dt.date.fromisoformat(r["filed"]) - d).days
    near = sorted((r for r in meta.get("results") or [] if r.get("filed") and abs(gap(r)) <= 3), key=lambda r: abs(gap(r)))
    periodic = sorted((r for r in meta.get("periodic") or [] if r.get("filed") and -5 <= gap(r) <= 75), key=gap)
    foreign = sorted((r for r in meta.get("foreign") or [] if r.get("filed") and abs(gap(r)) <= 3), key=lambda r: abs(gap(r)))
    newest = (meta.get("foreign") or [None])[0]
    return {"results": near[0] if near else None, "quarterly": periodic[0] if periodic else None, "foreign": foreign[0] if foreign else newest}


def safe_url(url: str | None) -> str | None:
    return url if isinstance(url, str) and re.match(r"https?://[^\s]+$", url, re.I) else None


def has_path(url: str) -> bool:
    return bool(urlsplit(url).path.strip("/"))


def release_time(day: str, meta: dict | None, flash: dict | None, timing: str | None, yahoo: dict | None) -> dict:
    """The best statement about the report's time, with its kind (pure, tested)."""
    filing = term_filings(meta or {}, day).get("results") if meta else None
    accepted = (flash or {}).get("accepted") or (filing or {}).get("accepted")
    if accepted:
        return {"kind": "actual", "ts": accepted, "source": "SEC acceptance of the 8-K"}
    typical = typical_time((meta or {}).get("results") or [], day)
    if yahoo and yahoo.get("date_confirmed") and yahoo.get("release_ts") and dt.datetime.fromtimestamp(yahoo["release_ts"], ET).date().isoformat() == day and not typical:
        return {"kind": "announced", "ts": yahoo["release_ts"], "source": "Yahoo, date confirmed; the time is usually a round placeholder"}
    if typical:
        return {"kind": "historical", "ts": at_et(day, typical["median"]), "source": f"median of the last {typical['n']} results filings",
                "earliest_et": typical["earliest_et"], "latest_et": typical["latest_et"], "n": typical["n"],
                "date_confirmed": bool(yahoo and yahoo.get("date_confirmed"))}
    return {"kind": "session", "ts": None, "text": timing or "n/a", "source": "calendar session only"}


def call_details(day: str, meta: dict | None, flash: dict | None, yahoo: dict | None) -> dict:
    """Call time and link, each with where it came from. The link falls back from this release to last quarter's release
    to the investor site; the last one is marked, because it only gets you near the webcast (pure, tested)."""
    this = (flash or {}).get("call") or {}
    last = (meta or {}).get("last_call") or {}
    out: dict = {"ts": None, "time_kind": None, "time_source": None, "url": None, "url_kind": None}
    if this.get("ts"):
        out.update(ts=this["ts"], time_kind="announced", time_source="press release")
    elif yahoo and yahoo.get("call_ts") and yahoo.get("date_confirmed") and dt.datetime.fromtimestamp(yahoo["call_ts"], ET).date().isoformat() == day:
        out.update(ts=yahoo["call_ts"], time_kind="announced", time_source="Yahoo")
    elif last.get("minutes") is not None:
        out.update(ts=at_et(day, last["minutes"]), time_kind="historical", time_source="time of last quarter's call")
    # most releases only name the company's site (153 of 217 links in the October 2026 sample): that is no way into the call
    if safe_url(this.get("url")) and has_path(this["url"]):
        out.update(url=this["url"], url_kind="release", url_note="webcast link from this release")
    elif safe_url(last.get("url")) and has_path(last["url"]):
        out.update(url=last["url"], url_kind="last_release", url_note="link from last quarter's release, may have changed")
    elif safe_url(this.get("url")) or safe_url(last.get("url")):
        out.update(url=this.get("url") or last.get("url"), url_kind="ir_fallback", url_note="the release only names the company site: look for the investor page")
    else:
        site = safe_url((meta or {}).get("investor_site")) or safe_url((yahoo or {}).get("website"))
        if site:
            out.update(url=site, url_kind="ir_fallback", url_note="no webcast link found: company site, look for the investor page")
    return out


def yahoo_anchors(history: list[dict], day: str) -> list[float]:
    """Yahoo's reported EPS of the previous and the year-ago quarter, strictly before the report (pure, tested)."""
    d = dt.date.fromisoformat(day)
    earlier = sorted(((dt.date.fromisoformat(h["when"][:10]), h["eps_reported"]) for h in history if h.get("eps_reported") is not None and (d - dt.date.fromisoformat(h["when"][:10])).days > 20), reverse=True)
    out = [earlier[0][1]] if earlier else []
    out += [v for w, v in earlier if 340 <= (d - w).days <= 400][:1]
    return out


def nasdaq_anchors(history: list[dict], last_year_eps, day: str) -> list[float]:
    """Nasdaq's previous quarter plus the year-ago EPS of its calendar row, both on Nasdaq's basis (pure, tested)."""
    from .earnings_reported import money
    d = dt.date.fromisoformat(day)
    earlier = sorted(((h["date"], h["eps"]) for h in history if h.get("date") and (d - dt.date.fromisoformat(h["date"])).days > 20), reverse=True)
    out = [earlier[0][1]] if earlier else []
    year = money(last_year_eps)
    if year is not None:
        out.append(year)
    return out


def _row(source: dict, kind: str, parsed: dict) -> dict:
    cands, anchors, cons = (parsed["eps"], source.get("eps_anchors"), source.get("eps")) if kind == "eps" else \
        (parsed["revenue"], source.get("rev_anchors"), source.get("rev"))
    picked = ep.choose(cands, anchors or [], kind)
    v = ep.verdict(picked.get("value"), cons, picked["status"], kind, picked.get("basis"))
    return {"source": source["source"], "frozen": source.get("frozen"), "consensus": cons, "analysts": source.get("analysts" if kind == "eps" else "rev_analysts"),
            "quarter": source.get("quarter"), "status": picked["status"], "actual": picked.get("value"), "label": picked.get("label"), "basis": picked.get("basis"),
            "quote": picked.get("quote"), "reason": picked.get("reason"), **v}


def overall(rows: list[dict]) -> str | None:
    """One word for the row: the verdict if all sources that could compare agree (pure, tested)."""
    words = {r.get("verdict") for r in rows if r.get("verdict") in ("beat", "miss", "in line")}
    if len(words) == 1:
        return words.pop()
    if words:
        return "sources disagree"
    return "basis unclear" if any(r.get("verdict") == "basis unclear" for r in rows) else None


def figures(cands: list[dict], limit: int = 6) -> list[dict]:
    """What the release itself says, deduplicated, whatever the comparison decides: tables first."""
    seen, out = set(), []
    for c in sorted(cands, key=lambda c: (c.get("where") != "table", c.get("basis") == "gaap")):
        key = (c.get("basis"), round(c["value"], 2))
        if key not in seen:
            seen.add(key)
            out.append({k: c.get(k) for k in ("value", "label", "basis", "where", "quote")})
        if len(out) >= limit:
            break
    return out


def evaluate(parsed: dict, consensus: list[dict]) -> dict:
    """Release figures against every frozen consensus (pure, tested). No consensus: figures without a verdict."""
    eps = [_row(c, "eps", parsed) for c in consensus if c.get("eps") is not None]
    rev = [_row(c, "revenue", parsed) for c in consensus if c.get("rev") is not None]
    return {"eps": {"rows": eps, "verdict": overall(eps), "figures": figures(parsed["eps"])},
            "revenue": {"rows": rev, "verdict": overall(rev), "figures": figures(parsed["revenue"], 4)}}


def money_text(v: float | None) -> str:
    if v is None:
        return "-"
    for size, word in ((1e9, "B"), (1e6, "M")):
        if abs(v) >= size:
            return f"{v / size:,.2f} {word}"
    return f"{v:,.2f}"


def headline(symbol: str, data: dict) -> tuple[str, str]:
    """Title and body for toast and push, from computed figures only (pure, tested)."""
    parts = []
    for name, block, fmt in (("EPS", data["result"]["eps"], lambda x: f"{x:.2f}"), ("Revenue", data["result"]["revenue"], money_text)):
        conf = [r for r in block["rows"] if r.get("status") == "confirmed"]
        if conf:
            r = conf[0]
            parts.append(f"{name} {fmt(r['actual'])} vs {fmt(r['consensus'])} ({r['source']}): {r.get('verdict')}")
        elif block["figures"]:
            f = block["figures"][0]
            parts.append(f"{name} {fmt(f['value'])}: {block['verdict'] or 'no frozen consensus'}")
    return f"{symbol} reported {data.get('quarter') or ''}".strip(), " · ".join(parts) + ". " + BASE_RATE


def verify_ai(items: list, source: str) -> tuple[list[dict], int]:
    """An AI reading only counts if its quote stands word for word in the release and holds the number (pure, tested)."""
    norm = lambda t: re.sub(r"\s+", " ", t or "").strip().lower()     # noqa: E731
    text = norm(source)
    kept, dropped = [], 0
    for it in items if isinstance(items, list) else []:
        quote = norm(str((it or {}).get("quote")))
        digits = re.sub(r"[^\d.]", "", str((it or {}).get("value"))).strip(".")
        if quote and quote in text and digits and digits in re.sub(r"[,$\s]", "", quote):
            kept.append({"metric": str(it.get("metric"))[:80], "value": str(it.get("value"))[:40], "quote": str(it.get("quote"))[:400]})
        else:
            dropped += 1
    return kept, dropped


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


# ------------------------------------------------------------------ data
def _sec(ctx):
    return ctx.hub.get("sec") if ctx.hub else None


def contact_ok(ctx) -> bool:
    sec = _sec(ctx)
    return bool(sec and sec.has_contact())


async def calendar_rows(ctx) -> list[dict]:
    """Yesterday plus the next week from the free calendar, ranked. Cached: the page and the collector share one fetch."""
    from . import timeline
    today = dt.date.today()

    async def build():
        res = await ctx.hub.first("earnings", "earnings", today - dt.timedelta(days=1), 9)
        return {"items": res.get("data", []), "error_detail": res.get("error"), "source": res.get("source")}
    data = await ctx.cache.get(f"earnings:desk:{today}", 1800, build, disk=True)
    watch, major = {s.upper() for s in (ctx.settings.get("watchlist") or [])}, timeline.major_symbols()
    return [{**r, **timeline.earnings_rank(r, watch, major), "watchlist": (r.get("symbol") or "").upper() in watch} for r in data.get("items") or []]


def relevant(rows: list[dict]) -> list[dict]:
    """What the collector prepares and polls for: high and medium importance, the biggest of a day when there are many."""
    days: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("importance") in ("high", "medium") and r.get("symbol") and r.get("date"):
            days.setdefault(r["date"], []).append(r)
    out = []
    for items in days.values():
        out += sorted(items, key=lambda r: (not r.get("watchlist"), -(r.get("cap") or 0)))[:MAX_TERMS_PER_DAY]
    return out


async def refresh_meta(ctx, symbol: str, known: dict | None = None) -> dict:
    """The company's EDGAR history. Reads last quarter's release once per filing, for its call time and webcast link."""
    sec = _sec(ctx)
    if not contact_ok(ctx):
        raise ConnectorError("SEC contact email needed (Settings → Connectors → SEC EDGAR)")
    cik, sub = await sec.submissions(symbol)
    if not cik:
        meta = {"covered": "no", "reason": NOT_COVERED}
    else:
        p = parse_earnings_filings(sub, cik)
        covered = "yes" if p["results"] or p["periodic"] else "foreign" if p["foreign"] else "no"
        meta = {"covered": covered, "cik": cik, "name": p["name"], "investor_site": p["investor_site"], "results": p["results"][:12], "periodic": p["periodic"][:10],
                "foreign": p["foreign"][:12], "reason": {"foreign": FOREIGN, "no": NOT_COVERED}.get(covered)}
        last = (known or {}).get("last_call") or {}
        newest = p["results"][0] if p["results"] else None
        if newest and last.get("accession") != newest["accession"]:
            try:
                docs = await sec.filing_documents(cik, newest["accession"])
                ex = exhibit_of(docs)
                if ex:
                    filed = dt.datetime.fromtimestamp(newest["accepted"], dt.timezone.utc) if newest.get("accepted") else None
                    call = ep.call_info(ep.blocks(decode(await sec.document(ex["url"]))), filed)
                    last = {"accession": newest["accession"], "url": call.get("url"), "minutes": et_minutes(call["ts"]) if call.get("ts") else None}
            except ConnectorError:
                pass
        meta["last_call"] = last
    await ctx.db.run(ctx.db.earnings_meta_put, symbol, meta)
    return meta


def exhibit_of(docs: list[dict]) -> dict | None:
    """The press release of a results 8-K: Exhibit 99.x (GE files it as plain EX-99)."""
    return next((d for d in docs if (d.get("type") or "").upper().startswith("EX-99")), None)


def _yahoo_term(symbol: str, day: str) -> dict:
    """Blocking: estimates, year-ago values, confirmed date and call time from Yahoo."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    info = t.get_info() or {}
    hist = []
    df = t.get_earnings_dates(limit=12)
    if df is not None:
        for ts, row in df.iterrows():
            e, r = row.get("EPS Estimate"), row.get("Reported EPS")
            hist.append({"when": ts.isoformat(), "eps_estimate": None if e != e else float(e), "eps_reported": None if r != r else float(r)})
    d = dt.date.fromisoformat(day)
    row = next((h for h in hist if abs((dt.date.fromisoformat(h["when"][:10]) - d).days) <= 1), None)
    if row and row["eps_reported"] is not None:
        return {}          # already reported: this is no longer a pre-report consensus
    out = {"date_confirmed": info.get("isEarningsDateEstimate") is False, "call_ts": info.get("earningsCallTimestampStart"), "release_ts": info.get("earningsTimestamp"),
           "website": info.get("irWebsite") or info.get("website"), "eps": row["eps_estimate"] if row else None, "eps_anchors": yahoo_anchors(hist, day)}
    try:
        est, rev = t.earnings_estimate, t.revenue_estimate
        eps0 = float(est.loc["0q", "avg"])
        out["analysts"] = int(est.loc["0q", "numberOfAnalysts"])
        if out["eps"] is None:
            out["eps"] = eps0
        # 0q rolls after the report: the revenue line only counts while its EPS still matches this report's estimate
        if out["eps"] and abs(eps0 - out["eps"]) <= 0.15 * abs(out["eps"]):
            out["rev"] = float(rev.loc["0q", "avg"])
            out["rev_anchors"] = [float(rev.loc["0q", "yearAgoRevenue"])]
            out["rev_analysts"] = int(rev.loc["0q", "numberOfAnalysts"])
    except Exception:  # noqa: BLE001 - Yahoo's tables come and go; EPS from the dates table still stands
        pass
    return out


async def freeze(ctx, term: dict) -> bool:
    """Snapshot both consensus numbers. Refused once the report's window has opened or a flash exists."""
    from .earnings_reported import money
    sym, day = term["symbol"], term["date"]
    metas = await ctx.db.run(ctx.db.earnings_meta_get, [sym])
    typical = typical_time((metas.get(sym) or {}).get("results") or [], day)
    if time.time() >= window(day, term.get("timing"), typical)[0] or await ctx.db.run(ctx.db.flash_get, sym, day):
        return False
    nasdaq = ctx.hub.get("nasdaq")
    hist = []
    try:
        hist = await nasdaq.surprise_history(sym)
    except ConnectorError:
        pass
    eps = money(term.get("eps_forecast"))
    if eps is not None:
        await ctx.db.run(ctx.db.consensus_put, sym, day, "nasdaq", {"eps": eps, "eps_anchors": nasdaq_anchors(hist, term.get("last_year_eps"), day),
                                                                    "analysts": term.get("estimates"), "quarter": term.get("quarter")})
    try:
        y = await asyncio.to_thread(_yahoo_term, sym, day)
    except Exception:  # noqa: BLE001 - keep the Nasdaq side
        y = {}
    if y.get("eps") is not None:
        await ctx.db.run(ctx.db.consensus_put, sym, day, "yahoo", {**y, "quarter": term.get("quarter")})
    return True


def catching_up(accepted: float | None, at: float) -> bool:
    """True for a filing read long after SEC accepted it (pure, tested)."""
    return accepted is not None and at - accepted > CATCH_UP_SECONDS


async def collect_flash(ctx, term: dict, filing: dict, cik: int, *, seen: float | None = None, late: bool = False) -> dict:
    """Read one results filing into a flash. Store first, then tell the user."""
    sym, day = term["symbol"], term["date"]
    seen = seen or time.time()
    sec = _sec(ctx)
    docs = await sec.filing_documents(cik, filing["accession"])
    ex = exhibit_of(docs)
    url = (ex or {}).get("url") or filing.get("url")
    html = decode(await sec.document(url))
    filed = dt.datetime.fromtimestamp(filing["accepted"], dt.timezone.utc) if filing.get("accepted") else None
    parsed = await asyncio.to_thread(ep.parse_release, html, filed)
    consensus = await ctx.db.run(ctx.db.consensus_get, sym, day)
    parsed_at = time.time()
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing['accession'].replace('-', '')}/{filing['accession']}-index.htm"
    data = {"name": term.get("name"), "timing": term.get("timing"), "quarter": parsed["quarter"], "form": filing.get("form", "8-K"), "exhibit_url": url, "exhibit_found": bool(ex),
            "index_url": index_url, "result": evaluate(parsed, consensus), "guidance": parsed["guidance"], "call": parsed["call"], "highlights": parsed["highlights"],
            "consensus_frozen": bool(consensus), "late": late,
            "latency": None if late else {"sec_to_seen": seen - filing["accepted"] if filing.get("accepted") else None, "seen_to_shown": parsed_at - seen,
                                          "total": parsed_at - filing["accepted"] if filing.get("accepted") else None}}
    await ctx.db.run(ctx.db.flash_put, sym, day, filing["accession"], filing.get("accepted"), seen, parsed_at, data)
    if not late and not catching_up(filing.get("accepted"), parsed_at):
        title, body = headline(sym, data)
        ctx.broker.publish("earnings_flash", {"symbol": sym, "day": day, "title": title, "body": body, "watchlist": bool(term.get("watchlist")), "url": url})
    return data


async def prepare(ctx) -> dict:
    """Background: company histories for the coming week, consensus snapshots for the next days."""
    terms = relevant(await calendar_rows(ctx))
    today = dt.date.today()
    terms = [t for t in terms if t["date"] >= today.isoformat()]
    metas = await ctx.db.run(ctx.db.earnings_meta_get, sorted({t["symbol"] for t in terms}))
    done = {"meta": 0, "frozen": 0}
    now = time.time()
    if contact_ok(ctx):
        for sym in sorted({t["symbol"] for t in terms}):
            m = metas.get(sym)
            if not m or now - (m.get("updated") or 0) > META_MAX_AGE:
                try:
                    metas[sym] = {**await refresh_meta(ctx, sym, m), "updated": time.time()}
                    done["meta"] += 1
                except ConnectorError:
                    continue
    state = ctx.extras.setdefault("earnings_frozen", {})
    horizon = (today + dt.timedelta(days=FREEZE_DAYS)).isoformat()
    for t in terms:
        if t["date"] > horizon:
            continue
        key = (t["symbol"], t["date"])
        start = window(t["date"], t.get("timing"), typical_time((metas.get(t["symbol"]) or {}).get("results") or [], t["date"]))[0]
        age = now - state.get(key, 0)
        if now < start and (age > 3 * 3600 or (start - now < 5400 and age > 1800)):
            if await freeze(ctx, t):
                state[key] = now
                done["frozen"] += 1
    return done


async def tick(ctx) -> dict:
    """Background, every 30 s: no network unless a report is due right now. One feed request covers all companies; the
    per-company list is the slow fallback, for a feed that scrolled past a filing."""
    if not contact_ok(ctx):
        return {"due": 0}
    now = time.time()
    today = dt.date.today().isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    terms = [t for t in relevant(await calendar_rows(ctx)) if t["date"] in (today, yesterday)]
    if not terms:
        return {"due": 0}
    metas = await ctx.db.run(ctx.db.earnings_meta_get, sorted({t["symbol"] for t in terms}))
    due = []
    for t in terms:
        m = metas.get(t["symbol"]) or {}
        if m.get("covered") != "yes" or await ctx.db.run(ctx.db.flash_get, t["symbol"], t["date"]):
            continue
        ph = phase(t["date"], t.get("timing"), typical_time(m.get("results") or [], t["date"]), now)
        if ph:
            due.append((t, m, ph))
    if not due:
        return {"due": 0}
    sec = _sec(ctx)
    found = 0
    by_cik = {m["cik"]: (t, m) for t, m, _ in due}
    handled = set()
    if any(ph == "hot" for *_, ph in due):
        for f in await sec.current_filings("8-K", 100):
            hit = by_cik.get(f["cik"])
            if not hit or "2.02" not in f["items"] or not f.get("accepted"):
                continue
            t, _ = hit
            if abs((dt.datetime.fromtimestamp(f["accepted"], ET).date() - dt.date.fromisoformat(t["date"])).days) > 1:
                continue
            await collect_flash(ctx, t, {"accession": f["accession"], "accepted": f["accepted"], "form": f["form"]}, f["cik"], seen=now)
            handled.add(f["cik"])
            found += 1
    checked = ctx.extras.setdefault("earnings_checked", {})
    for t, m, ph in due:
        if m["cik"] in handled or now - checked.get(t["symbol"], 0) < (FALLBACK_HOT if ph == "hot" else FALLBACK_LATE):
            continue
        checked[t["symbol"]] = now
        fresh = await refresh_meta(ctx, t["symbol"], m)
        filing = term_filings(fresh, t["date"])["results"]
        if filing:
            await collect_flash(ctx, t, filing, m["cik"], seen=time.time())
            found += 1
    return {"due": len(due), "found": found}


# ------------------------------------------------------------------ page
def row_view(r: dict, meta: dict | None, flash: dict | None, consensus: list[dict]) -> dict:
    """One line of the Earnings tab (pure)."""
    yahoo = next((c for c in consensus if c.get("source") == "yahoo"), None)
    day = r["date"]
    return {**r, "covered": (meta or {}).get("covered"), "cover_note": (meta or {}).get("reason"), "release": release_time(day, meta, flash, r.get("timing"), yahoo),
            "call": call_details(day, meta, flash, yahoo), "frozen": [{"source": c["source"], "eps": c.get("eps"), "rev": c.get("rev"), "at": c.get("frozen")} for c in consensus],
            "flash": {"eps": flash["result"]["eps"]["verdict"], "revenue": flash["result"]["revenue"]["verdict"]} if flash else None}


async def desk(ctx) -> dict:
    today = dt.date.today().isoformat()
    rows = [r for r in await calendar_rows(ctx) if r.get("date") and r.get("symbol") and r["date"] >= today]
    metas = await ctx.db.run(ctx.db.earnings_meta_get, sorted({r["symbol"] for r in rows}))
    flashes, cons = await ctx.db.run(ctx.db.flash_since, today), await ctx.db.run(ctx.db.consensus_since, today)
    out = [row_view(r, metas.get(r["symbol"]), flashes.get((r["symbol"], r["date"])), cons.get((r["symbol"], r["date"]), [])) for r in rows]
    return {"items": out, "sec_contact": contact_ok(ctx), "base_rate": BASE_RATE, "asof": time.time(), "source": "nasdaq",
            "note": "Times: actual = SEC acceptance; announced = named before the fact; historical = median of the company's last results filings. Companies of medium or high "
                    "importance get their history and consensus snapshot in the background; open any other row to load it."}


def valid(symbol: str, day: str) -> bool:
    return bool(SYMBOL_RE.match(symbol or "") and DAY_RE.match(day or ""))


async def term(ctx, symbol: str, day: str) -> dict:
    """Everything about one report: times, call, documents, consensus snapshot, flash. Loads the company's history on demand."""
    metas = await ctx.db.run(ctx.db.earnings_meta_get, [symbol])
    meta = metas.get(symbol)
    if contact_ok(ctx) and (not meta or time.time() - (meta.get("updated") or 0) > 3600):
        try:
            meta = await refresh_meta(ctx, symbol, meta)
        except ConnectorError as e:
            if not meta:
                return {"error": str(e), "sec_contact": True}
    flash = await ctx.db.run(ctx.db.flash_get, symbol, day)
    cons = await ctx.db.run(ctx.db.consensus_get, symbol, day)
    yahoo = next((c for c in cons if c.get("source") == "yahoo"), None)
    filings = term_filings(meta or {}, day)
    timing = (flash or {}).get("timing")
    return {"symbol": symbol, "day": day, "sec_contact": contact_ok(ctx), "covered": (meta or {}).get("covered"), "cover_note": (meta or {}).get("reason"), "name": (meta or {}).get("name"),
            "release": release_time(day, meta, flash, timing, yahoo), "typical": typical_time((meta or {}).get("results") or [], day), "call": call_details(day, meta, flash, yahoo),
            "documents": {"results": filings["results"], "exhibit_url": (flash or {}).get("exhibit_url"), "quarterly": filings["quarterly"], "foreign": filings["foreign"]},
            "consensus": cons, "flash": flash, "files": list_files(ctx, symbol, day), "base_rate": BASE_RATE,
            "ai_available": bool(ctx.settings.get("ai.provider"))}


async def collect_now(ctx, symbol: str, day: str) -> dict:
    """Read a report on request (also an old one). Marked late, so no latency is claimed for it."""
    t = await term(ctx, symbol, day)
    if t.get("error"):
        return t
    filing = t["documents"]["results"]
    if not filing:
        return {"error": "No results 8-K within three days of this date." if t.get("covered") == "yes" else (t.get("cover_note") or NOT_COVERED)}
    metas = await ctx.db.run(ctx.db.earnings_meta_get, [symbol])
    row = {"symbol": symbol, "date": day, "name": t.get("name")}
    return await collect_flash(ctx, row, filing, metas[symbol]["cik"], late=True)


def _folder(ctx, symbol: str, day: str):
    return ctx.data_dir / "earnings" / symbol / day


def list_files(ctx, symbol: str, day: str) -> list[dict]:
    folder = _folder(ctx, symbol, day)
    if not folder.is_dir():
        return []
    return [{"name": p.name, "bytes": p.stat().st_size, "path": str(p)} for p in sorted(folder.iterdir()) if p.is_file()]


async def save(ctx, symbol: str, day: str, doc: str, fmt: str) -> dict:
    """Store a report locally. The address always comes from SEC's own filing list, never from the browser. Only the data
    folder is written, and these files stay out of the repository."""
    if doc not in ("release", "quarterly") or fmt not in ("html", "text"):
        return {"error": "unknown document or format"}
    t = await term(ctx, symbol, day)
    if t.get("error"):
        return t
    docs = t["documents"]
    sec = _sec(ctx)
    url, name = None, doc
    if doc == "release":
        url = docs.get("exhibit_url")
        if not url and docs.get("results"):
            metas = await ctx.db.run(ctx.db.earnings_meta_get, [symbol])
            found = exhibit_of(await sec.filing_documents(metas[symbol]["cik"], docs["results"]["accession"]))
            url = (found or {}).get("url") or docs["results"].get("url")
        name = "press_release"
    elif docs.get("quarterly"):
        url = docs["quarterly"].get("url")
        name = docs["quarterly"]["form"].replace("/", "-")
    if not url:
        return {"error": "That document is not on EDGAR (yet)."}
    raw = await sec.document(url)
    folder = _folder(ctx, symbol, day)
    folder.mkdir(parents=True, exist_ok=True)
    if fmt == "text":
        path = folder / f"{name}.txt"
        text = await asyncio.to_thread(ep.plain_text, decode(raw))
        path.write_text(f"Source: {url}\n\n{text}", encoding="utf-8")
    else:
        path = folder / f"{name}.html"
        path.write_bytes(raw)
    return {"path": str(path), "bytes": path.stat().st_size, "source": url, "files": list_files(ctx, symbol, day)}


async def flash_list(ctx, limit: int = 100) -> dict:
    return {"items": await ctx.db.run(ctx.db.flash_list, limit), "base_rate": BASE_RATE, "sec_contact": contact_ok(ctx), "asof": time.time(),
            "note": "Read from SEC filings by rules. Hit or miss only where the release's figure sits on the basis of a consensus frozen before the report; otherwise 'basis unclear'. "
                    "Latency = SEC acceptance to display; the press wire is usually earlier than SEC."}


async def annotate_timeline(ctx, items: list[dict]) -> None:
    """Give earnings on the timeline their best known time, from what the background job stored (no network)."""
    earn = [i for i in items if i.get("kind") == "earnings"]
    metas = await ctx.db.run(ctx.db.earnings_meta_get, sorted({i["tag"] for i in earn}))
    first = min((i["day"] for i in earn), default="")
    flashes, cons = await ctx.db.run(ctx.db.flash_since, first), await ctx.db.run(ctx.db.consensus_since, first)
    for i in earn:
        m = metas.get(i["tag"])
        if not m:
            continue
        rel = release_time(i["day"], m, flashes.get((i["tag"], i["day"])), None, next((c for c in cons.get((i["tag"], i["day"]), []) if c.get("source") == "yahoo"), None))
        if rel.get("ts"):
            i["ts"] = rel["ts"]
            i["time_kind"] = rel["kind"]
            i["detail"] = " · ".join(x for x in (f"time: {rel['kind']}", i.get("detail")) if x)


async def ai_reading(ctx, symbol: str, day: str) -> dict:
    """Optional, on request only, with the user's own key: a second reading of the release. Every number must come with a
    word-for-word quote; whatever fails the check is dropped. The rule-based flash works without this."""
    from ..ai import assist
    flash = await ctx.db.run(ctx.db.flash_get, symbol, day)
    if not flash or not flash.get("exhibit_url"):
        return {"error": "Collect the report first."}
    html = decode(await _sec(ctx).document(flash["exhibit_url"]))
    source = await asyncio.to_thread(ep.plain_text, html)
    res = await assist.complete(ctx, "earnings_flash", "Read this release.", {"release": source[:40000]})
    if res.get("error"):
        return {"error": res["error"]}
    m = re.search(r"\[.*\]", res.get("text") or "", flags=re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except ValueError:
        items = []
    kept, dropped = verify_ai(items, source)
    ai = {"items": kept, "dropped": dropped, "provider": res.get("provider"), "model": res.get("model"), "at": time.time()}
    await ctx.db.run(ctx.db.flash_put, symbol, day, flash["accession"], flash["accepted"], flash["seen"], flash["parsed"],
                     {**{k: v for k, v in flash.items() if k not in ("symbol", "day", "accession", "accepted", "seen", "parsed")}, "ai": ai})
    return ai
