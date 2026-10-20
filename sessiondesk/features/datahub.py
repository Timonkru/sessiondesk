"""Data hub: the numeric series SessionDesk sees, with their history, in one local table - and early warnings when
a series moves unusually against its own past.

Sources (free, no key needed):
  - market board: daily closes of indices, futures, yields, FX, commodities, crypto, volatility, sectors (Yahoo)
  - macro: Treasury curve, inflation, labour market, credit spreads, liquidity, euro yields (FRED)
  - oil: EIA Weekly Petroleum Status Report, U.S. stocks table (current and previous week; history builds up)
  - attention: headlines per day and theme (Fed, ECB, oil, tariffs, geopolitics ...) from your own news archive

Early warning = the latest change is unusual for THIS series: robust z-score against its own last 250 changes
(median and MAD, so one old crash does not hide everything). It describes, it does not predict.
"""
from __future__ import annotations

import csv
import io
import statistics
import time

from . import assets, macro, markets
from ..connectors.base import stable_id

Z_WARN = 3.0
MIN_HISTORY = 40
EIA_URL = "https://ir.eia.gov/wpsr/table4.csv"
EIA_ROWS = {"Crude Oil": "Crude oil stocks excl. SPR", "Total Motor Gasoline": "Gasoline stocks",
            "Distillate Fuel Oil": "Distillate stocks", "Kerosene-Type Jet Fuel": "Jet fuel stocks",
            "Propane/Propylene": "Propane stocks", "SPR": "Strategic petroleum reserve"}
NEWS_THEMES = ["fed", "ecb", "boj", "us_macro", "yields", "tariffs", "geopolitics", "oil", "gold", "crypto", "china", "tech", "risk"]
RATES = {"^IRX", "^FVX", "^TNX", "^TYX"}


# ------------------------------------------------------------------ analysis (pure, tested)
def changes(points: list[tuple[str, float]], kind: str) -> list[tuple[str, float]]:
    """Per observation: percent change (prices), difference (rates, spreads, levels), the level itself (counts)."""
    if kind == "count":
        return list(points)
    out = []
    for (_, a), (d, b) in zip(points, points[1:]):
        if kind == "price":
            if a:
                out.append((d, (b / a - 1) * 100))
        else:
            out.append((d, b - a))
    return out


def robust_z(history: list[float], x: float) -> float | None:
    if len(history) < MIN_HISTORY:
        return None
    med = statistics.median(history)
    mad = statistics.median(abs(h - med) for h in history) * 1.4826
    if not mad:
        return None
    return (x - med) / mad


def assess(points: list[tuple[str, float]], kind: str) -> dict | None:
    """Latest change of a series against its own past: z, and since when nothing this large happened."""
    ch = changes(points, kind)
    if len(ch) < MIN_HISTORY + 1:
        return None
    day, x = ch[-1]
    past = [c for _, c in ch[-251:-1]]
    z = robust_z(past, x)
    if z is None:
        return None
    since = None
    for d, c in reversed(ch[:-1]):
        if (x >= 0 and c >= x) or (x < 0 and c <= x):
            since = d
            break
    return {"day": day, "change": x, "z": z, "value": points[-1][1], "largest_since": since,
            "history": len(ch) - 1, "typical": statistics.median(abs(c) for c in past)}


def describe(meta: dict, a: dict) -> str:
    unit = "%" if meta["kind"] == "price" else ""
    what = "headlines" if meta["kind"] == "count" else "move"
    size = (f"{a['change']:+.2f}{unit}" if meta["kind"] != "count" else f"{a['change']:.0f}")
    since = f"largest since {a['largest_since']}" if a.get("largest_since") else f"largest in {a['history']} observations"
    typical = f"typical {a['typical']:.2f}{unit}" if meta["kind"] != "count" else f"typical {a['typical']:.0f} per day"
    return f"{meta['name']}: {what} {size} ({a['z']:+.1f} σ against its own history; {typical}; {since})."


# ------------------------------------------------------------------ collectors
def _meta(id_, name, category, source, kind, unit=""):
    return {"id": id_, "name": name, "category": category, "source": source, "kind": kind, "unit": unit}


