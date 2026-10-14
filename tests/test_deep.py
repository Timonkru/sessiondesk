"""Deep instrument data: statement parsing, earnings reactions, performance statistics, seasonality, max pain."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from sessiondesk.features import deep


def _bars(closes, start=dt.datetime(2016, 1, 4, 14, 30, tzinfo=dt.timezone.utc)):
    out, day = [], start
    for c in closes:
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        out.append({"t": int(day.timestamp()), "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000})
        day += dt.timedelta(days=1)
    return out


def test_frame_rows_and_growth():
    cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    df = pd.DataFrame({cols[0]: [120.0, 60.0, 30.0, 2.4], cols[1]: [100.0, 45.0, 20.0, 2.0]},
                      index=["Total Revenue", "Gross Profit", "Operating Income", "Diluted EPS"])
    rows = deep.enrich_income(deep.frame_rows(df, deep.INCOME), quarterly=False)
    assert rows[0]["period"] == "2025-12-31" and rows[0]["revenue"] == 120
    assert rows[0]["revenue_growth"] == pytest.approx(0.2) and rows[0]["eps_growth"] == pytest.approx(0.2)
    assert rows[0]["gross_margin"] == pytest.approx(0.5) and rows[0]["operating_margin"] == pytest.approx(0.25)
    assert "revenue_growth" not in rows[1]


def test_earnings_reaction_uses_exchange_local_time():
    bars = _bars([100, 101, 110, 108], start=dt.datetime(2026, 7, 20, 13, 30, tzinfo=dt.timezone.utc))   # Mon..Thu
    ny = ZoneInfo("America/New_York")
    after = deep.reaction(bars, dt.datetime(2026, 7, 21, 16, 5, tzinfo=ny), "America/New_York")
    assert after["timing"] == "after close" and after["move"] == pytest.approx(110 / 101 - 1)
    before = deep.reaction(bars, dt.datetime(2026, 7, 22, 7, 0, tzinfo=ny), "America/New_York")
    assert before["timing"] == "before open" and before["move"] == pytest.approx(110 / 101 - 1)
    # A German company reporting at 22:00 Berlin = 16:00 New York -> after the Xetra close -> next session
    berlin = deep.reaction(bars, dt.datetime(2026, 7, 21, 16, 0, tzinfo=ny), "Europe/Berlin")
    assert berlin["timing"] == "after close" and berlin["move"] == pytest.approx(110 / 101 - 1)


def test_perf_stats_returns_drawdown_and_beta():
    closes = [100 * (1.001 ** i) for i in range(800)]
    closes[700] = closes[699] * 0.8                     # a drawdown inside the last year
    bars = _bars(closes)
    bench = _bars([100 * (1.0005 ** i) for i in range(800)])
    s = deep.perf_stats(bars, bench)
    assert s["returns"]["1M"] > 0 and s["returns"]["1Y"] > 0
    assert s["drawdown"]["max_1y"] <= -0.19
    assert s["range_52w"]["high"] >= s["last"] * 0.99
    assert "1Y" in s["relative"] and "YTD" in s["relative"]


def test_seasonality_counts_months():
    closes = [100 + (i % 21) for i in range(260 * 3)]
    sea = deep.seasonality(_bars(closes))
    assert len(sea["months"]) == 12 and sum(m["n"] for m in sea["months"]) >= 30
    assert sea["years"] and all("return" in y for y in sea["years"])


def test_max_pain_picks_lowest_payout_strike():
    calls = pd.DataFrame({"strike": [90.0, 100.0, 110.0], "openInterest": [10, 100, 500]})
    puts = pd.DataFrame({"strike": [90.0, 100.0, 110.0], "openInterest": [500, 100, 10]})
    assert deep.max_pain(calls, puts) == 100.0


def test_earnings_stats():
    rows = [{"move": 0.05, "surprise_pct": 3.0}, {"move": -0.04, "surprise_pct": -2.0}, {"move": 0.02, "surprise_pct": 1.0}]
    st = deep.earnings_stats(rows)
    assert st["n"] == 3 and st["avg_abs_move"] == pytest.approx(0.11 / 3) and st["beat_share"] == pytest.approx(2 / 3)
    assert st["avg_move_on_miss"] == pytest.approx(-0.04)
