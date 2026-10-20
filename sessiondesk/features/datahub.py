"""Data hub: the numeric series SessionDesk sees, with their history, in one local table - and early warnings when
a series moves unusually against its own past.

Sources (free, no key needed):
  - market board: daily closes of indices, futures, yields, FX, commodities, crypto, volatility, sectors (Yahoo)
  - macro: Treasury curve, inflation, labour market, credit spreads, liquidity, euro yields (FRED)
  - oil: EIA Weekly Petroleum Status Report, U.S. stocks table (current and previous week; history builds up)
  - power: European day-ahead prices (Energy-Charts); gas: EU imports by route and LNG send-out (ENTSOG)
  - gas storage: GIE AGSI+ per country and EU (free key, only when the user entered one)
  - attention: headlines per day and theme (Fed, ECB, oil, tariffs, geopolitics ...) from your own news archive

Early warning = the latest change is unusual for THIS series: robust z-score against its own last 250 changes
(median and MAD, so one old crash does not hide everything). It describes, it does not predict.
"""
from __future__ import annotations

import csv
import io
import re
import statistics
import time

from . import assets, macro, markets
from ..connectors.base import stable_id

Z_WARN = 3.0
MIN_HISTORY = 40
EIA_URL = "https://ir.eia.gov/wpsr/table4.csv"
# table4 row -> (series name, EIA history code). "Crude Oil" in table4 is the total INCLUDING the SPR;
# commercial stocks are the row "Commercial (Excluding SPR)".
EIA_ROWS = {"Commercial (Excluding SPR)": ("Crude oil stocks excl. SPR", "WCESTUS1"),
            "Crude Oil": ("Crude oil stocks incl. SPR", "WCRSTUS1"), "Cushing": ("Cushing crude stocks", "W_EPC0_SAX_YCUOK_MBBL"),
            "SPR": ("Strategic petroleum reserve", "WCSSTUS1"), "Total Motor Gasoline": ("Gasoline stocks", "WGTSTUS1"),
            "Distillate Fuel Oil": ("Distillate stocks", "WDISTUS1"), "Kerosene-Type Jet Fuel": ("Jet fuel stocks", "WKJSTUS1"),
            "Propane/Propylene": ("Propane stocks", "WPRSTUS1")}
EIA_HISTORY_URL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={code}&f=W"
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
    out, seen = [], set()
    for r in rows[1:]:
        key = r[0].strip() if r else ""
        if len(r) < 3 or key not in EIA_ROWS or key in seen:
            continue
        seen.add(key)
        name, code = EIA_ROWS[key]
        try:
            out.append({"name": name, "code": code, "points": [(day(head[2]), float(r[2])), (day(head[1]), float(r[1]))]})
        except ValueError:
            continue
    return out


def parse_eia_history(html: str, scale: float = 1.0) -> list[tuple[str, float]]:
    """EIA's weekly history page (one row per month, up to five 'MM/DD | value' pairs) -> [(day, value * scale)] (pure, tested)."""
    out = []
    for year, body in re.findall(r"<td class='B6'>(?:&nbsp;)*(\d{4})-\w+</td>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td class='B[35]'>([^<]*)</td>", body)
        for d, v in zip(cells[0::2], cells[1::2]):
            d = d.replace("&nbsp;", "").strip()
            v = v.replace("&nbsp;", "").replace(",", "").strip()
            try:
                out.append((f"{year}-{d[:2]}-{d[3:5]}", round(float(v) * scale, 6)))
            except ValueError:
                continue
    return out


async def _backfill(ctx, series_id: str, url: str, scale: float) -> None:
    """Load the full weekly history once, when a series has only the few weeks collected so far."""
    if len(await ctx.db.run(ctx.db.observations, series_id, 60)) >= 50:
        return
    try:
        resp = await ctx.http.get(url, headers={"User-Agent": "SessionDesk"}, timeout=60, follow_redirects=True)
    except Exception:                               # history is a bonus; the weekly table still updates
        return
    if resp.status_code == 200:
        pts = parse_eia_history(resp.text, scale)
        if pts:
            meta = next((s for s in await ctx.db.run(ctx.db.series_list) if s["id"] == series_id), None)
            if meta:
                await ctx.db.run(ctx.db.upsert_series, meta, pts)


