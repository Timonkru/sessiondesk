"""Earnings nowcast: company proxy collectors, fiscal quarters from SEC facts, regression nowcast, consensus history,
the Quiver adapter and the page API - all offline."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import random

import httpx

from sessiondesk.connectors.keyed import finnhub_history, merge_history
from sessiondesk.connectors.public import parse_form4, parse_form4_list
from sessiondesk.features import nowcast, proxies


def _fact(start, end, val, filed="2026-01-01", fy=2025, fp="Q1"):
    return {"start": start, "end": end, "val": val, "filed": filed, "fy": fy, "fp": fp, "form": "10-Q"}


def _calendar_quarters(years, rev_fn):
    """Calendar-quarter company: three 10-Q quarters per year plus the fiscal year (Q4 has to be derived)."""
    facts = []
    for y in years:
        qs = [(f"{y}-01-01", f"{y}-03-31"), (f"{y}-04-01", f"{y}-06-30"), (f"{y}-07-01", f"{y}-09-30"), (f"{y}-10-01", f"{y}-12-31")]
        vals = [rev_fn(y, i) for i in range(4)]
        for i, (s, e) in enumerate(qs[:3]):
            facts.append(_fact(s, e, vals[i], filed=f"{y}-{3 * i + 4:02d}-20", fy=y, fp=f"Q{i + 1}"))
        facts.append({**_fact(f"{y}-01-01", f"{y}-12-31", sum(vals), filed=f"{y + 1}-02-01", fy=y, fp="FY"), "form": "10-K"})
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": facts}}}}}


def test_sec_quarters_derive_q4_prefer_concepts_and_restatements():
    facts = _calendar_quarters([2024, 2025], lambda y, i: 100.0 + i + (y - 2024) * 10)
    q = nowcast.sec_quarters(facts)
    assert [x["end"] for x in q] == ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30",
                                      "2025-09-30", "2025-12-31"]
    assert q[3]["revenue"] == 103.0 and q[3]["derived"] and q[3]["start"] == "2024-10-01"
    # a preferred concept wins over 'Revenues'; within a concept the latest filing wins (restatement)
    facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [
        _fact("2025-01-01", "2025-03-31", 999.0, filed="2025-04-20"), _fact("2025-01-01", "2025-03-31", 111.0, filed="2026-04-20")]}}
    q = {x["end"]: x for x in nowcast.sec_quarters(facts)}
    assert q["2025-03-31"]["revenue"] == 111.0
    assert nowcast.sec_quarters({}) == []


def test_year_ago_and_next_quarter_follow_52_week_years():
    q = [{"start": "2024-06-30", "end": "2024-09-28", "revenue": 1}, {"start": "2024-09-29", "end": "2024-12-28", "revenue": 1},
         {"start": "2025-06-29", "end": "2025-09-27", "revenue": 1}]
    assert nowcast.year_ago(q, q[2])["end"] == "2024-09-28"
    nxt = nowcast.next_quarter(q)
    assert nxt["start"] == "2025-09-28" and nxt["year_ago"]["end"] == "2024-12-28"
    assert nxt["end"] == (dt.date(2025, 9, 28) + dt.timedelta(days=90)).isoformat()
    assert nowcast.next_quarter([]) is None and nowcast.year_ago(q, q[0]) is None


def test_proxy_change_z_ols_beats():
    pts = [((dt.date(2024, 1, 1) + dt.timedelta(days=i)).isoformat(), 100.0 if i < 366 else 110.0) for i in range(800)]
    c = nowcast.proxy_change(pts, "2025-01-01", "2025-03-31")
    assert abs(c["value"] - 10.0) < 1e-9 and c["unit"] == "%"
    rank = [("2024-02-01", 50.0), ("2025-02-01", 20.0)]
    assert nowcast.proxy_change(rank, "2025-01-01", "2025-03-31", lower_better=True, min_coverage=0) == \
        {"value": 30.0, "now": 20.0, "ago": 50.0, "days": 1, "unit": "places"}
    assert nowcast.proxy_change(pts[:10], "2025-01-01", "2025-03-31") is None            # no year-ago data
    assert nowcast.small_z([1.0] * 3, 5.0) is None and nowcast.small_z([1, 2, 3, 4, 5, 6, 7, 8], 4.5) == 0.0
    f = nowcast.ols([1, 2, 3, 4], [3, 5, 7, 9.5])
    assert abs(f["b"] - 2.15) < 1e-9 and f["n"] == 4 and f["r"] > 0.99
    assert nowcast.ols([1, 1, 1], [1, 2, 3]) is None
    b = nowcast.beat_rate([{"e": 1, "a": 2}, {"e": 1, "a": 0.5}, {"e": 1, "a": None}], "e", "a")
    assert b["n"] == 2 and b["beats"] == 1 and b["rate"] == 0.5 and nowcast.beat_rate([], "e", "a") is None


def test_analyse_nowcast_needs_eight_quarters_and_uses_the_fixed_primary():
    rnd = random.Random(7)
    years = list(range(2017, 2026))
    growth = {y: rnd.uniform(-5, 15) for y in years}

    def rev(y, i):
        r = 1000.0
        for yy in years[: years.index(y) + 1]:
            r *= 1 + growth[yy] / 100
        return r
    quarters = nowcast.sec_quarters(_calendar_quarters(years, rev))
    # a proxy whose level grows with the same yearly rates (+ noise): YoY of proxy ~ YoY of revenue
    pts, day, level = [], dt.date(2016, 1, 1), 100.0
    while day <= dt.date(2026, 2, 15):
        g = growth.get(day.year, 0.0)
        pts.append((day.isoformat(), level * (1 + g / 100) * (1 + rnd.gauss(0, 0.002))))
        if day.month == 12 and day.day == 31:
            level *= 1 + g / 100
        day += dt.timedelta(days=1)
    res = nowcast.analyse(quarters, {"wiki": pts, "steam": pts[-30:]}, "wiki", today=dt.date(2026, 2, 15))
    assert res["quarter"]["start"] == "2026-01-01" and res["quarter"]["running"]
    w = res["proxies"]["wiki"]
    assert w["fit"]["n"] >= 8 and w["fit"]["r"] > 0.9 and w["z"] is not None
    assert res["nowcast"]["proxy"] == "wiki" and res["nowcast"]["partial"] and res["nowcast"]["revenue"] > 0
    assert "fit" not in res["proxies"]["steam"]                                           # 30 days: no history
    res = nowcast.analyse(quarters, {"steam": pts[-30:]}, "steam", today=dt.date(2026, 2, 15))
    assert res["nowcast"]["missing"].startswith("needs 8 quarters")
    assert not res["quarter"]["stale"]
    old = nowcast.analyse(quarters[:-4], {"wiki": pts}, "wiki", today=dt.date(2026, 2, 15))       # SEC data end a year early
    assert old["quarter"]["stale"] and old["nowcast"] is None and old["quarter"]["last_filed"] == "2024-12-31"
    gap = nowcast.consensus_gap({"growth": 10.0, "resid_sd": 2.0}, 1050.0, 1000.0)
    assert abs(gap["implied_growth"] - 5.0) < 1e-9 and abs(gap["gap_pp"] - 5.0) < 1e-9 and abs(gap["gap_sd"] - 2.5) < 1e-9
    assert nowcast.consensus_gap(None, 1, 1) is None


def test_diverging_needs_gap_and_proxy_in_the_same_direction():
    cfg = nowcast.alert_config({})
    assert cfg == {"enabled": False, "gap_sd": 2.0, "min_z": 2.0}                       # off by default
    row = {"symbol": "X", "primary": "wiki", "gap": {"gap_sd": 2.5}, "proxies": {"wiki": {"z": 2.1}}}
    assert nowcast.diverging([row], cfg) == [row]
    assert nowcast.diverging([{**row, "proxies": {"wiki": {"z": -2.1}}}], cfg) == []
    assert nowcast.diverging([{**row, "gap": {"gap_sd": 1.0}}], cfg) == []
    assert nowcast.diverging([{**row, "gap": None}], cfg) == []


def test_proxy_parsers():
    assert proxies.parse_wiki({"items": [{"timestamp": "2026090100", "views": 5674}, {"timestamp": "x"}]}) == [("2026-09-01", 5674.0)]
    assert proxies.wiki_title(" iPhone") == "IPhone" and proxies.wiki_title("Tesla, Inc.") == "Tesla,_Inc."
    html = ('<tr><td class="a">10/29/2026</td>\n<td class="a">2,516,359</td></tr>'
            '<tr><td class="a">1/2/2024</td><td class="a">2,555,447</td></tr>')
    assert proxies.parse_tsa(html) == [("2024-01-02", 2555447.0), ("2026-10-29", 2516359.0)]
    feed = {"feed": {"entry": [{"id": {"attributes": {"im:id": "1"}}}, {"id": {"attributes": {"im:id": "570060128"}}}]}}
    assert proxies.parse_apps(feed) == {"1": 1, "570060128": 2}
    csv = ("date,jobcountry,indeed_job_postings_index,variable,display_name\n"
           "2020-02-01,US,100,total postings,Software Development\n2020-02-01,US,100,new postings,Software Development\n"
           "2020-02-02,US,99.5,total postings,Software Development\n2020-02-01,US,100,total postings,Nursing\n")
    assert proxies.parse_indeed(csv, {"software_development"}) == {"software_development": [("2020-02-01", 100.0), ("2020-02-02", 99.5)]}
    agg = "date,jobcountry,indeed_job_postings_index_SA,indeed_job_postings_index_NSA,variable\n2020-02-01,US,100,100,total postings\n"
    assert proxies.parse_indeed(agg, {"total"}) == {"total": [("2020-02-01", 100.0)]}
    ids = proxies.series_ids("dal", {"wikipedia": ["Delta Air Lines"], "tsa": True, "apps": [1], "indeed": {"sector": "Aviation"}})
    assert ids == {"wiki": "wiki:DAL", "tsa": "tsa:us", "apps_grossing": "apps:DAL:grossing", "apps_free": "apps:DAL:free",
                   "indeed": "indeed:US:aviation", "insiders": "form4:DAL:net"}
    assert "insiders" not in proxies.series_ids("SAP.DE", {"wikipedia": ["SAP"]})


def test_form4_parsing_and_monthly_net():
    xml = """<?xml version="1.0"?><ownershipDocument><nonDerivativeTable>
      <nonDerivativeTransaction><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>10.5</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
      <nonDerivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>20</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
      <nonDerivativeTransaction><transactionCoding><transactionCode>M</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>999</value></transactionShares><transactionPricePerShare><value>1</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
      </nonDerivativeTable></ownershipDocument>"""
    assert parse_form4(xml) == {"buy_usd": 200.0, "sell_usd": 1050.0, "buys": 1, "sells": 1}
    assert parse_form4("not xml")["buys"] == 0
    subs = {"filings": {"recent": {"form": ["4", "8-K", "4"], "accessionNumber": ["0001-26-000004", "x", "0002-26-1"],
                                   "primaryDocument": ["xslF345X06/wk-form4_1.xml", "a.htm", "doc.htm"], "filingDate": ["2026-10-29", "", ""]}}}
    assert parse_form4_list(subs, 1065280, 10) == [{"accession": "0001-26-000004", "date": "2026-10-29",
                                                    "xml": "https://www.sec.gov/Archives/edgar/data/1065280/000126000004/wk-form4_1.xml"}]
    seen = {"a": {"date": "2026-07-15", "buy_usd": 0, "sell_usd": 500}, "b": {"date": "2026-09-02", "buy_usd": 100, "sell_usd": 0}}
    pts = proxies.monthly_net(seen)
    assert pts[:2] == [("2026-08-01", 0.0), ("2026-09-01", 100.0)]                       # July (oldest, maybe partial) left out


def test_consensus_history_shapes():
    cal = {"earningsCalendar": [{"date": "2026-07-17", "year": 2026, "quarter": 2, "epsEstimate": 7.0, "epsActual": 7.2,
                                 "revenueEstimate": 11e9, "revenueActual": 11.1e9}]}
    eps = [{"period": "2026-06-30", "year": 2026, "quarter": 2, "estimate": 6.9, "actual": 7.2},
           {"period": "2026-03-31", "year": 2026, "quarter": 1, "estimate": 6.0, "actual": 6.5}]
    rows = merge_history(finnhub_history(eps, cal))
    assert [r["date"] for r in rows] == ["2026-03-31", "2026-07-17"]
    assert rows[1]["eps_estimate"] == 7.0 and rows[1]["period"] == "2026-06-30" and rows[1]["revenue_actual"] == 11.1e9
    assert rows[0]["revenue_estimate"] is None
    assert merge_history([{"date": "2026-01-01"}]) == []


def test_collectors_store_series(client, monkeypatch):
    ctx = client.app_state["ctx"]
    monkeypatch.setattr(proxies, "PAUSE", 0)
    m = proxies.load_map(ctx)                                    # first use writes the neutral example file
    assert (ctx.data_dir / proxies.FILE).exists() and set(m["companies"]) == {"NFLX", "DAL", "EA", "DUOL"}
    seen = []

    def handler(request):
        url = str(request.url)
        seen.append(url)
        if "wikimedia.org" in url:
            return httpx.Response(200, json={"items": [{"timestamp": "2026102900", "views": 10}, {"timestamp": "2026103000", "views": 12}]})
        if "steampowered" in url:
            return httpx.Response(200, json={"response": {"player_count": 1000, "result": 1}})
        if "itunes.apple.com" in url:
            return httpx.Response(200, json={"feed": {"entry": [{"id": {"attributes": {"im:id": "570060128"}}}]}})
        if "hiring-lab" in url:
            return httpx.Response(200, text="date,jobcountry,indeed_job_postings_index,variable,display_name\n"
                                            "2026-10-20,US,80,total postings,Media & Communications\n")
        if "tsa.gov" in url:
            return httpx.Response(200, text='<td>10/29/2026</td><td>2,516,359</td>')
        return httpx.Response(404)
    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    n = asyncio.run(proxies.collect(ctx))
    assert n >= 7
    assert ctx.db.observations("wiki:NFLX", 10) == [("2026-10-29", 10.0), ("2026-10-30", 12.0)]
    assert ctx.db.observations("steam:EA", 10)[-1][1] == 3000.0                     # three games summed
    assert ctx.db.observations("apps:DUOL:grossing", 10)[-1][1] == 1.0
    assert ctx.db.observations("indeed:US:media_communications", 10) == [("2026-10-20", 80.0)]
    assert ctx.db.observations("tsa:us", 10) == [("2026-10-29", 2516359.0)]
    assert not any("sec.gov/Archives" in u for u in seen)                             # Form 4 needs the SEC contact email
    hub = {s["id"]: s for s in client.get("/api/hub").json()["series"]}
    assert hub["wiki:NFLX"]["group"] == "companies" and hub["tsa:us"]["url"].startswith("https://www.tsa.gov")
    from sessiondesk.features import datahub
    assert not datahub.warns("wiki:NFLX") and not datahub.warns("form4:NFLX:net")


def test_nowcast_api_unvalidated_alert_off_and_no_key_leak(client, monkeypatch):
    from sessiondesk.features import deep
    ctx = client.app_state["ctx"]

    async def street(_ctx, symbol):
        return {"revenue_estimates": [{"period": "0q", "avg": 12.5e9, "yearAgoRevenue": 11.5e9, "numberOfAnalysts": 30}]}

    async def earnings(_ctx, symbol):
        return {"history": [{"eps_estimate": 1.0, "eps_reported": 1.1}, {"eps_estimate": 1.0, "eps_reported": 0.9},
                            {"eps_estimate": 1.0, "eps_reported": 1.2}], "upcoming": {"when": "2027-01-20T21:00:00+00:00"}}
    monkeypatch.setattr(deep, "street", street)
    monkeypatch.setattr(deep, "earnings", earnings)
    d = client.get("/api/nowcast").json()
    assert d["validation"]["status"] == "unvalidated" and "Unvalidated" in d["validation"]["text"]
    assert d["alert"]["enabled"] is False and d["keys"] == {"fmp": False, "finnhub": False, "quiver": False}
    rows = {r["symbol"]: r for r in d["rows"]}
    assert {"NFLX", "DAL", "EA", "DUOL"} <= set(rows)
    r = rows["NFLX"]
    assert r["consensus"]["source"] == "Yahoo (free)" and r["consensus"]["revenue"] == 12.5e9
    assert r["consensus_history"]["status"] == "key needed" and r["beat_revenue"] is None
    assert r["beat_eps"]["beats"] == 2 and r["beat_eps"]["n"] == 3 and r["report_date"] == "2027-01-20"
    text = json.dumps(d).lower()
    assert "buy signal" not in text and "sell signal" not in text
    # the verdict of the pending test goes into the mapping file, not the code
    p = ctx.data_dir / proxies.FILE
    m = json.loads(p.read_text(encoding="utf-8"))
    m["validation"] = {"status": "no edge", "text": "Out-of-sample: no edge."}
    p.write_text(json.dumps(m), encoding="utf-8")
    assert client.get("/api/nowcast?fresh=1").json()["validation"] == {"status": "no edge", "text": "Out-of-sample: no edge."}
    # alert: off -> no check; switched on it is stored
    assert asyncio.run(nowcast.run_check(ctx)) == []
    a = client.put("/api/nowcast_alert", json={"enabled": True, "gap_sd": 3}).json()["alert"]
    assert a == {"enabled": True, "gap_sd": 3.0, "min_z": 2.0}
    # Quiver: listed, unverified, its key never comes back
    key = "quivertoken12345678"
    r = client.post("/api/connectors/quiver", json={"enabled": True, "fields": {"api_key": key}}).json()
    assert key not in str(r)
    conns = client.get("/api/connectors").json()
    q = next(c for c in conns["items"] if c["id"] == "quiver")
    assert q["verified"] is False and q["tier"] == "paid"
    for path in ("/api/connectors", "/api/nowcast?fresh=1"):
        assert key not in client.get(path).text
