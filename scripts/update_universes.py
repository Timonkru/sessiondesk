"""Refresh the bundled index member lists from Wikipedia.

Run from the repo root:  python scripts/update_universes.py
Needs pandas + lxml (dev only; the app reads the CSVs with the standard library).
Index providers rebalance quarterly - re-run after March/June/September/December reviews.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import sys
import urllib.request
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "sessiondesk" / "data" / "universes"
UA = {"User-Agent": "SessionDesk/0.1 (universe refresh; +https://github.com/Timonkru/sessiondesk)"}


def tables(url: str) -> list[pd.DataFrame]:
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8")
    return pd.read_html(io.StringIO(html))


def pick(dfs, *needed) -> pd.DataFrame:
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if all(any(n.lower() in c.lower() for c in cols) for n in needed):
            return df
    raise SystemExit(f"no table with columns {needed}")


def col(df, name) -> str:
    return next(c for c in df.columns if name.lower() in str(c).lower())


DOW30 = ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"]   # membership as of 2026-10-15


def rows_of(name: str) -> list[dict]:
    lines = [ln for ln in (OUT / f"{name}.csv").read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    return list(csv.DictReader(lines))


def write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# source: Wikipedia, fetched {dt.date.today().isoformat()} - re-run scripts/update_universes.py after index reviews\n")
        w = csv.DictWriter(fh, fieldnames=["symbol", "name", "sector", "industry"])
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} members -> {path}")


def main() -> int:
    sp = pick(tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"), "Symbol", "GICS Sector")
    write("sp500", [{"symbol": str(r[col(sp, "Symbol")]).replace(".", "-"), "name": r[col(sp, "Security")],
                     "sector": r[col(sp, "GICS Sector")], "industry": r[col(sp, "Sub-Industry")]} for _, r in sp.iterrows()])

    nd = pick(tables("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"), "Ticker", "Company")
    sector, sub = col(nd, "Industry"), col(nd, "Subsector")      # ICB classification on this page
    write("nasdaq100", [{"symbol": str(r[col(nd, "Ticker")]).replace(".", "-"), "name": r[col(nd, "Company")],
                         "sector": r[sector], "industry": r[sub]} for _, r in nd.iterrows()])

    dx = pick(tables("https://en.wikipedia.org/wiki/DAX"), "Ticker", "Company")
    rows = []
    for _, r in dx.iterrows():
        sym = str(r[col(dx, "Ticker")]).strip()
        if "." not in sym:
            sym = sym + ".DE"
        sector_col = next((c for c in dx.columns if "sector" in str(c).lower()), None)
        rows.append({"symbol": sym, "name": r[col(dx, "Company")], "sector": r[sector_col] if sector_col else "", "industry": ""})
    write("dax40", rows)

    ft = pick(tables("https://en.wikipedia.org/wiki/FTSE_100_Index"), "Company", "Ticker")
    sec = next((c for c in ft.columns if "sector" in str(c).lower()), None)
    write("ftse100", [{"symbol": str(r[col(ft, "Ticker")]).strip().rstrip(".").replace(".", "-") + ".L", "name": r[col(ft, "Company")],
                       "sector": r[sec] if sec else "", "industry": ""} for _, r in ft.iterrows()])

    ca = pick(tables("https://en.wikipedia.org/wiki/CAC_40"), "Company", "Ticker")
    write("cac40", [{"symbol": str(r[col(ca, "Ticker")]).strip(), "name": r[col(ca, "Company")], "sector": r[col(ca, "Sector")],
                     "industry": r[col(ca, "GICS Sub")]} for _, r in ca.iterrows()])

    sm = pick(tables("https://en.wikipedia.org/wiki/Swiss_Market_Index"), "Name", "Ticker", "Sector")
    rows = []
    for _, r in sm.iterrows():
        t = str(r[col(sm, "Ticker")]).strip()
        if t and t.lower() != "nan" and t.isalnum():
            rows.append({"symbol": t + ".SW", "name": r[col(sm, "Name")], "sector": r[col(sm, "Sector")], "industry": ""})
    write("smi", rows)

    es = pick(tables("https://en.wikipedia.org/wiki/EURO_STOXX_50"), "Ticker", "Name", "Sector")
    write("stoxx50", [{"symbol": str(r[col(es, "Ticker")]).strip(), "name": r[col(es, "Name")], "sector": r[col(es, "Sector")],
                       "industry": ""} for _, r in es.iterrows()])

    # Wikipedia no longer carries a parseable Dow table: the 30 members are maintained here (changes are rare and announced).
    sp = {r["symbol"]: r for r in rows_of("sp500")}
    write("dow30", [{"symbol": t, "name": sp.get(t, {}).get("name", t), "sector": sp.get(t, {}).get("sector", ""),
                     "industry": sp.get(t, {}).get("industry", "")} for t in DOW30])
    return 0


if __name__ == "__main__":
    sys.exit(main())
