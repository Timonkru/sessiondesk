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


def test_power_daily_base_price():
    import datetime as dt
    utc = dt.timezone.utc
    day1 = int(dt.datetime(2026, 10, 19, tzinfo=utc).timestamp())
    unix = [day1 + i * 900 for i in range(96)] + [day1 + 86400 + i * 900 for i in range(10)]   # day 2 only partly published
    prices = [100.0] * 48 + [50.0] * 47 + [None] + [80.0] * 10
    assert datahub.power_daily(unix, prices, utc) == [("2026-10-19", round((48 * 100 + 47 * 50) / 95, 2))]
    assert datahub.power_daily([], [], utc) == []
    assert "c=DE" in datahub.source_url("power:de-lu")


def _flow(key_op, point, day, value):
    import datetime as dt
    end = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    return {"operatorKey": key_op, "pointKey": point, "directionKey": "entry", "periodFrom": f"{day}T06:00:00+02:00",
            "periodTo": f"{end}T06:00:00+02:00", "value": value}


def test_entsog_daily_counts_only_complete_days():
    rows = ([_flow("FR-TSO-0003", "ITP-00045", f"2026-10-{d:02d}", 500e6) for d in range(1, 21)]
            + [_flow("BE-TSO-0001", "ITP-00106", f"2026-10-{d:02d}", "400000000") for d in range(1, 20)]   # day 20 not yet reported
            + [_flow("DE-TSO-0009", "ITP-00525", f"2026-10-0{d}", 1e6) for d in range(1, 4)]           # silent since day 3: closed
            + [_flow("DK-TSO-0001", "ITP-00630", "2026-10-05", "")])                                   # "not available" rows carry no value
    groups = {"norway": ["fr-tso-0003itp-00045entry", "be-tso-0001itp-00106entry", "de-tso-0009itp-00525entry", "dk-tso-0001itp-00630entry"],
              "nothing": ["xx-tso-0001itp-99999entry"]}
    out = datahub.entsog_daily(rows, groups)
    assert "nothing" not in out
    pts = dict(out["norway"])
    assert pts["2026-10-01"] == 901.0 and pts["2026-10-04"] == 900.0       # GWh/d; the closed point counts while it reported
    assert "2026-10-20" not in pts and max(pts) == "2026-10-19"             # a late point keeps the newest day out
    assert datahub.entsog_daily([], groups) == {}
    import datetime as dt
    running = dt.datetime(2026, 10, 20, 9, 30, tzinfo=dt.timezone.utc)                # gas day 19.10. ended 04:00 UTC on the 20th
    partial = rows + [_flow("FR-TSO-0003", "ITP-00045", "2026-10-20", 20e6)]
    assert max(dict(datahub.entsog_daily(partial, {"fr": groups["norway"][:1]}, now=running)["fr"])) == "2026-10-19"
    assert datahub.sum_complete([[("a", 1.0), ("b", 2.0)], [("b", 3.0), ("c", 4.0)]]) == [("b", 5.0)]
    assert datahub.sum_complete([[("a", 1.0)], []]) == []
    groups = datahub.entsog_groups()
    keys = [k for _, ks in groups.values() for k in ks]
    assert len(keys) == len(set(keys)) and "lng_nl" in groups and "turkstream" in groups
    assert "hu-tso-0001itp-10013entry" not in keys and "it-tso-0001itp-00008entry" not in keys   # no double count of TurkStream / TAP
    assert datahub.source_url("entsog:total").startswith("https://transparency.entsog.eu")
    assert datahub.source_url("agsi:de:full") == "https://agsi.gie.eu/data-overview/DE"
    assert datahub.source_url("agsi:eu:injection") == "https://agsi.gie.eu/data-overview/eu"


def test_collect_entsog_stores_routes_and_totals(client, monkeypatch):
    import httpx
    ctx = client.app_state["ctx"]
    seen = []

    def handler(request):
        seen.append(request)
        keys = request.url.params["pointDirection"].split(",")
        rows = []
        for k in keys:
            op, point = k[:11].upper(), k[11:20].upper()
            rows += [_flow(op, point, f"2026-10-{d:02d}", 10e6) for d in range(1, 11)]
        return httpx.Response(200, json={"operationalData": rows})
    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(datahub, "ENTSOG_PAUSE", 0)
    n = asyncio.run(datahub.collect_entsog(ctx))
    assert n == len(datahub.entsog_groups()) + 2
    assert all(r.url.host == "transparency.entsog.eu" and r.url.params["indicator"] == "Physical Flow" for r in seen)
    nl = ctx.db.observations("entsog:lng_nl", 50)
    assert nl[-1] == ("2026-10-10", 20.0) and len(nl) == 10              # two terminals x 10 GWh/d
    n_keys = sum(len(ks) for _, ks in datahub.entsog_groups().values())
    assert ctx.db.observations("entsog:total", 50)[-1][1] == n_keys * 10.0
    import datetime as dt
    rnd = random.Random(3)
    jump = [((dt.date(2026, 10, 10) - dt.timedelta(days=300 - i)).isoformat(), 100 + rnd.gauss(0, 2)) for i in range(301)]
    jump.append(("2026-10-11", 500.0))
    for sid in ("entsog:lng_lt", "entsog:lng_total"):
        ctx.db.upsert_series({"id": sid, "name": sid, "category": datahub.ENTSOG_CATEGORY, "source": "t", "kind": "level"}, jump)
    assert {w["symbol"] for w in asyncio.run(datahub.scan(ctx, publish=False))} >= {"entsog:lng_total"}
    assert "entsog:lng_lt" not in {w["symbol"] for w in asyncio.run(datahub.scan(ctx, publish=False))}
    assert [datahub.warns(x) for x in ("entsog:total", "entsog:tap", "agsi:de:full", "agsi:de:injection", "fred:DGS10")] ==         [True, False, True, False, True]
    rows = {r["id"]: r for r in client.get("/api/commodities").json()["gas_flows"]}
    assert list(rows)[0] == "entsog:total" and rows["entsog:turkstream"]["last"] == 10.0
    hub = {s["id"]: s for s in client.get("/api/hub").json()["series"]}
    assert hub["entsog:norway"]["url"].startswith("https://transparency.entsog.eu")

    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    assert asyncio.run(datahub.collect_entsog(ctx)) == 0                # rate limit: stop, keep what is stored
    assert ctx.db.observations("entsog:lng_nl", 50)[-1] == ("2026-10-10", 20.0)


