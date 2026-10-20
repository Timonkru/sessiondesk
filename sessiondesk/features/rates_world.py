"""Government yields and policy rates by country, from the official free sources (no key):

  United States   FRED (Treasury constant maturities, effective fed funds)
  Euro area       ECB data portal: AAA government curve (Svensson spot rates) and the deposit facility rate
  United Kingdom  Bank of England database: Bank Rate, SONIA, nominal zero-coupon 5/10/20 years
  Japan           Ministry of Finance: JGB benchmark curve (daily CSV); no free machine-readable BoJ policy rate

"2y minus policy" is a rough gauge of what the market expects the central bank to do over two years - it also
contains a term premium, so it is not a clean expectation. The UK has no 2-year point in the BoE's nominal series,
so the UK row uses 5 years. Every value carries its date and a link.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io

ECB = "https://data-api.ecb.europa.eu/service/data/"
BOE = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
MOF = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
UA = {"User-Agent": "Mozilla/5.0 (SessionDesk; +https://github.com/Timonkru/sessiondesk)"}
TENORS = ["3m", "1y", "2y", "5y", "10y", "30y"]


def parse_ecb_csv(text: str) -> dict[str, tuple[str, float]]:
    """ECB csvdata -> {series key: (last date, last value)} (pure, tested)."""
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            out[r["KEY"]] = (r["TIME_PERIOD"], float(r["OBS_VALUE"]))
        except (KeyError, ValueError):
            continue
    return out


def parse_boe_csv(text: str) -> dict[str, tuple[str, float]]:
    """BoE IADB CSV (DATE, code, code ...; '16 Oct 2026') -> last non-empty value per code (pure, tested)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0].upper() != "DATE":
        return {}
    codes, out = rows[0][1:], {}
    for r in rows[1:]:
        try:
            day = dt.datetime.strptime(r[0].strip(), "%d %b %Y").date().isoformat()
        except ValueError:
            continue
        for code, v in zip(codes, r[1:]):
            try:
                out[code] = (day, float(v))
            except ValueError:
                continue
    return out


def parse_mof_csv(text: str) -> tuple[str, dict[str, float]] | None:
    """MOF jgbcme.csv -> (last date, {tenor: yield}) (pure, tested)."""
    rows = list(csv.reader(io.StringIO(text)))
    head = next((r for r in rows if r and r[0] == "Date"), None)
    if not head:
        return None
    last = None
    for r in rows[rows.index(head) + 1:]:
        if r and r[0][:4].isdigit():
            last = r
    if not last:
        return None
    y, m, d = (int(x) for x in last[0].split("/"))
    vals = {}
    for k, v in zip(head[1:], last[1:]):
        try:
            vals[k.lower()] = float(v)
        except ValueError:
            continue
    return dt.date(y, m, d).isoformat(), vals


def _row(country, policy, policy_name, curve: dict[str, tuple[str, float]], gauge_tenor: str, source: str, url: str) -> dict:
    vals = {k: v[1] for k, v in curve.items()}
    days = [v[0] for v in curve.values()]
    p = policy[1] if policy else None
    g = vals.get(gauge_tenor)
    return {"country": country, "policy_name": policy_name, "policy": p, "policy_date": policy[0] if policy else None,
            **{t: vals.get(t) for t in TENORS}, "date": max(days) if days else None,
            "s2s10": (vals["10y"] - vals["2y"]) * 100 if "10y" in vals and "2y" in vals else None,
            "gauge_tenor": gauge_tenor, "gauge_bp": (g - p) * 100 if g is not None and p is not None else None,
            "source": source, "url": url}


