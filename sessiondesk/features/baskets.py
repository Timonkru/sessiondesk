"""Your own baskets: a set of symbols with weights (equal if none given), followed like an index.

The basket line is buy-and-hold from the first common day: value(t) = 100 * sum(w_i * P_i(t) / P_i(t0)), weights
normalised to 1. Daily closes are free (Yahoo); each basket is also stored in the data hub so it gets the same early
warnings as any other series. Stored in your local settings ("baskets").
"""
from __future__ import annotations

import re
import secrets

from .sectors import returns


def parse_members(text: str) -> list[dict]:
    """'AAPL 30, MSFT 20, NVDA' -> weights normalised; symbols without a weight share the rest equally (pure, tested)."""
    items = []
    for part in re.split(r"[,;\n]+", text or ""):
        bits = part.strip().split()
        if not bits:
            continue
        sym = bits[0].upper()
        w = None
        if len(bits) > 1:
            try:
                w = float(bits[1].rstrip("%").replace(",", "."))
            except ValueError:
                w = None
        items.append({"symbol": sym, "weight": w})
    if not items:
        return []
    weighted = [i["weight"] for i in items if i["weight"] is not None]
    missing = [i for i in items if i["weight"] is None]
    if missing:
        given = sum(weighted)
        if not weighted:
            share = 1.0                                             # nothing given: equal weights
        elif given < 100:
            share = (100.0 - given) / len(missing)                  # the rest of 100 split equally
        else:
            share = given / len(weighted)                           # over 100 already: average of the given ones
        for i in missing:
            i["weight"] = share
    total = sum(i["weight"] for i in items) or 1.0
    return [{"symbol": i["symbol"], "weight": i["weight"] / total} for i in items]


def basket_line(series: dict[str, list[tuple[str, float]]], members: list[dict]) -> list[tuple[str, float]]:
    """Buy-and-hold basket value from the first day every member has a price (pure, tested)."""
    have = [m for m in members if series.get(m["symbol"])]
    if not have:
        return []
    maps = {m["symbol"]: dict(series[m["symbol"]]) for m in have}
    days = sorted(set.intersection(*(set(v) for v in maps.values())))
    if not days:
        return []
    t0 = days[0]
    wsum = sum(m["weight"] for m in have)
    return [(d, 100 * sum(m["weight"] / wsum * maps[m["symbol"]][d] / maps[m["symbol"]][t0] for m in have)) for d in days]


def all_baskets(ctx) -> list[dict]:
    return list(ctx.settings.get("baskets") or [])


def save(ctx, name: str, members_text: str, basket_id: str | None = None, benchmark: str = "SPY") -> dict:
    members = parse_members(members_text)
    if not name.strip() or not members:
        return {"error": "a name and at least one symbol are required"}
    baskets = all_baskets(ctx)
    bid = basket_id or secrets.token_hex(4)
    entry = {"id": bid, "name": name.strip()[:60], "members": members, "benchmark": (benchmark or "SPY").upper()}
    baskets = [b for b in baskets if b["id"] != bid] + [entry]
    ctx.settings.replace("baskets", baskets)
    return {"basket": entry, "baskets": baskets}


def delete(ctx, basket_id: str) -> dict:
    baskets = [b for b in all_baskets(ctx) if b["id"] != basket_id]
    ctx.settings.replace("baskets", baskets)
    return {"baskets": baskets}


def _name(ctx, symbol: str) -> str:
    """Company name from the bundled index lists, else from a cached profile; empty when unknown."""
    from . import universe
    m = universe.lookup(symbol)
    if m:
        return m.get("name") or ""
    prof = ctx.cache.peek(f"profile:v2:{symbol}", disk=True) or {}
    return prof.get("name") or "" if "error" not in prof else ""


async def view(ctx, basket_id: str) -> dict:
    b = next((x for x in all_baskets(ctx) if x["id"] == basket_id), None)
    if not b:
        return {"error": "unknown basket"}
    yahoo = ctx.hub.get("yahoo")

    async def build():
        syms = [m["symbol"] for m in b["members"]] + [b.get("benchmark") or "SPY"]
        return {"series": await yahoo.daily_series(syms, "2y")}
    data = await ctx.cache.get(f"basket:{basket_id}:{'-'.join(m['symbol'] for m in b['members'])}", 900, build)
    series = data.get("series", {})
    line = basket_line(series, b["members"])
    bench_pts = series.get(b.get("benchmark") or "SPY") or []
    bench = dict(bench_pts)
    t0 = line[0][0] if line else None
    bench_line = [(d, 100 * bench[d] / bench[t0]) for d, _ in line if t0 in bench and d in bench]
    rows = []
    for m in b["members"]:
        pts = series.get(m["symbol"])
        r = returns(pts) if pts else {}
        rows.append({**m, "name": _name(ctx, m["symbol"]), "last": pts[-1][1] if pts else None, **r, "missing": not pts,
                     "contrib_1m": (m["weight"] * r["1m"]) if r.get("1m") is not None else None})
    if line:
        await ctx.db.run(ctx.db.upsert_series, {"id": f"basket:{basket_id}", "name": f"Basket {b['name']}", "category": "Your baskets",
                                                "source": "your basket (buy-and-hold from the first common day)", "kind": "price"}, line)
    return {"basket": b, "line": line, "benchmark_line": bench_line, "returns": returns(line) if line else {},
            "benchmark_returns": returns(bench_pts) if bench_pts else {}, "members": rows,
            "note": "Buy-and-hold from the first day all members have prices (no rebalancing, no dividends, no currency "
                    "conversion - members in different currencies are mixed as quoted)."}
