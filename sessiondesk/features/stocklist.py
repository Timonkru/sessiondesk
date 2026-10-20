"""One list of stocks for every level of the Markets tree: an index, a region, a sector, an industry, or all.

Rows are the screener measures (moves, distance to highs and averages, RSI, volatility, cached fundamentals) for
the members of the bundled index lists, merged across indices (a stock in the DAX and the Euro Stoxx 50 appears
once, with both names in "indices"), plus a broad sector ("group", eleven sectors) and an industry. The industry
is the member file's sub-industry where it has one (S&P 500, Nasdaq-100, CAC 40) and its own sector text otherwise.
"""
from __future__ import annotations

from . import universe
from .screener import screen
from .sectors import canonical_sector

REGIONS = {"us": ("United States", ["sp500", "nasdaq100", "dow30"]),
           "eu": ("Europe", ["stoxx50", "dax40", "cac40", "ftse100", "smi", "ftsemib", "ibex35", "aex25"]),
           "ca": ("Canada", ["tsx60"]),
           "asia": ("Asia-Pacific", ["nikkei225", "hsi", "asx200"])}
GROUP_LABELS = {"technology": "Technology", "communication": "Communication", "discretionary": "Consumer discretionary",
                "staples": "Consumer staples", "financials": "Financials", "health": "Health care", "industrials": "Industrials",
                "energy": "Energy", "materials": "Materials", "utilities": "Utilities", "real_estate": "Real estate"}


def region_of(key: str) -> str:
    return next((r for r, (_, keys) in REGIONS.items() if key in keys), "eu")


def scope_universes(scope: str) -> tuple[str, list[str]]:
    """"all", "region:us", "index:dax40" -> (label, universe keys) (pure, tested)."""
    kind, _, key = (scope or "all").partition(":")
    if kind == "index" and key in universe.UNIVERSES:
        return universe.UNIVERSES[key], [key]
    if kind == "region" and key in REGIONS:
        return REGIONS[key][0], list(REGIONS[key][1])
    return "All indices", [k for _, keys in REGIONS.values() for k in keys]


def merge(per_universe: dict[str, list[dict]]) -> list[dict]:
    """Union of screener rows by symbol, with the indices each stock belongs to, its sector group and industry (pure, tested)."""
    out: dict[str, dict] = {}
    for key, rows in per_universe.items():
        for r in rows:
            if r["symbol"] in out:
                out[r["symbol"]]["indices"].append(universe.UNIVERSES[key])
                continue
            group = canonical_sector(r.get("sector"), r.get("industry"))
            out[r["symbol"]] = {**r, "indices": [universe.UNIVERSES[key]], "group": group,
                                "group_label": GROUP_LABELS.get(group or "", "Other"),
                                "industry": r.get("industry") or r.get("sector") or ""}
    return list(out.values())


async def stocks(ctx, scope: str = "all", group: str | None = None, industry: str | None = None) -> dict:
    label, keys = scope_universes(scope)
    per, notes = {}, []
    for k in keys:
        d = await screen(ctx, k)
        if "error" in d:
            notes.append(f"{universe.UNIVERSES[k]}: {d['error']}")
            continue
        per[k] = d["rows"]
    rows = merge(per)
    if group:
        rows = [r for r in rows if r["group"] == group]
    if industry:
        rows = [r for r in rows if r["industry"] == industry]
    with_profile = sum(1 for r in rows if r.get("market_cap") is not None)
    return {"scope": scope, "label": label, "universes": keys, "rows": rows, "n": len(rows),
            "groups": [{"key": k, "label": v} for k, v in GROUP_LABELS.items()],
            "note": ("Members of the bundled index lists; a stock in several indices appears once. Moves from one year of daily "
                     f"closes, today's value live. Market cap, forward P/E and yield only where a profile is cached ({with_profile} "
                     f"of {len(rows)}). Sectors folded into eleven groups; industry = the index file's sub-industry, else its sector. "
                     "A list describes; it is not a signal.") + (" Missing: " + "; ".join(notes) if notes else "")}
