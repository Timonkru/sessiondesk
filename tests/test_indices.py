"""Index internals: breadth counts, divergence flag, contributions, bottom-up P/E, own history, FactSet parsing."""
from __future__ import annotations

import pytest

from sessiondesk.features import indices


def _series(start: float, step: float, n: int = 260) -> list[float]:
    return [start + step * i for i in range(n)]


def test_breadth_counts_and_line():
    closes = {"UP": _series(100, 0.5), "DOWN": _series(300, -0.5), "FLAT": [50.0] * 259 + [50.5]}
    b = indices.breadth(closes, _series(1000, 1))
    assert b["n"] == 3 and b["up"] == 2 and b["down"] == 1
    assert b["above50_pct"] == pytest.approx(200 / 3)          # UP and FLAT (last tick above its flat average)
    assert b["new_high52"] == 2 and b["new_low52"] == 1
    assert len(b["line"]) == 61 and b["line"][-1] == pytest.approx(b["above50_pct"])
    assert len(b["index_line"]) == len(b["line"])
    assert "divergence" not in b                               # breadth did not fall while the index rose


def test_breadth_flags_narrowing_advance():
    # index at a new high; breadth: 10 members were above their 50-day average, half of them roll over in the last 15 days
    closes = {}
    for k in range(10):
        c = _series(100, 0.2)
        if k < 5:
            c = c[:-15] + [c[-16] - 0.6 * j for j in range(1, 16)]
        closes[f"M{k}"] = c
    b = indices.breadth(closes, _series(1000, 1))
    assert b["breadth_20d_pts"] <= -10
    assert b["divergence"].startswith("bearish")


def test_breadth_skips_short_histories():
    assert indices.breadth({"NEW": [1.0] * 30}, []) == {}
    # a recent listing (70 closes) counts today but must not cut the 60-session line short
    b = indices.breadth({"OLD": _series(100, 0.5), "IPO": _series(10, 0.1, 70)}, [])
    assert b["n"] == 2 and len(b["line"]) == 61


def test_drivers_price_weighted_use_the_divisor():
    rows = [{"symbol": "A", "pct": 1.0, "abs": 6.0}, {"symbol": "B", "pct": -1.0, "abs": -2.0}]
    out = indices.drivers(rows, {}, True, 0.1)                       # divisor 0.1: $1 = 10 index points
    assert [r["symbol"] for r in out] == ["B", "A"]
    assert out[1]["points"] == pytest.approx(60.0) and out[0]["points"] == pytest.approx(-20.0)
    # signs follow the member's own move even if the index quote disagrees (live test 19.10.2026)
    idx = [1000.0, 1010.0]                                            # index up while the members' dollar sum is down
    closes = {"UP": [100.0, 101.0], "DOWN": [200.0, 195.0]}
    blk = indices.driver_block(indices.period_rows(closes, 1), {}, True, idx, 1)
    assert blk["drivers_up"][0]["symbol"] == "UP" and blk["drivers_down"][0]["symbol"] == "DOWN"
    assert blk["contrib_total"] < 0 < blk["index_points"]             # the gap is shown, not hidden


def test_drivers_cap_weighted_and_missing_caps():
    rows = [{"symbol": "BIG", "pct": 1.0, "abs": 1}, {"symbol": "SMALL", "pct": -4.0, "abs": -1}, {"symbol": "NOCAP", "pct": 9.0, "abs": 1}]
    out = indices.drivers(rows, {"BIG": 900.0, "SMALL": 100.0}, False, None)
    assert [r["symbol"] for r in out] == ["SMALL", "BIG"]          # NOCAP has no weight, left out
    assert out[1]["contrib_pct"] == pytest.approx(0.9) and out[0]["contrib_pct"] == pytest.approx(-0.4)
    assert indices.drivers(rows, {}, False, None) == []            # caller falls back to plain movers


