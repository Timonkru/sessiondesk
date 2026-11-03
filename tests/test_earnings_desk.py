"""Earnings desk: reading a press release by rules, the basis check that decides whether hit or miss may be shown, times
with their kind, consensus freezing, the collector's polling discipline, saved files - all offline."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time

import httpx
import pytest

from sessiondesk.connectors.public import nasdaq_actual, parse_current_feed, parse_earnings_filings, parse_filing_index, parse_nasdaq_surprise
from sessiondesk.features import earnings_desk as desk
from sessiondesk.features import earnings_parse as ep
from sessiondesk.push import config as push_config, format_event

LRCX_LIKE = """<html><body>
<p>Example Research Reports Financial Results for the Quarter Ended September 27, 2026</p>
<p>Revenue of $8.22 billion. U.S. GAAP diluted EPS of $2.19. Non-GAAP diluted EPS of $2.20.</p>
<table><tr><td>(in thousands, except per share data)</td></tr>
<tr><td>U.S. GAAP</td></tr>
<tr><td></td><td>September 2026</td><td>June 2026</td><td>Change Q/Q</td></tr>
<tr><td>Revenue</td><td>$</td><td>8,219,418</td><td>$</td><td>6,722,238</td><td>+22%</td></tr>
<tr><td>Diluted EPS</td><td>$</td><td>2.19</td><td>$</td><td>1.81</td><td>+ 21%</td></tr>
<tr><td>Non-GAAP</td></tr>
<tr><td></td><td>September 2026</td><td>June 2026</td><td>Change Q/Q</td></tr>
<tr><td>Diluted EPS</td><td>$</td><td>2.20</td><td>$</td><td>1.82</td><td>+ 21%</td></tr>
</table>
<p>Outlook</p>
<p>For the quarter ending December 27, 2026, the company is providing the following guidance:</p>
<table><tr><td>Revenue</td><td>$8.60 Billion</td></tr><tr><td>Net income per diluted share</td><td>$2.33</td></tr></table>
<p>The company will host a conference call today at 2:00 p.m. PT. A live <a href="https://investor.example.com/webcast">webcast</a> is available.</p>
<p>Statements in this release that are forward-looking statements may differ from actual results; we expect 12% growth in revenue.</p>
</body></html>"""

GE_LIKE = """<html><body>
<p>EXAMPLE AEROSPACE ANNOUNCES THIRD QUARTER 2026 RESULTS</p>
<p>Total Company Results &amp; Guidance</p>
<table><tr><td>Dollars in millions; per-share amounts in dollars, diluted</td><td>2026</td><td>2025</td><td>Year on Year</td></tr>
<tr><td>GAAP Metrics</td></tr>
<tr><td>Total Revenue</td><td>$14,118</td><td>$12,181</td><td>16</td><td>%</td></tr>
<tr><td>Continuing EPS</td><td>2.32</td><td>2.04</td><td>14</td><td>%</td></tr>
<tr><td>Non-GAAP Metrics</td></tr>
<tr><td>Adjusted EPS</td><td>2.25</td><td>1.66</td><td>36</td><td>%</td></tr>
</table></body></html>"""


def test_blocks_keep_table_rows_and_drop_scripts():
    bl = ep.blocks("<html><script>alert(1)</script><p>Hello <b>you</b></p><table><tr><td>A</td><td></td><td>1</td></tr></table></html>")
    assert bl[0] == {"kind": "text", "text": "Hello you", "links": []}
    assert bl[1]["rows"] == [["A", "1"]]
    assert "alert" not in ep.plain_text("<script>alert(1)</script><p>x</p>")


def test_row_values_drop_percentages_and_keep_negatives():
    assert ep.row_values(["Diluted EPS", "$", "2.19", "$", "1.81", "+ 21%"]) == ("Diluted EPS", [2.19, 1.81])
    assert ep.row_values(["Net loss per share", "(", "0.12", ")", "0.30"]) == ("Net loss per share", [-0.12, 0.30])
    assert ep.row_values(["Adjusted EPS", "2.25", "1.66", "36", "%"])[1] == [2.25, 1.66]
    assert ep.row_values(["Item", "—", "1.50"])[1] == [None, 1.5]


def test_parse_finds_both_bases_with_quotes_and_skips_guidance():
    r = ep.parse_release(LRCX_LIKE)
    tables = [c for c in r["eps"] if c["where"] == "table"]
    assert [(c["value"], c["basis"]) for c in tables] == [(2.19, "gaap"), (2.2, "adjusted")]
    assert all("2.33" not in c["quote"] for c in r["eps"])       # the outlook table is no result
    assert tables[0]["quote"].startswith("Diluted EPS")
    assert r["revenue"][0]["value"] == 8.22e9 or 8219418000.0 in [c["value"] for c in r["revenue"]]
    assert r["guidance"]["found"] and all("forward-looking" not in q for q in r["guidance"]["quotes"])
    assert r["quarter"] == "Quarter Ended September 27, 2026"


def test_heading_with_results_and_guidance_does_not_swallow_the_table():
    """GE 2026-10-20: 'Total Company Results & Guidance' sits above the results table."""
    r = ep.parse_release(GE_LIKE)
    assert {(c["value"], c["basis"]) for c in r["eps"] if c["where"] == "table"} == {(2.32, "gaap"), (2.25, "adjusted")}


def test_columns_oldest_first_and_ambiguous_headers():
    rows = [["", "2025", "2026"], ["Diluted EPS", "1.00", "1.40"]]
    assert ep._current_column(rows, 1) == 1
    assert ep._current_column([["Q3 2025", "Q3 2026", "Q2 2026"], ["x", "1", "2", "3"]], 1) is None     # HOOD: says nothing about the quarter
    assert ep._current_column([["2026", "2025"], ["x", "1", "2"]], 1) == 0
    assert ep._current_column([["2025", "2026", "2025", "2026"], ["x", "1", "2", "3", "4"]], 1) == 1


def test_choose_confirms_only_through_an_earlier_vendor_figure():
    c = [{"value": 2.19, "prior": [1.81], "basis": "gaap", "label": "GAAP", "where": "table"},
         {"value": 2.2, "prior": [1.82], "basis": "adjusted", "label": "Non-GAAP", "where": "table"}]
    picked = ep.choose(c, [1.82])
    assert picked["status"] == "confirmed" and picked["value"] == 2.2
    assert ep.choose(c, [])["status"] == "unclear"
    assert ep.choose(c, [9.99])["status"] == "unclear"
    assert ep.choose([], [1.0])["status"] == "none"


def test_gaap_row_matching_is_not_enough_when_an_adjusted_figure_differs():
    """JPM 2026-10-13: GAAP 5.57 matches the year-ago 5.07 (no adjustments then), but the vendor's number is 5.75."""
    c = [{"value": 5.57, "prior": [5.07], "basis": "gaap", "label": "EPS", "where": "table"},
         {"value": 5.75, "prior": [], "basis": "adjusted", "label": "excl. items", "where": "text"}]
    assert ep.choose(c, [5.07])["status"] == "unclear"


