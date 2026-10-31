"""Earnings nowcast: for companies with a report coming up, what the free company proxies (features/proxies.py) say
about the fiscal quarter being reported, next to the consensus and the company's own beat history.

Per company:
  fiscal quarters   from the company's own XBRL filings at the SEC (10-Q/10-K revenue, start and end of every fiscal
                    quarter; Q4 = fiscal year minus Q1-Q3). The quarter to be reported is the one after the last filed
                    quarter, with the length of its year-ago counterpart - so 52/53-week years and odd fiscal years line up.
  proxy YoY         mean of the proxy over the quarter (to date, when it is still running) against the same days one
                    year earlier; for App Store ranks the change in rank (positive = climbed).
  proxy z           that YoY against the proxy's own YoY in past quarters (median and MAD, at least 8 quarters).
  nowcast           only with at least 8 past quarters of proxy YoY and revenue YoY: least squares revenue YoY = a + b x
                    proxy YoY, for the proxy fixed in the mapping file ("primary") - never chosen by best fit.
  gap               nowcast minus the consensus' implied growth, also in residual standard deviations of the regression.
  beat base rate    share of past quarters the reported EPS beat the consensus (Yahoo), revenue beats when an FMP or
                    Finnhub key gives the revenue estimate history.
None of this is validated: no out-of-sample test of these proxies against surprises or price reactions has been run.
The page says so on every row and makes no buy or sell statement.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import statistics
import time

from . import proxies

MIN_QUARTERS = 8
STALE_AFTER_DAYS = 75
LOOKAHEAD_DAYS = 14
MAX_INDEX_ROWS = 25
REVENUE_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                    "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"]
VALIDATION = {"status": "unvalidated",
              "text": "Unvalidated. An out-of-sample test of these free proxies against earnings surprises is still running; "
                      "until its verdict is shown here, read every number on this page as a description, not as a signal."}
ALERT_DEFAULTS = {"enabled": False, "gap_sd": 2.0, "min_z": 2.0}


# ------------------------------------------------------------------ fiscal quarters (pure, tested)
def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def sec_quarters(facts: dict) -> list[dict]:
    """XBRL company facts -> fiscal quarters oldest first: [{start, end, revenue, fy, fp}]. Per period the first
    revenue concept of REVENUE_CONCEPTS that has it, the latest filing wins (restatements); Q4 = fiscal year minus the
    three quarters inside it."""
    gaap = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    periods: dict[tuple[str, str], dict] = {}
    for rank, concept in enumerate(REVENUE_CONCEPTS):
        for f in ((gaap.get(concept) or {}).get("units") or {}).get("USD") or []:
            if not f.get("start") or not f.get("end") or f.get("val") is None:
                continue
            key = (f["start"], f["end"])
            cur = periods.get(key)
            cand = {"start": f["start"], "end": f["end"], "value": float(f["val"]), "rank": rank, "filed": f.get("filed") or "",
                    "fy": f.get("fy"), "fp": f.get("fp")}
            if cur is None or rank < cur["rank"] or (rank == cur["rank"] and cand["filed"] > cur["filed"]):
                periods[key] = cand
    quarters, years = {}, []
    for (s, e), p in periods.items():
        days = (_d(e) - _d(s)).days
        if 80 <= days <= 100:
            quarters[e] = {"start": s, "end": e, "revenue": p["value"], "fy": p["fy"], "fp": p["fp"]}
        elif 350 <= days <= 380:
            years.append(p)
    for y in years:
        inside = [q for q in quarters.values() if q["start"] >= y["start"] and q["end"] <= y["end"]]
        if len(inside) == 3:
            last = max(q["end"] for q in inside)
            start = (_d(last) + dt.timedelta(days=1)).isoformat()
            if y["end"] not in quarters and 80 <= (_d(y["end"]) - _d(start)).days <= 100:
                quarters[y["end"]] = {"start": start, "end": y["end"], "revenue": y["value"] - sum(q["revenue"] for q in inside),
                                      "fy": y["fy"], "fp": "Q4", "derived": True}
    return [quarters[e] for e in sorted(quarters)]


def year_ago(quarters: list[dict], q: dict) -> dict | None:
    """The quarter ending 364 +/- 10 days before q (pure, tested)."""
    target = _d(q["end"]) - dt.timedelta(days=364)
    best = min(quarters, key=lambda x: abs((_d(x["end"]) - target).days), default=None)
    return best if best and abs((_d(best["end"]) - target).days) <= 10 and best["end"] != q["end"] else None


def next_quarter(quarters: list[dict]) -> dict | None:
    """The fiscal quarter after the last filed one, shaped like its year-ago counterpart (pure, tested)."""
    if not quarters:
        return None
    last = quarters[-1]
    start = _d(last["end"]) + dt.timedelta(days=1)
    ago = next((q for q in quarters if abs((_d(q["start"]) - (start - dt.timedelta(days=364))).days) <= 10), None)
    length = (_d(ago["end"]) - _d(ago["start"])).days if ago else 90
    return {"start": start.isoformat(), "end": (start + dt.timedelta(days=length)).isoformat(), "revenue": None, "next": True,
            "year_ago": ago}


# ------------------------------------------------------------------ proxy numbers (pure, tested)
def window_mean(points: list[tuple[str, float]], start: str, end: str) -> tuple[float | None, int]:
    vals = [v for d, v in points if start <= d <= end]
    return (sum(vals) / len(vals) if vals else None), len(vals)


def proxy_change(points: list[tuple[str, float]], start: str, end: str, lower_better: bool = False,
                 min_coverage: float = 0.5, monthly: bool = False) -> dict | None:
    """Proxy over [start, end] against the same days one year (364 days) earlier: YoY in % (ranks: places climbed).
    Needs data on at least min_coverage of the days in both windows (monthly series: at least one month each)."""
    s, e = _d(start), _d(end)
    days = (e - s).days + 1
    ps, pe = (s - dt.timedelta(days=364)).isoformat(), (e - dt.timedelta(days=364)).isoformat()
    now_v, n_now = window_mean(points, start, end)
    ago_v, n_ago = window_mean(points, ps, pe)
    need = 1 if monthly else max(1, int(days * min_coverage))
    if now_v is None or ago_v is None or n_now < need or n_ago < need:
        return None
    if lower_better:
        return {"value": ago_v - now_v, "now": now_v, "ago": ago_v, "days": n_now, "unit": "places"}
    if monthly:
        return {"value": now_v - ago_v, "now": now_v, "ago": ago_v, "days": n_now, "unit": "USD/month"}
    if ago_v <= 0:
        return None
    return {"value": (now_v / ago_v - 1) * 100, "now": now_v, "ago": ago_v, "days": n_now, "unit": "%"}


def small_z(history: list[float], x: float, min_n: int = MIN_QUARTERS) -> float | None:
    """Robust z (median, MAD) for short histories such as quarterly YoY values."""
    if len(history) < min_n:
        return None
    med = statistics.median(history)
    mad = statistics.median(abs(h - med) for h in history) * 1.4826
    return (x - med) / mad if mad else None


def ols(xs: list[float], ys: list[float]) -> dict | None:
    """y = a + b x by least squares, with r, residual SD and the t-stat of b (pure, tested)."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    sse = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    sd = math.sqrt(sse / (n - 2)) if n > 2 else None
    se_b = sd / math.sqrt(sxx) if sd else None
    return {"a": a, "b": b, "n": n, "r": (b * math.sqrt(sxx / syy)) if syy else None, "resid_sd": sd,
            "t_b": (b / se_b) if se_b else None}


