"""Jobs schedule/commands/imports, MT5 bridge files, research reader, AI prompt building."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sessiondesk.ai import assist
from sessiondesk.connectors.mt5 import MT5Bridge, read_tsv
from sessiondesk.features import jobs, research


# ------------------------------------------------------------------ jobs
def test_next_run_daily_and_interval():
    now = dt.datetime(2026, 10, 12, 8, 0).timestamp()           # Monday 08:00 local
    due = jobs.next_run({"daily": "08:40", "weekdays": [0, 1, 2, 3, 4]}, now)
    assert dt.datetime.fromtimestamp(due) == dt.datetime(2026, 10, 12, 8, 40)
    after = jobs.next_run({"daily": "08:40", "weekdays": [0, 1, 2, 3, 4]}, now + 3600, last=due)
    assert dt.datetime.fromtimestamp(after) == dt.datetime(2026, 10, 13, 8, 40)
    sat = dt.datetime(2026, 10, 17, 9, 0).timestamp()
    assert dt.datetime.fromtimestamp(jobs.next_run({"daily": "08:40", "weekdays": [0, 1, 2, 3, 4]}, sat)).weekday() == 0
    assert jobs.next_run({"every_minutes": 30}, now, last=now - 600) == pytest.approx(now + 1200)


def _job(cmd, python=None):
    return jobs.Job(id="x", name="x", group="", cwd=Path("."), cmd=cmd, source="t", editable=True, python=python)


def test_build_command_wraps_script_types():
    assert jobs.build_command(_job("echo hi")) == ("echo hi", True)
    assert jobs.build_command(_job(["python", "a.py"], python="C:/venv/python.exe"))[0][:2] == ["C:/venv/python.exe", "-u"]
    assert jobs.build_command(_job(["run.ps1"]))[0][0] == "powershell"
    if sys.platform.startswith("win"):
        assert jobs.build_command(_job(["routine.bat", "--eu"]))[0][:3] == ["cmd", "/c", "routine.bat"]


def test_imported_job_file_is_read_only_and_resolves_workspace(tmp_path):
    ext = tmp_path / "other" / "jobs.json"
    ext.parent.mkdir()
    (tmp_path / "proj").mkdir()
    ext.write_text(json.dumps({"workspace": "..", "python": "py.exe",
                               "jobs": [{"id": "lvl", "name": "Levels", "cwd": "proj", "cmd": ["python", "b.py"], "clipboard": "out.txt"}],
                               "workflows": [{"name": "Morning", "steps": ["lvl"]}],
                               "artifacts": [{"group": "Pine", "label": "Gamma", "path": "proj/g.pine"}]}), encoding="utf-8")
    (tmp_path / "proj" / "g.pine").write_text("//@version=6", encoding="utf-8")
    settings = SimpleNamespace(get=lambda key, default=None: [str(ext)] if key == "jobs_files" else default)
    ctx = SimpleNamespace(settings=settings, data_dir=tmp_path, broker=SimpleNamespace(publish=lambda *a, **k: None))
    jm = jobs.JobManager(ctx)
    job = jm.jobs["lvl"]
    assert not job.editable and job.cwd == (tmp_path / "proj").resolve() and job.python == "py.exe"
    assert jm.workflows[0]["name"] == "Morning"
    arts = jm.list_artifacts()
    assert any(a["label"] == "Gamma" and a["exists"] for a in arts)
    assert jm.artifact_allowed(str(tmp_path / "proj" / "g.pine"))
    assert not jm.artifact_allowed(str(tmp_path / "secret.txt"))
    assert "read-only" in jm.upsert({"id": "lvl", "cmd": "echo"})["error"]


# ------------------------------------------------------------------ MT5 bridge
def _write(folder: Path, name: str, kind: str, cols: list[str], rows: list[list[str]], age: float = 0):
    head = f"#sessiondesk\t1.00\t{kind}\t{int(time.time() - age)}\t10800\t52000123\n"
    folder.joinpath(name).write_text(head + "\t".join(cols) + "\n" + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")


def test_bridge_files_are_read_and_masked(tmp_path):
    _write(tmp_path, "account_52000123.tsv", "account",
           ["login", "server", "company", "currency", "balance", "equity", "margin", "free_margin", "profit", "leverage", "trade_allowed", "connected"],
           [["52000123", "Demo-Server", "Broker", "EUR", "10000", "9900", "100", "9800", "-100", "100", "1", "1"]])
    _write(tmp_path, "positions_52000123.tsv", "positions",
           ["ticket", "symbol", "side", "volume", "open_price", "open_time_utc", "sl", "tp", "price", "profit", "swap", "magic", "comment", "risk_to_stop", "digits"],
           [["1", "GER40", "LONG", "1.00", "24000", "1", "23950", "0", "23990", "-10", "0", "202507", "", "50", "1"]])
    settings = SimpleNamespace(get=lambda key, default=None: {"connectors.mt5.folder": str(tmp_path), "privacy.mask_accounts": True}.get(key, default))
    conn = MT5Bridge(SimpleNamespace(settings=settings, secrets=None))
    import asyncio
    acc = asyncio.run(conn.account())[0]
    pos = asyncio.run(conn.positions())[0]
    assert acc["login"] == "…123" and acc["equity"] == 9900 and acc["trade_allowed"] and acc["fresh"]
    assert pos["risk_to_stop"] == 50 and not pos["manual"] and pos["account"] == "…123"
    assert read_tsv(tmp_path / "missing.tsv") is None


def test_stale_bridge_file_is_flagged(tmp_path):
    _write(tmp_path, "account_1.tsv", "account", ["login", "equity"], [["1", "5"]], age=600)
    settings = SimpleNamespace(get=lambda key, default=None: {"connectors.mt5.folder": str(tmp_path)}.get(key, default))
    import asyncio
    acc = asyncio.run(MT5Bridge(SimpleNamespace(settings=settings, secrets=None)).account())[0]
    assert acc["fresh"] is False


# ------------------------------------------------------------------ research reader
def test_reader_extracts_text_and_drops_scripts():
    html = """<html><head><title>T</title><meta property="og:title" content="Real title"><script>evil()</script></head>
    <body><nav>menu</nav><article><h2>Section</h2><p>First paragraph with enough words to count as real text here.</p>
    <script>alert(1)</script><ul><li>point one</li></ul><blockquote>quoted</blockquote></article><footer>f</footer></body></html>"""
    a = research.extract(html, "https://example.com/x")
    texts = [b["text"] for b in a["blocks"]]
    assert a["title"] == "Real title" and "Section" in texts and "point one" in texts
    assert not any("alert" in t or "evil" in t or "menu" in t for t in texts)
    assert a["teaser_only"]


@pytest.mark.parametrize("url,ok", [("https://example.com/a", True), ("http://127.0.0.1:8765/api", False),
                                    ("http://localhost/x", False), ("http://192.168.1.10/", False), ("file:///etc/passwd", False)])
def test_reader_blocks_local_addresses(url, ok):
    assert research.safe_url(url) is ok


# ------------------------------------------------------------------ AI prompt
def test_ai_context_is_compacted_and_capped():
    ctx = {"page": "X", "rows": [{"v": 1.23456789, "none": None, "spark": [1, 2, 3]} for _ in range(100)]}
    text = assist.context_json(ctx)
    assert "1.2346" in text and "spark" not in text and "none" not in text
    assert len(assist.context_json({"big": "x" * 100_000}, max_chars=1000)) < 1100


def test_system_prompt_carries_the_rules():
    p = assist.system_prompt("explain", "German")
    assert "ONLY facts" in p and "German" in p and "no price targets" in p
    support = assist.system_prompt("support", "English", [{"id": "yahoo", "name": "Yahoo", "tier": "free", "active": True}])
    assert "DOCUMENTATION" in support and "yahoo" in support


# ------------------------------------------------------------------ earlier export format + Telegram
def test_legacy_export_files_are_understood(tmp_path):
    now = int(time.time())
    (tmp_path / "status_777000111.tsv").write_text(
        f"#updated\t{now}\t777000111\nbalance\t10000\nequity\t10050.5\ncurrency\tEUR\nconnected\t1\nalgo_terminal\t1\n"
        "algo_account\t1\nrisk_multiplier\t0.5\nchart\tGER40\tPERIOD_M15\tSomeEA\n", encoding="utf-8")
    (tmp_path / "pos_777000111.tsv").write_text(
        f"#updated\t{now}\t777000111\t10050.5\tEUR\tbridge-v2\nGER40\tLONG\t1.0000\t24000.0\t23950.0\t50.00\t50.00\t202510\t9\t2.4\t9\t{now - 600}\n",
        encoding="utf-8")
    (tmp_path / "deals_777000111.tsv").write_text(
        f"#updated\t{now}\t777000111\t10000\t10050.5\tEUR\n{now - 900}\t9\tGER40\t202510\tBUY\t0\t1.00\t0.00\t-2.00\n"
        f"{now - 300}\t9\tGER40\t202510\tSELL\t1\t1.00\t40.00\t-2.00\n", encoding="utf-8")
    (tmp_path / "calendar.tsv").write_text(f"#updated\t{now}\n{now + 3600}\tUSD\t3\tCore CPI m/m\t\t0.2\t0.3\t%\t0\n", encoding="utf-8")
    settings = SimpleNamespace(get=lambda key, default=None: {"connectors.mt5.folder": f"{tmp_path};{tmp_path / 'missing'}",
                                                              "privacy.mask_accounts": False}.get(key, default))
    conn = MT5Bridge(SimpleNamespace(settings=settings, secrets=None))
    import asyncio
    acc = asyncio.run(conn.account())[0]
    assert acc["equity"] == 10050.5 and acc["trade_allowed"] and acc["extra"]["risk_multiplier"] == "0.5" and acc["fresh"]
    pos = asyncio.run(conn.positions())[0]
    assert pos["magic"] == "202510" and pos["risk_to_stop"] == 50 and pos["sl"] == 23950
    eas = asyncio.run(conn.eas())
    assert eas[0]["expert"] == "SomeEA" and eas[0]["timeframe"] == "M15"
    from sessiondesk.features.broker import ea_performance
    perf = ea_performance(asyncio.run(conn.deals()), time.time() - 86400, {"202510": "Breakout"})
    assert perf[0]["label"] == "Breakout" and perf[0]["trades"] == 1 and perf[0]["net"] == pytest.approx(36.0)
    cal = asyncio.run(conn.calendar())
    assert cal[0]["title"] == "Core CPI m/m" and cal[0]["impact"] == "high" and cal[0]["forecast"] == "0.2%"


def test_telegram_preview_parser():
    from sessiondesk.features.feeds import parse_telegram
    page = ('<div class="tgme_widget_message_wrap"><div data-post="chan/101"></div>'
            '<div class="tgme_widget_message_text js-message_text">US CPI MoM Actual 0.4% (Forecast 0.2%) $MACRO</div>'
            '<time datetime="2026-10-14T12:30:01+00:00"></time></div>'
            '<div class="tgme_widget_message_wrap"><div data-post="chan/102"></div>'
            '<div class="tgme_widget_message_text">FED&#39;S WALLER: CUTS STILL APPROPRIATE (@Chan)</div>'
            '<time datetime="2026-10-14T12:31:00+00:00"></time></div>')
    items = parse_telegram(page, "Chan", "chan")
    assert [i["title"] for i in items] == ["FED'S WALLER: CUTS STILL APPROPRIATE", "US CPI MoM Actual 0.4% (Forecast 0.2%)"]
    assert items[0]["url"] == "https://t.me/chan/102" and items[1]["published"] < items[0]["published"]


def test_research_recommendations_say_why():
    from sessiondesk.features import news
    now = 1_790_000_000.0
    items = [{"title": "What the ECB's next step means for European equities", "published": now - 3600, "symbols": []},
             {"title": "Nvidia's data center margins under the microscope", "published": now - 7200, "symbols": ["NVDA"]},
             {"title": "A history of the yen carry trade", "published": now - 86400, "symbols": []},
             {"title": "ECB minutes, old news", "published": now - 30 * 86400, "symbols": []}]
    held = news.held_map([{"symbol": "GER40.cash"}])
    rec = research.recommend(items, held, {"NVDA"}, ["Why the yen matters again"], now)
    why = {r["title"][:12]: r["why"] for r in rec}
    assert why["What the ECB"] == ["touches your open DAX"]
    assert why["Nvidia's dat"] == ["names NVDA (watchlist)"]
    assert why["A history of"] == ["topic you saved before: japan"]
    assert "ECB minutes," not in why                                   # older than 14 days
    assert rec[0]["title"].startswith("What the ECB")                 # positions weigh most


def test_bridge_120_cash_bookings(tmp_path):
    cols = ["ticket", "time_utc", "symbol", "type", "entry", "volume", "price", "profit", "commission", "swap", "magic", "position_id",
            "comment", "fee"]
    _write(tmp_path, "deals_52000123.tsv", "deals", cols, [
        ["11", "100", "GER40", "BUY", "0", "1.00", "24000", "0", "-2", "0", "0", "11", "", "-0.5"],
        ["12", "200", "GER40", "SELL", "1", "1.00", "24050", "50", "-2", "0", "0", "11", "", "0"],
        ["13", "210", "", "TAX", "0", "0", "0", "-11.86", "0", "0", "0", "0", "Tax", "0"],
        ["14", "300", "", "BALANCE", "0", "0", "0", "1000", "0", "0", "0", "0", "Deposit", "0"]])
    _write(tmp_path, "deals_52000999.tsv", "deals", cols[:-1], [["21", "100", "US30", "BUY", "0", "1", "1", "0", "0", "0", "0", "21", ""]])
    settings = SimpleNamespace(get=lambda key, default=None: {"connectors.mt5.folder": str(tmp_path), "privacy.mask_accounts": False}.get(key, default))
    conn = MT5Bridge(SimpleNamespace(settings=settings, secrets=None))
    import asyncio
    deals = asyncio.run(conn.deals())
    assert {d["type"] for d in deals} == {"BUY", "SELL"} and next(d for d in deals if d["ticket"] == "11")["net"] == -2.5   # fee counted
    book = asyncio.run(conn.cash())
    assert book["covered"] == ["52000123"]                       # the older export (no fee column) carries no bookings
    assert [(c["type"], c["amount"]) for c in book["rows"]] == [("TAX", -11.86), ("BALANCE", 1000.0)]