def test_only_the_next_two_columns_confirm():
    """NEE: segment columns 0.71, 0.53, -0.11 and the total 1.13 in column four would match the year-ago figure by chance."""
    assert ep.choose([{"value": 0.71, "prior": [0.53, -0.11, 1.13], "basis": "adjusted", "label": "x", "where": "table"}], [1.13])["status"] == "unclear"


def test_same_label_further_down_counts_as_earlier_quarter():
    """NSC gives the year-ago quarter in its own table, same label."""
    c = [{"value": 3.62, "prior": [], "basis": "adjusted", "label": "Adjusted diluted EPS", "where": "table"},
         {"value": 3.3, "prior": [], "basis": "adjusted", "label": "Adjusted diluted EPS", "where": "table"}]
    ep._merge_same_label(c)
    assert ep.choose(c[:1], [3.3])["value"] == 3.62


def test_reconciliations_and_long_series_are_not_period_rows():
    assert ep.period_row([2.19, 1.81, 1.24]) and ep.period_row([2.25, 1.66, 6.13, 4.8]) and ep.period_row([1.0])
    assert not ep.period_row([3.01, 0.07, 3.08])          # UNP: reported + adjustment = adjusted
    assert not ep.period_row([1.25, 1.43, 1.71, 2.52, 6.89, 2.9, 2.1, 2.2, 7.22])       # NEM: quarter is the eighth column


