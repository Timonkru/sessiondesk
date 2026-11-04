"""Briefing evidence: weekend coverage, local schedule, partial failures and model input budget."""
import asyncio
import datetime as dt
import json

import pytest

from sessiondesk.ai import assist
from sessiondesk.features import briefing, today


def test_monday_news_includes_friday_close_across_dst():
    monday = dt.datetime(2026, 10, 26, 7, 52, tzinfo=dt.timezone.utc).timestamp()
    start = dt.datetime.fromtimestamp(briefing.news_start(monday), dt.timezone.utc)
    assert start.isoformat() == "2026-10-23T20:00:00+00:00"
    # EU changed clocks, the US has not: the user's local time must stay explicit.
    event = monday + 98 * 60
    schedule, events = briefing.schedule_context({
        "schedule": [{"when": event - 600, "in_sec": 88 * 60, "session": "EU", "label": "test start", "collisions": []}],
        "events": [{"ts": event, "currency": "EUR", "title": "Ifo", "impact": "medium"}],
    }, briefing.ZoneInfo("Europe/Berlin"))
    assert schedule[0]["local"] == "2026-10-26T10:20+01:00"
    assert events[0]["local"] == "2026-10-26T10:30+01:00"
    assert events[0]["near_schedule"][0]["event_minus_schedule_min"] == 10


def test_news_keeps_relevant_normal_items_and_deduplicates(client):
    rows = [
        {"title": "German economy: Ifo weakens", "source": "one", "published": 1, "impact": "normal", "summary": "Survey details"},
        {"title": "German economy: Ifo weakens!", "source": "two", "published": 2, "impact": "normal"},
        {"title": "Other headline", "published": 3, "impact": "normal"},
    ]
    items = briefing.select_news(rows, ["DAX"], client.app_state["ctx"].settings)
    assert len(items) == 2
    assert items[0]["relevant_to"] == ["DAX"] and items[0]["summary"] == "Survey details"


FLASH = {"name": "Lam", "timing": "after close", "quarter": "Sep 2026", "consensus_frozen": True, "guidance": {"direction": "raised", "quotes": ["a", "b", "c"]}, "call": {"ts": 1793000000},
         "result": {"eps": {"verdict": "beat", "figures": [], "rows": [{"source": "yahoo", "actual": 2.2, "consensus": 2.0, "verdict": "beat", "basis": "adjusted", "label": "Non-GAAP EPS", "quote": "long"}]},
                    "revenue": {"verdict": "basis unclear", "figures": [{"value": 5e9, "basis": None, "label": "Revenue", "quote": "long"}],
                                "rows": [{"source": "yahoo", "actual": None, "consensus": 4.8e9, "verdict": "basis unclear", "why": "no match"}]}}}


def _no_network_options(monkeypatch):
    async def putcall(_):
        return {"rows": [{"symbol": "SPY", "pc_volume": 1.2, "pc_oi": 1.5, "expiries": ["x"]}], "asof": 1793000000}

    async def reported(_):
        return {"items": [], "asof": 1793000000}
    monkeypatch.setattr(briefing.indices, "putcall", putcall)
    monkeypatch.setattr(briefing.earnings_reported, "reported", reported)


def test_flash_view_keeps_verdicts_only_with_a_confirmed_basis():
    v = briefing.flash_view({**FLASH, "accepted": 1793000000})
    assert v["eps"]["verdict"] == "beat" and v["eps"]["compared"][0]["consensus_source"] == "yahoo" and "in_release" not in v["eps"]
    assert v["revenue"]["verdict"] == "basis unclear" and v["revenue"]["compared"] == [] and v["revenue"]["why"] == "no match"
    assert v["revenue"]["in_release"] == [{"value": 5e9, "basis": None, "label": "Revenue"}]
    assert v["guidance"] == {"direction": "raised", "quote": "a"}


def test_merge_reported_combines_sources_and_names_what_is_missing():
    vendor = [{"symbol": "AAA", "date": "2026-11-03", "timing": "before open", "importance": "medium", "cap": 5, "actual": 1.0, "estimate": 0.9, "surprise_pct": 11.1, "source": "Nasdaq", "move": 2.0, "market": 0.5, "excess": 1.5},
              {"symbol": "OLD", "date": "2026-10-30", "importance": "high", "cap": 9, "actual": 1.0, "estimate": 0.9},
              {"symbol": "BBB", "date": "2026-11-03", "timing": "after close", "importance": "high", "cap": 9, "actual": 3.0, "estimate": 3.1, "source": "Yahoo", "move": None}]
    m = briefing.merge_reported(vendor, {("BBB", "2026-11-03"): FLASH, ("CCC", "2026-11-03"): FLASH, ("OLD", "2026-10-30"): FLASH},
                                [{"symbol": "AAA", "date": "2026-11-03"}, {"symbol": "DDD", "date": "2026-11-03"}, {"symbol": "EEE", "date": "2026-10-30"}], "2026-11-03")
    assert [r["symbol"] for r in m["items"]] == ["BBB", "AAA", "CCC"]
    assert m["items"][0]["reaction"] is None and m["items"][0]["sec_filing"]["eps"]["verdict"] == "beat"
    assert m["items"][1]["reaction"]["vs_sp500_pct"] == 1.5 and "sec_filing" not in m["items"][1]
    assert m["items"][2]["vendor_eps"] is None
    assert m["no_result_yet"] == ["DDD"]
    assert all("cap" not in r for r in m["items"])


