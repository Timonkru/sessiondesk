"""BTC vs the short-term holder realized price: parsers of both sources, the zone state machine, the alert path."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import struct
from types import SimpleNamespace

from sessiondesk.features import onchain, sthzone


def test_checkonchain_trace_plain_and_binary():
    plain = '{"name":"Price","x":["2026-10-26"],"y":[80000]},{"name":"STH Cost Basis","x":["2026-10-26T00:00:00+00:00","2026-10-27T00:00:00+00:00"],"y":[75735.34,75746.53]}'
    assert onchain.parse_checkonchain(plain) == [("2026-10-26", 75735.34), ("2026-10-27", 75746.53)]
    bdata = json.dumps(base64.b64encode(struct.pack("<2d", 75735.34, 75746.53)).decode()).replace("/", "\\u002f")
    binary = '{"name":"STH Cost Basis","x":["2026-10-26T00:00:00+00:00","2026-10-27T00:00:00+00:00"],"y":{"dtype":"f8","bdata":' + bdata + '}}'
    assert onchain.parse_checkonchain(binary) == [("2026-10-26", 75735.34), ("2026-10-27", 75746.53)]
    assert onchain.parse_checkonchain("<html>nothing</html>") == []


def test_bgeometrics_rows():
    rows = [{"d": "2026-10-20", "unixTs": "1792454400", "sthRealizedPrice": "74736.27"}, {"d": "2026-10-19", "sthRealizedPrice": "74682.09"},
            {"d": "bad"}]
    assert onchain.parse_bgeometrics(rows) == [("2026-10-19", 74682.09), ("2026-10-20", 74736.27)]
    assert onchain.parse_bgeometrics({"d": "2026-10-20", "sthRealizedPrice": "74736.27", "delayed": True}) == [("2026-10-20", 74736.27)]


def test_zone_fires_once_per_visit():
    lvl, band, rearm = 75000.0, 200.0, 50.0
    st, ev = sthzone.step(None, 80000, lvl, band, rearm)
    assert ev is None and st == {"inside": False, "side": "above"}             # first check only records
    st, ev = sthzone.step(st, 75150, lvl, band, rearm)
    assert ev == {"type": "enter", "from": "above"} and st["inside"]
    for p in (75020, 74950, 75190, 75240):                                     # hovering, crossing, edge: no repeat
        st, ev = sthzone.step(st, p, lvl, band, rearm)
        assert ev is None
    st, ev = sthzone.step(st, 75260, lvl, band, rearm)                         # left by band + rearm: armed again
    assert ev is None and not st["inside"]
    st, ev = sthzone.step(st, 75199, lvl, band, rearm)
    assert ev["type"] == "enter"


def test_zone_catches_a_jump_across_the_level():
    st, _ = sthzone.step(None, 76000, 75000, 200, 50)
    st, ev = sthzone.step(st, 74000, 75000, 200, 50)                           # fell through the zone between checks
    assert ev == {"type": "cross", "from": "above"}


def test_zone_starting_inside_does_not_alert_after_a_restart():
    st, ev = sthzone.step(None, 75100, 75000, 200, 50)
    assert ev is None and st["inside"]


class _DB:
    def __init__(self, series):
        self.series, self.alerts = series, []

    async def run(self, fn, *args):
        return fn(*args)

    def observations(self, sid, limit=400):
        return self.series.get(sid, [])

    def add_alert(self, alert):
        self.alerts.append(alert)
        return True


def _ctx(tmp_path, series, price, monkeypatch, settings=None):
    published = []
    today = dt.date.today()
    ctx = SimpleNamespace(data_dir=tmp_path, settings=SimpleNamespace(get=lambda k, d=None: (settings or {}).get(k, d)),
                          db=_DB(series), broker=SimpleNamespace(publish=lambda kind, data: published.append((kind, data))))

    async def fake_price(_ctx, _sym):
        return {"price": price["v"], "time": 0}
    monkeypatch.setattr(sthzone, "btc_price", fake_price)
    return ctx, published, today


def test_run_check_publishes_like_an_own_alert_and_pauses_on_old_levels(tmp_path, monkeypatch):
    price = {"v": 80000.0}
    today = dt.date.today().isoformat()
    ctx, published, _ = _ctx(tmp_path, {"onchain:sth_rp": [("2026-01-01", 70000.0), (today, 75000.0)]}, price, monkeypatch)
    assert asyncio.run(sthzone.run_check(ctx)) is None                         # first check records
    price["v"] = 75120.0
    alert = asyncio.run(sthzone.run_check(ctx))
    assert alert and published[-1][0] == "price_alert" and alert["data"]["source"] == "sth"
    assert "within 200 $" in alert["title"] and "75,000" in alert["body"] and ctx.db.alerts
    old = (dt.date.today() - dt.timedelta(days=7)).isoformat()                 # only the delayed free source: paused
    ctx2, published2, _ = _ctx(tmp_path / "x", {"onchain:sth_rp_bgeo": [(old, 75000.0)]}, {"v": 75000.0}, monkeypatch)
    (tmp_path / "x").mkdir()
    assert asyncio.run(sthzone.run_check(ctx2)) is None and not published2
    st = asyncio.run(sthzone.status(ctx2))
    assert st["paused"] and st["level"]["series"] == "onchain:sth_rp_bgeo"


def test_level_reports_the_cross_check(tmp_path, monkeypatch):
    ctx, _, _ = _ctx(tmp_path, {"onchain:sth_rp": [("2026-10-20", 74612.94), ("2026-10-27", 75746.53)],
                                "onchain:sth_rp_bgeo": [("2026-10-20", 74736.27)]}, {"v": 80000.0}, monkeypatch)
    lv = asyncio.run(sthzone.level(ctx))
    assert lv["value"] == 75746.53 and lv["series"] == "onchain:sth_rp"
    assert lv["check"]["day"] == "2026-10-20" and round(lv["check"]["diff"], 2) == -123.33
