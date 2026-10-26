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
