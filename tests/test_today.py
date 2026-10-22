"""Today page logic (schedule, prop meter, rule flags) and the journal maths."""
from __future__ import annotations

import datetime as dt

import pytest

from sessiondesk.features import journal, today

SESSIONS = {"EU": {"open": "09:00", "close": "17:30", "tz": "Europe/Berlin", "calendar": "EU"},
            "US": {"open": "09:30", "close": "16:00", "tz": "America/New_York", "calendar": "US"}}


def test_schedule_relative_absolute_and_holidays():
    entries = [{"label": "2nd candle", "session": "EU", "offset_min": 30}, {"label": "midday", "session": "EU", "time": "12:15", "tz": "Europe/Berlin"},
               {"label": "late", "session": "EU", "time": "23:00", "tz": "Europe/Berlin"}]
    items = today.schedule_for(dt.date(2026, 10, 14), SESSIONS, entries)
    labels = [i["label"] for i in items]
    assert labels.count("cash open") == 2 and "2nd candle" in labels and "midday" in labels and "late" not in labels
    second = next(i for i in items if i["label"] == "2nd candle")
    assert second["when"].astimezone(dt.timezone.utc).strftime("%H:%M") == "07:30"
    assert today.schedule_for(dt.date(2026, 12, 25), SESSIONS, entries) == []          # both exchanges closed
    assert [i["session"] for i in today.schedule_for(dt.date(2026, 11, 26), SESSIONS, [])] == ["EU", "EU"]   # US Thanksgiving


def test_collisions_with_high_impact_releases():
    item = today.schedule_for(dt.date(2026, 10, 14), SESSIONS, [])[2]                 # US cash open 13:30 UTC
    events = [{"ts": item["when"].timestamp() - 3600, "impact": "high", "currency": "USD", "title": "CPI"},
              {"ts": item["when"].timestamp() + 600, "impact": "high", "currency": "USD", "title": "Fed speech"},
              {"ts": item["when"].timestamp() + 300, "impact": "medium", "currency": "USD", "title": "minor"}]
    today.mark_collisions([item], events)
    assert item["collisions"] == ["USD Fed speech"]


def test_prop_meter_with_exporter_day_start():
    acc = {"login": "…002", "equity": 98500.0, "currency": "USD",
           "extra": {"day_start_balance": "100000", "risk_multiplier": "0.5", "all_time_high": "101000"}}
    rule = today.rules_for("…002", {"*": {"own_stop_pct": 1.5, "risk_per_trade_pct": 0.25}, "002": {"daily_loss_pct": 5, "max_loss_pct": 10,
                                                                                                    "initial_balance": 100000}})
    m = today.prop_meter(acc, rule, None)
    assert m["day_pct"] == pytest.approx(-1.5) and m["own_stop_room_pct"] == pytest.approx(0.0)
    assert m["daily_loss_room_pct"] == pytest.approx(3.5) and m["losers_left"] == pytest.approx(0.0)
    assert m["max_loss_room"] == pytest.approx(8500) and m["day_start_source"] == "exporter"
    m2 = today.prop_meter({"login": "x", "equity": 10100.0, "extra": {}}, {"own_stop_pct": 1.5, "risk_per_trade_pct": 0.25}, 10000.0)
    assert m2["day_pct"] == pytest.approx(1.0) and m2["losers_left"] == pytest.approx(10.0) and m2["day_start_source"] == "first seen today"


def test_rule_flags():
    accounts = [{"login": "a", "equity": 10000.0}]
    positions = [{"account": "a", "symbol": "GER40", "side": "LONG", "sl": 1.0, "risk_to_stop": 50.0, "manual": False},
                 {"account": "a", "symbol": "NAS100", "side": "SHORT", "sl": None, "risk_to_stop": None, "manual": True}]
    flags = today.rule_flags(accounts, positions, {"*": {"risk_per_trade_pct": 0.25, "max_slots": 1}})
    text = " | ".join(f["text"] for f in flags)
    assert "risks 0.50%" in text and "no stop" in text and "opened by hand" in text and "2 open positions" in text


def test_journal_positions_and_r():
    deals = [{"account": "a", "position_id": "9", "time": 100, "entry": "0", "type": "BUY", "magic": "77", "symbol": "GER40", "net": -2.0},
             {"account": "a", "position_id": "9", "time": 200, "entry": "1", "type": "SELL", "magic": "0", "symbol": "GER40", "net": 52.0},
             {"account": "a", "position_id": "10", "time": 300, "entry": "0", "type": "SELL", "magic": "0", "symbol": "XAUUSD", "net": 0.0}]
    rows = journal.closed_positions(deals)
    assert len(rows) == 1 and rows[0]["side"] == "LONG" and rows[0]["magic"] == "77" and rows[0]["net"] == pytest.approx(50.0)
    assert journal.r_multiple({"net": 50.0, "risk_observed": 25.0}) == pytest.approx(2.0)
    assert journal.r_multiple({"net": 50.0, "risk_observed": 25.0, "risk_confirmed": 50.0}) == pytest.approx(1.0)
    st = journal.stats([{"magic": "77", "closed": 1, "net": 50.0, "risk_observed": 25.0}], {"77": "Breakout"})
    assert st[0]["setup"] == "Breakout" and st[0]["avg_r"] == pytest.approx(2.0) and st[0]["with_risk"] == 1