async def collect_eia(ctx) -> int:
    resp = await ctx.http.get(EIA_URL, headers={"User-Agent": "SessionDesk"}, timeout=20)
    if resp.status_code != 200:
        return 0
    rows = parse_eia_table(resp.text)
    for r in rows:
        sid = "eia:" + r["name"].lower().replace(" ", "_").replace(".", "")
        if r["code"] == "WCESTUS1":                 # before 2026-10-20 this id held the total incl. SPR by mistake
            old = await ctx.db.run(ctx.db.observations, sid, 10)
            if any(v > 600 for _, v in old):
                await ctx.db.run(ctx.db.delete_series, sid)
        await ctx.db.run(ctx.db.upsert_series, _meta(sid, r["name"] + " (mn bbl)", "Oil (EIA weekly)",
                                                     "EIA Weekly Petroleum Status Report", "level"), r["points"])
        await _backfill(ctx, sid, EIA_HISTORY_URL.format(code=r["code"]), 0.001)     # history is in thousand barrels
    return len(rows)


EIA_GAS_URL = "https://ir.eia.gov/ngs/wngsr.csv"
EIA_GAS_HISTORY = {"East": "R31", "Midwest": "R32", "South Central": "R33", "Mountain": "R34", "Pacific": "R35", "Lower 48 total": "R48"}
EIA_GAS_HISTORY_URL = "https://www.eia.gov/dnav/ng/hist/nw2_epg0_swo_{code}_bcfw.htm"


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
        if r["region"] in EIA_GAS_HISTORY:
            await _backfill(ctx, sid, EIA_GAS_HISTORY_URL.format(code=EIA_GAS_HISTORY[r["region"]].lower()), 1.0)
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


# European day-ahead power prices from Energy-Charts (Fraunhofer ISE), free and without a key. Data licence
# CC BY 4.0, Bundesnetzagentur | SMARD.de - the attribution travels with every series as its source.
POWER_URL = "https://api.energy-charts.info/price"
POWER_SOURCE = "Energy-Charts (Fraunhofer ISE), data Bundesnetzagentur | SMARD.de, CC BY 4.0"
POWER_ZONES = [("DE-LU", "Germany"), ("FR", "France"), ("NL", "Netherlands"), ("BE", "Belgium"), ("AT", "Austria"),
               ("CH", "Switzerland"), ("IT-North", "Italy North"), ("ES", "Spain"), ("PL", "Poland"), ("DK1", "Denmark West"),
               ("NO2", "Norway South"), ("SE3", "Sweden Central")]
POWER_PAUSE = 20.0                                  # seconds between zones; the API answers 429 to quick bursts
SLOW_COLLECTORS = {"power", "entsog", "agsi"}       # "collect now" starts these in the background


def _berlin():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Berlin")
    except Exception:                                # no tz database: CET without summer time is close enough for days
        import datetime as dt
        return dt.timezone(dt.timedelta(hours=1))


def power_daily(unix: list, prices: list, tz=None) -> list[tuple[str, float]]:
    """Quarter-hour (or hourly) day-ahead prices -> daily base price per local delivery day (pure, tested).
    A day needs at least 20 prices, so a half-published day is not shown as a full one."""
    import datetime as dt
    tz = tz or _berlin()
    days: dict[str, list[float]] = {}
    for t, p in zip(unix or [], prices or []):
        if p is None:
            continue
        days.setdefault(dt.datetime.fromtimestamp(t, tz).date().isoformat(), []).append(p)
    return [(d, round(sum(v) / len(v), 2)) for d, v in sorted(days.items()) if len(v) >= 20]


