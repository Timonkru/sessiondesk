"""Sector performance by region, from sector ETFs (free daily closes): 1 day, 1 week, 1 month, 3 months,
year to date and 1 year, absolute and relative to the region's broad market. ETFs carry fees and tracking
differences, so this is the sector picture, not the exact index return.
"""
from __future__ import annotations

import datetime as dt
import time

REGIONS = {
    "us": {"name": "United States - S&P 500 sectors (SPDR ETFs)", "benchmark": ("SPY", "S&P 500 (SPY)"), "sectors": [
        ("XLK", "Technology"), ("XLC", "Communication"), ("XLY", "Consumer discretionary"), ("XLF", "Financials"),
        ("XLV", "Health care"), ("XLI", "Industrials"), ("XLE", "Energy"), ("XLB", "Materials"), ("XLP", "Consumer staples"),
        ("XLU", "Utilities"), ("XLRE", "Real estate")]},
    "eu": {"name": "Europe - STOXX 600 sectors (iShares ETFs, Xetra)", "benchmark": ("^STOXX", "STOXX 600"), "sectors": [
        ("EXV1.DE", "Banks"), ("EXH5.DE", "Insurance"), ("EXH2.DE", "Financial services"), ("EXV3.DE", "Technology"),
        ("EXV4.DE", "Health care"), ("EXH1.DE", "Oil & gas"), ("EXV6.DE", "Basic resources"), ("EXV7.DE", "Chemicals"),
        ("EXH4.DE", "Industrial goods"), ("EXV8.DE", "Construction"), ("EXV5.DE", "Autos"), ("EXH3.DE", "Food & beverage"),
        ("EXH7.DE", "Personal & household"), ("EXH8.DE", "Retail"), ("EXV9.DE", "Travel & leisure"), ("EXH6.DE", "Media"),
        ("EXV2.DE", "Telecom"), ("EXH9.DE", "Utilities"), ("EXI5.DE", "Real estate")]},
}
PERIODS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "1y": 252}


def returns(points: list[tuple[str, float]], today: dt.date | None = None) -> dict:
    """Period returns in percent from dated closes (pure, tested)."""
    out = {}
    v = [p[1] for p in points]
    for name, k in PERIODS.items():
        out[name] = (v[-1] / v[-1 - k] - 1) * 100 if len(v) > k and v[-1 - k] else None
    year = str((today or dt.date.today()).year)
    prev = [val for d, val in points if d < year + "-01-01"]
    out["ytd"] = (v[-1] / prev[-1] - 1) * 100 if prev and prev[-1] else None
    return out


async def performance(ctx, region: str) -> dict:
    spec = REGIONS.get(region)
    if not spec:
        return {"error": "unknown region"}
    yahoo = ctx.hub.get("yahoo")

    async def build():
        syms = [s for s, _ in spec["sectors"]] + [spec["benchmark"][0]]
        data = await yahoo.daily_series(syms, "2y")
        if not data:
            return {"error": "no sector data"}
        bench = returns(data.get(spec["benchmark"][0], []))
        rows = []
        for sym, name in spec["sectors"]:
            pts = data.get(sym)
            if not pts:
                continue
            r = returns(pts)
            rows.append({"symbol": sym, "name": name, "last": pts[-1][1], "day": pts[-1][0], **r,
                         **{f"rel_{k}": (r[k] - bench[k]) if r.get(k) is not None and bench.get(k) is not None else None for k in r},
                         "spark": [v for _, v in pts[-60:]]})
        return {"region": region, "name": spec["name"], "benchmark": {"symbol": spec["benchmark"][0], "name": spec["benchmark"][1], **bench},
                "rows": rows, "asof": time.time()}
    return await ctx.cache.get(f"sectors:{region}", 900, build)