def test_today_endpoint_without_broker(client):
    d = client.get("/api/today").json()
    assert d["connected"] is False and isinstance(d["schedule"], list) and "flows" in d
    assert client.post("/api/notes", json={"text": "test note"}).json()["items"][0]["text"] == "test note"
    assert any(a["kind"] == "note" for a in client.get("/api/activity").json()["items"])


def test_journal_keeps_accounts_apart_and_hides_copies():
    t0 = 1_790_000_000
    rows = [{"account": "…001", "magic": "0", "closed": t0, "net": 100.0},
            {"account": "…001", "magic": "0", "closed": t0 + 90_000, "net": -40.0},
            {"account": "…002", "magic": "987654", "closed": t0, "net": 80.0}]
    st = journal.stats(rows, {"987654": "Copier (copies)"})
    assert {(s["account"], s["setup"]): s["net"] for s in st} == {("…001", "manual"): 60.0, ("…002", "Copier (copies)"): 80.0}
    cv = journal.curves(rows[:2], 30)
    assert [p["v"] for p in cv["…001"]["cum"]] == [100.0, 60.0] and len(cv["…001"]["periods"]) == 2
    assert journal.curves(rows[:2], 365)["…001"]["period"] == "week"


def test_journal_endpoint_hides_copier_trades(client):
    db = client.app_state["ctx"].db
    for pid, magic, net in (("1", "0", 50.0), ("2", "987654", 45.0)):
        db.journal_upsert({"account": "A", "position_id": pid, "symbol": "DAX", "side": "LONG", "magic": magic,
                           "opened": 1, "closed": __import__("time").time() - 3600, "net": net})
    client.patch("/api/settings", json={"copy_magics": ["987654"]})
    d = client.get("/api/journal?days=7").json()
    assert [t["position_id"] for t in d["trades"]] == ["1"] and d["copies_hidden"] == 1
    assert d["curves"]["A"]["total"] == 95.0              # the curve is the account's real P/L, copies included
    assert len(client.get("/api/journal?days=7&copies=true").json()["trades"]) == 2


def test_timeline_earnings_filter_and_endpoint(client):
    from sessiondesk.features import timeline
    rows = [{"symbol": "AAPL", "name": "Apple", "date": "2026-10-29", "timing": "after close", "market_cap": "$3,500,000,000,000"},
            {"symbol": "TINY", "name": "Tiny Corp", "date": "2026-10-29", "market_cap": "$900,000,000"},
            {"symbol": "MINE", "name": "Mine", "date": "2026-10-29", "market_cap": None}]
    out = timeline.earnings_items(rows, {"MINE"}, {"AAPL"})
    assert {(x["tag"], x["detail"].split(" · ")[-1]) for x in out} == {("AAPL", "index member"), ("MINE", "watchlist")}
    import time as _t
    soon = _t.time() + 7200

    async def events(start, end):
        return {"events": [{"ts": soon, "currency": "USD", "title": "CPI m/m", "impact": "high", "forecast": "0.3%"},
                           {"ts": soon, "currency": "USD", "title": "Minor index", "impact": "low"}], "sources": ["stub"]}
    client.app_state["ctx"].extras["calendar"].events = events
    d = client.get("/api/timeline?days=7").json()
    kinds = {x["kind"] for x in d["items"]}
    assert {"release", "session", "flow"} <= kinds                   # stub release + default sessions + rule-based flows
    assert [x["title"] for x in d["items"] if x["kind"] == "release"] == ["CPI m/m"]   # low impact left out
    assert all(x["day"] for x in d["items"])
    days = [x["day"] for x in d["items"]]
    assert days == sorted(days)


