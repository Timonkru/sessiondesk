"""Data hub: change kinds, robust z, 'largest since', EIA table parsing, series storage, warnings and CSV export."""
from __future__ import annotations

import asyncio
import random

import pytest

from sessiondesk.features import datahub


def _series(values, start=2020):
    import datetime as dt
    d0 = dt.date(start, 1, 1)
    return [((d0 + dt.timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


def test_changes_and_assess():
    assert datahub.changes(_series([100.0, 110.0]), "price")[0][1] == pytest.approx(10.0)
    assert datahub.changes(_series([4.0, 4.25]), "rate")[0][1] == pytest.approx(0.25)
    assert datahub.changes(_series([3.0, 5.0]), "count") == _series([3.0, 5.0])
    rnd = random.Random(1)
    vals, v = [], 100.0
    for _ in range(300):
        v *= 1 + rnd.gauss(0, 0.01)
        vals.append(v)
    big = vals[-1] * 0.94                                            # a 6 % drop after 1 % daily noise
    a = datahub.assess(_series(vals + [big]), "price")
    assert a["z"] < -4 and a["largest_since"] is None and a["history"] == 299
    calm = datahub.assess(_series(vals + [vals[-1] * 1.002]), "price")
    assert abs(calm["z"]) < 1
    assert datahub.assess(_series(vals[:20]), "price") is None        # too little history
    text = datahub.describe({"name": "DAX", "kind": "price"}, a)
    assert "DAX: move -6.00%" in text and "σ" in text


def test_parse_eia_table():
    text = ('"STUB_1","10/9/26","10/2/26","Difference","10/10/25","Percent Change"\n'
            '"Crude Oil","698.560","707.117","-8.557","831.530","-16.000"\n'
            '"Commercial (Excluding SPR)","415.577","424.134","-8.557","423.785","-1.900"\n'
            '"Total Motor Gasoline","220.1","221.0","-0.9","210.0","4.8"\n'
            '"Something else","1","2","3","4","5"\n')
    rows = datahub.parse_eia_table(text)
    assert [r["name"] for r in rows] == ["Crude oil stocks incl. SPR", "Crude oil stocks excl. SPR", "Gasoline stocks"]
    assert rows[1]["points"] == [("2026-10-02", 424.134), ("2026-10-09", 415.577)] and rows[1]["code"] == "WCESTUS1"


def test_parse_eia_history():
    html = ("<tr><td class='B6'>&nbsp;&nbsp;1982-Aug</td><td class='B5'>&nbsp;</td><td class='B3'>&nbsp;&nbsp;&nbsp;</td>"
            "<td class='B5'>08/20&nbsp;</td><td class='B3'>338,764&nbsp;&nbsp;&nbsp;</td><td class='B5'>08/27&nbsp;</td>"
            "<td class='B3'>336,138&nbsp;&nbsp;&nbsp;</td></tr>")
    assert datahub.parse_eia_history(html, 0.001) == [("1982-08-20", 338.764), ("1982-08-27", 336.138)]


def test_hub_store_scan_and_csv(client):
    ctx = client.app_state["ctx"]
    rnd = random.Random(2)
    vals, v = [], 50.0
    for _ in range(200):
        v += rnd.gauss(0, 0.05)
        vals.append(v)
    meta = {"id": "test:spread", "name": "Test spread", "category": "Test", "source": "unit test", "kind": "level"}
    ctx.db.upsert_series(meta, _series(vals + [vals[-1] + 1.0]))     # a 20-sigma jump
    events = []
    ctx.broker.listen(events.append)
    found = asyncio.run(datahub.scan(ctx))
    assert [w["symbol"] for w in found] == ["test:spread"]
    assert any(e["kind"] == "hub_warning" for e in events)
    assert asyncio.run(datahub.scan(ctx)) and sum(e["kind"] == "hub_warning" for e in events) == 1   # once per series and day
    d = client.get("/api/hub").json()
    row = next(s for s in d["series"] if s["id"] == "test:spread")
    assert row["z"] > 10 and len(row["spark"]) == 60 and d["warnings"][0]["symbol"] == "test:spread"
    csv_text = client.get("/api/hub/csv/test:spread").text
    assert csv_text.startswith("date,value\n2020-01-01,") and csv_text.count("\n") == 202
    assert "error" in client.get("/api/hub/series/nope").json()


def test_source_urls():
    assert datahub.source_url("fred:DGS10") == "https://fred.stlouisfed.org/series/DGS10"
    assert datahub.source_url("mkt:^GDAXI") == "https://finance.yahoo.com/quote/^GDAXI"
    assert "s=WCESTUS1" in datahub.source_url("eia:crude_oil_stocks_excl_spr")
    assert datahub.source_url("eiagas:lower_48_total").endswith("nw2_epg0_swo_r48_bcfw.htm")
    assert datahub.source_url("eiagas:east:vs5y") == datahub.EIA_GAS_REPORT
    assert datahub.source_url("basket:ab12") == "#/baskets/ab12" and datahub.source_url("x:y") is None
