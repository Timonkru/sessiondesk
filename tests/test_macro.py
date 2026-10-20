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
