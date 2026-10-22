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
    assert "start_balance" not in text and "end_balance" not in text and "return_pct,-2.0376" in text   # -208 of 10,208
    pdf = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(report.to_pdf(r, rid, fp))).pages)
    assert "10,208" not in pdf and "-502" not in pdf and "% of the start balance" in pdf
    # no bare number that could be read as money: every decimal figure carries a % (the profit factor is labelled as such)
    import re
    bare = [m for m in re.findall(r"[+-]?\d[\d,]*\.\d\d(?!\d)(?!\s*%)", pdf.replace(fp, "")) if m not in ("0.59",)]
    assert not bare, bare


def test_same_second_deals_are_one_step():
    deals = [{"time": T0 + 60, "position_id": "a", "symbol": "X", "type": "BUY", "entry": "0", "volume": 1, "net": 0.0},
             {"time": T0 + 60, "position_id": "b", "symbol": "X", "type": "BUY", "entry": "0", "volume": 1, "net": 0.0},
             {"time": T0 + 120, "position_id": "a", "symbol": "X", "type": "SELL", "entry": "1", "volume": 1, "net": -300.0},
             {"time": T0 + 120, "position_id": "b", "symbol": "X", "type": "SELL", "entry": "1", "volume": 1, "net": 300.0}]
    r = report.build(deals, {"label": "1", "currency": "USD", "balance": 1000.0}, T0, T0 + DAY, now=T0 + DAY)
    assert r["max_dd"] == 0 and r["net"] == 0                 # a hedge closed in one second is no drawdown


def _cash():
    return [{"ticket": "900", "time": T0 + 7300, "type": "TAX", "amount": -78.07, "comment": "tax"},          # 26.375 % of 296
            {"ticket": "901", "time": T0 + DAY + 5000, "type": "TAX", "amount": 132.40, "comment": "tax refund"},
            {"ticket": "902", "time": T0 + 1.5 * DAY, "type": "BALANCE", "amount": 5000.0, "comment": "deposit"},
            {"ticket": "903", "time": T0 + 2 * DAY, "type": "CHARGE", "amount": -3.0, "comment": "data fee"}]


def test_report_with_tax_and_deposit():
    r = report.build(_deals(), {"label": "123456", "currency": "EUR", "balance": 15_000.0}, T0, T0 + 3 * DAY, now=T0 + 3 * DAY, cash=_cash())
    trades_since = -4 + 300 - 2 - 500 - 2
    assert r["start_balance"] == 15_000 - trades_since - (-78.07 + 132.40 + 5000 - 3)          # exact, bookings included
    assert r["net"] == trades_since - 3                                                         # result before tax: trades + fee
    assert round(r["taxes"], 2) == 54.33 and r["deposits"] == 5000 and r["dietz"]
    denom = r["start_balance"] + 5000 * 1.5 / 3                                                 # deposit there for half the period
    assert abs(r["net_pct"] - r["net"] / denom * 100) < 1e-9
    assert abs(r["after_tax_pct"] - (r["net"] + r["taxes"]) / denom * 100) < 1e-9
    assert r["curve"][-1][1] == r["start_balance"] + r["net"]                                   # no tax, no deposit in the path
    assert sum(d["tax"] for d in r["days"]) == r["taxes"]
    fp = report.fingerprint(report.data_block(r))
    text = report.to_csv(r, report.report_id(r, fp), fp)
    assert "booking_id,time_utc,type,amount" in text and report.verify_csv(text)["ok"]
    assert not report.verify_csv(text.replace(",TAX,-78.07", ",TAX,-7.81"))["ok"]              # a changed tax shows
    raw = report.to_pdf(r, "SD-X", fp)
    pdf = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    assert "Taxes and other balance bookings" in pdf and "Return after tax" in pdf and "Modified Dietz" in pdf


def test_balance_check_counts_bookings_and_compare():
    deals, cash = _deals(), _cash()
    t = dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc).timestamp()
    true = 15_000.0 - sum(d["net"] for d in deals if d["time"] >= t) - sum(c["amount"] for c in cash if c["time"] >= t)
    assert report.balance_check(deals, 15_000.0, {"2026-10-02": true}, cash=cash)["worst"] is None
    assert report.balance_check(deals, 15_000.0, {"2026-10-02": true})["worst"] is not None      # without the bookings it misses
    old = {"account": "1", "positions": [["2", "a", "b", "X", "long", 1.0, 296.0]], "cash": []}
    assert report.compare_blocks(old, old) == []
    new = {**old, "positions": [["2", "a", "b", "X", "long", 1.0, 290.0]]}
    assert report.compare_blocks(old, new) == ["1 position(s) with other values: 2"]