async def collect_power(ctx) -> int:
    """One request per zone, spaced out; a zone is skipped when its newest delivery day is already known
    (tomorrow, or today before the ~13:00 CET auction result)."""
    import asyncio
    import datetime as dt
    tz = _berlin()
    now = dt.datetime.now(tz)
    today = now.date()
    n = 0
    for i, (zone, label) in enumerate(POWER_ZONES):
        sid = "power:" + zone.lower()
        have = await ctx.db.run(ctx.db.observations, sid, 60)
        last = have[-1][0] if have else ""
        if last >= (today + dt.timedelta(days=1)).isoformat() or (last >= today.isoformat() and now.hour < 13):
            continue
        start = today - dt.timedelta(days=3 * 365 if len(have) < 50 else 10)
        if i and n:
            await asyncio.sleep(POWER_PAUSE)
        try:
            resp = await ctx.http.get(POWER_URL, params={"bzn": zone, "start": start.isoformat(),
                                                          "end": (today + dt.timedelta(days=2)).isoformat()},
                                      headers={"User-Agent": "SessionDesk"}, timeout=60)
        except Exception:
            continue
        if resp.status_code == 429:                  # back off until the next run
            break
        if resp.status_code != 200:
            continue
        data = resp.json()
        pts = power_daily(data.get("unix_seconds"), data.get("price"), tz)
        if pts:
            await ctx.db.run(ctx.db.upsert_series, _meta(sid, f"Power day-ahead {label} (EUR/MWh, daily base)", "Power (day-ahead)",
                                                         POWER_SOURCE, "level"), pts)
            n += 1
    return n


# European gas imports from the ENTSOG Transparency Platform, free and without a key: daily physical flows at the
# EU entry points, as reported by the transmission operators (recent days are "provisional" and get revised).
# A point key is operator + point + direction. Each source is counted once, where it first enters the EU: TurkStream
# at Strandzha 2 (not again at Horgos RS->HU), TAP at Kipoi (not again at Melendugno after Albania). Kotlovka BY->LT
# is transit to Kaliningrad and left out. The Emden landing points (Norpipe, Europipe I) publish no flows on ENTSOG,
# so the Norway route covers the reported points only - checked live 2026-10-20.
ENTSOG_URL = "https://transparency.entsog.eu/api/v1/operationalData"
ENTSOG_SOURCE = "ENTSOG Transparency Platform (physical flows reported by the operators)"
ENTSOG_ROUTES = [
    ("norway", "Norway → EU pipelines (Emden not published)",
     ["fr-tso-0003itp-00045entry", "be-tso-0001itp-00106entry", "de-tso-0009itp-00525entry", "dk-tso-0001itp-00630entry"]),
    ("turkstream", "Russia → EU via TurkStream (Strandzha 2)", ["bg-tso-0001itp-00549entry"]),
    ("algeria", "Algeria → EU (Transmed, Medgaz)", ["it-tso-0001itp-00093entry", "es-tso-0006itp-00048entry"]),
    ("libya", "Libya → Italy (Greenstream)", ["it-tso-0001itp-00074entry"]),
    ("tap", "Azerbaijan → EU via TAP (Kipoi)", ["al-tso-0001itp-00274entry"]),
    ("uk", "UK → EU (Interconnector, BBL)", ["be-tso-0001itp-00061entry", "uk-tso-0004itp-00207entry"]),
]
ENTSOG_LNG = [
    ("NL", "Netherlands", ["nl-tso-0001lng-00027entry", "nl-tso-0001lng-00068entry"]),
    ("ES", "Spain", ["es-tso-0006lng-000%sentry" % n for n in ("12", "13", "16", "18", "21", "22", "23")]),
    ("IT", "Italy", ["it-tso-0001lng-000%sentry" % n for n in ("04", "15", "19", "69", "82")]),
    ("FR", "France", ["fr-tso-0003lng-00024entry", "fr-tso-0003lng-00029entry"]),
    ("DE", "Germany", ["de-tso-0005lng-00060entry", "de-tso-0009lng-00083entry", "de-tso-0001lng-00079entry", "de-tso-0017lng-00075entry"]),
    ("PT", "Portugal", ["pt-tso-0001lng-00026entry"]),
    ("PL", "Poland", ["pl-tso-0002lng-00006entry"]),
    ("BE", "Belgium", ["be-tso-0001lng-00017entry"]),
    ("GR", "Greece", ["gr-tso-0001lng-00014entry"]),
    ("HR", "Croatia", ["hr-tso-0001lng-00032entry"]),
    ("LT", "Lithuania", ["lt-tso-0001lng-00030entry"]),
    ("FI", "Finland", ["fi-tso-0003lng-00011entry", "fi-tso-0003lng-00072entry"]),
]
ENTSOG_PAUSE = 4.0                                  # seconds between requests
# Early warnings only where the robust z-score means something. Single routes and LNG countries move in steps
# (nominations, cargoes): on three years of data TAP would have warned on 52 of the last 120 days, Libya on 44,
# Polish LNG on 55, the two totals on 1 and 0 (measured 2026-10-20). So only the totals warn. AGSI injection and
# withdrawal sit at zero for months and then jump; the fill level keeps its warnings.
NO_WARN_PREFIX = ("entsog:",)
NO_WARN_SUFFIX = (":injection", ":withdrawal")
WARN_ANYWAY = {"entsog:total", "entsog:lng_total"}