def test_verdict_refuses_when_basis_is_unclear_or_the_gap_is_implausible():
    assert ep.verdict(2.2, 2.17, "confirmed")["verdict"] == "beat"
    assert ep.verdict(2.17, 2.17, "confirmed")["verdict"] == "in line"
    assert ep.verdict(2.0, 2.17, "confirmed")["verdict"] == "miss"
    assert ep.verdict(2.2, 2.17, "unclear")["verdict"] == "basis unclear"
    assert ep.verdict(None, 2.17, "confirmed")["verdict"] == "basis unclear"
    assert ep.verdict(2.2, None, "confirmed")["verdict"] is None
    assert ep.verdict(0.43, 1.11, "confirmed")["verdict"] == "basis unclear"       # REIT: EPS against an FFO consensus
    assert ep.verdict(2.56, 4.36, "confirmed", "eps", "gaap")["verdict"] == "basis unclear"   # VRTX: one-offs in GAAP
    assert ep.verdict(2.56, 4.36, "confirmed", "eps", "adjusted")["verdict"] == "miss"
    assert ep.verdict(0.54, 0.53773, "confirmed")["verdict"] == "in line"       # under a cent is rounding
    assert ep.verdict(0.55, 0.54, "confirmed")["verdict"] == "beat"


def test_call_time_and_link_from_the_release():
    filed = dt.datetime(2026, 10, 21, 20, 13, tzinfo=dt.timezone.utc)
    c = ep.call_info(ep.blocks(LRCX_LIKE), filed)
    assert dt.datetime.fromtimestamp(c["ts"], ep.ET).strftime("%Y-%m-%d %H:%M") == "2026-10-21 17:00"
    assert c["url"] == "https://investor.example.com/webcast"
    no_zone = ep.call_info(ep.blocks("<p>The conference call starts at 5:00 p.m.</p>"), filed)
    assert no_zone["ts"] is None          # without a time zone there is no exact time to show


def test_earnings_filings_times_are_utc_and_items_are_checked():
    data = {"name": "X", "filings": {"recent": {"form": ["10-Q", "8-K", "8-K", "6-K"], "accessionNumber": ["0-1", "0-2", "0-3", "0-4"],
                                                "filingDate": ["2026-10-22", "2026-10-21", "2026-09-01", "2026-08-01"], "reportDate": ["2026-09-27", "2026-10-21", "2026-09-01", ""],
                                                "acceptanceDateTime": ["2026-10-22T20:07:28.000Z", "2026-10-21T20:13:03.000Z", "2026-09-01T12:00:00.000Z", "2026-08-01T12:00:00.000Z"],
                                                "items": ["", "2.02,9.01", "8.01", ""], "primaryDocument": ["q.htm", "k.htm", "o.htm", "f.htm"]}}}
    p = parse_earnings_filings(data, 123)
    assert [r["accession"] for r in p["results"]] == ["0-2"]
    assert [r["form"] for r in p["periodic"]] == ["10-Q"] and [r["form"] for r in p["foreign"]] == ["6-K"]
    assert dt.datetime.fromtimestamp(p["results"][0]["accepted"], ep.ET).strftime("%H:%M:%S") == "16:13:03"
    assert p["results"][0]["url"].endswith("/123/02/k.htm")


