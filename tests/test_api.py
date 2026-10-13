"""HTTP API: security guard, page token, core endpoints against mocked sources, connectors never leak keys, AI streaming."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import TOKEN, sse_events


def test_api_requires_token_and_local_host(client):
    raw = TestClient(client.app)
    assert raw.get("/api/health", headers={"Host": "127.0.0.1:8765"}).status_code == 401
    assert raw.get("/api/health", headers={"Host": "127.0.0.1:8765", "X-SD-Token": "wrong"}).status_code == 401
    assert raw.get("/", headers={"Host": "evil.example.com"}).status_code == 403
    assert client.get("/api/health").json()["ok"] is True


def test_index_injects_token_and_csp(client):
    r = client.get("/")
    assert TOKEN in r.text and "{{TOKEN}}" not in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]


def test_overview_uses_quotes(client):
    d = client.get("/api/overview").json()
    sp = d["groups"][0]["rows"][0]
    assert sp["symbol"] == "^GSPC" and sp["price"] is not None and sp["change_pct"] > 0 and sp["source"] == "yahoo"
    rates = next(g for g in d["groups"] if g["title"] == "Rates")
    assert "change_bp" in rates["rows"][0]


def test_calendar_endpoint_merges_ff(client):
    d = client.get("/api/calendar?days=3650&back_hours=100000").json()
    titles = [e["title"] for e in d["events"]]
    assert "Core CPI m/m" in titles and d["sources"] == ["ffcal"] or "ffcal" in d["sources"]


def test_flows_endpoint(client):
    d = client.get("/api/flows?days=90").json()
    assert d["events"] and all({"date", "name", "mechanism", "verify"} <= set(e) for e in d["events"])


def test_connector_keys_never_leave_the_server(client):
    r = client.post("/api/connectors/finnhub", json={"enabled": True, "fields": {"api_key": "supersecretkey1234"}}).json()
    assert r["configured"] and r["active"]
    text = client.get("/api/connectors").text + client.get("/api/settings").text
    assert "supersecretkey1234" not in text and "…1234" in text


def test_ai_chat_without_provider_explains_setup(client):
    r = client.post("/api/ai/chat", json={"mode": "ask", "question": "hi", "context": {"page": "x"}})
    ev = sse_events(r.text)
    assert ev[0]["type"] == "error" and "Settings" in ev[0]["error"]


def test_ai_chat_streams_with_a_provider(client, monkeypatch):
    from sessiondesk.ai.providers import AnthropicProvider
    seen = {}

    async def fake_stream(self, system, messages, max_tokens=4000, effort=None):
        seen["system"], seen["messages"] = system, messages
        self.last_usage = {"model": "claude-opus-5-5", "in": 1000, "out": 100}
        for chunk in ("Facts ", "only."):
            yield chunk
    monkeypatch.setattr(AnthropicProvider, "stream", fake_stream)
    client.post("/api/connectors/anthropic", json={"fields": {"api_key": "sk-test"}})
    r = client.post("/api/ai/chat", json={"mode": "ask", "question": "What moved?", "context": {"page": "Markets", "x": 1.234567}})
    ev = sse_events(r.text)
    assert [e["type"] for e in ev] == ["meta", "text", "text", "done"]
    assert "".join(e["text"] for e in ev if e["type"] == "text") == "Facts only."
    assert "ONLY facts" in seen["system"] and "1.2346" in seen["messages"][-1]["content"]
    assert ev[-1]["cost"] > 0
    assert client.get("/api/ai/usage").json()["today"]["calls"] == 1


def test_jobs_lifecycle(client, tmp_path):
    r = client.put("/api/jobs", json={"id": "py", "name": "Python job", "cmd": ["python", "-c", "print('hello from job')"]}).json()
    assert r["ok"]
    jobs = client.get("/api/jobs").json()["jobs"]
    assert jobs[0]["id"] == "py" and jobs[0]["editable"]
    import asyncio
    jm = client.app_state["ctx"].extras["jobs"]
    status = client.portal.call(jm.run, jm.jobs["py"])
    assert status == "ok"
    assert any("hello from job" in ln for ln in client.get("/api/jobs/py/log").json()["lines"])
    assert client.delete("/api/jobs/py").json()["ok"]
    assert asyncio  # keep import used


def test_settings_patch_lists_replace(client):
    client.patch("/api/settings", json={"watchlist": ["AAA", "BBB"], "alerts": {"min_abs_pct": 5}})
    s = client.get("/api/settings").json()["settings"]
    assert s["watchlist"] == ["AAA", "BBB"] and s["alerts"]["min_abs_pct"] == 5 and s["alerts"]["min_abs_z"] == 2.5