def warns(series_id: str) -> bool:
    """Does this series take part in the early warnings? (pure, tested)"""
    if series_id in WARN_ANYWAY:
        return True
    return not (series_id.startswith(NO_WARN_PREFIX) or (series_id.startswith("agsi:") and series_id.endswith(NO_WARN_SUFFIX)))
ENTSOG_CATEGORY = "Gas flows (ENTSOG)"


def entsog_groups() -> dict[str, tuple[str, list[str]]]:
    """series key -> (label, point keys): one series per route and per LNG country."""
    out = {k: (label, keys) for k, label, keys in ENTSOG_ROUTES}
    out.update({"lng_" + c.lower(): (f"LNG send-out {name}", keys) for c, name, keys in ENTSOG_LNG})
    return out


def entsog_daily(rows: list[dict], groups: dict[str, list[str]], now=None, stale_days: int = 10) -> dict[str, list[tuple[str, float]]]:
    """ENTSOG operationalData rows -> {series: [(gas day, GWh/d)]} (pure, tested).
    The gas day still running (06:00 to 06:00 CET) is left out: operators publish it hourly as a partial value.
    A day only counts when every point of the series that reports at all has reported it: a point is expected
    from its first row on, and up to the end unless it fell silent more than `stale_days` before the newest day
    (a closed terminal must not freeze its series; a point that is merely late must not shrink the latest sum)."""
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    vals: dict[str, dict[str, float]] = {}
    for r in rows:
        key = f"{r.get('operatorKey', '')}{r.get('pointKey', '')}{r.get('directionKey', '')}".lower()
        try:
            v = float(r.get("value"))
            if r.get("periodTo") and dt.datetime.fromisoformat(r["periodTo"]) > now:
                continue
        except (TypeError, ValueError):
            continue
        day = str(r.get("periodFrom") or "")[:10]
        if day:
            vals.setdefault(key, {})[day] = v
    if not vals:
        return {}
    newest = max(d for v in vals.values() for d in v)
    cutoff = (dt.date.fromisoformat(newest) - dt.timedelta(days=stale_days)).isoformat()
    out = {}
    for name, keys in groups.items():
        live = [k for k in keys if k in vals]
        if not live:
            continue
        span = {k: (min(vals[k]), max(vals[k])) for k in live}
        pts = []
        for day in sorted({d for k in live for d in vals[k]}):
            expected = [k for k in live if span[k][0] <= day and (day <= span[k][1] or span[k][1] >= cutoff)]
            if all(day in vals[k] for k in expected):
                pts.append((day, round(sum(vals[k][day] for k in expected) / 1e6, 3)))
        out[name] = pts
    return out