async def collect_markets(ctx) -> int:
    yahoo = ctx.hub.get("yahoo")
    if not yahoo:
        return 0
    groups = ctx.settings.get("overview_groups") or markets.OVERVIEW
    names = {s: (g, label) for g, items in groups for s, label in items}
    data = await yahoo.daily_series(list(names), "2y")
    for sym, pts in data.items():
        g, label = names[sym]
        kind = "rate" if sym in RATES else "price"
        await ctx.db.run(ctx.db.upsert_series, _meta(f"mkt:{sym}", label, g, "Yahoo (daily close, today live)", kind,
                                                     "%" if kind == "rate" else ""), pts)
    return len(data)


async def collect_fred(ctx) -> int:
    fred = ctx.hub.get("fred")
    if not fred or not fred.active():
        return 0
    spec = ([(f"US {t} yield", sid, "Rates", "rate") for t, sid in macro.CURVE if t in ("3m", "2y", "10y", "30y")]
            + [(n, sid, "Rates", "rate") for n, sid in macro.EXTRA_SERIES]
            + [(n, sid, "Inflation & growth", "level") for n, sid, _ in macro.GROWTH]
            + [(n, sid, "Credit & liquidity", "level") for n, sid, _ in macro.CREDIT]
            + [(f"{c} 10y yield (monthly)", sid, "Euro area", "rate") for c, sid in macro.EURO_10Y])
    n = 0
    for name, sid, cat, kind in dict(((s[1], s) for s in spec)).values():     # one entry per FRED id
        try:
            res = await fred.series(sid)
        except Exception:
            continue
        pts = [(d, v) for d, v in res.get("points", [])][-2600:]
        if pts:
            await ctx.db.run(ctx.db.upsert_series, _meta(f"fred:{sid}", name, cat, f"FRED {sid}", kind), pts)
            n += 1
    return n