def test_tax_months_and_estimate():
    from sessiondesk.features import taxes
    deals = [{"time": T0 + 3600, "net": 400.0}, {"time": T0 + 40 * DAY, "net": -100.0}]
    cash = [{"time": T0 + 4000, "type": "TAX", "amount": -105.5}, {"time": T0 + 40 * DAY + 10, "type": "TAX", "amount": 26.38},
            {"time": T0 + 5000, "type": "BALANCE", "amount": 2000.0}, {"time": T0 + 6000, "type": "CHARGE", "amount": -5.0}]
    rows = {m["month"]: m for m in taxes.months(deals, cash, 2026)}
    oct_, nov = rows["2026-10"], rows["2026-11"]
    assert oct_["result"] == 395 and oct_["withheld"] == -105.5 and oct_["deposits"] == 2000 and oct_["fees"] == -5
    assert round(oct_["rate"], 2) == round(105.5 / 395 * 100, 2) and oct_["after_tax"] == 395 - 105.5
    assert nov["refunded"] == 26.38 and nov["rate"] is None                     # a loss month: refund, no rate
    # estimate without bookings: the non-trade change between recorded day starts
    t1 = dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc).timestamp()
    deals2 = [{"time": t1 + 3600, "net": 300.0}]
    est = taxes.estimate(deals2, 10_220.0, {"2026-10-02": 10_000.0})              # 300 traded, balance only +220: -80 not trades
    assert len(est) == 1 and round(est[0]["non_trade"], 2) == -80.0 and est[0]["to"] == "now"


def test_recheck_explains_a_moved_start_balance():
    pos = [["1", "a", "b", "X", "long", 1.0, 100.0], ["2", "a", "b", "X", "short", 1.0, -40.0]]
    old = {"start_balance": 1000.0, "end_balance": 1060.0, "positions": pos}
    assert "identical" in report.explain(old, {**old, "start_balance": 989.37, "end_balance": 1049.37})
    assert report.explain(old, {**old, "start_balance": 989.37, "end_balance": 1060.0}) is None          # not one booking
    pct_old = {"return_pct": 6.0, "positions": [["1", "a", "b", "X", "long", "", 10.0], ["2", "a", "b", "X", "short", "", -4.0]]}
    pct_new = {"return_pct": 6.1, "positions": [["1", "a", "b", "X", "long", "", 10.1], ["2", "a", "b", "X", "short", "", -4.04]]}
    assert "same factor" in report.explain(pct_old, pct_new)
    assert report.explain(pct_old, {**pct_new, "positions": [["1", "a", "b", "X", "long", "", 10.1], ["2", "a", "b", "X", "short", "", -5.0]]}) is None


def test_balance_comment_decides_the_booking_type():
    from sessiondesk.connectors.mt5 import booking_type
    assert booking_type("BALANCE", "WHT #10000001:20000001") == "TAX"                 # Pepperstone GmbH: tax per trade
    assert booking_type("BALANCE", "Tax settlement #A0000000000001") == "TAX"         # refund when losses are offset
    assert booking_type("BALANCE", "Dividend US500 #30000001") == "DIVIDEND"
    assert booking_type("BALANCE", "DP card01 #P0000000000001") == "BALANCE"         # deposit
    assert booking_type("BALANCE", "WD CC_01 :WTH0000000000001") == "BALANCE"         # withdrawal
    assert booking_type("CHARGE", "WHT looks like tax") == "CHARGE"                   # only BALANCE is refined
    assert booking_type("BALANCE", None) == "BALANCE"


def test_day_balance_and_account_curve_end_at_the_real_balance():
    r = report.build(_deals(), {"label": "123456", "currency": "EUR", "balance": 15_000.0}, T0, T0 + 3 * DAY, now=T0 + 3 * DAY, cash=_cash())
    assert abs(r["days"][-1]["balance"] - 15_000.0) < 1e-9 and abs(r["balance_curve"][-1][1] - 15_000.0) < 1e-9
    assert r["curve"][-1][1] == r["start_balance"] + r["net"]                         # performance path unchanged
    assert abs(r["days"][-1]["perf_balance"] - r["curve"][-1][1]) < 1e-9
    assert round(sum(d["bookings"] for d in r["days"]), 2) == round(-78.07 + 132.40 + 5000, 2)   # the fee is result, not a booking


def test_performance_report_sums_taxes_tax_report_itemises():
    r = report.build(_deals(), {"label": "123456", "currency": "EUR", "balance": 15_000.0}, T0, T0 + 3 * DAY, now=T0 + 3 * DAY, cash=_cash())
    texts = {}
    for mode in ("summed", "itemised"):
        r["tax_detail"] = mode
        b = report.data_block(r)
        assert b["tax_detail"] == mode
        fp = report.fingerprint(b)
        csv_text = report.to_csv(r, report.report_id(r, fp), fp)
        assert report.verify_csv(csv_text)["ok"]
        raw = report.to_pdf(r, "SD-X", fp)
        texts[mode] = (csv_text, "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(raw)).pages))
    s_csv, s_pdf = texts["summed"]
    i_csv, i_pdf = texts["itemised"]
    assert ",TAX," not in s_csv and "tax_net,54.33" in s_csv and ",BALANCE,5000.0" in s_csv
    assert ",TAX,-78.07" in i_csv and "tax_net" not in i_csv
    assert not report.verify_csv(s_csv.replace("tax_net,54.33", "tax_net,5.43"))["ok"]       # a changed tax sum shows
    assert "Trading performance report" in s_pdf and "Taxes, net (itemised in the tax report)" in s_pdf
    assert "Return after tax" not in s_pdf and "tax refund" not in s_pdf
    assert "Trading performance and tax report" in i_pdf and "Taxes per month" in i_pdf and "tax refund" in i_pdf
    assert "15,000.00" in s_pdf                                                             # day table ends at the real balance