def sum_complete(parts: list[list[tuple[str, float]]]) -> list[tuple[str, float]]:
    """Day-by-day sum of several series, only on days all of them have (pure, tested)."""
    if not parts or not all(parts):
        return []
    maps = [dict(p) for p in parts]
    days = set(maps[0]).intersection(*maps[1:])
    return [(d, round(sum(m[d] for m in maps), 3)) for d in sorted(days)]


async def collect_entsog(ctx) -> int:
    """Daily EU gas imports by route and LNG send-out by country. The first run loads three years in one-year
    chunks; later runs reload the last two weeks (provisional values get revised). Any failed request aborts the
    run, so a half-loaded window is never stored."""
    import asyncio
    import datetime as dt
    groups = entsog_groups()
    keys = [k for _, ks in groups.values() for k in ks]
    have = await ctx.db.run(ctx.db.observations, "entsog:total", 400)
    today = dt.date.today()
    start = today - dt.timedelta(days=3 * 365 if len(have) < 300 else 14)
    windows, a = [], start
    while a <= today:
        b = min(a + dt.timedelta(days=365), today)
        windows.append((a, b))
        a = b + dt.timedelta(days=1)
    rows, first = [], True
    for a, b in windows:
        for i in range(0, len(keys), 20):
            if not first:
                await asyncio.sleep(ENTSOG_PAUSE)
            first = False
            try:
                resp = await ctx.http.get(ENTSOG_URL, params={"limit": -1, "indicator": "Physical Flow", "periodType": "day",
                                                               "timezone": "CET", "from": a.isoformat(), "to": b.isoformat(),
                                                               "pointDirection": ",".join(keys[i:i + 20])},
                                          headers={"User-Agent": "SessionDesk"}, timeout=120)
            except Exception:
                return 0
            if resp.status_code == 404 and "No result" in resp.text:     # no rows for these points in this window
                continue
            if resp.status_code != 200:              # 429 included: stop and try again next run
                return 0
            try:
                rows += resp.json().get("operationalData") or []
            except ValueError:
                return 0
    daily = entsog_daily(rows, {k: ks for k, (_, ks) in groups.items()})
    lng = [daily.get("lng_" + c.lower(), []) for c, _, _ in ENTSOG_LNG]
    daily["lng_total"] = sum_complete(lng)
    daily["total"] = sum_complete([daily.get(k, []) for k, _, _ in ENTSOG_ROUTES] + [daily["lng_total"]])
    labels = {k: label for k, (label, _) in groups.items()}
    labels.update({"lng_total": "LNG send-out EU total", "total": "EU gas imports total (pipelines + LNG)"})
    n = 0
    for k, pts in daily.items():
        if pts:
            await ctx.db.run(ctx.db.upsert_series, _meta("entsog:" + k, f"{labels[k]} (GWh/d)", ENTSOG_CATEGORY, ENTSOG_SOURCE, "level"), pts)
            n += 1
    return n


# EU gas storage from GIE AGSI+ (free key, entered by the user in Settings -> Connectors; connector `agsi`).
AGSI_SCOPES = [("eu", "EU"), ("DE", "Germany"), ("IT", "Italy"), ("FR", "France"), ("NL", "Netherlands"), ("AT", "Austria")]
AGSI_CATEGORY = "Gas storage (AGSI+)"
AGSI_SOURCE = "GIE AGSI+ (Aggregated Gas Storage Inventory)"
AGSI_FIELDS = [("full", "fill level (%)"), ("injection", "injection (GWh/d)"), ("withdrawal", "withdrawal (GWh/d)")]


async def collect_agsi(ctx) -> int:
    """Fill level, injection and withdrawal per country and for the EU. Skips quietly without a key; the first
    run per country loads three years, later runs the last two weeks (operators revise recent days)."""
    import datetime as dt
    conn = ctx.hub.get("agsi") if ctx.hub else None
    if not conn or not conn.active():
        return 0
    today = dt.date.today()
    n = 0
    for code, label in AGSI_SCOPES:
        base = f"agsi:{code.lower()}"
        have = await ctx.db.run(ctx.db.observations, base + ":full", 400)
        start = today - dt.timedelta(days=3 * 365 if len(have) < 300 else 14)
        try:
            days = await conn.storage(code, start.isoformat(), today.isoformat())
        except Exception as exc:                     # bad key, 429, outage: stop until the next run
            ctx.hub.mark("agsi", f"storage: {exc}")
            break
        ctx.hub.mark("agsi")
        for field, what in AGSI_FIELDS:
            pts = [(d["day"], d[field]) for d in days if d.get(field) is not None]
            if pts:
                await ctx.db.run(ctx.db.upsert_series, _meta(f"{base}:{field}", f"Gas storage {label} {what}", AGSI_CATEGORY,
                                                             AGSI_SOURCE, "level"), pts)
        n += 1
    return n


