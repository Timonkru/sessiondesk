"""Process hygiene: jobs start without console windows, dead autostart services come back, a SessionDesk that lost
its port to a newer start ends itself."""
from __future__ import annotations

import subprocess
import sys

from sessiondesk import app as app_mod
from sessiondesk.features import jobs


def test_jobs_start_without_a_console_window():
    flags = jobs.spawn_flags()
    if sys.platform.startswith("win"):
        assert flags & subprocess.CREATE_NO_WINDOW and flags & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert flags == 0


def test_service_restart_backs_off():
    assert [jobs.restart_delay(n) for n in range(7)] == [30, 60, 120, 300, 600, 600, 600]


def test_superseded_only_by_a_newer_instance_on_the_same_port():
    assert app_mod.superseded({"pid": 2, "port": 8765}, pid=1, port=8765)
    assert not app_mod.superseded({"pid": 1, "port": 8765}, pid=1, port=8765)     # that is me
    assert not app_mod.superseded({"pid": 2, "port": 8777}, pid=1, port=8765)     # another port, same data dir
    assert not app_mod.superseded(None, pid=1, port=8765)


def test_autostart_service_with_saved_failed_status_starts_once(tmp_path):
    import asyncio
    import json
    import time
    from types import SimpleNamespace
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": [{"id": "svc", "name": "Service", "cmd": ["python", "x.py"],
                                                               "service": True, "autostart": True}]}), encoding="utf-8")
    # 26.10.2026: the saved status of the last session was "failed" - autostart and the restart rule both fired
    (tmp_path / "jobs_state.json").write_text(json.dumps({"svc": {"status": "failed", "last_end": time.time() - 3600}}), encoding="utf-8")
    ctx = SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: d), data_dir=tmp_path,
                          broker=SimpleNamespace(publish=lambda *a, **k: None))
    jm = jobs.JobManager(ctx)
    started = []

    async def fake_run(job):
        started.append(job.id)
        await asyncio.sleep(0.05)
        return job.status
    jm.run = fake_run

    async def go():
        task = asyncio.ensure_future(jm.scheduler())
        await asyncio.sleep(0.2)
        task.cancel()
    asyncio.run(go())
    assert started == ["svc"]
    assert jm.start("svc") == {"error": "already running"}       # a second start before run() gets the loop
