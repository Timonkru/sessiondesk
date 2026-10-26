"""Freshness and labelling: front contracts by expiry rule, unit conversion, yields around the clock, the official
Treasury curve, today's session vs the last one, late FRED observations."""
from __future__ import annotations

import datetime as dt

import pytest

from sessiondesk.connectors.public import parse_cnbc, parse_treasury_csv
from sessiondesk.features import futures, macro, movers


def test_gas_front_contract_follows_the_expiry_rule():
    # NYMEX Henry Hub: 3 business days before the 1st of the delivery month. 1 Nov 2026 is a Sunday -> Wed 28 Oct.
    assert futures.business_days_before(dt.date(2026, 11, 1), 3) == dt.date(2026, 10, 28)
    ng = futures.months("NG", dt.date(2026, 10, 26), 3)
    assert [m["symbol"] for m in ng] == ["NGX26.NYM", "NGZ26.NYM", "NGF27.NYM"]   # Yahoo's NG=F was already December
    assert ng[0]["expiry"] == "2026-10-28" and ng[0]["unit"] == "$/MMBtu"
    assert futures.months("NG", dt.date(2026, 10, 29), 1)[0]["symbol"] == "NGZ26.NYM"   # after expiry: December
    ttf = futures.front("TTF=F", dt.date(2026, 10, 26))
    assert ttf["symbol"] == "TTFX26.NYM" and ttf["expiry"] == "2026-10-29" and ttf["unit"] == "EUR/MWh"
    assert futures.front("GC=F") is None                                           # others stay continuous


def test_oil_expiry_rules():
    assert futures.expiry("BZ", 2026, 12) == dt.date(2026, 10, 30)     # Brent: last business day two months before
    assert futures.expiry("BZ", 2027, 1) == dt.date(2026, 11, 30)
    assert futures.expiry("CL", 2026, 12) == dt.date(2026, 11, 20)     # WTI: 3 business days before 25 Nov (a Wed)
    assert futures.expiry("CL", 2027, 1) == dt.date(2026, 12, 22)      # 25 Dec is a Friday -> 3 before it
    assert futures.expiry("CL", 2026, 11) == dt.date(2026, 10, 20)     # 25 Oct 2026 is a Sunday -> anchor Fri 23 Oct
    assert futures.expiry("HO", 2026, 11) == dt.date(2026, 10, 30)
    # 26.10.2026: Yahoo's BZ=F already showed January; the exchange front is still December
    assert futures.front("BZ=F", dt.date(2026, 10, 26))["symbol"] == "BZZ26.NYM"


def test_ttf_conversion_to_henry_hub_units():
    # 26.10.2026: TTF 96.085 EUR/MWh, EUR/USD 1.1199 -> 31.54 $/MMBtu
    assert futures.ttf_in_usd_mmbtu(96.085, 1.1199) == pytest.approx(31.54, abs=0.01)
    assert 1 / futures.MWH_PER_MMBTU == pytest.approx(3.412, abs=0.001)


def test_parse_cnbc_yields():
    data = {"FormattedQuoteResult": {"FormattedQuote": [
        {"symbol": "US10Y", "last": "4.986%", "previous_day_closing": "4.988%", "last_time": "2026-10-26T07:20:55.000-0400", "name": "U.S. 10 Year Treasury"},
        {"symbol": ".GDAXI", "last": "25,386.15", "previous_day_closing": "25,181.65", "last_time": "2026-10-26T13:05:00.000+0200"},
        {"symbol": "BAD", "last": "N/A"}]}}
    q = parse_cnbc(data)
    assert set(q) == {"US10Y", ".GDAXI"}
    assert q["US10Y"]["price"] == 4.986 and q["US10Y"]["change"] == pytest.approx(-0.002)
    assert q["US10Y"]["time"] == dt.datetime(2026, 10, 26, 11, 20, 55, tzinfo=dt.timezone.utc).timestamp()
    assert q[".GDAXI"]["price"] == 25386.15


def test_parse_treasury_curve():
    text = ('Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
            "10/23/2026,4.11,4.11,4.16,4.22,4.30,4.30,4.44,4.69,4.75,4.82,4.89,5.00,5.37,5.33\n"
            "10/22/2026,4.11,4.10,4.16,4.22,4.29,4.29,4.41,4.65,4.72,4.78,4.86,4.96,5.32,\n")
    days = parse_treasury_csv(text)
    assert days[0] == {"date": "2026-10-23", "yields": {"1m": 4.11, "3m": 4.22, "6m": 4.3, "1y": 4.44, "2y": 4.69, "3y": 4.75,
                                                       "5y": 4.82, "7y": 4.89, "10y": 5.0, "20y": 5.37, "30y": 5.33}}
    assert "30y" not in days[1]["yields"] and days[1]["yields"]["10y"] == 4.96          # empty cell skipped


def test_traded_today_separates_the_last_session():
    now = dt.datetime(2026, 10, 26, 10, 0, tzinfo=dt.timezone.utc).timestamp()          # Monday, before the US open
    friday_us = dt.datetime(2026, 10, 23, 20, 0, tzinfo=dt.timezone.utc).timestamp()
    monday_eu = dt.datetime(2026, 10, 26, 9, 55, tzinfo=dt.timezone.utc).timestamp()
    sydney = dt.datetime(2026, 10, 25, 23, 30, tzinfo=dt.timezone.utc).timestamp()       # Monday's ASX session
    assert not movers.traded_today(friday_us, now)
    assert movers.traded_today(monday_eu, now) and movers.traded_today(sydney, now)
    assert movers.traded_today(None, now)                                                 # unknown time: keep it


def test_late_fred_observation():
    today = dt.date(2026, 10, 26)
    assert macro.late("BAMLH0A0HYM2", "2026-10-22", today) == (4, False)
    assert macro.late("BAMLH0A0HYM2", "2026-10-19", today) == (7, True)                  # daily spread a week old
    assert macro.late("CPIAUCSL", "2026-09-01", today)[1] is False                       # monthly: normal lag
    assert macro.late("UNKNOWN", "2020-01-01", today)[1] is False                        # no rule, no flag