def test_parse_agsi():
    from sessiondesk.connectors.keyed import parse_agsi
    data = [{"code": "DE", "gasDayStart": "2026-10-19", "full": "77.81", "injection": "310.5", "withdrawal": "12.0", "gasInStorage": "191.2", "status": "C"},
            {"code": "DE", "gasDayStart": "2026-10-18", "full": "77.6", "injection": "-", "withdrawal": "", "gasInStorage": "190.7", "status": "E"},
            {"code": "DE", "gasDayStart": "2026-10-17", "full": "77.4", "status": "N"},
            {"code": "21Z000000000271O", "gasDayStart": "2026-10-19", "full": "50"}]
    rows = parse_agsi(data, "de")
    assert [r["day"] for r in rows] == ["2026-10-18", "2026-10-19"]
    assert rows[1] == {"day": "2026-10-19", "full": 77.81, "injection": 310.5, "withdrawal": 12.0, "stock": 191.2}
    assert rows[0]["injection"] is None and parse_agsi([], "eu") == []


def test_agsi_key_needed_then_collected_without_leaking(client, monkeypatch):
    import httpx
    monkeypatch.delenv("SESSIONDESK_AGSI_API_KEY", raising=False)
    ctx = client.app_state["ctx"]
    assert asyncio.run(datahub.collect_agsi(ctx)) == 0                  # no key: quietly nothing
    d = client.get("/api/commodities").json()
    assert d["gas_storage"] == [] and d["agsi"] == {"configured": False, "active": False, "verified": False}
    assert not any(s["name"] == "GIE AGSI+" for s in d["more_sources"])

    key = "agsitestkey98765"
    r = client.post("/api/connectors/agsi", json={"enabled": True, "fields": {"api_key": key}}).json()
    assert key not in str(r)
    seen = []

    def handler(request):
        seen.append(request)
        if request.headers.get("x-key") != key:
            return httpx.Response(200, json={"error": "access denied", "message": "Invalid or missing API key", "data": []})
        code = request.url.params.get("country") or "eu"
        page = int(request.url.params["page"])
        day = "2026-10-19" if page == 1 else "2026-10-18"
        return httpx.Response(200, json={"last_page": 2, "data": [{"code": code.upper() if code != "eu" else "eu", "gasDayStart": day,
                                                                   "full": "80.5" if page == 1 else "80.0", "injection": "200",
                                                                   "withdrawal": "5", "gasInStorage": "100", "status": "C"}]})
    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(type(ctx.hub.get("agsi")), "PAUSE", 0)
    assert asyncio.run(datahub.collect_agsi(ctx)) == len(datahub.AGSI_SCOPES)
    assert {r.url.params.get("type") for r in seen} == {None, "eu"} and all(r.url.params["size"] == "300" for r in seen)
    assert ctx.db.observations("agsi:de:full", 10) == [("2026-10-18", 80.0), ("2026-10-19", 80.5)]
    d = client.get("/api/commodities").json()
    de = next(s for s in d["gas_storage"] if s["code"] == "de")
    assert de["full"] == 80.5 and de["full_prev"] == 80.0 and de["injection"] == 200.0 and de["name"] == "Germany"
    assert [s["code"] for s in d["gas_storage"]][0] == "eu" and d["agsi"]["configured"] is True
    for path in ("/api/connectors", "/api/commodities", "/api/hub"):
        assert key not in client.get(path).text

    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"error": "access denied", "message": "Invalid or missing API key", "data": []})))
    assert asyncio.run(datahub.collect_agsi(ctx)) == 0                  # wrong key: stops, health shows the error
    assert "access denied" in ctx.hub.health["agsi"]["last_error"]


def test_iv30_interpolation_and_hours():
    import datetime as dt
    rows = [{"days": 20, "atm_iv": 0.20}, {"days": 40, "atm_iv": 0.30}, {"days": 5, "atm_iv": None}]
    v = datahub.iv30(rows)                                   # total variance 0.8 at 20 d, 3.6 at 40 d -> 2.2 at 30 d
    assert abs(v - (2.2 / 30) ** 0.5) < 1e-9
    assert datahub.iv30([{"days": 45, "atm_iv": 0.25}]) == 0.25 and datahub.iv30([{"days": 90, "atm_iv": 0.25}]) is None
    assert datahub.us_options_live(dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.timezone.utc))
    assert not datahub.us_options_live(dt.datetime(2026, 10, 20, 7, 0, tzinfo=dt.timezone.utc))
    assert not datahub.us_options_live(dt.datetime(2026, 10, 24, 15, 0, tzinfo=dt.timezone.utc))      # Saturday