def beat_rate(rows: list[dict], est: str, act: str) -> dict | None:
    done = [r for r in rows if r.get(est) is not None and r.get(act) is not None]
    if not done:
        return None
    beats = sum(r[act] > r[est] for r in done)
    p = beats / len(done)
    return {"rate": p, "n": len(done), "beats": beats, "se": math.sqrt(p * (1 - p) / len(done))}


def analyse(quarters: list[dict], series: dict[str, list[tuple[str, float]]], primary: str | None,
            today: dt.date | None = None) -> dict:
    """Proxy YoY, z and the regression nowcast for the quarter after the last filed one (pure, tested).
    series: proxy key -> points. Returns {"quarter", "proxies": {key: {...}}, "nowcast"}."""
    today = today or dt.date.today()
    target = next_quarter(quarters)
    if not target:
        return {"quarter": None, "proxies": {}, "nowcast": None}
    end_to_date = min(target["end"], today.isoformat())
    running = end_to_date < target["end"]
    rev_yoy = {}
    for q in quarters:
        ago = year_ago(quarters, q)
        if ago and ago["revenue"]:
            rev_yoy[q["end"]] = (q["revenue"] / ago["revenue"] - 1) * 100
    out = {}
    for key, pts in series.items():
        if not pts:
            continue
        lower = key in proxies.LOWER_IS_BETTER
        monthly = key == "insiders"
        now = proxy_change(pts, target["start"], end_to_date, lower, monthly=monthly) if target["start"] <= end_to_date else None
        hist = []
        for q in quarters:
            c = proxy_change(pts, q["start"], q["end"], lower, monthly=monthly)
            if c:
                hist.append((q["end"], c["value"]))
        row = {"label": proxies.PROXIES.get(key, key), "now": now, "history_n": len(hist),
               "z": small_z([v for _, v in hist], now["value"]) if now else None, "first": pts[0][0], "last": pts[-1][0]}
        pairs = [(v, rev_yoy[e]) for e, v in hist if e in rev_yoy]
        if key != "insiders" and len(pairs) >= MIN_QUARTERS:
            row["fit"] = ols([p[0] for p in pairs], [p[1] for p in pairs])
        row["pairs"] = len(pairs)
        out[key] = row
    nowcast = None
    p = out.get(primary or "")
    if p and p.get("fit") and p.get("now"):
        f = p["fit"]
        g = f["a"] + f["b"] * p["now"]["value"]
        base = (target.get("year_ago") or {}).get("revenue")
        nowcast = {"proxy": primary, "growth": g, "revenue": base * (1 + g / 100) if base else None, "n": f["n"], "r": f["r"],
                   "resid_sd": f["resid_sd"], "t_b": f["t_b"], "partial": running}
    elif p:
        nowcast = {"proxy": primary, "missing": f"needs {MIN_QUARTERS} quarters with proxy and revenue, has {p.get('pairs', 0)}"}
    # a 10-Q is due 40-45 days after the quarter; when the quarter after the last filed one ended long before that,
    # the SEC data stop early (other revenue tag, filing gap) and this is not the quarter the company reports next
    stale = (_d(target["end"]) + dt.timedelta(days=STALE_AFTER_DAYS)) < today
    if stale:
        nowcast = None
    return {"quarter": {"start": target["start"], "end": target["end"], "to_date": end_to_date, "running": running, "stale": stale,
                        "last_filed": quarters[-1]["end"],
                        "year_ago_revenue": (target.get("year_ago") or {}).get("revenue"),
                        "year_ago_end": (target.get("year_ago") or {}).get("end")},
            "proxies": out, "nowcast": nowcast, "revenue_quarters": len(quarters)}