def test_earnings_rank_and_endpoint(client):
    from sessiondesk.features import timeline
    rank = lambda r: timeline.earnings_rank(r, {"MINE"}, {"IDX"})            # noqa: E731
    assert rank({"symbol": "MINE", "market_cap": None}) == {"cap": None, "importance": "high", "why": "watchlist"}
    assert rank({"symbol": "MEGA", "market_cap": "$250,000,000,000"}) == {"cap": 250e9, "importance": "high", "why": "mega cap"}
    assert rank({"symbol": "IDX", "market_cap": "$12,000,000,000"}) == {"cap": 12e9, "importance": "medium", "why": "index member"}
    assert rank({"symbol": "BIG", "market_cap": "$60,000,000,000"})["why"] == "large cap"
    assert rank({"symbol": "TINY", "market_cap": "$900,000,000"}) == {"cap": 9e8, "importance": "low", "why": None}

    async def first(capability, method, *args):
        return {"data": [{"symbol": "AAPL", "date": "2026-10-29", "market_cap": "$3,500,000,000,000"},
                         {"symbol": "TINY", "date": "2026-10-29", "market_cap": "$900,000,000"}], "source": "stub"}
    client.app_state["ctx"].hub.first = first
    items = {r["symbol"]: r for r in client.get("/api/earnings?days=3").json()["items"]}
    assert items["AAPL"]["importance"] == "high" and items["AAPL"]["cap"] == 3.5e12
    assert items["TINY"]["importance"] == "low"


def test_journal_start_balances_and_pct():
    import time as _t
    from sessiondesk.features import journal
    d1, d2 = _t.mktime(_t.strptime("2026-10-19 12:00", "%Y-%m-%d %H:%M")), _t.mktime(_t.strptime("2026-10-20 12:00", "%Y-%m-%d %H:%M"))
    closed = [{"account": "A", "closed": d1, "net": 100.0}, {"account": "A", "closed": d2, "net": -50.0}]
    sb = journal.start_balances(closed, 10050.0, ["2026-10-19", "2026-10-20"])
    assert sb == {"2026-10-19": 10000.0, "2026-10-20": 10100.0}                     # 10050 now = 10000 + 100 - 50
    assert journal.start_balances(closed, 10050.0, ["2026-10-20"], {"2026-10-20": 9999.0}) == {"2026-10-20": 9999.0}   # stored wins
    cv = journal.curves(closed, 30)
    rows = [dict(r) for r in closed]
    journal.with_pct(cv, rows, {"A": sb})
    assert cv["A"]["periods"][0]["pct"] == 1.0 and round(cv["A"]["periods"][1]["pct"], 4) == round(-50 / 10100 * 100, 4)
    assert cv["A"]["cum"][-1]["pct"] == 0.5 and rows[0]["pct"] == 1.0


def test_earnings_reported_helpers():
    from sessiondesk.features import earnings_reported as er
    assert er.money("$1.66") == 1.66 and er.money("($0.12)") == -0.12 and er.money("N/A") is None and er.money(None) is None
    closes = [("2026-10-16", 100.0), ("2026-10-19", 102.0), ("2026-10-20", 110.16), ("2026-10-21", 99.144)]
    assert round(er.reaction(closes, "2026-10-20", "after close"), 2) == -10.0       # digested on the 21st
    assert round(er.reaction(closes, "2026-10-20", "pre-market"), 2) == 8.0          # digested on the 20th
    assert er.reaction(closes, "2026-10-18", "pre-market") is None                    # no session on the report day


def test_timeline_results():
    from sessiondesk.features import timeline
    now = 1_800_000_000
    assert timeline.release_result({"ts": now + 60, "actual": None, "forecast": "1%"}, now) is None          # not out yet
    assert timeline.release_result({"ts": now - 60, "actual": None, "forecast": "1%"}, now) == {"missing": True}
    assert timeline.release_result({"ts": now - 60, "actual": None, "forecast": None}, now) is None          # a speech
    r = timeline.release_result({"ts": now - 60, "actual": "2.8%", "forecast": "2.5%", "previous": "3.0%", "surprise": 0.3}, now)
    assert r["verdict"] == "above" and r["actual"] == "2.8%"
    e = timeline.earnings_result({"eps_actual": "$1.20", "eps_forecast": "$1.00", "surprise_pct": 20.0, "beat": True, "move": -3.1})
    assert e["verdict"] == "beat" and e["move"] == -3.1


def test_nasdaq_eps_only_with_surprise_and_yahoo_match():
    from sessiondesk.connectors.public import nasdaq_actual
    from sessiondesk.features.earnings_reported import yahoo_match
    # LRCX 2026-10-21 before Nasdaq had the result: "eps" is the year-ago quarter
    assert nasdaq_actual({"eps": "$1.26", "surprise": "N/A", "epsForecast": "$2.17"}) is None
    assert nasdaq_actual({"eps": "$2.20", "surprise": "1.38"}) == "$2.20"
    assert nasdaq_actual({"eps": "", "surprise": "5"}) is None
    hist = [{"when": "2026-10-21T16:00:00-04:00", "eps_estimate": 2.18, "eps_reported": 2.20},
            {"when": "2025-10-22T16:00:00-04:00", "eps_estimate": 1.22, "eps_reported": 1.26}]
    assert yahoo_match(hist, "2026-10-21")["eps_reported"] == 2.20
    assert yahoo_match([{"when": "2026-10-21T16:00:00-04:00", "eps_estimate": 2.18, "eps_reported": None}], "2026-10-21") is None
