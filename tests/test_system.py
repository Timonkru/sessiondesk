"""System page: loop states, connector health bookkeeping, the /api/system snapshot."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sessiondesk.connectors.base import Hub
from sessiondesk.features import system


def test_loop_states():
    now = 10_000.0
    assert system.loop_state({"registered": now - 10, "first_delay": 60}, now) == "waiting"
    assert system.loop_state({"registered": now - 4000, "first_delay": 60}, now) == "stuck"
    ok = {"last_end": now - 30, "last_ok": now - 30, "interval": 60}
    assert system.loop_state(ok, now) == "ok"
    assert system.loop_state({**ok, "last_end": now - 400, "last_ok": now - 400}, now) == "late"
    assert system.loop_state({**ok, "last_error_ts": now - 30, "last_ok": now - 90}, now) == "error"
    assert system.loop_state({**ok, "last_error_ts": now - 900}, now) == "ok"     # recovered since


class _Conn:
    tier, capabilities = "free", ("quotes",)

    def __init__(self, cid, fail):
        self.id, self.fail = cid, fail

    def active(self):
        return True

    async def quotes(self):
        if self.fail:
            raise RuntimeError("HTTP 503")
        return {"X": 1}


def test_hub_records_failures_and_successes():
    hub = Hub(SimpleNamespace(settings=SimpleNamespace(get=lambda k: None)), [_Conn("bad", True), _Conn("good", False)])
    res = asyncio.run(hub.first("quotes", "quotes"))
    assert res["source"] == "good"
    assert hub.health["bad"]["errors"] == 1 and "503" in hub.health["bad"]["last_error"]
    assert hub.health["good"]["ok"] == 1 and "last_error" not in hub.health["good"]
    asyncio.run(hub.gather("quotes", "quotes"))
    assert hub.health["bad"]["errors"] == 2 and hub.health["good"]["ok"] == 2


def test_system_endpoint(client, tmp_path):
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "broken.py").write_text("raise ValueError('nope')\n", encoding="utf-8")
    client.post("/api/extensions/reload")
    d = client.get("/api/system").json()
    assert d["app"]["version"] and d["app"]["news_archive"] == 0
    assert any(i["area"] == "extension" and "nope" in i["text"] for i in d["issues"])
    assert d["counts"]["error"] >= 1
    assert {"loops", "connectors", "exporters", "jobs", "level_files"} <= set(d)


def test_shutdown_needs_the_launcher(client):
    assert "error" in client.post("/api/shutdown").json()
    fake = SimpleNamespace(should_exit=False)
    client.app.state.server = fake
    assert client.post("/api/shutdown").json() == {"ok": True} and fake.should_exit is True


def test_stop_without_server_cleans_run_file(tmp_path):
    from sessiondesk.__main__ import stop_running, write_run_file
    assert "does not seem to run" in stop_running(tmp_path)
    path = write_run_file(tmp_path, 1, "127.0.0.1", "tok")           # port 1: nothing listens there
    assert path.exists()
    assert "No answer" in stop_running(tmp_path) and not path.exists()
