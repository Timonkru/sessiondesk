"""One timeline for everything scheduled: economic releases, earnings that matter to you, forced flows and your own
session schedule. The other pages show only slices of it (Today: what concerns you now; the header: the next
high-impact release).

Earnings are filtered to what is likely to matter: your watchlist, members of the Dow 30, Nasdaq-100, DAX 40 and
Euro Stoxx 50, and anything above a market cap of 50 bn USD. The Earnings tab keeps the full list.
"""
from __future__ import annotations

import datetime as dt
import re
import time

from . import flows, universe
from .today import DEFAULT_SESSIONS, schedule_for

BIG_CAP = 50e9
MAJOR = ("dow30", "nasdaq100", "dax40", "stoxx50")


def _cap(text) -> float | None:
    if text in (None, "", "N/A"):
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(text)))
    except ValueError:
        return None


def earnings_items(rows: list[dict], watch: set[str], major: set[str]) -> list[dict]:
    out = []
    for r in rows:
        sym = (r.get("symbol") or "").upper()
        cap = _cap(r.get("market_cap"))
        why = "watchlist" if sym in watch else "index member" if sym in major else "large cap" if cap and cap >= BIG_CAP else None
        if not why:
            continue
        out.append({"day": r.get("date"), "ts": None, "kind": "earnings", "tag": sym, "title": f"{r.get('name') or sym} reports",
                    "detail": " · ".join(x for x in (r.get("timing"), f"EPS est. {r['eps_forecast']}" if r.get("eps_forecast") else "", why) if x),
                    "link": f"#/stock/{sym}", "level": "high" if sym in watch else "normal"})
    return out


async def timeline(ctx, days: int = 7) -> dict:
    now = time.time()
    today = dt.date.today()
    end = today + dt.timedelta(days=days)
    items: list[dict] = []

    cal = await ctx.extras["calendar"].events(now - 6 * 3600, now + days * 86400)
    for e in cal.get("events", []):
        if e.get("impact") not in ("high", "medium"):
            continue
        items.append({"day": dt.date.fromtimestamp(e["ts"]).isoformat(), "ts": e["ts"], "kind": "release", "tag": e.get("currency"),
                      "title": e.get("title"), "level": e.get("impact"),
                      "detail": " · ".join(x for x in (f"fcst {e['forecast']}" if e.get("forecast") else "",
                                                       f"prev {e['previous']}" if e.get("previous") else "",
                                                       f"actual {e['actual']}" if e.get("actual") else "") if x)})

    errors = {}
    earn = ctx.cache.peek(f"earnings:{days}:{today}", disk=True)
    if earn is None:
        res = await ctx.hub.first("earnings", "earnings", today, days)
        earn = {"items": res.get("data", []), "error_detail": res.get("error")}
    if earn.get("error_detail"):
        errors["earnings"] = earn["error_detail"]
    watch = {s.upper() for s in (ctx.settings.get("watchlist") or [])}
    major = {m["symbol"].upper() for u in MAJOR for m in universe.members(u)}
    items += earnings_items(earn.get("items") or [], watch, major)

    for f in flows.events_between(today, end):
        items.append({"day": f["date"], "ts": None, "kind": "flow", "tag": ", ".join(f.get("markets", [])[:2]), "title": f["name"],
                      "detail": f.get("time", ""), "level": f.get("size", "low"), "link": "#/flows"})

    sessions = ctx.settings.get("sessions") or DEFAULT_SESSIONS
    entries = ctx.settings.get("schedule") or []
    d = today
    while d <= end:
        for s in schedule_for(d, sessions, entries):
            ts = s["when"].timestamp()
            if ts < now - 1800:
                continue
            items.append({"day": d.isoformat(), "ts": ts, "kind": "session" if s.get("kind") == "session" else "setup",
                          "tag": s.get("session"), "title": s.get("label"), "detail": "", "level": "normal"})
        d += dt.timedelta(days=1)

    # all-day items (earnings, flows) lead their day; timed items follow in time order
    items.sort(key=lambda x: (x["day"] or "", 0 if x["ts"] is None else 1, x["ts"] or 0, x["kind"]))
    return {"items": items, "days": days, "asof": now, "errors": errors, "sources": cal.get("sources", []),
            "note": "Releases (high and medium impact), earnings of your watchlist, the big indices' members and large caps, "
                    "forced flows from published rules, and your own schedule (Settings → Schedule). Earnings dates come "
                    "from the free calendar and can move."}
