"""Review facts must describe full exported populations and keep inference limits explicit."""
import datetime as dt
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from sessiondesk.ai import assist
from sessiondesk.features import review, today

TZ = ZoneInfo("Europe/Berlin")


def deal(account, position, entry, volume, time, net, magic="0", **extra):
    return {"account": account, "ticket": f"{position}-{entry}-{time}", "position_id": position, "symbol": "TEST",
            "entry": entry, "volume": volume, "time": time, "net": net, "magic": magic, "type": "BUY", **extra}


def test_closed_positions_include_entry_costs_and_reject_partial_lifecycles():
    rows = [deal("a", "1", "0", 2, 10, -2, "77"), deal("a", "1", "1", 1, 20, 50),
            deal("a", "1", "1", 1, 30, -10), deal("a", "partial", "0", 2, 10, 0),
            deal("a", "partial", "1", 1, 30, 10), deal("a", "missing", "1", 1, 30, 20),
            deal("a", "reversed", "0", 1, 10, 0), deal("a", "reversed", "2", 2, 20, 2),
            deal("a", "reversed", "1", 1, 30, 3)]
    closed, excluded = review.closed_trades(rows + [rows[0]], [])
    assert len(closed) == 1 and closed[0]["net"] == 38 and closed[0]["magic"] == "77"
    assert closed[0]["closed"] == 30
    assert excluded == {"partial_or_inconsistent_volume": 1, "entry_outside_export": 1, "reversal_positions": 1}
    assert review.closed_trades(rows[:3], [{"account": "a", "position_id": "1"}])[0] == []


def test_metrics_report_payoff_fragility_r_coverage_and_equal_time_uncertainty():
    start = 1_800_000_000
    rows = [{"closed": start + i * 60, "opened": start - 60, "net": v, "position_id": str(i),
             "risk_confirmed": 10 if i == 0 else None, "risk_observed": 20 if i == 1 else None}
            for i, v in enumerate((100, -30, -20, 0))]
    m = review.metrics(rows, TZ)
    assert m["trades"] == 4 and m["active_days"] == 1 and m["net"] == 50
    assert m["profit_factor"] == 2 and m["avg_win"] == 100 and m["avg_loss"] == -25
    assert m["net_without_best_trade"] == -50 and m["max_closed_pnl_drawdown"] == 50
    assert m["max_consecutive_losses"] == 2
    assert m["confirmed_r"] == {"n": 1, "avg": 10}
    assert m["observed_r_proxy"] == {"n": 1, "avg": -1.5}
    assert m["cost_components"]["commission"] is None
    tied = [{"closed": start, "net": 100}, {"closed": start, "net": -90}]
    assert review.metrics(tied, TZ)["max_closed_pnl_drawdown"] == 0
    assert review.metrics(tied, TZ)["max_consecutive_losses"] is None
    assert review.metrics([], TZ)["profit_factor"] is None


def test_accounts_copies_and_nonoverlapping_windows_stay_separate():
    now = 1_800_000_000
    rows = [{"account": "a", "position_id": "x", "magic": "0", "symbol": "X", "closed": now - 86400, "net": 100},
            {"account": "a", "position_id": "y", "magic": "0", "symbol": "X", "closed": now - 10 * 86400, "net": -20},
            {"account": "b", "position_id": "z", "magic": "88", "symbol": "X", "closed": now - 86400, "net": 3}]
    result = review.account_analysis(rows, {"a": "A", "b": "B"}, {"a": "EUR", "b": "USD"}, {"88": "Copier"}, {"88"}, now, TZ)
    assert result[0]["week"]["net"] == 100 and result[0]["previous_23d"]["net"] == -20
    assert result[0]["last_30d"]["net"] == 80 and result[0]["currency"] == "EUR"
    assert result[1]["week"]["net"] == 3 and result[1]["copy_trades"] == 1
    assert result[1]["by_setup"][0]["role"] == "copy"