def consensus_gap(nowcast: dict | None, consensus: float | None, year_ago_revenue: float | None) -> dict | None:
    """Nowcast growth minus the growth implied by the consensus, in pp and in residual SDs (pure, tested)."""
    if not nowcast or nowcast.get("growth") is None or not consensus or not year_ago_revenue:
        return None
    implied = (consensus / year_ago_revenue - 1) * 100
    gap = nowcast["growth"] - implied
    sd = nowcast.get("resid_sd")
    return {"implied_growth": implied, "gap_pp": gap, "gap_sd": gap / sd if sd else None}


# ------------------------------------------------------------------ gathering
async def _facts(ctx, symbol: str) -> dict:
    sec = ctx.hub.get("sec")
    if not sec or "." in symbol:
        return {"quarters": []}

    async def build():
        return {"quarters": sec_quarters(await sec.company_facts(symbol))}
    return await ctx.cache.get(f"nowcast:sec:{symbol}", 24 * 3600, build, disk=True)


def _yahoo_consensus(street: dict) -> dict | None:
    row = next((r for r in street.get("revenue_estimates") or [] if r.get("period") == "0q"), None)
    if not row or not row.get("avg"):
        return None
    return {"revenue": row["avg"], "year_ago": row.get("yearAgoRevenue"), "analysts": row.get("numberOfAnalysts"), "source": "Yahoo (free)"}


async def _keyed_history(ctx, symbol: str) -> dict:
    """Consensus history from the first active keyed source (FMP, then Finnhub)."""
    conns = [c for c in (ctx.hub.get("fmp"), ctx.hub.get("finnhub")) if c and c.active()]
    if not conns:
        return {"status": "key needed", "rows": []}
    for c in conns:
        async def build(c=c):
            return {"rows": await c.earnings_history(symbol)}
        res = await ctx.cache.get(f"nowcast:hist:{c.id}:{symbol}", 12 * 3600, build, disk=True)
        if res.get("rows"):
            return {"status": "ok", "source": c.name, "rows": res["rows"]}
        if res.get("error"):
            ctx.hub.mark(c.id, f"earnings history: {res['error']}")
    return {"status": "no history", "rows": []}


