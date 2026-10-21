"""Central bank monitor: Fed, ECB, Bank of England, Bank of Japan - policy rate, the next decision with a countdown,
the last decision and how the currency and the stock index moved that day, and what the market prices.

Meeting schedules are read from each bank's own page (parsed, cached for a day) - nothing is typed in by hand. What
the market prices: for the Fed from fed funds futures (the Macro page's path), for the others from the gap between the
2-year yield and the policy rate (a rough gauge that contains a term premium).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import re
import time

UA = {"User-Agent": "Mozilla/5.0 (SessionDesk; +https://github.com/Timonkru/sessiondesk)"}
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                           "october", "november", "december"])}
BANKS = {
    "fed": dict(name="Federal Reserve (FOMC)", ccy="USD", url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                rates="United States", fx=("DX-Y.NYB", "US dollar index"), index=("^GSPC", "S&P 500")),
    "ecb": dict(name="European Central Bank", ccy="EUR", url="https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
                rates="Euro area (AAA)", fx=("EURUSD=X", "EUR/USD"), index=("^STOXX50E", "Euro Stoxx 50")),
    "boe": dict(name="Bank of England (MPC)", ccy="GBP", url="https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
                rates="United Kingdom", fx=("GBPUSD=X", "GBP/USD"), index=("^FTSE", "FTSE 100")),
    "boj": dict(name="Bank of Japan", ccy="JPY", url="https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
                rates="Japan", fx=("JPY=X", "USD/JPY"), index=("^N225", "Nikkei 225")),
}


def _text(html: str) -> str:
    t = re.sub(r"<[^>]+>", " | ", html).replace("&nbsp;", " ")
    t = re.sub(r"(\s*\|\s*)+", " | ", t)
    return re.sub(r"\s+", " ", t)


def parse_fed(html: str) -> list[str]:
    """Decision days (the second day of each FOMC meeting) for every year on the page (pure, tested)."""
    t = _text(html)
    out = []
    for m in re.finditer(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|$)", t, re.S):
        year = int(m.group(1))
        for mm in re.finditer(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
                              r"(?:/(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))?"
                              r" (?:\| )?(\d{1,2})-(\d{1,2})\b", m.group(2)):
            month = mm.group(2) or mm.group(1)
            mon = MONTHS.get(month.lower()) or next(v for k, v in MONTHS.items() if k.startswith(month.lower()[:3]))
            try:
                out.append(dt.date(year, mon, int(mm.group(4))).isoformat())
            except ValueError:
                continue
    return dedupe(sorted(set(out)))


def dedupe(days: list[str], gap: int = 4) -> list[str]:
    """One date per meeting: a tentative and a confirmed listing a day apart count once, the later date wins (pure)."""
    out: list[str] = []
    for d in days:
        if out and (dt.date.fromisoformat(d) - dt.date.fromisoformat(out[-1])).days < gap:
            out[-1] = d
        else:
            out.append(d)
    return out


def parse_ecb(html: str) -> list[str]:
    """Monetary policy decision days (the day with the press conference) (pure, tested)."""
    t = _text(html)
    out = set()
    for m in re.finditer(r"(\d{2})/(\d{2})/(\d{4}) \| Governing Council of the ECB: monetary policy meeting[^|]*press conference", t):
        out.add(dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat())
    return sorted(out)


def parse_boe(html: str) -> tuple[list[str], float | None]:
    """Announcement days per confirmed year, and the current Bank Rate (pure, tested)."""
    t = _text(html)
    out = []
    for m in re.finditer(r"(\d{4}) confirmed dates(.*?)(?=\d{4} confirmed dates|Monetary Policy Committee Reports|$)", t, re.S):
        year = int(m.group(1))
        for d in re.finditer(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday) (\d{1,2}) (January|February|March|April|May|June|July|August|"
                             r"September|October|November|December)", m.group(2)):
            out.append(dt.date(year, MONTHS[d.group(2).lower()], int(d.group(1))).isoformat())
    rate = re.search(r"Current Bank Rate \| ([\d.]+)%", t)
    return sorted(set(out)), float(rate.group(1)) if rate else None


def parse_boj(html: str) -> list[str]:
    """Decision days (the second day of each Monetary Policy Meeting) from the yearly tables (pure, tested)."""
    t = _text(html)
    out = []
    abbr = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "June": 6, "Jun": 6, "July": 7, "Jul": 7, "Aug": 8, "Sept": 9,
            "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    for tbl in re.finditer(r"Table : (\d{4}) (?:\| )?Date of MPM(.*?)(?=Table : \d{4}|$)", t, re.S):
        year = int(tbl.group(1))
        for m in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec)\.? (\d{1,2}) \(\w+\.?\), (\d{1,2}) \(\w+\.?\)", tbl.group(2)):
            try:
                out.append(dt.date(year, abbr[m.group(1)], int(m.group(3))).isoformat())
            except (KeyError, ValueError):
                continue
    return sorted(set(out))


def day_move(closes: list[tuple[str, float]], day: str) -> float | None:
    """Close-to-close move of the decision day in percent; if the series has no point on that date (FX series are
    sometimes stamped a day off) the next point within three days is used (pure, tested)."""
    days = [d for d, _ in closes]
    limit = (dt.date.fromisoformat(day) + dt.timedelta(days=3)).isoformat()
    i = next((k for k, d in enumerate(days) if day <= d <= limit), None)
    if i is None or i == 0 or not closes[i - 1][1]:
        return None
    return (closes[i][1] / closes[i - 1][1] - 1) * 100


def parse_ecb_last(html: str) -> str | None:
    """The latest monetary policy press conference named on the ECB calendar page (pure, tested)."""
    m = re.search(r"Latest monetary policy press conference \| (\d{1,2}) (January|February|March|April|May|June|July|August|September|"
                  r"October|November|December) (\d{4})", _text(html))
    return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat() if m else None


async def schedules(ctx) -> dict:
    async def build():
        async def one(key):
            r = await ctx.http.get(BANKS[key]["url"], headers=UA, timeout=30, follow_redirects=True)
            if r.status_code != 200:
                return key, {"dates": [], "error": f"HTTP {r.status_code}"}
            if key == "fed":
                return key, {"dates": parse_fed(r.text)}
            if key == "ecb":
                last = parse_ecb_last(r.text)
                return key, {"dates": sorted(set(parse_ecb(r.text) + ([last] if last else [])))}
            if key == "boe":
                d, rate = parse_boe(r.text)
                return key, {"dates": d, "rate": rate}
            return key, {"dates": parse_boj(r.text)}
        res = await asyncio.gather(*(one(k) for k in BANKS), return_exceptions=True)
        return {k: v for k, v in (r for r in res if not isinstance(r, Exception))}
    return await ctx.cache.get("cb:schedules:v2", 24 * 3600, build, disk=True)


async def monitor(ctx) -> dict:
    from .macro import fed_path
    from .rates_world import world
    yahoo = ctx.hub.get("yahoo")
    sched, w, fp = await asyncio.gather(schedules(ctx), world(ctx), fed_path(ctx), return_exceptions=True)
    sched = {} if isinstance(sched, Exception) else sched
    w = {} if isinstance(w, Exception) else w
    fp = {} if isinstance(fp, Exception) else fp
    rates = {r["country"]: r for r in w.get("rows", [])}
    syms = [s for b in BANKS.values() for s in (b["fx"][0], b["index"][0])]
    closes = await yahoo.daily_series(syms, "1y")
    today = dt.date.today().isoformat()
    now = time.time()
    rows = []
    for key, b in BANKS.items():
        s = sched.get(key) or {}
        dates = s.get("dates") or []
        nxt = [d for d in dates if d >= today]
        past = [d for d in dates if d < today]
        last = past[-1] if past else None
        r = rates.get(b["rates"]) or {}
        policy = s.get("rate") if key == "boe" and s.get("rate") is not None else r.get("policy")
        rows.append({"key": key, "name": b["name"], "ccy": b["ccy"], "policy": policy, "url": b["url"],
                     "next": nxt[0] if nxt else None, "days_to_next": (dt.date.fromisoformat(nxt[0]) - dt.date.today()).days if nxt else None,
                     "upcoming": nxt[1:5], "last": last,
                     "last_reaction": {"fx": (b["fx"][1], day_move(closes.get(b["fx"][0]) or [], last) if last else None),
                                       "index": (b["index"][1], day_move(closes.get(b["index"][0]) or [], last) if last else None)},
                     "gauge_bp": r.get("gauge_bp"), "gauge_tenor": r.get("gauge_tenor"), "y2": r.get("2y"),
                     "schedule_error": s.get("error"), "meetings_known": len(dates)})
    fed_next = None
    if fp and not fp.get("error"):
        fed_next = {k: fp.get(k) for k in ("rows", "note", "current") if k in fp}
    return {"banks": rows, "fed_path": fed_next, "asof": now,
            "note": "Meeting dates read from each central bank's own calendar page (refreshed daily). Policy rate: Fed effective "
                    "funds rate, ECB deposit rate, BoE Bank Rate; the BoJ rate has no free machine-readable source. 'Priced' = "
                    "2-year yield minus the policy rate (a rough gauge with a term premium in it); the Fed path from futures is "
                    "on Macro > Rates. Reaction = close-to-close move on the decision day."}
