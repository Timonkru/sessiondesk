"""Portfolio exposures: classification of broker symbols and per-account exposure tables."""
from __future__ import annotations

from sessiondesk.features import portfolio


def test_classify_symbols():
    assert portfolio.classify("GER40.cash")["legs"] == {"EUR": 1.0} and portfolio.classify("GER40.cash")["cls"] == "Index"
    fx = portfolio.classify("EURUSD")
    assert fx["cls"] == "FX" and fx["legs"] == {"EUR": 1.0, "USD": -1.0}
    assert portfolio.classify("XAUUSD")["cls"] == "Commodity"
    st = portfolio.classify("NVDA.US")
    assert st["cls"] == "Stock" and st["legs"] == {"USD": 1.0} and st["sector"] == "Technology"
    assert portfolio.classify("SAP.DE")["legs"] == {"EUR": 1.0}


def test_exposures_per_account():
    positions = [{"account": "A", "symbol": "GER40.cash", "side": "LONG", "money_per_pct": 50.0, "risk_to_stop": 100.0, "sl": 1},
                 {"account": "A", "symbol": "EURUSD", "side": "SHORT", "money_per_pct": 20.0, "risk_to_stop": 50.0, "sl": 1},
                 {"account": "A", "symbol": "NVDA.US", "side": "LONG", "money_per_pct": None},
                 {"account": "B", "symbol": "US100.cash", "side": "SHORT", "money_per_pct": 10.0}]
    accounts = [{"login": "A", "equity": 10000.0, "currency": "EUR"}, {"login": "B", "equity": 5000.0, "currency": "USD"}]
    a, b = portfolio.exposures(positions, accounts)
    assert a["gross"] == 7000 and a["net"] == 3000 and a["gross_pct"] == 70 and a["missing_notional"] == 1
    assert {r["name"]: r["net"] for r in a["by_currency"]} == {"EUR": 3000.0, "USD": 2000.0}   # DAX +5000 EUR, short EURUSD -2000 EUR +2000 USD
    assert a["risk_pct"] == 1.5 and a["largest"][0]["symbol"] == "GER40.cash"
    assert b["net_pct"] == -20 and b["without_stop"] == 1                                       # accounts stay separate