def test_share_classes_are_not_counted_twice():
    profiles = [{"symbol": "GOOGL", "name": "Alphabet Inc.", "market_cap": 4.2e12, "shares": 5.9e9, "price": 350.0},
                {"symbol": "GOOG", "name": "Alphabet Inc.", "market_cap": 4.2e12, "shares": 5.5e9, "price": 345.0},
                {"symbol": "MSFT", "name": "Microsoft", "market_cap": 3.5e12, "shares": 7.4e9, "price": 470.0}]
    caps = indices.class_caps(profiles)
    assert caps["GOOGL"] == pytest.approx(5.9e9 * 350) and caps["GOOG"] == pytest.approx(5.5e9 * 345)
    assert caps["MSFT"] == 3.5e12                                  # single class: the reported cap stays


def test_aggregate_pe_cap_and_price_weighted():
    profiles = [{"symbol": "A", "pe_forward": 20, "market_cap": 200, "price": 100, "eps_forward": 5},
                {"symbol": "B", "pe_forward": 10, "market_cap": 100, "price": 50, "eps_forward": 5},
                {"symbol": "JUNK", "pe_forward": 5000, "market_cap": 50}]
    cap = indices.aggregate_pe(profiles, False)
    assert cap["fwd_pe"] == pytest.approx(300 / 20) and cap["used"] == 2
    assert cap["rejected"] == ["JUNK (5000.0)"]
    price = indices.aggregate_pe(profiles, True)
    assert price["fwd_pe"] == pytest.approx(150 / 10)
    assert indices.aggregate_pe([{"symbol": "X"}], False) is None


def test_history_one_point_per_day(tmp_path):
    path = tmp_path / "valuation_history.jsonl"
    indices.record_history(path, "DAX 40", 14.0, "2026-10-14")
    indices.record_history(path, "DAX 40", 15.0, "2026-10-15")
    again = indices.record_history(path, "DAX 40", 15.5, "2026-10-15")   # same day: not appended twice
    indices.record_history(path, "Dow 30", 20.0, "2026-10-15")
    assert again["n"] == 2 and again["since"] == "2026-10-14"
    assert again["percentile"] == pytest.approx(100.0)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


FACTSET_TEXT = """Key Metrics ... The forward 12-month P/E ratio for the S&P 500 is 22.4. This P/E ratio is above the
5-year average (19.9) and above the 10-year average (18.6). ... For CY 2026, analysts are predicting earnings growth
of 12.1% and revenue growth of 6.4%. For CY 2027, analysts are calling for earnings growth of 13.9%. ... Based on this
closing price of 6,712.45 ... the trailing 12-month P/E ratio is 27.1 ... the bottom-up target price for the S&P 500 is 7,610.22"""


def test_parse_factset_sentences():
    out = indices.parse_factset(FACTSET_TEXT)
    assert out["fwd_pe"] == 22.4 and out["pe_avg5"] == 19.9 and out["pe_avg10"] == 18.6
    assert out["close"] == 6712.45 and out["target"] == 7610.22 and out["trailing_pe"] == 27.1
    assert out["cy_growth"] == {"2026": 12.1, "2027": 13.9}
    assert out["fwd_eps"] == pytest.approx(6712.45 / 22.4)
    with pytest.raises(ValueError):
        indices.parse_factset("a report without the sentence")


def test_drivers_over_a_week_and_a_month():
    closes = {"UP": [100.0] * 30 + [110.0] * 5, "DOWN": [50.0] * 30 + [45.0] * 5}
    idx = [1500.0] * 30 + [1550.0] * 5                             # = price sum / 0.1, a consistent price-weighted index
    rows = indices.period_rows(closes, 5)                         # five sessions back is the last 100 / 50
    assert {r["symbol"]: round(r["pct"], 1) for r in rows} == {"UP": 10.0, "DOWN": -10.0}
    blk = indices.driver_block(rows, {}, True, idx, 5)
    assert blk["index_points"] == 50.0 and blk["sessions"] == 5 and blk["divisor"] == pytest.approx(0.1)
    assert blk["drivers_up"][0]["symbol"] == "UP" and blk["drivers_up"][0]["points"] == pytest.approx(100.0)
    assert blk["contrib_total"] == pytest.approx(blk["index_points"])
    assert indices.driver_block(indices.period_rows(closes, 1), {}, True, idx, 1)["index_points"] == 0.0   # flat last session
    assert indices.period_rows({"SHORT": [1.0, 2.0]}, 5) == []
