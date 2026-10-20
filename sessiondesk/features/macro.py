"""Macro panel: yield curve, Fed-funds path from futures, volatility structure, positioning, risk appetite.

Descriptive context, not timing tools - each block states its source and sample.
"""
from __future__ import annotations

import asyncio
import csv
import io
import datetime as dt
import math

MONTH_CODES = "FGHJKMNQUVXZ"
CURVE = [("1m", "DGS1MO"), ("3m", "DGS3MO"), ("6m", "DGS6MO"), ("1y", "DGS1"), ("2y", "DGS2"), ("3y", "DGS3"),
         ("5y", "DGS5"), ("7y", "DGS7"), ("10y", "DGS10"), ("20y", "DGS20"), ("30y", "DGS30")]
EXTRA_SERIES = [("10y real (TIPS)", "DFII10"), ("10y breakeven inflation", "T10YIE"), ("High-yield spread", "BAMLH0A0HYM2"),
                ("Fed funds effective", "DFF")]
RISK_RATIOS = [("High yield vs Treasuries", "HYG", "IEF"), ("Cyclicals vs staples", "XLY", "XLP"),
               ("Small vs large caps", "IWM", "SPY"), ("Copper vs gold", "HG=F", "GC=F"),
               ("High beta vs low vol", "SPHB", "SPLV"), ("Emerging vs developed", "EEM", "EFA"),
               ("Semis vs market", "SOXX", "SPY"), ("Equal vs cap weight", "RSP", "SPY")]


def ff_contracts(today: dt.date, n: int = 10) -> list[tuple[str, str]]:
    out = []
    for k in range(n):
        m, y = (today.month - 1 + k) % 12, today.year + (today.month - 1 + k) // 12
        out.append((f"ZQ{MONTH_CODES[m]}{str(y)[2:]}.CBT", dt.date(y, m + 1, 1).strftime("%b %y")))
    return out


async def rates(ctx) -> dict:
    fred = ctx.hub.get("fred")

    async def build():
        ids = [s for _, s in CURVE + EXTRA_SERIES]
        res = await asyncio.gather(*(fred.series(i) for i in ids), return_exceptions=True)
        series = {i: r["points"] for i, r in zip(ids, res) if not isinstance(r, Exception) and r.get("points")}
        if not series:
            return {"error": "FRED returned no data"}

        def point(sid, back=0):
            pts = series.get(sid) or []
            return pts[-1 - back] if len(pts) > back else None
        curve = []
        for label, sid in CURVE:
            now, wk = point(sid), point(sid, 5)
            if now:
                curve.append({"tenor": label, "date": now[0], "yield": now[1], "chg_1w_bp": (now[1] - wk[1]) * 100 if wk else None})
        extras = []
        for label, sid in EXTRA_SERIES:
            now, wk = point(sid), point(sid, 5)
            if now:
                extras.append({"label": label, "id": sid, "date": now[0], "value": now[1], "chg_1w": now[1] - wk[1] if wk else None})
        by = {c["tenor"]: c["yield"] for c in curve}
        spreads = {f"{a}/{b}": (by[b] - by[a]) * 100 for a, b in (("3m", "10y"), ("2y", "10y"), ("5y", "30y")) if a in by and b in by}
        return {"curve": curve, "extras": extras, "spreads_bp": spreads, "source": "FRED (daily, previous close)"}
    return await ctx.cache.get("macro:rates", 3600, build, disk=True)