def parse_eia_table(text: str) -> list[dict]:
    """EIA WPSR table 4 (U.S. stocks): first data column = this week, second = previous week."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 3:
        return []
    import datetime as dt
    head = rows[0]

    def day(s):
        return dt.datetime.strptime(s.strip(), "%m/%d/%y").strftime("%Y-%m-%d")
    out = []
    for r in rows[1:]:
        if len(r) < 3 or r[0].strip() not in EIA_ROWS:
            continue
        try:
            out.append({"name": EIA_ROWS[r[0].strip()], "points": [(day(head[2]), float(r[2])), (day(head[1]), float(r[1]))]})
        except ValueError:
            continue
    return out


async def collect_eia(ctx) -> int:
    resp = await ctx.http.get(EIA_URL, headers={"User-Agent": "SessionDesk"}, timeout=20)
    if resp.status_code != 200:
        return 0
    rows = parse_eia_table(resp.text)
    for r in rows:
        await ctx.db.run(ctx.db.upsert_series, _meta("eia:" + r["name"].lower().replace(" ", "_").replace(".", ""), r["name"] + " (mn bbl)",
                                                     "Oil (EIA weekly)", "EIA Weekly Petroleum Status Report", "level"), r["points"])
    return len(rows)


EIA_GAS_URL = "https://ir.eia.gov/ngs/wngsr.csv"


def parse_eia_gas(text: str) -> list[dict]:
    """EIA Weekly Natural Gas Storage Report (Lower 48): stocks per region for this and the previous week,
    plus the year-ago level and the 5-year average for the current week (pure, tested)."""
    import datetime as dt
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    dates = next((r for r in rows if len(r) > 4 and r[0] == "" and r[1][:2].isdigit()), None)
    if not dates:
        return []

    def day(s):
        return dt.datetime.strptime(s.strip(), "%d-%b-%y").strftime("%Y-%m-%d")

    def num(s):
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None
    cur, prev = day(dates[1]), day(dates[4])
    out = []
    for r in rows:
        name = r[0].strip() if r else ""
        if name in ("East", "Midwest", "Mountain", "Pacific", "South Central", "Total") and len(r) > 20:
            now, before = num(r[1]), num(r[4])
            if now is None or before is None:
                continue
            out.append({"region": "Lower 48 total" if name == "Total" else name, "points": [(prev, before), (cur, now)],
                        "year_ago": num(r[13]), "avg5": num(r[19])})
    return out


async def collect_eia_gas(ctx) -> int:
    resp = await ctx.http.get(EIA_GAS_URL, headers={"User-Agent": "SessionDesk"}, timeout=20, follow_redirects=True)
    if resp.status_code != 200:
        return 0
    rows = parse_eia_gas(resp.content.decode("utf-8", "ignore"))
    for r in rows:
        sid = "eiagas:" + r["region"].lower().replace(" ", "_")
        await ctx.db.run(ctx.db.upsert_series, _meta(sid, f"US gas storage {r['region']} (Bcf)", "Gas (EIA weekly)",
                                                     "EIA Weekly Natural Gas Storage Report", "level"), r["points"])
        if r.get("avg5") is not None:
            await ctx.db.run(ctx.db.upsert_series, _meta(sid + ":vs5y", f"US gas storage {r['region']} vs 5-year average (Bcf)",
                                                         "Gas (EIA weekly)", "EIA Weekly Natural Gas Storage Report", "level"),
                             [(r["points"][-1][0], r["points"][-1][1] - r["avg5"])])
    return len(rows)


async def collect_news(ctx) -> int:
    import re
    themes = {t: re.compile(assets.THEMES[t], re.I) for t in NEWS_THEMES if t in assets.THEMES}
    since = int(time.time() - 120 * 86400)
    counts = await ctx.db.run(ctx.db.news_counts, themes, since)
    import datetime as dt
    first = dt.date.fromtimestamp(since)
    days = [(first + dt.timedelta(days=i)).isoformat() for i in range((dt.date.today() - first).days + 1)]
    archive_start = min((d for c in counts.values() for d in c), default=None)
    for t, c in counts.items():
        pts = [(d, float(c.get(d, 0))) for d in days if archive_start and d >= archive_start]
        if pts:
            await ctx.db.run(ctx.db.upsert_series, _meta(f"news:{t}", f"Headlines about {t.replace('_', ' ')}", "Attention (your news archive)",
                                                         "SessionDesk news archive", "count"), pts)
    return len(counts)


async def collect_eia_all(ctx) -> int:
    return await collect_eia(ctx) + await collect_eia_gas(ctx)


COLLECTORS = {"markets": (collect_markets, 900), "fred": (collect_fred, 6 * 3600), "eia": (collect_eia_all, 6 * 3600),
              "news": (collect_news, 3600)}


# ------------------------------------------------------------------ warnings and views
async def scan(ctx, publish: bool = True) -> list[dict]:
    out = []
    for s in await ctx.db.run(ctx.db.series_list):
        pts = await ctx.db.run(ctx.db.observations, s["id"], 400)
        a = assess(pts, s["kind"])
        if not a or abs(a["z"]) < Z_WARN:
            continue
        if s["kind"] == "count" and a["z"] < 0:
            continue                                   # quiet news days are no warning
        if s["kind"] == "count" and a["day"] == time.strftime("%Y-%m-%d", time.gmtime()) and a["change"] < 5:
            continue
        text = describe(s, a)
        alert = {"id": stable_id("hub", s["id"], a["day"]), "ts": time.time(), "kind": "hub", "symbol": s["id"],
                 "title": f"Unusual: {s['name']} ({a['z']:+.1f} σ)", "body": text, "data": {**a, "series": s["id"], "category": s["category"]}}
        out.append(alert)
        if publish and await ctx.db.run(ctx.db.add_alert, alert):
            ctx.broker.publish("hub_warning", {"alert": alert})
    return sorted(out, key=lambda x: -abs(x["data"]["z"]))


async def overview(ctx) -> dict:
    rows = []
    for s in await ctx.db.run(ctx.db.series_list):
        pts = await ctx.db.run(ctx.db.observations, s["id"], 90)
        a = assess(await ctx.db.run(ctx.db.observations, s["id"], 400), s["kind"]) if pts else None
        rows.append({**s, "last": pts[-1][1] if pts else None, "day": pts[-1][0] if pts else None,
                     "change": a["change"] if a else None, "z": a["z"] if a else None,
                     "spark": [v for _, v in pts[-60:]]})
    warnings = [w for w in await ctx.db.run(ctx.db.alerts, 60, "hub") if w["ts"] > time.time() - 3 * 86400]
    return {"series": rows, "warnings": warnings, "z_warn": Z_WARN, "asof": time.time(),
            "note": "Every series is measured against its own history: z = (latest change - median) / robust spread of its last "
                    f"250 changes; |z| ≥ {Z_WARN:g} is flagged. Unusual is not the same as meaningful, and it says nothing "
                    "about what comes next."}
