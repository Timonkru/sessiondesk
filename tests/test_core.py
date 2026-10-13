"""Cache, settings/secrets, valuation math, forced-flow dates, calendar merge, news triage, movers maths."""
from __future__ import annotations

import asyncio
import datetime as dt
import time

import pytest

from sessiondesk.cache import Cache
from sessiondesk.features import calendar as cal
from sessiondesk.features import flows, movers, news, valuation
from sessiondesk.settings import Secrets, Settings


# ------------------------------------------------------------------ cache
def test_cache_fresh_swr_and_single_flight():
    async def run():
        cache, calls = Cache(), {"n": 0}

        async def build():
            calls["n"] += 1
            await asyncio.sleep(0.01)
            return {"v": calls["n"]}
        a, b = await asyncio.gather(cache.get("k", 60, build), cache.get("k", 60, build))
        assert a["v"] == b["v"] == 1 and calls["n"] == 1          # one build for concurrent callers
        assert (await cache.get("k", 60, build))["v"] == 1         # fresh hit
        stale = await cache.get("k", 0, build)                     # expired -> old value now, rebuild in background
        assert stale["v"] == 1 and stale["refreshing"]
        await asyncio.sleep(0.05)
        assert (await cache.get("k", 60, build))["v"] == 2
    asyncio.run(run())


def test_cache_failure_keeps_last_good_value_and_backs_off():
    async def run():
        cache, state = Cache(), {"fail": False, "n": 0}

        async def build():
            state["n"] += 1
            if state["fail"]:
                raise RuntimeError("provider down")
            return {"v": 1}
        await cache.get("k", 60, build)
        state["fail"] = True
        await cache.get("k", 0, build, swr=False)
        res = await cache.get("k", 0, build, swr=False)
        assert res["v"] == 1 and res["stale"] and "provider down" in res["stale_reason"]
        n = state["n"]
        await cache.get("k", 0, build, swr=False)
        assert state["n"] == n                                     # inside the retry window: no new call
        never = await cache.get("x", 60, build)
        assert "error" in never
    asyncio.run(run())


def test_secrets_are_described_never_returned(tmp_path, monkeypatch):
    monkeypatch.delenv("SESSIONDESK_FINNHUB_API_KEY", raising=False)
    s = Secrets(tmp_path)
    s.set("finnhub.api_key", "abcdef123456")
    d = s.describe("finnhub.api_key")
    assert d == {"set": True, "source": "app", "hint": "…3456"}
    monkeypatch.setenv("SESSIONDESK_FINNHUB_API_KEY", "envkey9999")
    assert s.get("finnhub.api_key") == "envkey9999" and s.describe("finnhub.api_key")["source"].startswith("env")
    s.set("finnhub.api_key", "")
    monkeypatch.delenv("SESSIONDESK_FINNHUB_API_KEY")
    assert s.get("finnhub.api_key") is None


def test_settings_merge_and_persist(tmp_path):
    st = Settings(tmp_path)
    st.update({"alerts": {"min_abs_pct": 4.0}})
    again = Settings(tmp_path)
    assert again.get("alerts.min_abs_pct") == 4.0 and again.get("alerts.min_abs_z") == 2.5


# ------------------------------------------------------------------ valuation
def test_dcf_reduces_to_gordon_growth():
    # growth == terminal: value = FCF1 / (r - g) exactly
    v = valuation.dcf_per_share(100.0, 0.03, discount=0.08, terminal=0.03, years=10, net_debt=0.0, shares=1.0)
    assert v == pytest.approx(100 * 1.03 / 0.05, rel=1e-9)


def test_implied_growth_round_trip():
    kw = dict(discount=0.09, terminal=0.025, years=10, net_debt=50.0, shares=10.0)
    price = valuation.dcf_per_share(20.0, 0.12, **kw)
    assert valuation.implied_growth(price, 20.0, **kw) == pytest.approx(0.12, abs=1e-6)
    assert valuation.implied_growth(price, -5.0, **kw) is None


def test_multiples_flags_implausible_and_inconsistent():
    rows = {r["key"]: r for r in valuation.check_multiples({"pe_trailing": -12, "pe_forward": 30, "price": 100, "eps_forward": 1430,
                                                            "ev_ebitda": 900})}
    assert "negative" in rows["pe_trailing"]["flag"]
    assert "inconsistent" in rows["pe_forward"]["flag"]
    assert "implausible" in rows["ev_ebitda"]["flag"]


# ------------------------------------------------------------------ forced flows
def test_flow_dates_follow_rules():
    assert flows.third_friday(2026, 10) == dt.date(2026, 10, 16)
    assert flows.expiry_friday(2026, 12) == dt.date(2026, 12, 18)
    assert flows.vix_expiry(2026, 10) == dt.date(2026, 10, 21)
    assert flows.last_business_day(2026, 11, "US") == dt.date(2026, 11, 30)
    assert flows.gotobi_days(2026, 10) == [dt.date(2026, 10, d) for d in (5, 9, 15, 20, 23, 30)]
    evs = flows.events_between(dt.date(2026, 11, 1), dt.date(2026, 12, 31))
    names = {(e["date"], e["name"]) for e in evs}
    assert ("2026-11-30", "MSCI semi-annual index review effective") in names
    assert any(d == "2026-12-18" and "Nasdaq-100" in n and "reconstitution" in n for d, n in names)