async def company_row(ctx, symbol: str, mapping: dict, report: dict | None) -> dict:
    from .deep import earnings as deep_earnings, street as deep_street
    entry = mapping.get(symbol) or {}
    ids = proxies.series_ids(symbol, entry) if entry else {}
    facts, street, earn, keyed = await asyncio.gather(_facts(ctx, symbol), deep_street(ctx, symbol), deep_earnings(ctx, symbol),
                                                      _keyed_history(ctx, symbol), return_exceptions=True)
    facts = facts if isinstance(facts, dict) else {"error": str(facts)}
    street = street if isinstance(street, dict) else {}
    earn = earn if isinstance(earn, dict) else {}
    keyed = keyed if isinstance(keyed, dict) else {"status": "error", "rows": []}
    series = {k: await ctx.db.run(ctx.db.observations, sid, 5000) for k, sid in ids.items()}
    quarters = facts.get("quarters") or []
    res = analyse(quarters, series, entry.get("primary"))
    cons = None
    keyed_rows = keyed.get("rows") or []
    if keyed_rows:
        upcoming = [r for r in keyed_rows if r.get("revenue_actual") is None and r.get("revenue_estimate")]
        if upcoming:
            cons = {"revenue": upcoming[0]["revenue_estimate"], "source": keyed.get("source"), "date": upcoming[0]["date"]}
    cons = cons or _yahoo_consensus(street)
    q = res.get("quarter") or {}
    if cons and cons.get("year_ago") and q.get("year_ago_revenue"):
        cons["matches_quarter"] = abs(cons["year_ago"] / q["year_ago_revenue"] - 1) < 0.03
    eps_rows = [{"eps_estimate": r.get("eps_estimate"), "eps_actual": r.get("eps_reported")} for r in earn.get("history") or []]
    up = earn.get("upcoming") or {}
    when = (report or {}).get("date") or (str(up.get("when"))[:10] if up.get("when") else None)
    if q.get("stale") and cons:
        cons["matches_quarter"] = False
    gap = consensus_gap(res.get("nowcast"), (cons or {}).get("revenue") if (cons or {}).get("matches_quarter", True) else None,
                        q.get("year_ago_revenue"))
    return {"symbol": symbol, "name": (report or {}).get("name") or "", "report_date": when, "timing": (report or {}).get("timing"),
            "why": "mapped" if entry else (report or {}).get("why") or "watchlist", "mapped": bool(entry), "primary": entry.get("primary"),
            "series": ids, "quarter": res.get("quarter"), "revenue_quarters": len(quarters), "sec_error": facts.get("error"),
            "proxies": res.get("proxies"), "nowcast": res.get("nowcast"), "consensus": cons, "gap": gap,
            "beat_eps": beat_rate(eps_rows, "eps_estimate", "eps_actual"),
            "beat_revenue": beat_rate(keyed_rows, "revenue_estimate", "revenue_actual"),
            "consensus_history": {"status": keyed.get("status"), "source": keyed.get("source"), "quarters": len(keyed_rows)},
            "validation": VALIDATION["status"]}


async def _calendar(ctx) -> list[dict]:
    from . import timeline
    today = dt.date.today()

    async def build():
        res = await ctx.hub.first("earnings", "earnings", today, LOOKAHEAD_DAYS)
        return {"items": res.get("data") or [], "error_detail": res.get("error")}
    cal = await ctx.cache.get(f"nowcast:cal:{today}", 6 * 3600, build, disk=True)
    watch = {s.upper() for s in (ctx.settings.get("watchlist") or [])}
    major = timeline.major_symbols()
    rows = [{**r, **timeline.earnings_rank(r, watch, major)} for r in cal.get("items") or []]
    return [r for r in rows if r.get("importance") in ("high", "medium") and r.get("date")]


def validation(mapping_file: dict) -> dict:
    """The verdict of the out-of-sample test goes into the mapping file ("validation": {"status", "text"}) once it exists."""
    v = mapping_file.get("validation")
    if isinstance(v, dict) and v.get("text"):
        return {"status": str(v.get("status") or "unvalidated"), "text": str(v["text"])}
    return dict(VALIDATION)


