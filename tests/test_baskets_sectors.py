"""Sector returns, basket weights and line, EIA gas storage parsing, basket API."""
from __future__ import annotations

import datetime as dt

import pytest

from sessiondesk.features import baskets, datahub, sectors


def _pts(values, start=dt.date(2025, 12, 1)):
    return [((start + dt.timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


def test_period_returns_and_ytd():
    pts = _pts([100.0] * 30 + [110.0] + [121.0])                       # 2025-12-01 .. 2026-01-01
    r = sectors.returns(pts, today=dt.date(2026, 1, 1))
    assert r["1d"] == pytest.approx(10.0) and r["1w"] == pytest.approx(21.0)
    assert r["ytd"] == pytest.approx(10.0)                              # against the last close of 2025 (110)
    assert r["1y"] is None


def test_parse_members_weights():
    eq = baskets.parse_members("AAPL, msft, NVDA")
    assert [m["symbol"] for m in eq] == ["AAPL", "MSFT", "NVDA"] and all(m["weight"] == pytest.approx(1 / 3) for m in eq)
    mixed = baskets.parse_members("NVDA 50, AMD, AVGO")                 # the rest of 100 split equally
    assert [round(m["weight"], 2) for m in mixed] == [0.5, 0.25, 0.25]
    pct = baskets.parse_members("A 30%; B 70%")
    assert [m["weight"] for m in pct] == pytest.approx([0.3, 0.7])
    assert baskets.parse_members("") == []


def test_basket_line_buy_and_hold():
    series = {"A": _pts([10.0, 11.0, 12.0]), "B": _pts([100.0, 100.0, 50.0])}
    line = baskets.basket_line(series, [{"symbol": "A", "weight": 0.5}, {"symbol": "B", "weight": 0.5}])
    assert [round(v, 2) for _, v in line] == [100.0, 105.0, 85.0]
    assert baskets.basket_line(series, [{"symbol": "X", "weight": 1.0}]) == []


def test_parse_eia_gas():
    text = ('Energy Information Administration\n"Working Gas"\nRegion,Stocks in billion (Bcf),,,,,,,,,,,,Historical Comparisons\n'
            ',,,,,,,,,,,,,Year Ago (10/09/25),,,,,,5-Year (2021-25) Average\n'
            ',09-Oct-26,,,02-Oct-26,,,net change (Bcf),,,implied flow (Bcf),,,stocks (Bcf),,,% change,,,stocks (Bcf),,,% change\n'
            'East,"884","","","862","",,"22","",,"22",,"","880",,,"0.5",,,"856",,,"3.3",,"",""\n'
            'Total,"3,567","","","3,500","",,"67","",,"67",,"","3,710",,,"-3.9",,,"3,522",,,"1.3",,"",""\n')
    rows = datahub.parse_eia_gas(text)
    assert [r["region"] for r in rows] == ["East", "Lower 48 total"]
    assert rows[1]["points"] == [("2026-10-02", 3500.0), ("2026-10-09", 3567.0)]
    assert rows[1]["year_ago"] == 3710.0 and rows[1]["avg5"] == 3522.0


def test_basket_api_roundtrip(client):
    assert "error" in client.post("/api/baskets", json={"name": "", "members": "AAPL"}).json()
    b = client.post("/api/baskets", json={"name": "Chips", "members": "NVDA 60, AMD"}).json()["basket"]
    assert b["members"][1] == {"symbol": "AMD", "weight": pytest.approx(0.4)} and b["benchmark"] == "SPY"
    assert [x["name"] for x in client.get("/api/baskets").json()["baskets"]] == ["Chips"]
    client.delete(f"/api/baskets/{b['id']}")
    assert client.get("/api/baskets").json()["baskets"] == []


def test_fx_proxies_and_volume_stats():
    from sessiondesk.features import deep
    assert deep.fx_pair("EURUSD=X") == "EURUSD" and deep.fx_pair("JPY=X") == "USDJPY" and deep.fx_pair("DX-Y.NYB") == "DXY"
    assert deep.fx_pair("AAPL") is None and deep.fx_pair("SEKNOK=X") is None
    assert deep.fx_proxy("JPY=X") == {"pair": "USDJPY", "options": "FXY", "future": "6J", "inverted": True}
    syms, roll = deep.quarterly_contracts("6E", dt.date(2026, 10, 20))
    assert syms == ["6EZ26.CME", "6EH27.CME"] and roll == dt.date(2026, 9, 14)       # 3rd Wed 16 Sep minus 2 days
    assert deep.quarterly_contracts("DX", dt.date(2026, 12, 14))[0] == ["DXZ26.NYB", "DXH27.NYB"]
    assert deep.quarterly_contracts("DX", dt.date(2026, 12, 15))[1] == dt.date(2026, 12, 14)
    day = 86400
    bars = [{"t": i * day, "v": 100} for i in range(30)] + [{"t": 30 * day, "v": 300}, {"t": 31 * day, "v": 50}]
    v = deep.volume_stats(bars, now=31 * day + 3600)                    # the bar of day 31 is still running
    assert v["last"] == 300 and v["avg20"] == 100 and v["ratio20"] == 3 and v["today_so_far"] == 50 and not v["repeated"]
    rep = deep.volume_stats(bars[:-2] + [{"t": 30 * day, "v": 100}], now=40 * day)
    assert rep["repeated"] and rep["last_day"] == "1970-01-30"
    since = deep.volume_stats(bars, now=40 * day, since=25 * day)
    assert since["avg_n"] == 6 and since["avg250"] is None
    assert deep.merge_volume([{"t": 1, "v": 2}], [{"t": 1, "v": 3}, {"t": 2, "v": 1}]) == [{"t": 1, "v": 5}, {"t": 2, "v": 1}]
    assert deep.volume_stats([{"t": 0, "v": 5}] * 3, now=10 * day) is None


def test_basket_delete_removes_hub_series(client):
    ctx = client.app_state["ctx"]
    b = client.post("/api/baskets", json={"name": "Gone", "members": "AAPL"}).json()["basket"]
    ctx.db.upsert_series({"id": "basket:" + b["id"], "name": "Gone", "category": "Your baskets", "source": "s", "kind": "price"}, [("2026-01-02", 100.0)])
    client.delete(f"/api/baskets/{b['id']}")
    assert all(s["id"] != "basket:" + b["id"] for s in ctx.db.series_list())


def test_canonical_sector_and_drilldown_errors(client):
    cs = sectors.canonical_sector
    assert cs("Automotive") == "discretionary" and cs("Support services") == "industrials" and cs("Energy technology") == "industrials"
    assert cs("Electrical utilities & independent power producers") == "utilities" and cs("Real Estate Investment Trusts") == "real_estate"
    assert cs("Consumer Defensive") == "staples" and cs("Information Technology") == "technology" and cs("Mining") == "materials"
    assert cs(None) is None
    from sessiondesk.features import universe
    assert all(cs(m.get("sector"), m.get("industry")) for u in universe.UNIVERSES for m in universe.members(u))   # nothing unmapped
    assert "error" in client.get("/api/sectors/us/NOPE").json()
