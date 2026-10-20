"""My desk: default layout, saving with validation."""
from __future__ import annotations


def test_desk_default_and_save(client):
    d = client.get("/api/desk").json()
    assert d["layouts"][0]["tiles"] and d["active"] == 0
    assert "error" in client.put("/api/desk", json={"layouts": []}).json()
    body = {"active": 5, "layouts": [{"name": "Trading", "tiles": [{"type": "quotes", "w": 99, "params": {"symbols": "AAPL"}}, {"no": "type"}]}]}
    saved = client.put("/api/desk", json=body).json()
    assert saved["active"] == 0 and saved["layouts"][0]["tiles"] == [{"type": "quotes", "w": 12, "params": {"symbols": "AAPL"}}]
    assert client.get("/api/desk").json() == saved
