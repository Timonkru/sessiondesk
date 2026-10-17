"""Price alerts: one-shot crossing check, persistence, API round trip with the mocked quote feed, push text."""
from __future__ import annotations

import asyncio

from sessiondesk import push
from sessiondesk.features import pricealerts


def test_check_is_one_shot():
    alerts = [{"id": "a", "symbol": "AAPL", "op": "above", "level": 350, "active": True},
              {"id": "b", "symbol": "AAPL", "op": "below", "level": 300, "active": True},
              {"id": "c", "symbol": "SAP.DE", "op": "below", "level": 200, "active": True}]
    fired = pricealerts.check(alerts, {"AAPL": {"price": 351.2}}, 1000.0)
    assert [a["id"] for a in fired] == ["a"]
    assert alerts[0]["active"] is False and alerts[0]["price_at_trigger"] == 351.2 and alerts[0]["triggered"] == 1000.0
    assert pricealerts.check(alerts, {"AAPL": {"price": 360}}, 1001.0) == []      # fired once only
    assert alerts[2]["active"] is True                                              # no quote: untouched


def test_api_create_check_rearm_delete(client):
    assert "error" in client.post("/api/price_alerts", json={"symbol": "AAPL", "op": "sideways", "level": 1}).json()
    assert "error" in client.post("/api/price_alerts", json={"symbol": "AAPL", "op": "above", "level": "abc"}).json()
    a = client.post("/api/price_alerts", json={"symbol": "aapl", "op": "above", "level": 50, "note": "test"}).json()["alert"]
    assert a["symbol"] == "AAPL" and a["active"]
    rows = client.get("/api/price_alerts").json()["alerts"]
    assert rows[0]["price"] is not None                                            # mocked quote feed answered

    ctx = client.app_state["ctx"]
    events = []
    ctx.broker.listen(events.append)
    fired = asyncio.run(pricealerts.run_check(ctx))                                # mocked AAPL > 100 > 50
    assert [f["id"] for f in fired] == [a["id"]]
    ev = next(e for e in events if e["kind"] == "price_alert")
    assert ev["alert"]["title"] == "AAPL above 50" and "test" in ev["alert"]["body"]
    assert client.get("/api/price_alerts").json()["alerts"][0]["active"] is False

    client.post(f"/api/price_alerts/{a['id']}", json={"rearm": True})
    assert client.get("/api/price_alerts").json()["alerts"][0]["active"] is True
    client.post(f"/api/price_alerts/{a['id']}", json={"delete": True})
    assert client.get("/api/price_alerts").json()["alerts"] == []


def test_price_alert_push_text():
    cfg = push.config(type("S", (), {"get": staticmethod(lambda k, d=None: None)}))
    msg = push.format_event({"kind": "price_alert", "alert": {"id": "x", "title": "AAPL above 350", "body": "traded at 351", "data": {"triggered": 5}}}, cfg)
    assert msg["title"] == "Price alert: AAPL above 350" and msg["priority"] == 4
