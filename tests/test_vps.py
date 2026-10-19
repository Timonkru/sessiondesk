"""MQL5 VPS status from synced hosting journals (UTF-16, one file per day)."""
from __future__ import annotations

import os
import time

from sessiondesk.features import vps

TERM = "\n".join([
    "GK\t0\t11:27:35.422\tTerminal\tMetaTrader 5 x64 build 6244 started for MetaQuotes Ltd.",
    "FN\t0\t11:27:35.422\tTerminal\tWindows Server 2022 build 20348 on Xen, admin, GMT+1",
    "AA\t0\t11:27:40.000\tExperts\texpert DemoEA (EURUSD,M5) loaded successfully",
    "AB\t0\t11:27:40.100\tExperts\texpert OtherEA (UK100,M1) loaded successfully",
    "AC\t0\t11:30:00.000\tExperts\texpert OtherEA (UK100,M1) removed",
    "AD\t1\t12:00:00.000\tNetwork\t'123456': connection to Broker-Live lost",
    "AE\t0\t12:38:36.018\tTerminal\t'123456': 1 charts, 1 EAs, 0 custom indicators, signal disabled",
    "AF\t0\t13:36:04.038\tTrades\t'123456': deal #4883 buy 0.5 EURUSD at 1.1213 done (based on order #5423)",
    "AG\t2\t13:40:00.000\tTerminal\tsomething went badly",
])
EXP = "\n".join([
    "XA\t0\t11:27:41.000\tDemoEA (EURUSD,M5)\tDemoEA 1.0 init | LIVE",
    "XB\t0\t13:00:00.000\tDemoEA (EURUSD,M5)\tSYMBOL DATA MISSING - retry",
])


def _logs(tmp_path):
    root = tmp_path / "Terminal" / "ABC"
    t = root / "Logs" / "hosting.777.terminal"
    e = root / "Logs" / "hosting.777.experts"
    t.mkdir(parents=True)
    e.mkdir(parents=True)
    (t / "20261019.log").write_bytes(("﻿" + TERM).encode("utf-16-le"))
    (e / "20261019.log").write_bytes(("﻿" + EXP).encode("utf-16-le"))
    (root / "MQL5" / "Files").mkdir(parents=True)
    return root


def test_vps_status_from_journals(tmp_path, monkeypatch):
    root = _logs(tmp_path)
    monkeypatch.delenv("APPDATA", raising=False)
    settings = {"connectors.mt5.folder": str(root / "MQL5" / "Files")}
    st = vps.status(type("S", (), {"get": staticmethod(lambda k, d=None: settings.get(k, d))}))
    assert len(st["hostings"]) == 1
    x = st["hostings"][0]
    assert x["id"] == "777" and x["timezone"] == "GMT+1"
    assert x["heartbeat"] == {"time": "2026-10-19 12:38:36", "account": "123456", "charts": 1, "eas": 1}
    assert [e["ea"] for e in x["eas"]] == ["DemoEA"] and x["eas"][0]["last_message"].startswith("SYMBOL DATA MISSING")
    assert x["deals"][0]["symbol"] == "EURUSD" and x["deals"][0]["volume"] == 0.5
    assert x["drops"] == 1 and x["restarts"] == 1
    texts = [w["text"] for w in x["warnings"]]
    assert any("MISSING" in t for t in texts) and any("badly" in t for t in texts)


def test_old_hostings_are_ignored_and_tail_reads_big_files(tmp_path, monkeypatch):
    root = _logs(tmp_path)
    log = root / "Logs" / "hosting.777.terminal" / "20261019.log"
    old = time.time() - 30 * 86400
    os.utime(log, (old, old))
    monkeypatch.delenv("APPDATA", raising=False)
    settings = {"connectors.mt5.folder": str(root / "MQL5" / "Files")}
    assert vps.status(type("S", (), {"get": staticmethod(lambda k, d=None: settings.get(k, d))}))["hostings"] == []
    big = tmp_path / "big.log"
    big.write_bytes(("x" * 1000 + "\n" + TERM).encode("utf-16-le"))
    assert vps.read_tail(big, max_bytes=2000)[-1].endswith("something went badly")
