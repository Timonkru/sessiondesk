"""Company structure: index weight estimates, snapshot diffs, change alerts."""
from __future__ import annotations

import asyncio

import pytest

from sessiondesk.features import company


def test_weight_estimates():
    members = ["A", "B", "C"]
    pw = company.weight_estimate("A", members, {}, {"A": 300.0, "B": 100.0, "C": 100.0}, True)
    assert pw["weight"] == pytest.approx(0.6) and pw["coverage"] == 3
    cw = company.weight_estimate("B", members, {"A": 6e12, "B": 2e12, "C": 2e12}, {}, False)
    assert cw["weight"] == pytest.approx(0.2) and cw["coverage"] == 3
    thin = company.weight_estimate("B", members, {"A": 6e12, "B": 2e12}, {}, False)     # 2 of 3 known: no weight
    assert thin["weight"] is None and "too few" in thin["basis"]
    assert company.weight_estimate("C", members, {"A": 1.0}, {}, False)["weight"] is None


def test_diff_and_first_snapshot():
    old = {"board": ["Ann", "Bob"], "officers": ["Cy (CEO)"], "indices": ["S&P 500"]}
    new = {"board": ["Ann", "Dee"], "officers": ["Cy (CEO)"], "indices": ["S&P 500", "Dow 30"]}
    assert company.diff(old, new) == ["board: new Dee", "board: gone Bob", "index membership: new Dow 30"]
    assert company.diff({"board": [], "officers": [], "indices": []}, new) == ["index membership: new Dow 30, S&P 500"]


def test_change_alert_after_second_snapshot(client, monkeypatch):
    ctx = client.app_state["ctx"]
    state = {"board": [{"name": "Ann", "position": "Director"}]}

    async def fake_people(_ctx, sym):
        return {"officers": [{"name": "Cy", "title": "CEO"}], "board": state["board"]}
    monkeypatch.setattr(company, "people", fake_people)
    events = []
    ctx.broker.listen(events.append)
    assert asyncio.run(company.detect_changes(ctx, ["AAPL"])) == []          # first look: baseline only
    state["board"] = [{"name": "Ann", "position": "Director"}, {"name": "Eve", "position": "Director"}]
    alerts = asyncio.run(company.detect_changes(ctx, ["AAPL"]))
    assert alerts and alerts[0]["body"] == "board: new Eve" and alerts[0]["kind"] == "company"
    assert any(e["kind"] == "hub_warning" for e in events)
    assert asyncio.run(company.detect_changes(ctx, ["AAPL"])) == []          # no change, no alert