def test_iv_row_gives_no_percentile_on_a_short_history():
    assert briefing.iv_row("SPY", []) is None
    assert briefing.iv_row("SPY", [("2026-11-03", 15.0)])["change_pts"] is None
    short = [(f"d{i}", 10.0 + i) for i in range(briefing.IV_RANK_MIN - 1)]
    assert briefing.iv_row("SPY", short)["percentile"] is None
    assert briefing.iv_row("SPY", short + [("z", 5.0)])["percentile"] == 2


def test_briefing_context_preserves_late_sections_and_headline_depth():
    facts = {"news": {"items": [{"title": str(i)} for i in range(60)]}, "credit": {"spread": 0}, "accounts": [{"fresh": False}]}
    d = json.loads(assist.briefing_context_json(facts))
    assert len(d["news"]["items"]) == 60
    assert d["credit"]["spread"] == 0 and d["accounts"][0]["fresh"] is False
    facts["news"]["items"] = [{"title": "a" * 1000} for _ in range(100)]
    d = json.loads(assist.briefing_context_json(facts, max_chars=5000))
    assert "context_reduced" in d and d["credit"]["spread"] == 0 and "accounts" in d
    assert len(assist.briefing_context_json(facts, max_chars=5000)) <= 5000


def test_briefing_facts_include_richer_evidence_and_survive_optional_failure(client, monkeypatch):
    ctx = client.app_state["ctx"]
    now = dt.datetime(2026, 10, 26, 7, 52, tzinfo=dt.timezone.utc).timestamp()
    monkeypatch.setattr(briefing.time, "time", lambda: now)

    async def overview(_):
        return {"groups": [{"title": "Futures", "rows": [{"label": "Nasdaq", "symbol": "NQ=F", "price": 100,
                                 "change_pct": 0, "time": now - 900, "source": "stub"}]}], "stale": True}

    async def snap(_):
        return {"accounts": [{"login": "masked", "day_pct": None, "fresh": False}], "flags": [], "schedule": [],
                "events": [], "flows": [{"name": "Month end", "mechanism": "Portfolio rebalance", "markets": ["equities"]}],
                "positions": [{"symbol": "GER40", "side": "LONG", "ticket": "private-ticket", "fresh": True}]}

    async def failed(_):
        raise RuntimeError("sensitive-provider-error")

    async def level_data(_):
        return {"rows": [{"asset": "DAX", "price": 100, "above": [{"label": "prior high", "level": 101}]}],
                "files": [{"path": "private-file-path"}], "asof": now}

    monkeypatch.setattr(briefing.markets, "overview", overview)
    monkeypatch.setattr(today, "snapshot", snap)
    monkeypatch.setattr(briefing.macro, "rates", failed)
    monkeypatch.setattr(briefing.levels, "snapshot", level_data)
    _no_network_options(monkeypatch)
    ctx.db.upsert_series({"id": "iv:SPY", "name": "SPY IV", "category": "Implied volatility", "source": "test", "kind": "rate"}, [("2026-10-22", 15.0), ("2026-10-23", 16.5)])
    ctx.db.flash_put("LRCX", "2026-10-23", "acc", now - 3600, now - 3590, now - 3589, FLASH)
    facts = client.portal.call(today.briefing_facts, ctx)
    assert facts["missing_sources"].get("options") is None and facts["missing_sources"].get("earnings_reported") is None
    assert facts["options"]["iv_30d"] == [{"symbol": "SPY", "iv30_pct": 16.5, "day": "2026-10-23", "change_pts": 1.5, "days_of_history": 2,
                                           "low": 15.0, "high": 16.5, "percentile": None}]
    assert facts["options"]["put_call"]["rows"][0]["pc_volume"] == 1.2
    assert [r["symbol"] for r in facts["earnings_reported"]["items"]] == ["LRCX"]
    assert facts["earnings_reported"]["vendor_list_unavailable"] is True
    assert facts["missing_sources"]["rates"] == "RuntimeError"
    assert facts["markets"][0]["rows"][0]["observed_utc"] == "2026-10-26T07:37+00:00"
    assert facts["market_data_status"]["stale"] is True
    assert facts["accounts"][0]["fresh"] is False
    assert facts["levels"]["rows"][0]["above"][0]["level"] == 101
    assert facts["forced_flows_5d"][0]["mechanism"] == "Portfolio rebalance"
    assert facts["news"]["since_utc"] == "2026-10-23T20:00+00:00"
    text = json.dumps(facts)
    assert all(s not in text for s in ("private-ticket", "private-file-path", "sensitive-provider-error"))


def test_briefing_request_uses_full_context_and_larger_budget(client, monkeypatch):
    from sessiondesk.ai.providers import AnthropicProvider
    seen = {}

    async def stream(self, system, messages, max_tokens=4000, effort=None):
        seen.update(system=system, messages=messages, max_tokens=max_tokens)
        self.last_usage = {"model": self.model(), "in": 100, "out": 30}
        yield "Session assessment."

    monkeypatch.setattr(AnthropicProvider, "stream", stream)
    client.post("/api/connectors/anthropic", json={"fields": {"api_key": "test-secret-never-output"}})
    facts = {"news": {"items": [{"title": str(i)} for i in range(50)]}, "credit": {"spread": 4}}
    result = client.portal.call(assist.complete, client.app_state["ctx"], "briefing", "Write today's briefing.", facts)
    assert result["text"] == "Session assessment."
    assert seen["max_tokens"] == 9000
    context = seen["messages"][-1]["content"].split("CONTEXT JSON:\n")[1].split("\n\nQUESTION:")[0]
    assert len(json.loads(context)["news"]["items"]) == 50
    assert "test-secret-never-output" not in json.dumps(seen)
