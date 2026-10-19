"""Levels, level alerts, asset mapping, book-risk maths, exporter specs and calendar history."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from sessiondesk.connectors.mt5 import MT5Bridge
from sessiondesk.features import assets, levels, risk

GAMMA = """=== GAMMA-LEVEL v2  2026-10-09 ===
NQ    STRUKT | LONG    | Flip 30413.78 | CW 30825.27 (2nd 31030.77) | PW 30414.27 (2nd 30619.77) | EM1d ±351.41 | Spot 30725.81
NQ    FLOW   | Vanna -1M (Vol-down=Verkauf @29592)
NQ    NAH    | CW 30701.97 | PW 30619.77 | Flip 30840.71
"""
CRYPTO = "BTC  spot 81805 | LONG    | Flip 72717 (+11.11%) | CW 82000/85000 | PW 68000/75000 | EM1d +/-1499\n"
GENERIC = "DAX pivot 24510\nGOLD weekly high 4300.5\n"


def settings(**kv):
    base = {"round_steps": {}, "asset_patterns": {}, "level_max_age_hours": 96}
    base.update(kv)
    return SimpleNamespace(get=lambda key, default=None: base.get(key, default))


def test_level_text_formats():
    lv = levels.parse_level_text(GAMMA + CRYPTO + GENERIC)
    nq = dict(lv["NQ"])
    assert nq["gamma flip"] == 30413.78 and nq["call wall 2nd"] == 31030.77 and nq["near gamma flip"] == 30840.71
    assert dict(lv["BTC"])["put wall 2nd"] == 75000
    assert dict(lv["DAX"])["pivot"] == 24510 and dict(lv["GOLD"])["weekly high"] == 4300.5
    assert "FLOW" not in str(lv)


def test_asset_mapping_and_round_steps():
    s = settings(asset_patterns={"DAX": ["DE40X"]})
    assert assets.asset_of("GER40.cash") == "DAX" and assets.asset_of("NAS100") == "NQ" and assets.asset_of("DE40X", s) == "DAX"
    assert assets.asset_of("EURUSD.pro") == "EURUSD" and assets.asset_of("XYZ123") is None
    assert assets.yahoo_ticker("EURUSD") == "EURUSD=X" and assets.yahoo_ticker("GOLD") == "GC=F"
    assert assets.round_step("USDJPY") == 1.0 and assets.round_step("DAX") == 1000
    assert "fed" in assets.themes_of("Powell signals patience") and "GOLD" in [a for a in assets.ASSET_THEMES if "fed" in assets.ASSET_THEMES[a]]


def test_level_alert_fires_once_per_crossing():
    s = settings()
    files = {"DAX": [("pivot", 24510.0, "test")]}
    al = levels.LevelAlerter(cooldown=600)
    q = lambda p: {"k": {"symbol": "GER40", "asset": "DAX", "price": p, "source": "broker"}}  # noqa: E731
    assert al.check(q(24490), files, s, now=1000) == []                  # baseline
    hits = al.check(q(24520), files, s, now=1005)
    assert [h["label"] for h in hits] == ["pivot"] and hits[0]["direction"] == "up"
    assert al.check(q(24505), files, s, now=1010) == []                  # back down within the cooldown: silent
    round_hits = al.check(q(25010), files, s, now=2000)
    assert any(h["label"].startswith("round 25000") for h in round_hits)


def test_ladder_orders_nearest_levels():
    s = settings()
    prices = {"k": {"symbol": "GER40", "asset": "DAX", "price": 24800.0, "prev_high": 24900.0, "prev_low": 24600.0, "source": "broker"}}
    row = levels.ladder(prices, {"DAX": [("gamma flip", 25027.4, "g")]}, s)[0]
    assert row["above"][0]["label"] == "prev day high" and row["below"][0]["label"] == "prev day low"
    assert any(x["label"] == "round 25000" for x in row["above"])


def test_corr_beta_on_aligned_hours():
    x = {h: (0.01 if h % 2 else -0.01) for h in range(100)}
    y = {h: v * 2 for h, v in x.items()}
    c, beta, n = risk.corr_beta(y, x)
    assert n == 100 and c == pytest.approx(1.0) and beta == pytest.approx(2.0)
    assert risk.corr_beta({1: 0.1}, {1: 0.2})[0] is None


def test_exporter_specs_and_calendar_history(tmp_path):
    now = int(time.time())
    (tmp_path / "sym_123456.tsv").write_text(f"#updated\t{now}\t123456\tEUR\nGER40\t12\t0.5\t1.0\t-12.5\t3.1\t1\t-11.2\t2.8\t3\t0.1\t1.0\n", encoding="utf-8")
    (tmp_path / "calhist.tsv").write_text(f"#updated\t{now}\n1\tUSD\tCore CPI m/m\t{now - 86400 * 30}\t0.3\t0.2\t0.3\t%\t1\n"
                                          f"1\tUSD\tCore CPI m/m\t{now - 86400 * 60}\t0.2\t0.3\t0.2\t%\t2\n", encoding="utf-8")
    s = SimpleNamespace(get=lambda key, default=None: {"connectors.mt5.folder": str(tmp_path), "privacy.mask_accounts": True}.get(key, default))
    conn = MT5Bridge(SimpleNamespace(settings=s, secrets=None))
    spec = asyncio.run(conn.specs())[0]
    assert spec["symbol"] == "GER40" and spec["triple_day"] == "Wed" and spec["swap_long_money"] == -11.2 and spec["account"] == "…456"
    hist = asyncio.run(conn.calhist())
    ev = hist["USD|Core CPI m/m"]
    assert len(ev["releases"]) == 2 and ev["releases"][0]["surprise"] == pytest.approx(0.1)


def test_level_alerts_one_per_market_and_rearm_only_after_moving_away():
    s = settings()
    files = {"FTSE": [("prev day low", 10798.0, "session")]}
    al = levels.LevelAlerter(cooldown=600)
    two = lambda a, b: {"UK100": {"symbol": "UK100", "asset": "FTSE", "price": a, "source": "broker"},   # noqa: E731
                        "UK100.cash": {"symbol": "UK100.cash", "asset": "FTSE", "price": b, "source": "broker"}}
    al.check(two(10790, 10791), files, s, now=1000)
    hits = al.check(two(10801, 10802), files, s, now=1005)
    assert len(hits) == 1                                                  # two symbols, one market, one alert
    # chopping around the level long after the cooldown: still silent (never 0.1 % = ~10.8 pts away)
    for i, p in enumerate([10795, 10801, 10794, 10802, 10796]):
        assert al.check(two(p, p), files, s, now=2000 + 700 * i) == []
    al.check(two(10812, 10812), files, s, now=6000)                      # moved away: re-armed
    assert len(al.check(two(10795, 10795), files, s, now=6700)) == 1
