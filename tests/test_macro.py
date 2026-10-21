"""Macro FRED transforms: year-on-year, month-on-month, difference, 4-week average, millions to billions."""
from __future__ import annotations

import pytest

from sessiondesk.features import macro


def _pts(values):
    return [(f"2026-{i + 1:02d}-01" if i < 12 else f"2027-{i - 11:02d}-01", v) for i, v in enumerate(values)]


def test_transforms():
    monthly = _pts([100.0 + i for i in range(14)])                # 14 months, +1 per month
    yoy = macro.transform(monthly, "yoy12")
    assert yoy["value"] == pytest.approx((113 / 101 - 1) * 100) and yoy["prev"] == pytest.approx((112 / 100 - 1) * 100)
    assert macro.transform(monthly, "mom")["value"] == pytest.approx((113 / 112 - 1) * 100)
    assert macro.transform(_pts([10.0, 15.0, 12.0]), "diff") == {"date": "2026-03-01", "value": -3.0, "prev": 5.0, "change": -8.0}
    avg = macro.transform(_pts([1.0, 2.0, 3.0, 4.0, 5.0]), "avg4")
    assert avg["value"] == pytest.approx(3.5) and avg["prev"] == pytest.approx(2.5)
    assert macro.transform(_pts([6000.0, 6755.6]), "mn_to_bn")["value"] == pytest.approx(6.7556)
    assert macro.transform(_pts([4.1, 4.2]), "level")["change"] == pytest.approx(0.1)
    assert macro.transform(_pts([1.0]), "level") is None
    assert macro.transform(_pts([100.0, 101.0]), "yoy12") is None  # not a year of data


def test_parse_jsonstat_and_ons():
    from sessiondesk.features import macro as m
    d = {"id": ["freq", "unit", "geo", "time"], "size": [1, 1, 2, 2],
         "dimension": {"freq": {"category": {"index": {"M": 0}}}, "unit": {"category": {"index": {"RCH_A": 0}}},
                       "geo": {"category": {"index": {"DE": 0, "EA": 1}}}, "time": {"category": {"index": {"2026-08": 0, "2026-09": 1}}}},
         "value": {"0": 2.1, "1": 2.3, "2": 2.0}}                 # EA 2026-09 missing
    assert m.parse_jsonstat(d) == {"DE": [("2026-08", 2.1), ("2026-09", 2.3)], "EA": [("2026-08", 2.0)]}
    text = '"Title","CPI"\n"CDID","D7G7"\n"2025","3.2"\n"2026 Q2","0.5"\n"2026 JUL","2.9"\n"2026 AUG","3.1"\n'
    assert m.parse_ons_csv(text) == [("2026-Q2", 0.5), ("2026-07", 2.9), ("2026-08", 3.1)]


def test_rates_world_parsers():
    from sessiondesk.features import rates_world as rw
    ecb = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE\nYC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,2026-10-19,3.0533254392\n"
           "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-10-20,2.5\n")
    e = rw.parse_ecb_csv(ecb)
    assert e["FM.D.U2.EUR.4F.KR.DFR.LEV"] == ("2026-10-20", 2.5)
    boe = "DATE,IUDBEDR,IUDSNZC\n16 Oct 2026,3.75,4.9054\n19 Oct 2026,3.75,\n"
    b = rw.parse_boe_csv(boe)
    assert b["IUDBEDR"] == ("2026-10-19", 3.75) and b["IUDSNZC"] == ("2026-10-16", 4.9054)     # empty cell keeps the last value
    mof = "Interest Rate (October 2026),,,(Unit : %)\nDate,1Y,2Y,10Y\n2026/10/16,1.649,1.918,2.958\n2026/10/19,1.642,1.904,2.935\n,,,\n"
    assert rw.parse_mof_csv(mof) == ("2026-10-19", {"1y": 1.642, "2y": 1.904, "10y": 2.935})
    row = rw._row("X", ("2026-10-20", 2.5), "p", {"2y": ("2026-10-19", 3.05), "10y": ("2026-10-19", 4.0)}, "2y", "s", "u")
    assert round(row["gauge_bp"]) == 55 and round(row["s2s10"]) == 95


def test_rates_world_history_parsers():
    from sessiondesk.features import rates_world as rw
    ecb = "KEY,FREQ,TIME_PERIOD,OBS_VALUE\nYC.X.SR_2Y,B,2026-10-19,2.05\nYC.X.SR_2Y,B,2026-10-16,2.01\nYC.X.SR_2Y,B,2026-10-20,bad\n"
    assert rw.ecb_points(ecb) == {"YC.X.SR_2Y": [("2026-10-16", 2.01), ("2026-10-19", 2.05)]}
    boe = "DATE,IUDBEDR,IUDMNZC\n15 Oct 2026,4.0,4.71\n16 Oct 2026,4.0,\n"
    assert rw.boe_points(boe) == {"IUDBEDR": [("2026-10-15", 4.0), ("2026-10-16", 4.0)], "IUDMNZC": [("2026-10-15", 4.71)]}
    mof = "Interest Rate,,,(Unit : %)\nDate,1Y,2Y,10Y\n1974/9/24,10.3,9.36,-\n2026/9/30,1.684,1.952,3.057\n"
    assert rw.mof_points(mof) == {"1y": [("1974-09-24", 10.3), ("2026-09-30", 1.684)], "2y": [("1974-09-24", 9.36), ("2026-09-30", 1.952)],
                                  "10y": [("2026-09-30", 3.057)]}


def test_central_bank_schedule_parsers():
    from sessiondesk.features import centralbanks as cb
    fed = "<p>2026 FOMC Meetings</p><div>January</div><div>27-28</div><div>March</div><div>17-18*</div><p>2025 FOMC Meetings</p><div>December</div><div>9-10</div>"
    assert cb.parse_fed(fed) == ["2025-12-10", "2026-01-28", "2026-03-18"]
    ecb = ("<td>28/10/2026</td><td>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 1)</td>"
           "<td>29/10/2026</td><td>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference</td>"
           "<td>25/11/2026</td><td>Governing Council of the ECB: non-monetary policy meeting (in Frankfurt)</td>")
    assert cb.parse_ecb(ecb) == ["2026-10-29"]
    boe = "<h3>2026 confirmed dates</h3><p>Thursday 5 November</p><p>Thursday&nbsp;17 December</p><p>Current Bank Rate</p><p>3.75%</p>"
    assert cb.parse_boe(boe) == (["2026-11-05", "2026-12-17"], 3.75)
    boj = "<p>Table : 2026</p><p>Date of MPM</p><td>Jan. 22 (Thurs.), 23 (Fri.) [PDF]</td><td>Jan. 23 (Fri.) [PDF]</td><td>Oct. 29 (Thurs.), 30 (Fri.)</td>"
    assert cb.parse_boj(boj) == ["2026-01-23", "2026-10-30"]
    assert cb.dedupe(["2027-01-26", "2027-01-27", "2027-03-17"]) == ["2027-01-27", "2027-03-17"]
    assert round(cb.day_move([("2026-10-28", 100.0), ("2026-10-29", 101.0)], "2026-10-29"), 2) == 1.0


def test_central_bank_extras():
    from sessiondesk.features import centralbanks as cb
    assert cb.parse_ecb_last("<p>Latest monetary policy press conference</p><p>10 September 2026</p>") == "2026-09-10"
    closes = [("2026-09-17", 100.0), ("2026-09-19", 102.0)]                 # no point stamped on the 18th
    assert round(cb.day_move(closes, "2026-09-18"), 2) == 2.0 and cb.day_move(closes, "2026-09-01") is None
