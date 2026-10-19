"""Screener: RSI, per-stock measures, rows from cached closes + cached profiles; member closes never mutate the cache."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sessiondesk.cache import Cache
from sessiondesk.features import indices, screener


def test_rsi_extremes_and_known_value():
    assert screener.rsi(list(range(1, 40))) == 100.0                  # only gains
    assert screener.rsi(list(range(40, 1, -1))) == pytest.approx(0.0)  # only losses
    assert screener.rsi([1.0] * 5) is None
    # alternating +1/-1 with equal sizes -> RSI 50
    assert screener.rsi([10 + (i % 2) for i in range(60)]) == pytest.approx(50.0, abs=2)


def test_metrics_from_closes():
    c = [100 + i * 0.5 for i in range(260)]                             # steady climb
    m = screener.metrics(c)
    assert m["from_high"] == pytest.approx(0.0) and m["above50"] and m["above200"]
    assert m["chg1d"] == pytest.approx((c[-1] / c[-2] - 1) * 100)
    assert m["rsi14"] == 100.0 and m["vol20"] < 1
    assert screener.metrics([1.0] * 10) is None


class _Yahoo:
    def __init__(self):
        self.calls = 0

    async def daily_closes(self, symbols, range_):
        self.calls += 1
        return {s: [100.0 + i for i in range(260)] for s in symbols}


def _ctx(tmp_path):
    yahoo = _Yahoo()
    hub = SimpleNamespace(get=lambda cid: yahoo, candidates=lambda cap: [])
    return SimpleNamespace(cache=Cache(tmp_path / "cache"), hub=hub, settings=SimpleNamespace(get=lambda k, d=None: d)), yahoo


def test_member_closes_keep_the_cached_index(tmp_path):
    ctx, yahoo = _ctx(tmp_path)
    first = asyncio.run(indices.member_closes(ctx, "dow30"))
    second = asyncio.run(indices.member_closes(ctx, "dow30"))
    assert yahoo.calls == 1                                              # second call from the cache
    assert len(first["index"]) == 260 and len(second["index"]) == 260   # the index series is still there


def test_screen_rows_with_cached_profile(tmp_path):
    ctx, _ = _ctx(tmp_path)
    asyncio.run(ctx.cache.get("profile:v2:AAPL", 3600, lambda: {"market_cap": 3e12, "pe_forward": 30.5, "dividend_yield": 0.004}))
    out = asyncio.run(screener.screen(ctx, "dow30"))
    assert out["with_profile"] == 1 and len(out["rows"]) == 30
    aapl = next(r for r in out["rows"] if r["symbol"] == "AAPL")
    assert aapl["pe_fwd"] == 30.5 and aapl["div_yield"] == pytest.approx(0.4) and aapl["sector"]
    assert "error" in asyncio.run(screener.screen(ctx, "nope"))
