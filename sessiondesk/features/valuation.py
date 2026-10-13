"""Stock valuation: multiples with plausibility checks, peer medians, reverse DCF, scenario DCF.

Rule: the code computes every number; assumptions (discount rate, terminal growth, horizon) are
explicit inputs the user can change in the UI, and the page states what each result depends on.

Reverse DCF answers the honest question: "what free-cash-flow growth does today's price assume?"
instead of pretending to know a fair value. Two-stage model: FCF grows at g for N years, then at
the terminal rate forever (Gordon growth), discounted at r; enterprise value minus net debt = equity.
"""
from __future__ import annotations

import asyncio
import math
import statistics

from . import universe

DEFAULTS = {"discount": 0.09, "terminal": 0.025, "years": 10}

MULTIPLES = [  # key, label, plausible range, what it means
    ("pe_trailing", "P/E (trailing)", (1, 400), "Price / last 12 months' earnings per share"),
    ("pe_forward", "P/E (forward)", (1, 400), "Price / analysts' next-12-month EPS estimate"),
    ("peg", "PEG", (0.05, 20), "Forward P/E divided by expected EPS growth (vendor figure)"),
    ("ev_ebitda", "EV / EBITDA", (0.5, 300), "Enterprise value / EBITDA - capital-structure neutral"),
    ("ev_revenue", "EV / revenue", (0.05, 200), "Enterprise value / sales"),
    ("ps", "P / sales", (0.05, 200), "Market cap / trailing revenue"),
    ("pb", "P / book", (0.05, 200), "Market cap / book equity - meaningful for banks and insurers"),
]
QUALITY = [
    ("gross_margin", "Gross margin", True), ("operating_margin", "Operating margin", True), ("net_margin", "Net margin", True),
    ("roe", "Return on equity", True), ("revenue_growth", "Revenue growth (y/y)", True),
    ("earnings_growth", "Earnings growth (y/y)", True), ("debt_to_equity", "Debt / equity", False),
    ("dividend_yield", "Dividend yield", False), ("payout_ratio", "Payout ratio", True),
]


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ------------------------------------------------------------------ DCF math (pure, tested)
def dcf_per_share(fcf0: float, growth: float, *, discount: float, terminal: float, years: int,
                  net_debt: float, shares: float) -> float:
    if discount <= terminal:
        raise ValueError("discount rate must exceed terminal growth")
    if shares <= 0:
        raise ValueError("shares must be positive")
    pv, fcf = 0.0, fcf0
    for t in range(1, years + 1):
        fcf *= 1 + growth
        pv += fcf / (1 + discount) ** t
    terminal_value = fcf * (1 + terminal) / (discount - terminal)
    pv += terminal_value / (1 + discount) ** years
    return (pv - net_debt) / shares


def implied_growth(price: float, fcf0: float, *, discount: float, terminal: float, years: int,
                   net_debt: float, shares: float, lo: float = -0.5, hi: float = 1.5) -> float | None:
    """Growth rate g that makes dcf_per_share == price (bisection; value rises monotonically in g)."""
    if fcf0 <= 0 or price <= 0:
        return None
    def f(g):
        return dcf_per_share(fcf0, g, discount=discount, terminal=terminal, years=years, net_debt=net_debt, shares=shares) - price
    if f(lo) > 0:
        return lo          # even shrinking FCF justifies the price -> report the floor
    if f(hi) < 0:
        return None        # price needs more than the search range -> "not reachable"
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def sensitivity(price, fcf0, *, discount, terminal, years, net_debt, shares) -> list[dict]:
    rows = []
    for d in (discount - 0.01, discount, discount + 0.01):
        cells = []
        for t in (terminal - 0.005, terminal, terminal + 0.005):
            try:
                g = implied_growth(price, fcf0, discount=d, terminal=t, years=years, net_debt=net_debt, shares=shares)
            except ValueError:
                g = None
            cells.append({"terminal": t, "growth": g})
        rows.append({"discount": d, "cells": cells})
    return rows


# ------------------------------------------------------------------ multiples
def check_multiples(p: dict) -> list[dict]:
    out = []
    for key, label, (lo, hi), meaning in MULTIPLES:
        v = _f(p.get(key))
        flag = None
        if v is None:
            flag = "missing"
        elif v < 0:
            flag = "negative (loss-making) - not meaningful"
        elif not lo <= v <= hi:
            flag = "implausible vendor value - ignored"
        out.append({"key": key, "label": label, "value": v, "flag": flag, "meaning": meaning})
    # Cross-check: Yahoo sometimes ships an EPS in the wrong currency/unit (seen: 1,430 USD forward EPS).
    price, eps_f, pe_f = _f(p.get("price") or p.get("market_price")), _f(p.get("eps_forward")), _f(p.get("pe_forward"))
    if price and eps_f and pe_f and eps_f > 0:
        if abs(price / eps_f - pe_f) / pe_f > 0.25:
            for row in out:
                if row["key"] == "pe_forward" and not row["flag"]:
                    row["flag"] = "inconsistent with price / forward EPS - check source"
    return out


