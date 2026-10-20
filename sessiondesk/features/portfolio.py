"""Portfolio view (PORT): what the open book is exposed to, per account.

Exposure of a position = money per 1 % move x 100 (the notional in the account's currency, signed by side), as the
broker export reports it. Per account: gross and net exposure as % of equity (gross = leverage), by asset class,
region, currency (an FX pair counts on both legs: long EURUSD = +EUR, -USD) and sector (single stocks), the largest
positions, and the risk to the stops. Accounts are never added together - they can hold different currencies.
Correlation and scenarios come from the book-risk module (risk.book).
"""
from __future__ import annotations

from collections import defaultdict

from . import assets

INDEX_INFO = {   # asset -> (region, currency)
    "DAX": ("Europe", "EUR"), "CAC": ("Europe", "EUR"), "STOXX": ("Europe", "EUR"), "FTSE": ("Europe", "GBP"), "SMI": ("Europe", "CHF"),
    "SPX": ("United States", "USD"), "NQ": ("United States", "USD"), "DOW": ("United States", "USD"), "RUSSELL": ("United States", "USD"),
    "NIKKEI": ("Asia-Pacific", "JPY"), "HK50": ("Asia-Pacific", "HKD"), "AUS200": ("Asia-Pacific", "AUD"),
}
COMMODITIES = {"GOLD", "SILVER", "OIL"}
CRYPTO = {"BTC", "ETH"}
SUFFIX = {"US": ("United States", "USD"), "DE": ("Europe", "EUR"), "PA": ("Europe", "EUR"), "AS": ("Europe", "EUR"), "MI": ("Europe", "EUR"),
          "MC": ("Europe", "EUR"), "L": ("Europe", "GBP"), "UK": ("Europe", "GBP"), "SW": ("Europe", "CHF"), "T": ("Asia-Pacific", "JPY"),
          "HK": ("Asia-Pacific", "HKD"), "AX": ("Asia-Pacific", "AUD"), "TO": ("Americas", "CAD")}


def classify(symbol: str, settings=None) -> dict:
    """Asset class, region, currency legs and (for stocks) sector of a broker symbol (pure, tested)."""
    asset = assets.asset_of(symbol, settings)
    if asset in INDEX_INFO:
        region, ccy = INDEX_INFO[asset]
        return {"asset": asset, "cls": "Index", "region": region, "legs": {ccy: 1.0}, "sector": None}
    if asset in COMMODITIES:
        return {"asset": asset, "cls": "Commodity", "region": "Global", "legs": {"USD": 1.0}, "sector": None}
    if asset in CRYPTO:
        return {"asset": asset, "cls": "Crypto", "region": "Global", "legs": {"USD": 1.0}, "sector": None}
    if asset and len(asset) == 6:
        return {"asset": asset, "cls": "FX", "region": "FX", "legs": {asset[:3]: 1.0, asset[3:]: -1.0}, "sector": None}
    s = (symbol or "").upper()
    base, _, suf = s.partition(".")
    region, ccy = SUFFIX.get(suf.split(".")[0] if suf else "US", ("Other", "?"))
    sector = None
    try:
        from . import universe
        from .sectors import canonical_sector
        from .stocklist import GROUP_LABELS
        m = universe.lookup(base if suf in ("US", "") else s) or universe.lookup(base)
        if m:
            sector = GROUP_LABELS.get(canonical_sector(m.get("sector"), m.get("industry")) or "", None)
    except Exception:
        sector = None
    return {"asset": base or s, "cls": "Stock", "region": region, "legs": {ccy: 1.0}, "sector": sector or "Unknown sector"}


def exposures(positions: list[dict], accounts: list[dict], settings=None) -> list[dict]:
    """Per account: exposure tables in % of equity (pure, tested)."""
    out = []
    by_acct: dict = defaultdict(list)
    for p in positions:
        by_acct[p.get("account")].append(p)
    info = {a.get("login"): a for a in accounts}
    for acct in sorted(by_acct, key=str):
        a = info.get(acct, {})
        eq = a.get("equity") or None
        pct = (lambda v: v / eq * 100 if eq else None)
        cls, region, ccy, sector = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
        gross = net = 0.0
        rows, missing = [], 0
        for p in by_acct[acct]:
            mpp = p.get("money_per_pct")
            if mpp is None:
                missing += 1
                continue
            sign = 1 if p.get("side") == "LONG" else -1
            notional = sign * abs(mpp) * 100
            c = classify(p.get("symbol", ""), settings)
            gross += abs(notional)
            net += notional
            cls[c["cls"]] += notional
            region[c["region"]] += notional
            for leg, w in c["legs"].items():
                ccy[leg] += notional * w
            if c["sector"]:
                sector[c["sector"]] += notional
            rows.append({"symbol": p.get("symbol"), "side": p.get("side"), "class": c["cls"], "notional": notional, "pct": pct(notional),
                         "risk_to_stop": p.get("risk_to_stop")})

        def table(d):
            return sorted(({"name": k, "net": v, "pct": pct(v)} for k, v in d.items() if abs(v) > 1e-9), key=lambda x: -abs(x["net"]))
        risk = sum(p.get("risk_to_stop") or 0 for p in by_acct[acct])
        out.append({"account": acct, "currency": a.get("currency"), "equity": eq, "positions": len(by_acct[acct]),
                    "gross": gross, "net": net, "gross_pct": pct(gross), "net_pct": pct(net),
                    "risk_to_stops": risk or None, "risk_pct": pct(risk) if risk else None,
                    "without_stop": sum(1 for p in by_acct[acct] if not p.get("sl")),
                    "by_class": table(cls), "by_region": table(region), "by_currency": table(ccy), "by_sector": table(sector),
                    "largest": sorted(rows, key=lambda r: -abs(r["notional"]))[:8], "missing_notional": missing})
    return out


async def view(ctx) -> dict:
    from . import broker, risk
    b = await broker.overview(ctx)
    if not b.get("connected", True) and not b.get("accounts"):
        return {"connected": False, "accounts": [], "note": b.get("note")}
    positions = [p for p in b.get("positions", []) if p.get("fresh", True)]
    accounts = b.get("accounts", [])
    book = await risk.book(ctx, positions, accounts) if positions else {"matrix": [], "scenarios": []}
    return {"connected": True, "accounts": exposures(positions, accounts, ctx.settings),
            "all_accounts": [{"account": a.get("login"), "equity": a.get("equity"), "currency": a.get("currency")} for a in accounts],
            "matrix": book.get("matrix", []), "scenarios": book.get("scenarios", []), "drivers": book.get("drivers", []),
            "note": "Exposure = the broker's money per 1 % move x 100, signed by side, in % of the account's equity (gross = "
                    "leverage). FX pairs count on both currency legs. Accounts are never added together. Correlation from "
                    "about 30 days of hourly returns; scenarios are sensitivities with stops ignored, not forecasts."}
