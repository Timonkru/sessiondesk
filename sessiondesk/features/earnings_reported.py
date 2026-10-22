"""Earnings that came out: the relevant reports of the last trading days with EPS actual vs. consensus, the surprise,
and how the stock reacted - in one list instead of one stock page at a time.

Reaction: a report after the close moves the next session (its close vs. the report day's close); a report before the
open (or without a time) moves the report day (its close vs. the previous close). The S&P 500 over the same session is
shown beside it, so a beat on a falling market day is not read as a disappointment. EPS from Nasdaq's calendar once
Nasdaq carries the surprise (before that its EPS field holds the year-ago quarter); reports Nasdaq has not filled in
yet come from Yahoo, estimate and actual from the same source. Consensus differs a little between providers.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time


def money(text) -> float | None:
    """'$1.66' / '($0.12)' / 'N/A' -> number (pure, tested)."""
    if text is None:
        return None
    t = str(text).replace("$", "").replace(",", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    try:
        v = float(t.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def yahoo_match(hist: list[dict], day: str) -> dict | None:
    """The Yahoo earnings row of a report day (its timestamp is in New York time, so the date part is the report day),
    only once Yahoo has the reported EPS (pure, tested)."""
    for h in hist or []:
        if str(h.get("when", ""))[:10] == day and h.get("eps_reported") is not None:
            return h
    return None


def reaction(closes: list[tuple[str, float]], day: str, timing: str) -> float | None:
    """Percent move of the session that digested the report (pure, tested)."""
    days = [d for d, _ in closes]
    vals = dict(closes)
    if timing == "after close":
        after = [d for d in days if d > day]
        on = [d for d in days if d <= day]
        if not after or not on:
            return None
        return (vals[after[0]] / vals[on[-1]] - 1) * 100
    on = [d for d in days if d >= day]
    before = [d for d in days if d < day]
    if not on or not before or on[0] != day:
        return None
    return (vals[day] / vals[before[-1]] - 1) * 100


async def reported(ctx, days_back: int = 6) -> dict:
    from . import timeline
    from .deep import _earnings_dates
    conn = ctx.hub.get("nasdaq")
    yahoo = ctx.hub.get("yahoo")

    async def build():
        start = dt.date.today() - dt.timedelta(days=days_back)
        rows = await conn.earnings(start, days_back + 1)
        watch, major = {s.upper() for s in (ctx.settings.get("watchlist") or [])}, timeline.major_symbols()
        rows = [{**r, **timeline.earnings_rank(r, watch, major)} for r in rows]
        rows = [r for r in rows if r["importance"] in ("high", "medium") and r.get("date") and r["date"] <= dt.date.today().isoformat()]
        for r in rows:
            r["source"] = "Nasdaq" if money(r.get("eps_actual")) is not None else None
        # Nasdaq fills in the actual a day or two late: fresh reports get it from Yahoo (estimate and actual from the same
        # source, so the surprise is consistent)
        late = [r for r in rows if r["source"] is None][:40]
        if late:
            sem = asyncio.Semaphore(6)

            async def one(r):
                async with sem:
                    try:
                        hist = await asyncio.to_thread(_earnings_dates, r["symbol"])
                    except Exception:  # noqa: BLE001 - stays without actual
                        return
                hit = yahoo_match(hist, r["date"])
                if hit:
                    r.update({"eps_actual": hit["eps_reported"], "eps_forecast": hit["eps_estimate"], "source": "Yahoo"})
            await asyncio.gather(*(one(r) for r in late))
        rows = [r for r in rows if money(r.get("eps_actual")) is not None]
        syms = sorted({r["symbol"] for r in rows})[:150]
        closes = await yahoo.daily_series(syms + ["^GSPC"], "1mo") if syms else {}
        out = []
        for r in rows:
            act, est = money(r.get("eps_actual")), money(r.get("eps_forecast"))
            move = reaction(closes.get(r["symbol"]) or [], r["date"], r.get("timing") or "")
            mkt = reaction(closes.get("^GSPC") or [], r["date"], r.get("timing") or "")
            out.append({**r, "actual": act, "estimate": est,
                        "surprise_pct": (act - est) / abs(est) * 100 if act is not None and est not in (None, 0) else None,
                        "beat": None if act is None or est is None else act > est,
                        "move": move, "market": mkt, "excess": move - mkt if move is not None and mkt is not None else None})
        out.sort(key=lambda x: (x["date"], x.get("cap") or 0), reverse=True)
        known = [x for x in out if x["beat"] is not None]
        return {"items": out, "asof": time.time(),
                "summary": {"reported": len(out), "beat": sum(1 for x in known if x["beat"]), "with_estimate": len(known)}}
    d = await ctx.cache.get(f"earnings:reported:v2:{dt.date.today()}:{days_back}", 3600, build, disk=True)
    # importance follows the current watchlist, re-ranked after the cache
    return {**d, "note": "Reports of the last trading days that matter (your watchlist, big-index members, large caps). EPS as Nasdaq "
                         "lists it (adjusted), for reports Nasdaq has not filled in yet as Yahoo lists it (column Source); reaction = the session that digested the report, next to the S&P 500 over the same "
                         "session. A beat that falls is usually guidance or revenue - open the stock's Earnings tab for the detail."}