# ------------------------------------------------------------------ drill-down: the stocks inside a sector
# The bundled index files name sectors differently (GICS, ICB, free text such as "Automotive" or "Support services").
# They are folded into eleven broad sectors; the first matching rule wins, so specific words come first.
CANONICAL_RULES = [
    ("real_estate", ("real estate",)),
    ("utilities", ("utilit", "power producers")),
    ("industrials", ("energy technology", "aerospace", "defence", "defense", "industrial", "mechanical", "logistics",
                     "support services", "distribution", "electrical", "engineering", "construction & materials")),
    ("materials", ("materials", "chemicals", "mining", "construction materials", "basic resources")),
    ("health", ("health", "pharma", "biotech", "medical")),
    ("communication", ("communication", "telecom", "media")),
    ("discretionary", ("discretionary", "cyclical", "consumer services", "automotive", "apparel", "travel", "leisure",
                       "general retailers", "retailers", "retail hospitality", "personal goods", "household goods",
                       "homebuilding", "e-commerce")),
    ("staples", ("staples", "defensive", "consumer goods", "beverages", "food", "tobacco")),
    ("financials", ("financial", "bank", "insurance", "investment trust", "collective investments")),
    ("technology", ("technology", "software", "electronic", "semiconductor")),
    ("energy", ("energy", "oil & gas", "oil and gas")),
]
SECTOR_OF_ETF = {
    "XLK": "technology", "XLC": "communication", "XLY": "discretionary", "XLF": "financials", "XLV": "health",
    "XLI": "industrials", "XLE": "energy", "XLB": "materials", "XLP": "staples", "XLU": "utilities", "XLRE": "real_estate",
    "EXV1.DE": "financials", "EXH5.DE": "financials", "EXH2.DE": "financials", "EXV3.DE": "technology", "EXV4.DE": "health",
    "EXH1.DE": "energy", "EXV6.DE": "materials", "EXV7.DE": "materials", "EXH4.DE": "industrials", "EXV8.DE": "materials",
    "EXV5.DE": "discretionary", "EXH3.DE": "staples", "EXH7.DE": "staples", "EXH8.DE": "discretionary",
    "EXV9.DE": "discretionary", "EXH6.DE": "communication", "EXV2.DE": "communication", "EXH9.DE": "utilities",
    "EXI5.DE": "real_estate",
}


# Whole sector names that the word rules would get wrong or miss (Nikkei's 36 industries, FTSE MIB, IBEX 35);
# checked first. "Gas" alone is the utility (Nikkei), not "Oil & Gas".
EXACT_SECTORS = {
    "gas": "utilities", "electric power": "utilities", "securities": "financials", "retail": "discretionary",
    "services": "industrials", "fishery": "staples", "petroleum": "energy", "rubber": "discretionary",
    "steel": "materials", "nonferrous metals": "materials", "glass & ceramics": "materials", "pulp & paper": "materials",
    "construction": "industrials", "machinery": "industrials", "shipbuilding": "industrials", "other manufacturing": "industrials",
    "manufacturing": "industrials", "infrastructure": "industrials", "aviation": "industrials", "air transport": "industrials",
    "land transport": "industrials", "marine transport": "industrials", "railway & bus": "industrials",
    "trading companies": "industrials", "electric machinery": "technology", "precision instruments": "technology",
    "tourism": "discretionary", "textile": "discretionary", "clothes and cosmetics": "discretionary", "gambling": "discretionary",
    "consumer products and services": "discretionary", "automobiles and parts": "discretionary",
    "automobiles & auto parts": "discretionary",
}


def canonical_sector(sector: str | None, industry: str | None = None) -> str | None:
    """Broad sector key for a member's sector text (pure, tested)."""
    exact = EXACT_SECTORS.get((sector or "").strip().lower())
    if exact:
        return exact
    text = f"{sector or ''} | {industry or ''}".lower()
    for key, words in CANONICAL_RULES:
        if any(w in (sector or "").lower() for w in words):
            return key
    for key, words in CANONICAL_RULES:                 # sector text unknown: try the industry
        if any(w in text for w in words):
            return key
    return None


async def drilldown(ctx, region: str, etf: str) -> dict:
    """The stocks of one sector, from the same stock list as every other level of the Markets tree."""
    from .stocklist import stocks
    spec = REGIONS.get(region)
    target = SECTOR_OF_ETF.get(etf)
    if not spec or not target or etf not in [s for s, _ in spec["sectors"]]:
        return {"error": "unknown sector"}
    d = await stocks(ctx, f"region:{region}", group=target)
    perf = await performance(ctx, region)
    etf_row = next((r for r in perf.get("rows", []) if r["symbol"] == etf), None)
    return {"region": region, "etf": etf, "sector": etf_row["name"] if etf_row else etf, "group": target, "etf_row": etf_row,
            "benchmark": perf.get("benchmark"), "rows": d["rows"], "n": d["n"],
            "note": ("Members of the S&P 500, Nasdaq-100 and Dow 30 in this sector. " if region == "us" else
                     "Members of Euro Stoxx 50, DAX, CAC 40, FTSE 100, SMI, FTSE MIB, IBEX 35 and AEX, grouped into eleven broad sectors - the STOXX "
                     "sector ETFs are finer (e.g. Banks, Insurance and Financial services all show the financials here). ")
                    + "Moves from one year of daily closes, today's value live."}
