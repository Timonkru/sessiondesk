"""My desk: default layout, saving with validation."""
from __future__ import annotations


def test_desk_default_and_save(client):
    d = client.get("/api/desk").json()
    assert d["layouts"][0]["tiles"] and d["active"] == 0
    assert "error" in client.put("/api/desk", json={"layouts": []}).json()
    body = {"active": 5, "layouts": [{"name": "Trading", "tiles": [{"type": "quotes", "w": 99, "params": {"symbols": "AAPL"}}, {"no": "type"}]}]}
    saved = client.put("/api/desk", json=body).json()
    assert saved["active"] == 0 and saved["layouts"][0]["tiles"] == [{"type": "quotes", "w": 24, "params": {"symbols": "AAPL"}}]
    assert client.get("/api/desk").json() == saved


def test_desk_keeps_grid_positions(client):
    body = {"layouts": [{"name": "Free", "tiles": [{"type": "chart", "x": 30, "y": 4.0, "w": 10, "h": 0, "params": {}},
                                                   {"type": "news", "x": "1", "y": True, "w": 6, "h": 12, "params": {}}]}]}
    tiles = client.put("/api/desk", json=body).json()["layouts"][0]["tiles"]
    assert tiles[0] == {"type": "chart", "x": 23, "y": 4, "w": 10, "h": 1, "params": {}}
    assert tiles[1] == {"type": "news", "w": 6, "h": 12, "params": {}}          # junk x/y dropped, the free grid re-places it