def test_review_uses_all_exported_positions_not_last_200_journal_entries(client, monkeypatch):
    ctx = client.app_state["ctx"]
    now = review.time.time()
    deals = []
    for i in range(350):
        deals += [deal("private-account-999", str(i + 1), "0", 1, now - 10000 + i * 2, -1),
                  deal("private-account-999", str(i + 1), "1", 1, now - 9999 + i * 2, 3)]

    async def fetch():
        return deals

    async def overview(_):
        return {"accounts": [{"login": "private-account-999", "currency": "EUR", "fresh": True, "equity": 1000}],
                "positions": [], "asof": now}

    monkeypatch.setattr(ctx.hub, "candidates", lambda _: [SimpleNamespace(id="stub", deals=fetch)])
    monkeypatch.setattr(review.broker, "overview", overview)
    facts = client.portal.call(today.briefing_facts, ctx, "review")
    m = facts["accounts"][0]["week"]
    assert m["trades"] == 350 and m["net"] == 700
    assert facts["coverage"]["closed_positions_in_30d"] == 350
    assert "private-account-999" not in json.dumps(facts)
    assert facts["accounts"][0]["account"].endswith("…999)")
    assert facts["display_timezone"] == "Europe/Berlin"


def test_old_stop_observation_does_not_become_current_stop_status(client, monkeypatch):
    ctx = client.app_state["ctx"]
    now = review.time.time()
    ctx.db.journal_upsert({"account": "a", "position_id": "p", "symbol": "TEST", "magic": "0",
                           "opened": now - 100, "closed": now - 50, "net": 10,
                           "context": "first seen yesterday, stop none", "risk_observed": 0})

    async def overview(_):
        return {"accounts": [{"login": "a", "fresh": True, "currency": "USD", "equity": 1000}],
                "positions": [{"account": "a", "position_id": "live", "symbol": "TEST", "side": "LONG", "sl": 95, "fresh": True}]}

    monkeypatch.setattr(review.broker, "overview", overview)
    monkeypatch.setattr(ctx.hub, "candidates", lambda _: [])
    facts = client.portal.call(today.briefing_facts, ctx, "review")
    assert facts["accounts"][0]["first_seen_stop_absent"] == 1
    assert facts["current_snapshot"]["positions_without_stop"] == []
    assert facts["coverage"]["performance_source"] == "journal fallback"


def test_review_stream_uses_larger_budget_and_structured_context(client, monkeypatch):
    from sessiondesk.ai.providers import AnthropicProvider
    seen = {}

    async def stream(self, system, messages, max_tokens=4000, effort=None):
        seen.update(system=system, messages=messages, max_tokens=max_tokens)
        self.last_usage = {"model": self.model(), "in": 100, "out": 30}
        yield "Complete weekly assessment."

    monkeypatch.setattr(AnthropicProvider, "stream", stream)
    client.post("/api/connectors/anthropic", json={"fields": {"api_key": "dummy-private-key"}})
    facts = {"accounts": [{"by_setup": [{"setup": f"setup {i}"} for i in range(50)]}], "coverage": {"complete": True}}
    result = client.portal.call(assist.complete, client.app_state["ctx"], "review", "Review", facts)
    assert result["text"] == "Complete weekly assessment." and seen["max_tokens"] == 9000
    evidence = seen["messages"][-1]["content"].split("CONTEXT JSON:\n")[1].split("\n\nQUESTION:")[0]
    assert len(json.loads(evidence)["accounts"][0]["by_setup"]) == 50
    assert "dummy-private-key" not in json.dumps(seen)


def test_mt5_deals_preserve_cost_breakdown_without_changing_net(client, monkeypatch):
    bridge = client.app_state["ctx"].hub.get("mt5")
    source = {"login": "example", "rows": [{"type": "BUY", "entry": "1", "position_id": "7", "ticket": "8",
              "time_utc": "1800000000", "symbol": "TEST", "volume": "1", "profit": "10", "commission": "-2",
              "swap": "-0.5", "fee": "-0.25", "magic": "0"}]}
    monkeypatch.setattr(bridge, "_new", lambda kind: [source] if kind == "deals" else [])
    monkeypatch.setattr(bridge, "_old", lambda *args: [])
    rows = client.portal.call(bridge.deals)
    assert rows[0]["net"] == 7.25
    assert rows[0]["profit"] == 10 and rows[0]["commission"] == -2 and rows[0]["swap"] == -0.5
    assert rows[0]["fee"] == -0.25
