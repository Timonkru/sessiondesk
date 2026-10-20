"""Index member lists bundled with the app (refresh: scripts/update_universes.py) + sector ETFs."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "data" / "universes"

UNIVERSES = {"sp500": "S&P 500", "nasdaq100": "Nasdaq-100", "dow30": "Dow 30", "tsx60": "S&P/TSX 60",
             "dax40": "DAX 40", "ftse100": "FTSE 100", "cac40": "CAC 40", "smi": "SMI", "stoxx50": "Euro Stoxx 50",
             "ftsemib": "FTSE MIB", "ibex35": "IBEX 35", "aex25": "AEX",
             "nikkei225": "Nikkei 225", "hsi": "Hang Seng", "asx200": "S&P/ASX 200"}
# The index each list is measured against. The S&P/TSX 60 has no free index quote on Yahoo: the iShares ETF
# that tracks it (XIU) stands in.
BENCHMARK = {"sp500": "^GSPC", "nasdaq100": "^NDX", "dow30": "^DJI", "tsx60": "XIU.TO", "dax40": "^GDAXI", "ftse100": "^FTSE",
             "cac40": "^FCHI", "smi": "^SSMI", "stoxx50": "^STOXX50E", "ftsemib": "FTSEMIB.MI", "ibex35": "^IBEX", "aex25": "^AEX",
             "nikkei225": "^N225", "hsi": "^HSI", "asx200": "^AXJO"}
REGION = {"sp500": "Americas", "nasdaq100": "Americas", "dow30": "Americas", "tsx60": "Americas",
          "nikkei225": "Asia-Pacific", "hsi": "Asia-Pacific", "asx200": "Asia-Pacific"}      # everything else: Europe

# GICS sector (S&P 500 file) / ICB industry (Nasdaq-100 file) -> SPDR sector ETF
SECTOR_ETF = {
    "Information Technology": "XLK", "Technology": "XLK", "Health Care": "XLV", "Financials": "XLF",
    "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Energy": "XLE", "Industrials": "XLI",
    "Materials": "XLB", "Basic Materials": "XLB", "Utilities": "XLU", "Real Estate": "XLRE",
    "Communication Services": "XLC", "Telecommunications": "XLC", "Consumer Services": "XLY",
    "Consumer Goods": "XLP", "Oil & Gas": "XLE",
}


@lru_cache(maxsize=None)
def members(universe: str) -> tuple[dict, ...]:
    path = HERE / f"{universe}.csv"
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    except OSError:
        return ()
    return tuple(dict(r) for r in csv.DictReader(lines))


def lookup(symbol: str) -> dict | None:
    for u in UNIVERSES:
        for m in members(u):
            if m["symbol"] == symbol:
                return {**m, "universe": u}
    return None


def sector_etf(symbol: str, sector: str | None = None) -> str | None:
    if "." in symbol:
        return None                      # non-US listing (.DE, .L, .PA, .SW ...): no matching US sector ETF
    if not sector:
        m = lookup(symbol)
        sector = m["sector"] if m else None
    return SECTOR_ETF.get(sector or "")


def peers(symbol: str, limit: int = 8) -> list[str]:
    me = lookup(symbol)
    if not me:
        return []
    pool = members(me["universe"])
    same_ind = [m["symbol"] for m in pool if m["symbol"] != symbol and me["industry"] and m["industry"] == me["industry"]]
    same_sec = [m["symbol"] for m in pool if m["symbol"] != symbol and m["sector"] == me["sector"] and m["symbol"] not in same_ind]
    return (same_ind + same_sec)[:limit]