def quality(p: dict) -> list[dict]:
    out = []
    for key, label, is_ratio in QUALITY:
        v = _f(p.get(key))
        out.append({"key": key, "label": label, "value": v, "percent": is_ratio or key == "dividend_yield"})
    return out


def peer_medians(profiles: list[dict]) -> dict:
    out = {}
    for key, _label, (lo, hi), _m in MULTIPLES:
        vals = [v for v in (_f(p.get(key)) for p in profiles) if v is not None and lo <= v <= hi]
        out[key] = {"median": statistics.median(vals) if vals else None, "n": len(vals)}
    for key, _label, _r in QUALITY:
        vals = [v for v in (_f(p.get(key)) for p in profiles) if v is not None]
        out[key] = {"median": statistics.median(vals) if vals else None, "n": len(vals)}
    return out


# ------------------------------------------------------------------ assembly
def latest_fcf(p: dict) -> tuple[float | None, str]:
    hist = [h for h in (p.get("fcf_history") or []) if _f(h.get("fcf")) is not None]
    if hist:
        hist.sort(key=lambda h: h["year"])
        return _f(hist[-1]["fcf"]), f"free cash flow, fiscal {hist[-1]['year']} (cash-flow statement)"
    if _f(p.get("fcf_info")) is not None:
        return _f(p.get("fcf_info")), "free cash flow, trailing (vendor summary field)"
    return None, "no free-cash-flow figure available"


def build_valuation(p: dict, peer_profiles: list[dict], peer_symbols: list[str]) -> dict:
    price = _f(p.get("price") or p.get("market_price"))
    shares = _f(p.get("shares"))
    fcf, fcf_note = latest_fcf(p)
    debt, cash = _f(p.get("debt")) or 0.0, _f(p.get("cash")) or 0.0
    net_debt = debt - cash
    caveats = ["Yahoo fundamentals are unofficial and sometimes wrong; implausible values are flagged and ignored.",
               "Discount rate and terminal growth are assumptions, not data - change them and watch the result move."]
    reverse = None
    same_ccy = not p.get("financial_currency") or not p.get("currency") or p.get("financial_currency") == p.get("currency")
    if not same_ccy:
        caveats.append(f"Financials are in {p.get('financial_currency')}, the share trades in {p.get('currency')}: "
                       "reverse DCF skipped to avoid mixing currencies.")
    elif price and shares and fcf:
        if fcf <= 0:
            caveats.append("Free cash flow is negative: a cash-flow DCF says nothing here - look at revenue multiples instead.")
        else:
            g = implied_growth(price, fcf, net_debt=net_debt, shares=shares, **DEFAULTS)
            reverse = {"implied_growth": g, "grid": sensitivity(price, fcf, net_debt=net_debt, shares=shares, **DEFAULTS),
                       "fcf_yield": fcf / (price * shares)}
    ups = None
    if price and _f(p.get("target_mean")):
        ups = _f(p.get("target_mean")) / price - 1
    return {
        "symbol": p.get("symbol"), "currency": p.get("currency"), "financial_currency": p.get("financial_currency"),
        "inputs": {"price": price, "shares": shares, "fcf": fcf, "fcf_note": fcf_note, "debt": debt, "cash": cash,
                   "net_debt": net_debt, "fcf_history": p.get("fcf_history") or []},
        "defaults": DEFAULTS, "reverse_dcf": reverse,
        "multiples": check_multiples(p), "quality": quality(p),
        "peers": {"symbols": peer_symbols, "medians": peer_medians(peer_profiles) if peer_profiles else {}},
        "street": {"target_mean": _f(p.get("target_mean")), "target_high": _f(p.get("target_high")),
                   "target_low": _f(p.get("target_low")), "analysts": p.get("analysts"),
                   "recommendation": p.get("recommendation"), "upside_to_mean": ups},
        "caveats": caveats,
    }


async def profile(ctx, symbol: str) -> dict:
    async def build():
        res = await ctx.hub.first("profile", "profile", symbol)
        if "error" in res:
            return res
        return res["data"]
    return await ctx.cache.get(f"profile:{symbol}", 12 * 3600, build, disk=True)


async def valuation(ctx, symbol: str) -> dict:
    p = await profile(ctx, symbol)
    if "error" in p:
        return p
    peer_syms = universe.peers(symbol, 8)
    peer_profiles = []
    if peer_syms:
        res = await asyncio.gather(*(profile(ctx, s) for s in peer_syms))
        peer_profiles = [r for r in res if "error" not in r]
    out = build_valuation(p, peer_profiles, [r.get("symbol") for r in peer_profiles])
    extra = [c for c in ctx.hub.candidates("profile_extra") if c.id == "fmp"]
    if extra:
        async def build_fmp():
            return await extra[0].profile_extra(symbol)
        fmp = await ctx.cache.get(f"fmp:{symbol}", 12 * 3600, build_fmp, disk=True)
        if "vendor_dcf" in fmp:
            out["vendor_dcf"] = {**fmp["vendor_dcf"], "source": "Financial Modeling Prep"}
    return out