def test_filing_index_and_current_feed():
    index = """<table><tr><th>Seq</th></tr>
    <tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/2/a.htm">a.htm</a></td><td>8-K</td></tr>
    <tr><td>2</td><td>EX-99</td><td><a href="/Archives/edgar/data/1/2/b.htm">b.htm</a></td><td>EX-99</td></tr></table>"""
    docs = parse_filing_index(index)
    assert docs[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1/2/a.htm"
    assert desk.exhibit_of(docs)["url"].endswith("b.htm")        # plain EX-99 counts (GE)
    feed = """<feed><entry><title>8-K - ACME CORP (0000000123) (Filer)</title><summary>Item 2.02: Results Item 9.01: Exhibits</summary>
    <updated>2026-11-02T16:05:46-05:00</updated><category term="8-K"/><id>urn:tag:sec.gov,2008:accession-number=0000000123-26-000001</id></entry></feed>"""
    row = parse_current_feed(feed)[0]
    assert row["cik"] == 123 and row["items"] == ["2.02", "9.01"] and row["accession"] == "0000000123-26-000001"
    assert dt.datetime.fromtimestamp(row["accepted"], ep.ET).strftime("%H:%M:%S") == "16:05:46"


def test_nasdaq_year_ago_figure_is_not_an_actual():
    """a9f5843: Nasdaq's eps holds the year-ago quarter while surprise is N/A."""
    assert nasdaq_actual({"eps": "$1.26", "surprise": "N/A"}) is None
    assert nasdaq_actual({"eps": "$2.20", "surprise": "1.38"}) == "$2.20"
    rows = parse_nasdaq_surprise({"data": {"earningsSurpriseTable": {"rows": [{"dateReported": "10/21/2026", "eps": 2.2, "fiscalQtrEnd": "Sep 2026"}, {"dateReported": "bad", "eps": 1}]}}})
    assert rows == [{"date": "2026-10-21", "eps": 2.2, "quarter": "Sep 2026"}]


def _results(*times):
    return [{"filed": d, "accepted": dt.datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=ep.ET).timestamp(), "accession": d} for d, t in times]


def test_typical_time_is_eastern_across_daylight_saving_and_excludes_the_day():
    r = _results(("2026-10-21", "16:13:00"), ("2026-07-29", "16:07:00"), ("2026-04-22", "16:09:00"), ("2026-01-28", "16:06:00"))
    t = desk.typical_time(r, "2026-10-21")
    assert t["n"] == 3 and t["median_et"] == "16:07" and t["earliest_et"] == "16:06" and t["latest_et"] == "16:09" and t["session"] == "after the close"
    assert desk.typical_time(r, "2020-01-01") is None


def test_times_carry_their_kind():
    meta = {"results": _results(("2026-07-29", "16:07:00"), ("2026-04-22", "16:09:00"))}
    hist = desk.release_time("2026-10-21", meta, None, "after close", None)
    assert hist["kind"] == "historical" and dt.datetime.fromtimestamp(hist["ts"], ep.ET).strftime("%H:%M") == "16:08"
    actual = desk.release_time("2026-07-29", meta, None, "after close", None)
    assert actual["kind"] == "actual"
    assert desk.release_time("2026-10-21", None, None, "after close", None) == {"kind": "session", "ts": None, "text": "after close", "source": "calendar session only"}


def test_call_link_falls_back_and_says_so():
    day = "2026-11-02"
    y = {"date_confirmed": True, "call_ts": desk.at_et(day, 17 * 60), "website": "https://example.com"}
    c = desk.call_details(day, {"last_call": {"url": "https://ir.example.com/q3", "minutes": 16 * 60 + 30}}, None, y)
    assert c["time_kind"] == "announced" and c["time_source"] == "Yahoo" and c["url_kind"] == "last_release"
    c = desk.call_details(day, {"last_call": {"url": "https://www.example.com"}}, None, None)
    assert c["url_kind"] == "ir_fallback"      # a bare company site is no way into the call
    c = desk.call_details(day, {"investor_site": "https://ir.example.com"}, None, None)
    assert c["url_kind"] == "ir_fallback" and "no webcast link" in c["url_note"] and c["ts"] is None
    assert desk.call_details(day, {"last_call": {"url": "javascript:alert(1)"}}, None, None)["url"] is None    # text from a filing never becomes a script link
    c = desk.call_details(day, {}, {"call": {"ts": 5.0, "url": "https://w.example.com/webcast"}}, y)
    assert (c["time_source"], c["url_kind"]) == ("press release", "release")


def test_window_and_phase():
    day = "2026-11-02"
    start, end = desk.window(day, "after close", None)
    assert dt.datetime.fromtimestamp(start, ep.ET).strftime("%H:%M") == "15:30" and dt.datetime.fromtimestamp(end, ep.ET).strftime("%H:%M") == "19:00"
    assert desk.phase(day, "after close", None, desk.at_et(day, 16 * 60)) == "hot"
    assert desk.phase(day, "after close", None, desk.at_et(day, 9 * 60)) is None
    assert desk.phase(day, "after close", None, desk.at_et("2026-11-03", 8 * 60)) == "late"
    assert desk.phase(day, "after close", None, desk.at_et("2026-11-03", 13 * 60)) is None
    # a company that files outside the calendar's session widens its window
    wide = {"n": 8, "earliest": 7 * 60, "latest": 7 * 60 + 30}
    assert desk.phase(day, "after close", wide, desk.at_et(day, 7 * 60)) == "hot"