COLLECTORS = {"markets": (collect_markets, 900), "fred": (collect_fred, 6 * 3600), "eia": (collect_eia_all, 6 * 3600),
              "news": (collect_news, 3600), "power": (collect_power, 3 * 3600), "entsog": (collect_entsog, 6 * 3600),
              "agsi": (collect_agsi, 6 * 3600)}


# ------------------------------------------------------------------ warnings and views
async def scan(ctx, publish: bool = True) -> list[dict]:
    out = []
    for s in await ctx.db.run(ctx.db.series_list):
        if not warns(s["id"]):
            continue                                   # moves in steps by nature (see NO_WARN_PREFIX)
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


EIA_GAS_REPORT = "https://ir.eia.gov/ngs/ngs.html"


def source_url(series_id: str) -> str | None:
    """Link to where the number comes from: the vendor's page for that series, or the app page that computes it (pure, tested)."""
    kind, _, key = series_id.partition(":")
    if kind == "fred":
        return "https://fred.stlouisfed.org/series/" + key
    if kind == "mkt":
        return "https://finance.yahoo.com/quote/" + key
    if kind == "eia":
        code = next((c for n, c in EIA_ROWS.values() if n.lower().replace(" ", "_").replace(".", "") == key), None)
        return EIA_HISTORY_URL.format(code=code) if code else "https://www.eia.gov/petroleum/supply/weekly/"
    if kind == "eiagas":
        region = key.split(":")[0]
        code = next((c for r, c in EIA_GAS_HISTORY.items() if r.lower().replace(" ", "_") == region), None)
        return EIA_GAS_HISTORY_URL.format(code=code.lower()) if code and not key.endswith(":vs5y") else EIA_GAS_REPORT
    if kind == "power":
        zone = next((z for z, _ in POWER_ZONES if z.lower() == key), key.upper())
        return f"https://www.energy-charts.info/charts/price_spot_market/chart.htm?l=en&c={zone.split('-')[0]}"
    if kind == "entsog":
        return "https://transparency.entsog.eu/#/map"
    if kind == "agsi":
        code = key.split(":")[0]
        return "https://agsi.gie.eu/data-overview/" + (code if code == "eu" else code.upper())
    if kind == "basket":
        return "#/baskets/" + key
    if kind == "news":
        return "#/news"
    return None


async def overview(ctx) -> dict:
    rows = []
    for s in await ctx.db.run(ctx.db.series_list):
        pts = await ctx.db.run(ctx.db.observations, s["id"], 90)
        a = assess(await ctx.db.run(ctx.db.observations, s["id"], 400), s["kind"]) if pts else None
        rows.append({**s, "url": source_url(s["id"]), "last": pts[-1][1] if pts else None, "day": pts[-1][0] if pts else None,
                     "change": a["change"] if a else None, "z": a["z"] if a else None,
                     "spark": [v for _, v in pts[-60:]]})
    warnings = [w for w in await ctx.db.run(ctx.db.alerts, 60, "hub") if w["ts"] > time.time() - 3 * 86400]
    return {"series": rows, "warnings": warnings, "z_warn": Z_WARN, "asof": time.time(),
            "note": "Every series is measured against its own history: z = (latest change - median) / robust spread of its last "
                    f"250 changes; |z| ≥ {Z_WARN:g} is flagged. Unusual is not the same as meaningful, and it says nothing "
                    "about what comes next."}