async def fed_path(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        strip = ff_contracts(dt.date.today())
        quotes = await yahoo.quotes([s for s, _ in strip], intraday=False)
        rows = []
        for sym, label in strip:
            q = quotes.get(sym)
            if q and q.get("price"):
                rows.append({"month": label, "implied": 100 - q["price"],
                             "chg_bp": -(q["change"] or 0) * 100 if q.get("change") is not None else None})
        if not rows:
            return {"error": "no Fed funds futures quotes"}
        base = rows[0]["implied"]
        for r in rows:
            r["vs_now_bp"] = (r["implied"] - base) * 100
            r["moves_25bp"] = r["vs_now_bp"] / 25
        return {"path": rows, "source": "CBOT 30-day Fed funds futures via Yahoo (delayed). Implied = 100 - price; "
                                        "monthly averages, so a mid-month meeting shows up split across two months."}
    return await ctx.cache.get("macro:fedpath", 900, build)


async def vol(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        terms = [("9d", "^VIX9D"), ("30d", "^VIX"), ("3m", "^VIX3M"), ("6m", "^VIX6M"), ("VVIX", "^VVIX"), ("MOVE", "^MOVE")]
        quotes, closes = await asyncio.gather(yahoo.quotes([t for _, t in terms], intraday=False),
                                              yahoo.daily_closes(["^GSPC"], "3mo"))
        curve = [{"term": label, "symbol": t, "value": quotes[t]["price"], "change": quotes[t].get("change")}
                 for label, t in terms if t in quotes]
        out = {"curve": curve}
        spx = closes.get("^GSPC", [])
        if len(spx) > 21:
            r = [math.log(b / a) for a, b in zip(spx, spx[1:])]
            for n in (10, 20):
                tail = r[-n:]
                mean = sum(tail) / n
                out[f"realized_{n}d"] = math.sqrt(sum((x - mean) ** 2 for x in tail) / (n - 1)) * math.sqrt(252) * 100
        by = {c["term"]: c["value"] for c in curve}
        if "30d" in by and "realized_20d" in out:
            out["risk_premium"] = by["30d"] - out["realized_20d"]
        if "30d" in by and "3m" in by:
            out["slope"] = by["3m"] - by["30d"]
            out["state"] = "contango (calm)" if out["slope"] > 0 else "backwardation (stress)"
        return out
    return await ctx.cache.get("macro:vol", 300, build)


async def risk_ratios(ctx) -> dict:
    yahoo = ctx.hub.get("yahoo")

    async def build():
        syms = sorted({s for _, a, b in RISK_RATIOS for s in (a, b)})
        closes = await yahoo.daily_closes(syms, "3mo")
        rows = []
        for label, a, b in RISK_RATIOS:
            ca, cb = closes.get(a, []), closes.get(b, [])
            k = min(len(ca), len(cb))
            if k < 22:
                continue
            ratio = [x / y for x, y in zip(ca[-k:], cb[-k:]) if y]
            rows.append({"label": label, "pair": f"{a}/{b}", "d1": (ratio[-1] / ratio[-2] - 1) * 100,
                         "d5": (ratio[-1] / ratio[-6] - 1) * 100, "d20": (ratio[-1] / ratio[-21] - 1) * 100})
        if not rows:
            return {"error": "no ratio data"}
        return {"rows": rows, "risk_on_5d": sum(r["d5"] > 0 for r in rows), "n": len(rows),
                "note": "Ratio up = the risk-on side outperforms. Aligned on the last common closes; descriptive only."}
    return await ctx.cache.get("macro:risk", 900, build)


async def cot(ctx) -> dict:
    conn = ctx.hub.get("cftc")

    async def build():
        return {"rows": await conn.cot(), "source": "CFTC Commitments of Traders (Tuesday positions, published Friday)"}
    return await ctx.cache.get("macro:cot", 6 * 3600, build, disk=True)


# ------------------------------------------------------------------ inflation & growth, credit & liquidity (FRED)
GROWTH = [("CPI, % y/y", "CPIAUCSL", "yoy12"), ("Core CPI, % y/y", "CPILFESL", "yoy12"),
          ("Core PCE, % y/y (Fed target 2 %)", "PCEPILFE", "yoy12"), ("Unemployment rate, %", "UNRATE", "level"),
          ("Payrolls, change in thousands", "PAYEMS", "diff"), ("Initial jobless claims, 4-week average", "ICSA", "avg4"),
          ("Retail sales, % m/m", "RSAFS", "mom"), ("GDPNow (Atlanta Fed nowcast), % q/q annualised", "GDPNOW", "level")]
CREDIT = [("High-yield spread (OAS), %", "BAMLH0A0HYM2", "level"), ("Investment-grade spread (OAS), %", "BAMLC0A0CM", "level"),
          ("Financial conditions (Chicago Fed NFCI, below 0 = looser than average)", "NFCI", "level"),
          ("Fed balance sheet, $ bn", "WALCL", "mn_to_bn"), ("Overnight reverse repo, $ bn", "RRPONTSYD", "level"),
          ("Treasury General Account, $ bn", "WTREGEN", "mn_to_bn")]
EURO_10Y = [("Germany", "IRLTLT01DEM156N"), ("France", "IRLTLT01FRM156N"), ("Italy", "IRLTLT01ITM156N")]


def transform(points: list[tuple[str, float]], how: str) -> dict | None:
    """Latest value, the one before, and the change, after a transform (pure, tested)."""
    v = [p[1] for p in points]

    def at(i):
        if how == "yoy12":
            return (v[i] / v[i - 12] - 1) * 100 if len(v) >= 12 - i and v[i - 12] else None
        if how == "mom":
            return (v[i] / v[i - 1] - 1) * 100 if len(v) >= 1 - i and v[i - 1] else None
        if how == "diff":
            return v[i] - v[i - 1] if len(v) >= 1 - i else None
        if how == "avg4":
            window = v[len(v) + i - 3: len(v) + i + 1] if i < -1 else v[-4:]
            return sum(window) / len(window) if len(window) == 4 else None
        if how == "mn_to_bn":
            return v[i] / 1000 if len(v) >= -i else None
        return v[i] if len(v) >= -i else None
    if len(v) < 2:
        return None
    now, prev = at(-1), at(-2)
    if now is None:
        return None
    return {"date": points[-1][0], "value": now, "prev": prev, "change": now - prev if prev is not None else None}


async def _fred_block(ctx, key: str, spec: list[tuple[str, str, str]], ttl: float, source: str) -> dict:
    fred = ctx.hub.get("fred")

    async def build():
        res = await asyncio.gather(*(fred.series(sid) for _, sid, _ in spec), return_exceptions=True)
        rows, missing = [], []
        for (label, sid, how), r in zip(spec, res):
            t = transform(r["points"], how) if not isinstance(r, Exception) and r.get("points") else None
            if t:
                rows.append({"label": label, "id": sid, **t})
            else:
                missing.append(sid)
        return {"rows": rows, "missing": missing, "source": source} if rows else {"error": "FRED returned no data"}
    return await ctx.cache.get(key, ttl, build, disk=True)


async def growth(ctx) -> dict:
    return await _fred_block(ctx, "macro:growth", GROWTH, 6 * 3600, "FRED (monthly / weekly releases; the date is the period, not the release day)")


async def credit(ctx) -> dict:
    out = dict(await _fred_block(ctx, "macro:credit", CREDIT, 3 * 3600, "FRED (daily / weekly)"))
    fred = ctx.hub.get("fred")

    async def build_euro():
        res = await asyncio.gather(*(fred.series(sid) for _, sid in EURO_10Y), return_exceptions=True)
        pts = {c: r["points"] for (c, _), r in zip(EURO_10Y, res) if not isinstance(r, Exception) and r.get("points")}
        if "Germany" not in pts:
            return {"error": "no euro area yields"}
        de = dict(pts["Germany"])
        rows = []
        for c, series in pts.items():
            d, y = series[-1]
            rows.append({"country": c, "date": d, "yield": y,             # spread against Germany in the SAME month
                         "spread_bp": (y - de[d]) * 100 if d in de else None})
        return {"rows": rows,
                "note": "Monthly averages of 10-year government bond yields (OECD via FRED) - the level of the spread, "
                        "not today's move. Daily spreads need a paid source."}
    out["euro"] = await ctx.cache.get("macro:euro10y", 12 * 3600, build_euro, disk=True)
    return out


# ------------------------------------------------------------------ inflation & growth by country (free official sources)
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
EU_GEOS = [("EA", "Euro area"), ("DE", "Germany"), ("FR", "France"), ("IT", "Italy"), ("ES", "Spain")]
# Eurostat queries per indicator; the euro area code differs by dataset (EA = changing composition, EA21 since 2026)
EU_QUERIES = {
    "cpi": ("prc_hicp_minr", {"unit": "RCH_A", "coicop18": "TOTAL"}, {"EA": "EA"}),
    "core": ("prc_hicp_minr", {"unit": "RCH_A", "coicop18": "TOT_X_NRG_FOOD"}, {"EA": "EA"}),
    "unemployment": ("une_rt_m", {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}, {"EA": "EA21"}),
    "gdp": ("namq_10_gdp", {"unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"}, {"EA": "EA"}),
}
ONS = "https://www.ons.gov.uk/generator"
UK_SERIES = {"cpi": "/economy/inflationandpriceindices/timeseries/d7g7/mm23",
             "core": "/economy/inflationandpriceindices/timeseries/dko8/mm23",
             "unemployment": "/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
             "gdp": "/economy/grossdomesticproductgdp/timeseries/ihyq/qna"}
FRED_COUNTRY = {   # (country, indicator): (FRED id, transform)
    ("United States", "cpi"): ("CPIAUCSL", "yoy12"), ("United States", "core"): ("CPILFESL", "yoy12"),
    ("United States", "unemployment"): ("UNRATE", "level"), ("United States", "gdp"): ("GDPC1", "mom"),
    ("Japan", "unemployment"): ("LRHUTTTTJPM156S", "level"), ("Japan", "gdp"): ("JPNRGDPEXP", "mom"),
}
INDICATORS = [("cpi", "Inflation, % y/y"), ("core", "Core inflation, % y/y (ex energy, food, alcohol, tobacco)"),
              ("unemployment", "Unemployment rate, %"), ("gdp", "Real GDP, % q/q (not annualised)")]
COUNTRIES = ["United States", "Euro area", "Germany", "France", "Italy", "Spain", "United Kingdom", "Japan"]


def parse_jsonstat(d: dict) -> dict[str, list[tuple[str, float]]]:
    """Eurostat JSON-stat 2.0 with one value per geo and period (all other dimensions fixed) -> {geo: [(period, value)]}
    (pure, tested)."""
    dims, size = d["id"], d["size"]
    index = {k: d["dimension"][k]["category"]["index"] for k in dims}
    geos = sorted(index["geo"], key=index["geo"].get)
    times = sorted(index["time"], key=index["time"].get)
    out = {}
    for g in geos:
        pts = []
        for t in times:
            n = 0
            for k, s in zip(dims, size):
                n = n * s + (index[k][g] if k == "geo" else index[k][t] if k == "time" else 0)
            v = d.get("value", {}).get(str(n))
            if v is not None:
                pts.append((t, float(v)))
        out[g] = pts
    return out


def parse_ons_csv(text: str) -> list[tuple[str, float]]:
    """ONS time-series CSV -> monthly ("2026 AUG") or quarterly ("2026 Q2") points; annual rows are skipped (pure, tested)."""
    months = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        parts = row[0].split()
        try:
            v = float(row[1])
        except ValueError:
            continue
        if len(parts) == 2 and parts[0].isdigit() and parts[1] in months:
            out.append((f"{parts[0]}-{months[parts[1]]:02d}", v))
        elif len(parts) == 2 and parts[0].isdigit() and parts[1] in ("Q1", "Q2", "Q3", "Q4"):
            out.append((f"{parts[0]}-{parts[1]}", v))
    return out


def _cell(points: list[tuple[str, float]], source: str, url: str) -> dict | None:
    if not points:
        return None
    return {"period": points[-1][0], "value": points[-1][1], "prev": points[-2][1] if len(points) > 1 else None,
            "source": source, "url": url}


async def international(ctx) -> dict:
    fred = ctx.hub.get("fred")

    async def eurostat(key):
        dataset, params, rename = EU_QUERIES[key]
        geos = [rename.get(g, g) for g, _ in EU_GEOS]
        q = [*params.items(), *(("geo", g) for g in geos), ("lastTimePeriod", "6")]
        resp = await ctx.http.get(EUROSTAT + dataset, params=q, timeout=40)
        if resp.status_code != 200:
            return key, {}
        data = parse_jsonstat(resp.json())
        back = {v: k for k, v in rename.items()}
        return key, {back.get(g, g): pts for g, pts in data.items()}

    async def ons(key):
        resp = await ctx.http.get(ONS, params={"format": "csv", "uri": UK_SERIES[key]}, headers={"User-Agent": "Mozilla/5.0 (SessionDesk)"},
                                  timeout=30, follow_redirects=True)
        return key, parse_ons_csv(resp.text) if resp.status_code == 200 else []

    async def fred_cell(country, key):
        sid, how = FRED_COUNTRY[(country, key)]
        r = await fred.series(sid)
        pts = r["points"]
        vals = []
        for i in range(max(1, len(pts) - 6), len(pts)):         # transformed tail, so prev is comparable
            t = transform(pts[: i + 1], how)
            if t:
                day = pts[i][0]                                         # FRED dates periods by their first day
                period = f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}" if key == "gdp" else day[:7]
                vals.append((period, t["value"]))
        return country, key, vals, sid

    async def build():
        eu, uk, fr = await asyncio.gather(
            asyncio.gather(*(eurostat(k) for k in EU_QUERIES), return_exceptions=True),
            asyncio.gather(*(ons(k) for k in UK_SERIES), return_exceptions=True),
            asyncio.gather(*(fred_cell(c, k) for c, k in FRED_COUNTRY), return_exceptions=True))
        table = {c: {} for c in COUNTRIES}
        names = dict(EU_GEOS)
        for res in eu:
            if isinstance(res, Exception):
                continue
            key, data = res
            dataset = EU_QUERIES[key][0]
            for g, pts in data.items():
                table[names[g]][key] = _cell(pts, f"Eurostat {dataset}", f"https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table")
        for res in uk:
            if not isinstance(res, Exception):
                key, pts = res
                table["United Kingdom"][key] = _cell(pts, "ONS", "https://www.ons.gov.uk" + UK_SERIES[key])
        for res in fr:
            if not isinstance(res, Exception):
                country, key, pts, sid = res
                table[country][key] = _cell(pts, f"FRED {sid}", "https://fred.stlouisfed.org/series/" + sid)
        if not any(v for row in table.values() for v in row.values()):
            return {"error": "no international data"}
        return {"countries": COUNTRIES, "indicators": [{"key": k, "label": label} for k, label in INDICATORS], "table": table,
                "note": "Latest official figure per country with its period (the release lags the period). Euro area = Eurostat "
                        "(EA21 for unemployment since Bulgaria joined in 2026), UK = ONS, US and Japan = FRED. US GDP is the "
                        "real quarterly change, not the annualised rate the US headlines use. Japan's CPI has no free source "
                        "without a key (e-Stat), so it stays empty."}
    return await ctx.cache.get("macro:international:v2", 12 * 3600, build, disk=True)