def test_anchors_only_use_earlier_quarters():
    hist = [{"when": "2026-10-21T16:00:00-04:00", "eps_reported": 2.2}, {"when": "2026-07-29T16:00:00-04:00", "eps_reported": 1.82},
            {"when": "2026-04-22T16:00:00-04:00", "eps_reported": 1.47}, {"when": "2025-10-22T16:00:00-04:00", "eps_reported": 1.26}]
    assert desk.yahoo_anchors(hist, "2026-10-21") == [1.82, 1.26]
    assert desk.nasdaq_anchors([{"date": "2026-10-21", "eps": 2.2}, {"date": "2026-07-29", "eps": 1.82}], "$1.26", "2026-10-21") == [1.82, 1.26]


def test_evaluate_per_source_and_overall():
    parsed = ep.parse_release(LRCX_LIKE)
    res = desk.evaluate(parsed, [{"source": "yahoo", "eps": 2.18, "eps_anchors": [1.82]}, {"source": "nasdaq", "eps": 2.25, "eps_anchors": [1.82]}])
    assert [r["verdict"] for r in res["eps"]["rows"]] == ["beat", "miss"] and res["eps"]["verdict"] == "sources disagree"
    res = desk.evaluate(parsed, [{"source": "nasdaq", "eps": 2.17, "eps_anchors": [7.77]}])
    assert res["eps"]["verdict"] == "basis unclear" and res["eps"]["figures"]        # figures stay visible without a verdict
    res = desk.evaluate(parsed, [])
    assert res["eps"]["verdict"] is None and res["eps"]["rows"] == []


def test_headline_never_makes_a_trade_statement():
    parsed = ep.parse_release(LRCX_LIKE)
    data = {"quarter": "Q3", "result": desk.evaluate(parsed, [{"source": "yahoo", "eps": 2.18, "eps_anchors": [1.82]}])}
    title, body = desk.headline("LRCX", data)
    assert title == "LRCX reported Q3" and "2.20 vs 2.18" in body and "beat" in body and "72 %" in body
    for word in ("buy", "sell", "target", "go long", "go short"):
        assert word not in body.lower()


def test_ai_reading_keeps_only_verbatim_quotes():
    src = "Revenue of $8.22 billion. Non-GAAP diluted EPS of $2.20."
    items = [{"metric": "eps", "value": "2.20", "quote": "Non-GAAP diluted EPS of $2.20"},
             {"metric": "eps", "value": "9.99", "quote": "Non-GAAP diluted EPS of $2.20"},
             {"metric": "rev", "value": "8.22", "quote": "Revenue was 8.22 billion"}]
    kept, dropped = desk.verify_ai(items, src)
    assert [k["value"] for k in kept] == ["2.20"] and dropped == 2
    assert desk.verify_ai("nonsense", src) == ([], 0)


def test_push_is_off_by_default_and_watchlist_only():
    ev = {"kind": "earnings_flash", "symbol": "AAPL", "day": "2026-11-02", "title": "t", "body": "b", "watchlist": True}

    class S:
        def __init__(self, v):
            self.v = v

        def get(self, key, default=None):
            return self.v if key == "push" else default
    assert push_config(S({}))["events"]["earnings_flash"] is False
    assert format_event(ev, push_config(S({}))) is None
    on = push_config(S({"events": {"earnings_flash": True}}))
    assert format_event(ev, on)["kind"] == "earnings_flash"
    assert format_event({**ev, "watchlist": False}, on) is None


