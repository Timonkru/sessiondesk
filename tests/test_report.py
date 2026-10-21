"""Performance report: figures from deals, fingerprint, CSV check (tampering shows), locked PDF, periods."""
from __future__ import annotations

import datetime as dt
import io

import pypdf

from sessiondesk.features import report

T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400


def _deals():
    d = lambda t, pid, typ, entry, vol, net, sym="DE40": {"time": T0 + t, "position_id": pid, "symbol": sym, "type": typ,  # noqa: E731
                                                       "entry": entry, "volume": vol, "net": net}
    return [
        d(-DAY, "1", "BUY", "0", 1.0, -2.0), d(-DAY + 600, "1", "SELL", "1", 1.0, 50.0),           # before the period
        d(3600, "2", "BUY", "0", 2.0, -4.0), d(7200, "2", "SELL", "1", 2.0, 300.0),               # +296 on day 1
        d(DAY + 3600, "3", "SELL", "0", 1.0, -2.0, "US500"), d(DAY + 4000, "3", "BUY", "1", 1.0, -500.0, "US500"),   # -502 day 2
        d(2 * DAY + 100, "4", "BUY", "0", 1.0, -2.0),                                              # still open: its cost counts
    ]


def _report():
    return report.build(_deals(), {"label": "123456", "currency": "EUR", "balance": 10_000.0, "server": "Demo-Server"},
                        T0, T0 + 3 * DAY, now=T0 + 3 * DAY)


def test_report_figures():
    r = _report()
    assert r["start_balance"] == 10_000 - (-4 + 300 - 2 - 500 - 2) and r["end_balance"] == 10_000
    assert r["net"] == -208 and r["trades"] == 2 and r["win_rate"] == 50
    assert [p["position_id"] for p in r["positions"]] == ["2", "3"] and r["positions"][0]["side"] == "long"
    assert r["other"] == -2                                     # entry cost of the position still open
    assert round(r["profit_factor"], 3) == round(296 / 502, 3)
    assert r["max_dd"] == 504                                  # peak 10,504 after the win, trough 10,000
    assert [d["day"] for d in r["days"]] == ["2026-10-01", "2026-10-02", "2026-10-03"] and r["worst_day"]["day"] == "2026-10-02"
    assert report.max_drawdown([100, 120, 90, 130, 100]) == (30, 25.0)


def test_report_csv_roundtrip_and_tampering():
    r = _report()
    fp = report.fingerprint(report.data_block(r))
    rid = report.report_id(r, fp)
    text = report.to_csv(r, rid, fp)
    ok = report.verify_csv(text)
    assert ok["ok"] and ok["recomputed"] == fp and ok["report_id"] == rid
    forged = text.replace(",-502.0", ",502.0")
    assert forged != text and not report.verify_csv(forged)["ok"]
    assert not report.verify_csv("a,b\n1,2\n")["ok"]


def test_report_pdf_is_locked_and_readable():
    r = _report()
    fp = report.fingerprint(report.data_block(r))
    rid = report.report_id(r, fp)
    raw = report.to_pdf(r, rid, fp)
    text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    assert rid in text and fp in text and "123456" in text
    locked = pypdf.PdfReader(io.BytesIO(report.lock(raw)))
    assert locked.is_encrypted and locked.decrypt("") and len(locked.pages) >= 3


def test_report_periods():
    today = dt.date(2026, 10, 21)
    a, b = report.period_bounds("last_month", today)
    assert report._day(a) == "2026-09-01" and report._day(b - 1) == "2026-09-30"
    a, b = report.period_bounds("custom", today, "2026-10-05", "2026-10-01")
    assert report._day(a) == "2026-10-01" and report._day(b - 1) == "2026-10-05"
    a, b = report.period_bounds("this_month", today)
    assert report._day(a) == "2026-10-01" and report._day(b - 1) == "2026-10-21"


def test_balance_check_spots_cash_moves():
    deals = _deals()
    day = "2026-10-02"
    t = dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc).timestamp()
    true_start = 10_000.0 - sum(d["net"] for d in deals if d["time"] >= t)
    ok = report.balance_check(deals, 10_000.0, {day: true_start})
    assert ok["matched"] == 1 and ok["worst"] is None
    bad = report.balance_check(deals, 10_000.0, {day: true_start + 250})          # a fee or payout the export does not show
    assert bad["matched"] == 0 and round(bad["worst"]["diff"]) == -250


def test_report_percent_only_has_no_amounts():
    r = {**_report(), "units": "percent"}
    fp = report.fingerprint(report.data_block(r))
    rid = report.report_id(r, fp)
    text = report.to_csv(r, rid, fp)
    assert report.verify_csv(text)["ok"] and "10208" not in text and "-502" not in text     # no balance, no money result
    assert "units,percent" in text and "-4.9177" in text                                      # -502 of 10,208
    pdf = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(report.to_pdf(r, rid, fp))).pages)
    assert "10,208" not in pdf and "-502" not in pdf and "% of the start balance" in pdf


def test_same_second_deals_are_one_step():
    deals = [{"time": T0 + 60, "position_id": "a", "symbol": "X", "type": "BUY", "entry": "0", "volume": 1, "net": 0.0},
             {"time": T0 + 60, "position_id": "b", "symbol": "X", "type": "BUY", "entry": "0", "volume": 1, "net": 0.0},
             {"time": T0 + 120, "position_id": "a", "symbol": "X", "type": "SELL", "entry": "1", "volume": 1, "net": -300.0},
             {"time": T0 + 120, "position_id": "b", "symbol": "X", "type": "SELL", "entry": "1", "volume": 1, "net": 300.0}]
    r = report.build(deals, {"label": "1", "currency": "USD", "balance": 1000.0}, T0, T0 + DAY, now=T0 + DAY)
    assert r["max_dd"] == 0 and r["net"] == 0                 # a hedge closed in one second is no drawdown