async def page(ctx) -> dict:
    async def build():
        mfile = proxies.load_map(ctx)
        mapping = mfile.get("companies") or {}
        cal = await _calendar(ctx)
        by_sym = {}
        for r in sorted(cal, key=lambda r: r["date"]):
            by_sym.setdefault(r["symbol"].upper(), r)
        watch = [s.upper() for s in ctx.settings.get("watchlist") or [] if not s.startswith("^") and "=" not in s]
        base = list(dict.fromkeys(list(mapping) + watch))
        index = [s for s in by_sym if s not in base][:MAX_INDEX_ROWS]
        sem = asyncio.Semaphore(4)

        async def one(sym):
            async with sem:
                try:
                    return await company_row(ctx, sym, mapping, by_sym.get(sym))
                except Exception as exc:                # noqa: BLE001 - one company must not break the page
                    return {"symbol": sym, "error": f"{type(exc).__name__}: {exc}", "series": {}, "proxies": {}}
        rows = await asyncio.gather(*(one(s) for s in base + index))
        rows = sorted(rows, key=lambda r: (r.get("report_date") or "9999", r["symbol"]))
        keys = {k: bool(ctx.hub.get(k) and ctx.hub.get(k).active()) for k in ("fmp", "finnhub", "quiver")}
        sec = ctx.hub.get("sec")
        return {"rows": rows, "validation": validation(mfile), "mapping_file": str(proxies.path(ctx)), "mapping_error": mfile.get("error"),
                "keys": keys, "sec_contact": bool(sec and sec.option("contact_email")), "asof": time.time(),
                "lookahead_days": LOOKAHEAD_DAYS, "alert": alert_config(ctx.settings), "proxy_errors": ctx.extras.get("proxy_errors") or {},
                "note": "Fiscal quarters come from the company's own SEC filings (US filers only). Proxy YoY = proxy mean in the "
                        "quarter (to date) vs the same days a year earlier; z = against the proxy's own past quarterly YoY. The "
                        f"nowcast needs {MIN_QUARTERS} past quarters and uses the proxy fixed in the mapping file. Consensus: "
                        "FMP/Finnhub with a key, otherwise Yahoo's current-quarter revenue estimate. Beat base rate = share of "
                        "past quarters above the consensus."}
    return await ctx.cache.get("nowcast:page", 3 * 3600, build)


# ------------------------------------------------------------------ alert (off by default)
def alert_config(settings) -> dict:
    out = {**ALERT_DEFAULTS, **(settings.get("nowcast_alert") or {})}
    out["gap_sd"] = max(0.5, float(out["gap_sd"]))
    out["min_z"] = max(0.0, float(out["min_z"]))
    out["enabled"] = bool(out["enabled"])
    return out


def diverging(rows: list[dict], cfg: dict) -> list[dict]:
    """Rows where the nowcast and the consensus are far apart: |gap| >= gap_sd residual SDs and the primary proxy's z
    at least min_z in the same direction (pure, tested)."""
    out = []
    for r in rows:
        gap = r.get("gap") or {}
        p = (r.get("proxies") or {}).get(r.get("primary") or "") or {}
        if gap.get("gap_sd") is None or p.get("z") is None:
            continue
        if abs(gap["gap_sd"]) >= cfg["gap_sd"] and abs(p["z"]) >= cfg["min_z"] and (gap["gap_sd"] > 0) == (p["z"] > 0):
            out.append(r)
    return out


def _state_path(ctx):
    return ctx.data_dir / "nowcast_alert_state.json"


async def run_check(ctx) -> list[dict]:
    """Background check: one notice per company and fiscal quarter, only when the user switched the alert on."""
    cfg = alert_config(ctx.settings)
    if not cfg["enabled"]:
        return []
    data = await page(ctx)
    try:
        sent = json.loads(_state_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = {}
    out = []
    for r in diverging(data.get("rows") or [], cfg):
        key = f"{r['symbol']}:{(r.get('quarter') or {}).get('end')}"
        if key in sent:
            continue
        g = r["gap"]
        now = time.time()
        alert = {"id": f"nowcast:{key}", "ts": now, "kind": "nowcast", "symbol": r["symbol"],
                 "title": f"{r['symbol']}: proxy nowcast and consensus diverge ({g['gap_sd']:+.1f} SD, unvalidated)",
                 "body": f"Proxy nowcast revenue growth {r['nowcast']['growth']:+.1f} % vs consensus-implied {g['implied_growth']:+.1f} % "
                         f"({proxies.PROXIES.get(r['primary'], r['primary'])}, n {r['nowcast']['n']}). Unvalidated description, not a signal.",
                 "data": {"source": "nowcast", "triggered": now, **g}}
        sent[key] = now
        if ctx.db:
            await ctx.db.run(ctx.db.add_alert, alert)
        ctx.broker.publish("price_alert", {"alert": alert})
        out.append(alert)
    try:
        _state_path(ctx).write_text(json.dumps(sent), encoding="utf-8")
    except OSError:
        pass
    return out