def _sec_handler(calls, *, feed=""):
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        calls.append(url)
        if "company_tickers" in url:
            return httpx.Response(200, json={"0": {"ticker": "ACME", "cik_str": 123}})
        if "getcurrent" in url:
            return httpx.Response(200, text=feed)
        if "submissions" in url:
            today = dt.date.today().isoformat()
            return httpx.Response(200, json={"name": "Acme", "investorWebsite": "https://ir.acme.example", "filings": {"recent": {
                "form": ["8-K"], "accessionNumber": ["0000000123-26-000001"], "filingDate": [today], "reportDate": [today],
                "acceptanceDateTime": [dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")], "items": ["2.02,9.01"], "primaryDocument": ["k.htm"]}}})
        if url.endswith("-index.htm"):
            return httpx.Response(200, text='<table><tr><td>2</td><td>EX</td><td><a href="/Archives/edgar/data/123/1/ex.htm">e</a></td><td>EX-99.1</td></tr></table>')
        if url.endswith("/ex.htm"):
            return httpx.Response(200, content=LRCX_LIKE.encode())
        if "earnings-surprise" in url:
            return httpx.Response(200, json={"data": {"earningsSurpriseTable": {"rows": []}}})
        return httpx.Response(404)
    return handler


def _ctx(client, handler, contact="me@example.com"):
    ctx = client.app_state["ctx"]
    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx.settings.update({"connectors": {"sec": {"contact_email": contact}}})
    return ctx


def test_no_contact_means_no_sec_traffic(client):
    calls = []
    ctx = _ctx(client, _sec_handler(calls), contact="")
    assert asyncio.run(desk.tick(ctx)) == {"due": 0}
    assert not calls
    assert client.get("/api/earnings/desk").json()["sec_contact"] is False


def test_freeze_is_refused_once_the_window_is_open(client, monkeypatch):
    ctx = _ctx(client, _sec_handler([]))
    monkeypatch.setattr(desk, "_yahoo_term", lambda s, d: {"eps": 2.0, "eps_anchors": [1.0]})
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    term = {"symbol": "ACME", "date": tomorrow, "timing": "after close", "eps_forecast": "$2.17", "last_year_eps": "$1.26", "quarter": "Sep/2026"}
    assert asyncio.run(desk.freeze(ctx, term)) is True
    rows = {r["source"]: r for r in ctx.db.consensus_get("ACME", tomorrow)}
    assert rows["nasdaq"]["eps"] == 2.17 and rows["nasdaq"]["eps_anchors"] == [1.26] and rows["yahoo"]["eps"] == 2.0
    # after the report's window opened: nothing is fetched or overwritten, however often it is asked
    before = time.time() - 1
    monkeypatch.setattr(desk, "window", lambda *a: (before, before + 10))
    monkeypatch.setattr(desk, "_yahoo_term", lambda s, d: pytest.fail("no fetch after the window opened"))
    assert asyncio.run(desk.freeze(ctx, {**term, "eps_forecast": "$9.99"})) is False
    assert {r["source"]: r for r in ctx.db.consensus_get("ACME", tomorrow)}["nasdaq"]["eps"] == 2.17


def test_yahoo_snapshot_is_refused_for_a_reported_quarter(monkeypatch):
    class T:
        def __init__(self, s):
            pass

        def get_info(self):
            return {}

        def get_earnings_dates(self, limit=12):
            import pandas as pd
            return pd.DataFrame({"EPS Estimate": [2.18], "Reported EPS": [2.20]}, index=[pd.Timestamp("2026-10-21 16:00", tz="America/New_York")])
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", T)
    assert desk._yahoo_term("LRCX", "2026-10-21") == {}


def test_collector_polls_only_when_due_and_reads_the_filing(client, monkeypatch):
    today = dt.date.today().isoformat()
    calls = []
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    feed = f"""<feed><entry><title>8-K - ACME (0000000123) (Filer)</title><summary>Item 2.02: x</summary><updated>{now}</updated>
    <category term="8-K"/><id>urn:accession-number=0000000123-26-000001</id></entry></feed>"""
    ctx = _ctx(client, _sec_handler(calls, feed=feed))

    async def rows(c):
        return [{"symbol": "ACME", "name": "Acme", "date": today, "timing": "after close", "importance": "high", "watchlist": True, "cap": 1e12}]
    monkeypatch.setattr(desk, "calendar_rows", rows)
    ctx.db.earnings_meta_put("ACME", {"covered": "yes", "cik": 123, "results": [], "periodic": []})
    ctx.db.consensus_put("ACME", today, "yahoo", {"eps": 2.18, "eps_anchors": [1.82]})
    # outside the window: not one request
    monkeypatch.setattr(desk, "phase", lambda *a: None)
    assert asyncio.run(desk.tick(ctx)) == {"due": 0}
    assert not calls
    # inside the window: one feed request, then the filing; afterwards nothing more is due
    monkeypatch.setattr(desk, "phase", lambda *a: "hot")
    out = asyncio.run(desk.tick(ctx))
    assert out == {"due": 1, "found": 1}
    assert sum("getcurrent" in c for c in calls) == 1
    flash = ctx.db.flash_get("ACME", today)
    assert flash["result"]["eps"]["verdict"] == "beat" and flash["latency"]["total"] is not None and flash["call"]["url"]
    calls.clear()
    assert asyncio.run(desk.tick(ctx)) == {"due": 0}
    assert not calls
    page = client.get("/api/earnings/flash").json()
    assert page["items"][0]["symbol"] == "ACME" and "72 %" in page["base_rate"]


def test_not_covered_is_said_not_guessed(client):
    _ctx(client, _sec_handler([]))
    t = client.get("/api/earnings/term/SAPXX?day=2026-10-21").json()
    assert t["covered"] == "no" and "Not covered" in t["cover_note"] and t["flash"] is None
    assert "error" in client.post("/api/earnings/flash/SAPXX?day=2026-10-21").json()


def test_save_writes_to_the_data_folder_and_serves_only_as_download(client):
    ctx = _ctx(client, _sec_handler([]))
    today = dt.date.today().isoformat()
    r = client.post(f"/api/earnings/save/ACME?day={today}&doc=release&format=text").json()
    assert r["path"].endswith("press_release.txt") and str(ctx.data_dir) in r["path"]
    assert "Source: https://www.sec.gov/Archives/" in open(r["path"], encoding="utf-8").read()
    html = client.post(f"/api/earnings/save/ACME?day={today}&doc=release&format=html").json()
    res = client.get(f"/api/earnings/file/ACME?day={today}&name=press_release.html")
    assert html["bytes"] > 0 and res.headers["content-disposition"].startswith("attachment") and res.headers["content-type"] == "application/octet-stream"
    assert client.get(f"/api/earnings/file/ACME?day={today}&name=../secrets.json").status_code == 404
    assert client.get("/api/earnings/term/AC%2F..?day=2026-01-01").status_code in (400, 404)
    assert client.post(f"/api/earnings/save/ACME?day={today}&doc=other&format=text").json()["error"]
    assert "No such" not in json.dumps(client.get(f"/api/earnings/term/ACME?day={today}").json()["files"])


def test_sec_document_refuses_foreign_addresses(client):
    from sessiondesk.connectors.base import ConnectorError
    ctx = _ctx(client, _sec_handler([]))
    with pytest.raises(ConnectorError):
        asyncio.run(ctx.hub.get("sec").document("https://evil.example.com/x"))


def test_sec_429_pauses_all_traffic(client):
    from sessiondesk.connectors.base import ConnectorError
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(429)
    ctx = _ctx(client, handler)
    sec = ctx.hub.get("sec")

    async def run():
        ctx.extras.pop("sec_limit", None)
        with pytest.raises(ConnectorError):
            await sec.current_filings()
        with pytest.raises(ConnectorError):
            await sec.current_filings()
    asyncio.run(run())
    assert len(calls) == 1


def test_labels_for_timeline_come_from_stored_data_only(client):
    ctx = _ctx(client, _sec_handler([]))
    calls_before = []
    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls_before.append(r) or httpx.Response(500)))
    ctx.db.earnings_meta_put("ACME", {"covered": "yes", "results": _results(("2026-07-29", "16:07:00"), ("2026-04-22", "16:09:00"))})
    items = [{"kind": "earnings", "tag": "ACME", "day": "2026-10-21", "ts": None}, {"kind": "earnings", "tag": "NEW", "day": "2026-10-21", "ts": None}]
    asyncio.run(desk.annotate_timeline(ctx, items))
    assert items[0]["time_kind"] == "historical" and items[0]["ts"] and items[1]["ts"] is None
    assert not calls_before
