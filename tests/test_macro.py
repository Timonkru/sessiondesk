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
