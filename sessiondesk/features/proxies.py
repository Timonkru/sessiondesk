"""Company proxies for the Data hub: free numbers that move with one company's business, collected per company.

  wiki      Wikipedia pageviews of the company's / brand's articles (Wikimedia REST API, daily, from 2015-07)
  tsa       TSA checkpoint travel numbers (tsa.gov, daily, from 2019) - one US series, for airlines
  steam     concurrent players of the company's games (Steam Web API, no key) - a snapshot per run, the day keeps
            the highest snapshot; Steam publishes no history, so the series starts with the first run
  apps      rank of the company's apps in Apple's US top-grossing and top-free charts (Apple RSS, top 100 only);
            no point on days the app is not in the top 100; history starts with the first run
  indeed    Indeed Hiring Lab job postings index per country and occupational category (GitHub CSV, from 2020-02);
            categories are job types ("Software Development"), not companies or industries
  insiders  open-market insider purchases minus sales per month from SEC Form 4 (code P and S only), via the SEC
            connector; needs the SEC contact email (Settings -> Connectors -> SEC EDGAR)
Google Trends is left out: there is no official API, the unofficial one answers 429 after a few calls and returns
numbers rescaled per request, so a stored history would not be comparable.

Which company gets which proxy is the user's file <data dir>/earnings_proxies.json (created with neutral examples on
first use; see docs/CONNECTORS.md). None of these proxies is validated as an earnings predictor - the Earnings
nowcast page says so on every row.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import json
import re
import urllib.parse

from ..connectors.base import ConnectorError

FILE = "earnings_proxies.json"
CATEGORY = "Company proxies"
UA = {"User-Agent": "SessionDesk/0.1 (+https://github.com/Timonkru/sessiondesk)"}
WIKI_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
            "{article}/daily/{start}/{end}")
WIKI_START = dt.date(2015, 7, 1)
TSA_URL = "https://www.tsa.gov/travel/passenger-volumes"
TSA_FIRST_YEAR = 2019
STEAM_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
APPS_URLS = {"grossing": "https://itunes.apple.com/us/rss/topgrossingapplications/limit=100/json",
             "free": "https://itunes.apple.com/us/rss/topfreeapplications/limit=100/json"}
INDEED_URL = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/{cc}/job_postings_by_sector_{cc}.csv"
INDEED_TOTAL_URL = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/{cc}/aggregate_job_postings_{cc}.csv"
FORM4_PER_RUN = 40                  # new Form 4 documents fetched per company and run (SEC allows 10 requests/s)
FORM4_PAUSE = 0.15
PAUSE = 0.5                         # between calls to the same free source

DEFAULT_MAP = {
    "_help": "Ticker -> free proxies. wikipedia: article titles on en.wikipedia (summed); tsa: true for US airlines; "
             "steam: Steam app ids (players summed); apps: Apple App Store ids (best rank counts); indeed: "
             "{country, sector} with sector = an Indeed category name, or 'total'; primary: the proxy the nowcast "
             "regression uses (wiki, tsa, steam, apps_grossing, apps_free, indeed) - fixed in advance, never picked "
             "by fit. Insider trades (SEC Form 4) are collected for every US ticker listed here.",
    "companies": {
        "NFLX": {"wikipedia": ["Netflix"], "indeed": {"country": "US", "sector": "Media & Communications"}, "primary": "wiki"},
        "DAL": {"wikipedia": ["Delta Air Lines"], "tsa": True, "primary": "tsa"},
        "EA": {"wikipedia": ["Electronic Arts"], "steam": [1172470, 2807960, 3405690], "primary": "steam"},
        "DUOL": {"wikipedia": ["Duolingo"], "apps": [570060128], "primary": "apps_grossing"},
    },
}
PROXIES = {"wiki": "Wikipedia pageviews", "tsa": "TSA checkpoint travellers", "steam": "Steam concurrent players",
           "apps_grossing": "App Store top-grossing rank", "apps_free": "App Store top-free rank",
           "indeed": "Indeed job postings index", "insiders": "Insider net purchases (Form 4)"}
LOWER_IS_BETTER = {"apps_grossing", "apps_free"}


# ------------------------------------------------------------------ the user's mapping file
def path(ctx):
    return ctx.data_dir / FILE


def load_map(ctx) -> dict:
    """The mapping file; written with the neutral examples when it does not exist yet."""
    p = path(ctx)
    if not p.exists():
        try:
            p.write_text(json.dumps(DEFAULT_MAP, indent=2), encoding="utf-8")
        except OSError:
            return {**DEFAULT_MAP, "error": f"could not write {p.name}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"companies": {}, "error": f"{p.name} is not valid JSON: {exc}"}
    comp = data.get("companies") if isinstance(data.get("companies"), dict) else {}
    return {**data, "companies": {str(k).upper(): v for k, v in comp.items() if isinstance(v, dict)}}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def series_ids(ticker: str, entry: dict) -> dict[str, str]:
    """proxy key -> Data hub series id for one mapped company (pure, tested)."""
    t = ticker.upper()
    out = {}
    if entry.get("wikipedia"):
        out["wiki"] = f"wiki:{t}"
    if entry.get("tsa"):
        out["tsa"] = "tsa:us"
    if entry.get("steam"):
        out["steam"] = f"steam:{t}"
    if entry.get("apps"):
        out["apps_grossing"] = f"apps:{t}:grossing"
        out["apps_free"] = f"apps:{t}:free"
    ind = entry.get("indeed")
    if isinstance(ind, dict) and ind.get("sector"):
        out["indeed"] = f"indeed:{str(ind.get('country') or 'US').upper()}:{slug(ind['sector'])}"
    if "." not in t:
        out["insiders"] = f"form4:{t}:net"
    return out


def _meta(id_, name, source, kind="level", unit=""):
    return {"id": id_, "name": name, "category": CATEGORY, "source": source, "kind": kind, "unit": unit}


async def _have(ctx, sid: str, n: int = 400):
    return await ctx.db.run(ctx.db.observations, sid, n)


# ------------------------------------------------------------------ Wikipedia
def wiki_title(article: str) -> str:
    """Wikipedia stores titles with a capital first letter: 'iPhone' is the page 'IPhone' - asked as 'iPhone', the
    pageviews API answers with a few stray days only (checked 2026-10-31) (pure, tested)."""
    t = article.strip().replace(" ", "_")
    return t[:1].upper() + t[1:]


def parse_wiki(payload: dict) -> list[tuple[str, float]]:
    """Wikimedia per-article rows -> [(day, views)] (pure, tested)."""
    out = []
    for r in (payload or {}).get("items") or []:
        ts = str(r.get("timestamp") or "")
        if len(ts) >= 8 and r.get("views") is not None:
            out.append((f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", float(r["views"])))
    return out


async def collect_wiki(ctx, companies: dict) -> int:
    from .datahub import sum_complete
    today = dt.date.today()
    n = 0
    for t, entry in companies.items():
        arts = [a for a in entry.get("wikipedia") or [] if isinstance(a, str) and a.strip()]
        if not arts:
            continue
        sid = f"wiki:{t}"
        start = WIKI_START if len(await _have(ctx, sid, 400)) < 365 else today - dt.timedelta(days=45)
        parts = []
        for a in arts:
            url = WIKI_URL.format(article=urllib.parse.quote(wiki_title(a), safe=""),
                                  start=start.strftime("%Y%m%d"), end=today.strftime("%Y%m%d"))
            try:
                resp = await ctx.http.get(url, headers=UA, timeout=60)
            except Exception:
                parts = []
                break
            if resp.status_code == 429:
                return n
            parts.append(parse_wiki(resp.json()) if resp.status_code == 200 else [])
            await asyncio.sleep(PAUSE)
        pts = sum_complete(parts) if len(parts) == len(arts) else []
        if pts:
            await ctx.db.run(ctx.db.upsert_series, _meta(sid, f"{t} Wikipedia pageviews ({', '.join(arts)})",
                                                         "Wikimedia pageviews API (en.wikipedia, users)", "count"), pts)
            n += 1
    return n


# ------------------------------------------------------------------ TSA
def parse_tsa(html: str) -> list[tuple[str, float]]:
    """tsa.gov passenger-volumes table: 'M/D/YYYY | 2,516,359' rows -> [(day, travellers)] (pure, tested)."""
    out = {}
    for m, d, y, v in re.findall(r"<td[^>]*>\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*</td>\s*<td[^>]*>\s*([\d,]+)\s*</td>", html):
        out[f"{y}-{int(m):02d}-{int(d):02d}"] = float(v.replace(",", ""))
    return sorted(out.items())


async def collect_tsa(ctx) -> int:
    have = await _have(ctx, "tsa:us", 400)
    urls = [TSA_URL]
    if len(have) < 300:
        urls += [f"{TSA_URL}/{y}" for y in range(TSA_FIRST_YEAR, dt.date.today().year)]
    pts = []
    for url in urls:
        try:
            resp = await ctx.http.get(url, headers={"User-Agent": "Mozilla/5.0 (SessionDesk)"}, timeout=40, follow_redirects=True)
        except Exception:
            continue
        if resp.status_code == 200:
            pts += parse_tsa(resp.text)
        await asyncio.sleep(PAUSE)
    if not pts:
        return 0
    await ctx.db.run(ctx.db.upsert_series, _meta("tsa:us", "TSA checkpoint travel numbers (US, travellers per day)",
                                                 "TSA checkpoint travel numbers (tsa.gov)"), sorted(dict(pts).items()))
    return 1


# ------------------------------------------------------------------ Steam
async def collect_steam(ctx, companies: dict) -> int:
    today = dt.date.today().isoformat()
    n = 0
    for t, entry in companies.items():
        apps = [a for a in entry.get("steam") or [] if str(a).isdigit()]
        if not apps:
            continue
        total = 0
        for a in apps:
            try:
                resp = await ctx.http.get(STEAM_URL, params={"appid": a}, headers=UA, timeout=20)
                r = (resp.json().get("response") or {}) if resp.status_code == 200 else {}
            except Exception:
                r = {}
            if r.get("result") != 1:
                total = None
                break
            total += int(r.get("player_count") or 0)
            await asyncio.sleep(PAUSE)
        if total is None:
            continue
        sid = f"steam:{t}"
        have = dict(await _have(ctx, sid, 3))
        value = max(total, have.get(today, 0))          # the day keeps its highest snapshot
        await ctx.db.run(ctx.db.upsert_series, _meta(sid, f"{t} Steam concurrent players (highest snapshot of the day, apps {', '.join(map(str, apps))})",
                                                     "Steam Web API GetNumberOfCurrentPlayers (snapshots taken by SessionDesk)"), [(today, float(value))])
        n += 1
    return n


# ------------------------------------------------------------------ Apple App Store charts
def parse_apps(payload: dict) -> dict[str, int]:
    """iTunes RSS chart -> {app id: rank} (pure, tested)."""
    out = {}
    for i, e in enumerate(((payload or {}).get("feed") or {}).get("entry") or [], start=1):
        aid = ((e.get("id") or {}).get("attributes") or {}).get("im:id")
        if aid:
            out[str(aid)] = i
    return out


async def collect_apps(ctx, companies: dict) -> int:
    wanted = {t: [str(a) for a in e.get("apps") or []] for t, e in companies.items() if e.get("apps")}
    if not wanted:
        return 0
    today = dt.date.today().isoformat()
    n = 0
    for chart, url in APPS_URLS.items():
        try:
            resp = await ctx.http.get(url, headers=UA, timeout=30, follow_redirects=True)
            ranks = parse_apps(resp.json()) if resp.status_code == 200 else {}
        except Exception:
            ranks = {}
        if not ranks:
            continue
        for t, ids in wanted.items():
            best = min((ranks[a] for a in ids if a in ranks), default=None)
            if best is None:
                continue                        # not in the top 100 today: no point rather than an invented rank
            await ctx.db.run(ctx.db.upsert_series, _meta(f"apps:{t}:{chart}", f"{t} App Store US top-{chart} rank (best of its apps; 1 = top)",
                                                         f"Apple iTunes RSS top-{chart} chart (US, top 100)", "level"), [(today, float(best))])
            n += 1
        await asyncio.sleep(PAUSE)
    return n


# ------------------------------------------------------------------ Indeed Hiring Lab
def parse_indeed(text: str, sectors: set[str]) -> dict[str, list[tuple[str, float]]]:
    """Hiring Lab CSV -> {sector slug: [(day, index)]} for the wanted categories, 'total postings' only; the aggregate
    file (seasonally adjusted column) answers for 'total' (pure, tested)."""
    out: dict[str, list[tuple[str, float]]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("variable") not in (None, "total postings"):
            continue
        name = r.get("display_name") or "total"
        key = slug(name)
        if key not in sectors:
            continue
        v = r.get("indeed_job_postings_index") or r.get("indeed_job_postings_index_SA")
        try:
            out.setdefault(key, []).append((r["date"], float(v)))
        except (TypeError, ValueError, KeyError):
            continue
    return out


async def collect_indeed(ctx, companies: dict) -> int:
    want: dict[str, set[str]] = {}
    for e in companies.values():
        ind = e.get("indeed")
        if isinstance(ind, dict) and ind.get("sector"):
            want.setdefault(str(ind.get("country") or "US").upper(), set()).add(slug(ind["sector"]))
    n = 0
    for cc, sectors in want.items():
        if not re.fullmatch(r"[A-Z]{2}", cc):
            continue

        async def build(cc=cc, sectors=sectors):
            got: dict = {}
            for url, need in ((INDEED_URL, sectors - {"total"}), (INDEED_TOTAL_URL, sectors & {"total"})):
                if not need:
                    continue
                resp = await ctx.http.get(url.format(cc=cc), headers=UA, timeout=120)
                if resp.status_code != 200:
                    raise ConnectorError(f"Indeed Hiring Lab HTTP {resp.status_code}")
                got.update(parse_indeed(resp.text, need))
            return {"series": got}
        # the sector file is ~12 MB: once a day is plenty (Hiring Lab updates daily, a few days behind)
        res = await ctx.cache.get(f"proxies:indeed:{cc}:{','.join(sorted(sectors))}", 86400, build, disk=True)
        for key, pts in (res.get("series") or {}).items():
            await ctx.db.run(ctx.db.upsert_series, _meta(f"indeed:{cc}:{key}", f"Indeed job postings {cc} {key.replace('_', ' ')} (index, Feb 2020 = 100)",
                                                         "Indeed Hiring Lab job postings tracker (GitHub, CC BY 4.0)"), [tuple(p) for p in pts])
            n += 1
    return n


# ------------------------------------------------------------------ SEC Form 4
def _seen_path(ctx):
    return ctx.data_dir / "form4_seen.json"


def monthly_net(seen: dict) -> list[tuple[str, float]]:
    """{accession: {date, buy_usd, sell_usd}} -> [(YYYY-MM-01, purchases - sales in USD)] for every month after the
    month of the oldest filing seen (that one may be incomplete) up to the newest; months without trades are 0
    (pure, tested)."""
    rows = [v for v in seen.values() if v.get("date")]
    if not rows:
        return []
    months: dict[str, float] = {}
    for v in rows:
        m = v["date"][:7]
        months[m] = months.get(m, 0.0) + float(v.get("buy_usd") or 0) - float(v.get("sell_usd") or 0)
    first, last = min(months), max(max(months), dt.date.today().strftime("%Y-%m"))
    out, y, mo = [], int(first[:4]), int(first[5:7])
    while True:
        mo += 1
        if mo > 12:
            y, mo = y + 1, 1
        key = f"{y:04d}-{mo:02d}"
        if key > last:
            break
        out.append((key + "-01", round(months.get(key, 0.0), 2)))
    return out


async def collect_form4(ctx, companies: dict) -> int:
    sec = ctx.hub.get("sec") if ctx.hub else None
    if not sec or not sec.enabled() or not sec.option("contact_email"):
        return 0
    try:
        seen_all = json.loads(_seen_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen_all = {}
    from ..connectors.public import parse_form4
    n = 0
    for t in companies:
        if "." in t:
            continue
        try:
            filings = await sec.form4_list(t, 60)
        except ConnectorError:
            continue
        seen = seen_all.setdefault(t, {})
        for f in [f for f in filings if f["accession"] not in seen][:FORM4_PER_RUN]:
            try:
                doc = await sec.form4_document(f["xml"])
            except ConnectorError:
                break
            seen[f["accession"]] = {"date": f["date"], **parse_form4(doc)}
            await asyncio.sleep(FORM4_PAUSE)
        pts = monthly_net(seen)
        if pts:
            await ctx.db.run(ctx.db.upsert_series, _meta(f"form4:{t}:net", f"{t} insider open-market purchases minus sales (USD per month)",
                                                         "SEC EDGAR Form 4 (codes P and S)"), pts)
            n += 1
        await asyncio.sleep(FORM4_PAUSE)
    try:
        _seen_path(ctx).write_text(json.dumps(seen_all), encoding="utf-8")
    except OSError:
        pass
    return n


# ------------------------------------------------------------------ the Data hub collector
async def collect(ctx) -> int:
    """All company proxies of the mapping file, one source after the other; a failing source does not stop the rest."""
    companies = load_map(ctx).get("companies") or {}
    n = 0
    for fn in (collect_wiki, collect_steam, collect_apps, collect_indeed, collect_form4):
        try:
            n += await fn(ctx, companies)
        except Exception as exc:                    # noqa: BLE001 - one source down must not block the others
            ctx.extras.setdefault("proxy_errors", {})[fn.__name__] = f"{type(exc).__name__}: {exc}"
    if any(e.get("tsa") for e in companies.values()):
        try:
            n += await collect_tsa(ctx)
        except Exception as exc:                    # noqa: BLE001
            ctx.extras.setdefault("proxy_errors", {})["collect_tsa"] = f"{type(exc).__name__}: {exc}"
    return n
