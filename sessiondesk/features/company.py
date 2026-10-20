"""Company structure: who runs and oversees it, which of the bundled indices hold it and with what weight, and
what changed since the last look.

People (free, Yahoo): executives with pay from the profile; board members from the insider roster (US filers:
Form 3/4 'Director'). Non-US companies usually show executives only.
Index weights: price-weighted Dow = price / sum of member prices; the others = market cap / sum of members' caps
from cached profiles (no free-float factors, no caps on single weights) - an estimate, coverage shown.
Changes: a daily snapshot per watched company (board, executives, index memberships); differences become alerts.
"""
from __future__ import annotations

import json
import time

from . import universe

SNAP_FILE = "company_snapshots.json"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _people(symbol: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(symbol)
    info = t.info or {}
    officers = [{"name": o.get("name"), "title": o.get("title"), "age": o.get("age"), "pay": _f(o.get("totalPay")),
                 "pay_year": o.get("fiscalYear")} for o in (info.get("companyOfficers") or []) if o.get("name")]
    board, roster = [], []
    try:
        r = t.insider_roster_holders
    except Exception:
        r = None
    if r is not None and not r.empty:
        for _, row in r.iterrows():
            item = {"name": str(row.get("Name") or "").title(), "position": row.get("Position"),
                    "last_transaction": row.get("Most Recent Transaction"), "last_date": str(row.get("Latest Transaction Date") or "")[:10],
                    "shares": _f(row.get("Shares Owned Directly"))}
            roster.append(item)
            if "director" in str(row.get("Position") or "").lower():
                board.append(item)
    chair = [o for o in officers if "chair" in (o.get("title") or "").lower()]
    return {"officers": officers, "board": board, "insiders": roster, "chair": chair,
            "note": "Board = insiders filed as 'Director' (US companies, Forms 3/4); executives and pay from the company profile. "
                    "Non-US companies usually list executives only - their supervisory boards are not in the free data."}


async def people(ctx, symbol: str) -> dict:
    return await ctx.cache.get(f"company:people:{symbol}", 24 * 3600, lambda: _people(symbol), disk=True)


MIN_COVERAGE = 0.9          # with fewer members known the denominator is too small and every weight comes out too high


def weight_estimate(symbol: str, members: list[str], caps: dict[str, float], prices: dict[str, float], price_weighted: bool) -> dict:
    """Share of one member in its index (pure, tested). None when too few members are known."""
    base, basis = (prices, "price / sum of prices") if price_weighted else (caps, "market cap / sum of caps")
    known = {m: base[m] for m in members if base.get(m)}
    total = sum(known.values())
    enough = len(known) >= MIN_COVERAGE * len(members)
    return {"weight": known[symbol] / total if enough and symbol in known and total else None,
            "basis": basis if enough else f"too few members known for a weight (needs {MIN_COVERAGE:.0%})",
            "coverage": len(known), "members": len(members)}


async def memberships(ctx, symbol: str) -> list[dict]:
    from .indices import PRICE_WEIGHTED
    out = []
    for key, name in universe.UNIVERSES.items():
        members = [m["symbol"] for m in universe.members(key)]
        if symbol not in members:
            continue
        caps, prices = {}, {}
        for m in members:
            p = ctx.cache.peek(f"profile:v2:{m}", disk=True) or {}
            if "error" not in p:
                caps[m] = _f(p.get("market_cap")) or 0
                prices[m] = _f(p.get("price") or p.get("market_price")) or 0
        closes = ctx.cache.peek(f"idx:closes:{key}", disk=True) or {}
        for m, c in (closes.get("closes") or {}).items():          # fresher prices for the Dow from the index page cache
            if c:
                prices[m] = c[-1]
        est = weight_estimate(symbol, members, caps, prices, key in PRICE_WEIGHTED)
        rank = None
        if est["weight"] is not None:
            base = prices if key in PRICE_WEIGHTED else caps
            ranked = sorted((m for m in members if base.get(m)), key=lambda m: -base[m])
            rank = ranked.index(symbol) + 1 if symbol in ranked else None
        out.append({"index": name, "key": key, "symbol": universe.BENCHMARK.get(key), "rank": rank, **est})
    return out


async def structure(ctx, symbol: str) -> dict:
    """People + index memberships for the instrument page."""
    p = await people(ctx, symbol)
    return {**p, "indices": await memberships(ctx, symbol), "asof": time.time()}


# ------------------------------------------------------------------ change detection
def snapshot_of(p: dict, indices: list[dict]) -> dict:
    return {"board": sorted({b["name"] for b in p.get("board", []) if b.get("name")}),
            "officers": sorted({f"{o['name']} ({o.get('title') or ''})" for o in p.get("officers", []) if o.get("name")}),
            "indices": sorted(i["index"] for i in indices)}


def diff(old: dict, new: dict) -> list[str]:
    """Human-readable differences between two snapshots (pure, tested)."""
    out = []
    labels = {"board": "board", "officers": "executives", "indices": "index membership"}
    for key, label in labels.items():
        a, b = set(old.get(key, [])), set(new.get(key, []))
        if not a and key != "indices":
            continue                           # first time this list had data: nothing to compare
        added, removed = sorted(b - a), sorted(a - b)
        if added:
            out.append(f"{label}: new {', '.join(added)}")
        if removed:
            out.append(f"{label}: gone {', '.join(removed)}")
    return out


async def detect_changes(ctx, symbols: list[str]) -> list[dict]:
    from ..connectors.base import stable_id
    path = ctx.data_dir / SNAP_FILE
    try:
        snaps = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snaps = {}
    alerts = []
    for sym in symbols:
        try:
            p = await people(ctx, sym)
        except Exception:
            continue
        if "error" in p:
            continue
        new = snapshot_of(p, await memberships(ctx, sym))
        old = snaps.get(sym)
        snaps[sym] = {**new, "ts": time.time()}
        if not old:
            continue
        changes = diff(old, new)
        if changes:
            alert = {"id": stable_id("company", sym, *changes), "ts": time.time(), "kind": "company", "symbol": sym,
                     "title": f"{sym}: company change", "body": "; ".join(changes), "data": {"old": old, "new": new}}
            if await ctx.db.run(ctx.db.add_alert, alert):
                ctx.broker.publish("hub_warning", {"alert": alert})
                alerts.append(alert)
    from ..settings import _write_private
    _write_private(path, snaps)
    return alerts