async def world(ctx) -> dict:
    http, fred = ctx.http, ctx.hub.get("fred")

    async def us():
        ids = {"3m": "DGS3MO", "1y": "DGS1", "2y": "DGS2", "5y": "DGS5", "10y": "DGS10", "30y": "DGS30"}
        res = await asyncio.gather(*(fred.series(s) for s in list(ids.values()) + ["DFF"]), return_exceptions=True)
        curve = {t: r["points"][-1] for t, r in zip(ids, res) if not isinstance(r, Exception) and r.get("points")}
        pol = res[-1]["points"][-1] if not isinstance(res[-1], Exception) and res[-1].get("points") else None
        return _row("United States", pol, "Fed funds (effective)", curve, "2y", "FRED", "https://fred.stlouisfed.org/series/DGS2")

    async def euro():
        tenors = {"3m": "SR_3M", "1y": "SR_1Y", "2y": "SR_2Y", "5y": "SR_5Y", "10y": "SR_10Y", "30y": "SR_30Y"}
        url = ECB + "YC/B.U2.EUR.4F.G_N_A.SV_C_YM." + "+".join(tenors.values())
        r1, r2 = await asyncio.gather(http.get(url, params={"lastNObservations": "1", "format": "csvdata"}, headers=UA, timeout=30),
                                      http.get(ECB + "FM/D.U2.EUR.4F.KR.DFR.LEV", params={"lastNObservations": "1", "format": "csvdata"},
                                               headers=UA, timeout=30))
        yc = parse_ecb_csv(r1.text) if r1.status_code == 200 else {}
        curve = {t: yc[f"YC.B.U2.EUR.4F.G_N_A.SV_C_YM.{code}"] for t, code in tenors.items() if f"YC.B.U2.EUR.4F.G_N_A.SV_C_YM.{code}" in yc}
        dfr = parse_ecb_csv(r2.text).get("FM.D.U2.EUR.4F.KR.DFR.LEV") if r2.status_code == 200 else None
        return _row("Euro area (AAA)", dfr, "ECB deposit rate", curve, "2y", "ECB data portal",
                    "https://data.ecb.europa.eu/data/datasets/YC")

    async def uk():
        start = (dt.date.today() - dt.timedelta(days=21)).strftime("%d/%b/%Y")
        r = await http.get(BOE, params={"csv.x": "yes", "Datefrom": start, "Dateto": "now", "SeriesCodes": "IUDBEDR,IUDSOIA,IUDSNZC,IUDMNZC,IUDLNZC",
                                        "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N"}, headers=UA, timeout=30, follow_redirects=True)
        b = parse_boe_csv(r.text) if r.status_code == 200 else {}
        curve = {t: b[c] for t, c in (("3m", "IUDSOIA"), ("5y", "IUDSNZC"), ("10y", "IUDMNZC"), ("30y", "IUDLNZC")) if c in b}
        row = _row("United Kingdom", b.get("IUDBEDR"), "Bank Rate", curve, "5y", "Bank of England database",
                   "https://www.bankofengland.co.uk/boeapps/database/")
        row["note"] = "3m = SONIA (overnight), 30y = 20-year point"
        return row

    async def japan():
        r = await http.get(MOF, headers=UA, timeout=30)
        parsed = parse_mof_csv(r.content.decode("shift_jis", "ignore")) if r.status_code == 200 else None
        if not parsed:
            return _row("Japan", None, "BoJ policy rate", {}, "2y", "Ministry of Finance", MOF)
        day, v = parsed
        curve = {t: (day, v[k]) for t, k in (("1y", "1y"), ("2y", "2y"), ("5y", "5y"), ("10y", "10y"), ("30y", "30y")) if k in v}
        return _row("Japan", None, "BoJ policy rate (no free feed)", curve, "2y", "Ministry of Finance (JGB curve)", MOF)

    async def build():
        rows = await asyncio.gather(us(), euro(), uk(), japan(), return_exceptions=True)
        out = [r for r in rows if not isinstance(r, Exception)]
        if not out:
            return {"error": "no rates source answered"}
        return {"rows": out, "tenors": TENORS,
                "note": "Latest official values, each with its date. '2y minus policy' (UK: 5y) is a rough gauge of the "
                        "rate path the market prices over that horizon - positive means hikes priced or a term premium, "
                        "negative means cuts. Euro area = the ECB's AAA government curve (close to Bunds). Japan's "
                        "policy rate has no free machine-readable source."}
    return await ctx.cache.get("rates:world", 3 * 3600, build, disk=True)


async def collect(ctx) -> int:
    """Data hub: 2y and 10y per country plus the policy rates, so alerts and charts work on them."""
    from .datahub import _meta
    d = await world(ctx)
    n = 0
    for r in d.get("rows", []):
        key = {"United States": "us", "Euro area (AAA)": "ea", "United Kingdom": "uk", "Japan": "jp"}.get(r["country"])
        if not key:
            continue
        for tenor in ("2y", "5y", "10y"):
            if r.get(tenor) is not None and r.get("date"):
                await ctx.db.run(ctx.db.upsert_series, _meta(f"gov:{key}{tenor}", f"{r['country']} {tenor} government yield",
                                                             "Rates by country", r["source"], "rate", "%"), [(r["date"], r[tenor])])
                n += 1
        if r.get("policy") is not None and r.get("policy_date"):
            await ctx.db.run(ctx.db.upsert_series, _meta(f"gov:{key}policy", f"{r['country']} {r['policy_name']}",
                                                         "Rates by country", r["source"], "rate", "%"), [(r["policy_date"], r["policy"])])
    return n