# ------------------------------------------------------------------ calendar
def test_calendar_merges_sources_and_keeps_periods_apart():
    from sessiondesk.connectors.mt5 import parse_mt5_calendar
    from sessiondesk.connectors.public import parse_ff
    from tests.conftest import FF_WEEK
    ff = parse_ff(FF_WEEK)
    ts = ff[0]["ts"]
    mt5 = parse_mt5_calendar([
        {"value_id": "1", "time_utc": str(int(ts)), "currency": "USD", "name": "Core CPI m/m", "importance": "3",
         "actual": "0.4", "forecast": "0.2", "previous": "0.3", "unit": "%"},
        {"value_id": "2", "time_utc": str(int(ts)), "currency": "USD", "name": "CPI y/y", "importance": "3",
         "actual": "", "forecast": "2.9", "previous": "2.8", "unit": "%"}])
    merged = cal.merge({"ffcal": ff, "mt5": mt5})
    core = [e for e in merged if e["title"] == "Core CPI m/m"]
    assert len(core) == 1 and core[0]["actual"] == "0.4%" and set(core[0]["sources"]) == {"mt5", "ffcal"}
    assert core[0]["surprise"] == pytest.approx(0.2)
    assert len([e for e in merged if "CPI" in e["title"]]) == 2          # m/m and y/y stay separate
    assert not cal.same_event(dict(ff[0]), dict(ff[1]))


def test_release_headline_matching():
    ev = {"title": "Core CPI m/m", "currency": "USD"}
    assert cal.headline_matches(ev, "US Core CPI MoM Actual 0.4% (Forecast 0.2%)")
    assert not cal.headline_matches(ev, "Oil rises on supply worries")


# ------------------------------------------------------------------ news triage
@pytest.mark.parametrize("title,impact", [
    ("Fed holds rates steady, signals patience", "high"),
    ("US CPI rises 0.4% in September vs 0.2% expected", "high"),
    ("Russia and Ukraine agree to truce talks", "high"),
    ("Powell says policy is well positioned", "medium"),
    ("Company X opens new office in Berlin", "normal"),
])
def test_news_classification(title, impact):
    assert news.classify({"title": title})[0] == impact


def test_symbol_tagging():
    tags = news.tag_symbols({"title": "Apple jumps; $NVDA slips (NASDAQ: AMD)", "summary": ""})
    assert {"NVDA", "AMD", "AAPL"} <= set(tags)


# ------------------------------------------------------------------ movers
def test_sigma_beta_and_rules():
    import math
    base = [100 * math.exp(0.01 * ((-1) ** i)) for i in range(70)]
    assert movers.sigma(base) == pytest.approx(0.0200, rel=0.05)
    assert movers.beta(base, base) == pytest.approx(1.0)
    rules = {"min_abs_pct": 3, "min_abs_z": 2.5, "always_abs_pct": 8, "watchlist_abs_pct": 2, "watchlist_abs_z": 2}
    assert movers.is_unusual(9.0, None, rules, False)
    assert movers.is_unusual(4.0, 3.0, rules, False) and not movers.is_unusual(4.0, 1.0, rules, False)
    assert movers.is_unusual(2.5, 2.2, rules, True) and not movers.is_unusual(2.5, 2.2, rules, False)


def test_explanation_attributes_move():
    row = {"symbol": "XYZ", "pct": -10.0, "z": -6.0, "bench_name": "S&P 500", "bench_pct": 0.5, "sector_etf": "XLC",
           "sector_pct": -1.0, "beta": 0.8, "explained_pct": -0.8, "specific_share": 0.92, "earnings": "before the open today",
           "headlines": [{"title": "XYZ cuts guidance"}]}
    text = movers.explain(row)
    assert "mostly stock-specific" in text and "Earnings" in text and "XYZ cuts guidance" in text


def test_headline_must_name_the_company():
    assert movers.mentions("Verizon Stock Fell 10% in a Day", "VZ", "Verizon")
    assert not movers.mentions("5 Dividend Stocks for Retirees", "VZ", "Verizon")
    assert movers.mentions("Is AT&T (T) Ready for a Starlink World", "T", "AT&T")
    assert not movers.mentions("Pineapple prices jump", "AAPL", "Apple Inc.")


def test_feed_parser_handles_undated_items():
    from sessiondesk.features.feeds import parse_feed
    raw = b"<rss><channel><item><title>No date here</title><link>https://x/1</link></item></channel></rss>"
    item = parse_feed(raw, "X")[0]
    assert item["undated"] and item["published"] < time.time() - 3600
