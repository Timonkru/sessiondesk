"""Canonical assets: broker symbol <-> market <-> free data ticker, and headline themes per market.

Broker CFD names differ per broker (GER40, DE40, GER40.cash ...). Everything that combines broker data
with market data (levels, book risk, event reactions, news per position) goes through asset_of().
Users can add or override patterns in settings["asset_patterns"] = {"ASSET": ["SUBSTRING", ...]}.
"""
from __future__ import annotations

import re

SYMBOL_PATTERNS = [            # order matters: first match wins
    ("DAX", ["GER40", "GER30", "DE40", "DE30", "DAX"]), ("FTSE", ["UK100", "FTSE"]), ("CAC", ["FRA40", "CAC"]),
    ("STOXX", ["EUSTX", "EU50", "STOXX"]), ("SMI", ["SWI20", "SMI"]), ("RUSSELL", ["US2000", "RUSSELL", "RUT"]),
    ("DOW", ["US30", "DJ30", "DOW", "WS30"]), ("NQ", ["US100", "NAS100", "USTEC", "NDX", "NAS"]),
    ("SPX", ["US500", "SP500", "SPX"]), ("NIKKEI", ["JP225", "JPN225", "NIKKEI", "NI225"]), ("HK50", ["HK50", "HSI"]),
    ("AUS200", ["AUS200", "ASX"]), ("GOLD", ["XAU", "GOLD"]), ("SILVER", ["XAG", "SILVER"]),
    ("OIL", ["USOIL", "UKOIL", "WTI", "BRENT", "XTI", "XBR", "OIL"]), ("BTC", ["BTC"]), ("ETH", ["ETH"]),
]
YAHOO = {"DAX": "^GDAXI", "FTSE": "^FTSE", "CAC": "^FCHI", "STOXX": "^STOXX50E", "SMI": "^SSMI", "NQ": "NQ=F",
         "DOW": "YM=F", "SPX": "ES=F", "RUSSELL": "RTY=F", "NIKKEI": "NKD=F", "HK50": "^HSI", "AUS200": "^AXJO",
         "GOLD": "GC=F", "SILVER": "SI=F", "OIL": "CL=F", "BTC": "BTC-USD", "ETH": "ETH-USD"}
FX = ("USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD")
DEFAULT_ROUND_STEPS = {"DAX": 1000, "NQ": 1000, "DOW": 1000, "SPX": 100, "FTSE": 500, "RUSSELL": 100, "NIKKEI": 1000,
                       "HK50": 1000, "GOLD": 100, "SILVER": 5, "OIL": 10, "BTC": 5000, "ETH": 500, "FX": 0.01}


def patterns(settings=None) -> list[tuple[str, list[str]]]:
    extra = (settings.get("asset_patterns") if settings else None) or {}
    return [(a, [p.upper() for p in pats]) for a, pats in extra.items()] + SYMBOL_PATTERNS


def asset_of(symbol: str, settings=None) -> str | None:
    """'GER40.cash' -> 'DAX', 'EURUSD' -> 'EURUSD', unknown -> None."""
    s = (symbol or "").upper()
    for asset, pats in patterns(settings):
        if any(p in s for p in pats):
            return asset
    core = re.sub(r"[^A-Z]", "", s)[:6]
    if len(core) == 6 and core[:3] in FX and core[3:] in FX:
        return core
    return None


def yahoo_ticker(asset: str | None) -> str | None:
    if not asset:
        return None
    if asset in YAHOO:
        return YAHOO[asset]
    if len(asset) == 6 and asset[:3] in FX and asset[3:] in FX:
        return f"{asset}=X"
    return None


def round_step(asset: str, settings=None) -> float:
    steps = {**DEFAULT_ROUND_STEPS, **((settings.get("round_steps") if settings else None) or {})}
    if asset in steps:
        return float(steps[asset])
    if len(asset) == 6 and asset[:3] in FX:
        step = float(steps.get("FX", 0.01))
        return step * 100 if asset.endswith("JPY") and step < 1 else step     # 0.01 big figure -> 1.00 for yen pairs
    return 0.0


# ------------------------------------------------------------------ headline themes per market
THEMES = {
    "fed": r"\bfed\b|federal reserve|fomc|powell|\bwaller\b|fed chair",
    "ecb": r"\becb\b|\bezb\b|lagarde|european central bank",
    "boe": r"\bboe\b|bank of england|bailey",
    "boj": r"\bboj\b|bank of japan|\bueda\b",
    "snb": r"\bsnb\b|swiss national bank",
    "pboc": r"\bpboc\b|people's bank of china",
    "us_macro": r"\bcpi\b|payrolls|jobs report|jobless claims|\bpce\b|us inflation|u\.s\. inflation|\bism\b|retail sales|us gdp|"
                r"u\.s\. gdp|us economy|u\.s\. economy|consumer confidence",
    "eu_macro": r"euro ?zone|eurozone|euro area|\bifo\b|\bzew\b|german (economy|inflation|gdp|industr|exports)|bundesbank",
    "uk_macro": r"uk (inflation|gdp|economy|budget)|british economy|\bgilts?\b|sterling",
    "japan": r"\byen\b|nikkei|\bjgbs?\b|japan(ese)?('s)? (economy|inflation|stocks|shares|bonds?|yields?|exports|gdp|government)",
    "china": r"(china|chinese|beijing)('s)? .{0,40}(economy|stimulus|exports?|property|gdp|pmi|stocks|tariffs?|trade)|hang seng|\byuan\b",
    "yields": r"treasury yield|treasuries|bond (yields?|sell-?off|rout|market)|10-year",
    "usd": r"us dollar|u\.s\. dollar|\bdxy\b|greenback|dollar index",
    "tariffs": r"tariff|trade war|trade deal|export controls?|sanctions?",
    "geopolitics": r"\biran|israel|ukraine|russia|\bnato\b|taiwan|north korea|strait of hormuz|red sea|houthi",
    "oil": r"\boil\b|crude|\bopec|brent|\bwti\b",
    "gold": r"\bgold\b|bullion",
    "crypto": r"bitcoin|\bbtc\b|ethereum|\bcrypto",
    "tech": r"nvidia|big tech|tech (stocks|shares|sell-?off|rally)|semiconductor|chipmakers?|nasdaq|\bai (boom|bubble|stocks|spending|capex)",
    "us_stocks": r"wall street|s&p 500|\bdow\b|dow jones|us stocks|u\.s\. stocks|stock futures",
    "eu_stocks": r"\bdax\b|european (stocks|shares|markets)|stoxx|\bftse\b(?! russell)|\bcac 40\b",
    "risk": r"sell-?off|plunge|crash|\brout\b|tumble|slump|panic|circuit breaker|turmoil|record high|all-time high",
}
_THEMES = {k: re.compile(v, re.IGNORECASE) for k, v in THEMES.items()}
_US = ["fed", "us_macro", "yields", "tariffs", "geopolitics", "risk", "us_stocks"]
_EU = ["ecb", "eu_macro", "fed", "us_macro", "tariffs", "geopolitics", "risk", "eu_stocks"]
ASSET_THEMES = {
    "DAX": _EU, "CAC": _EU, "STOXX": _EU, "SMI": _EU + ["snb"], "FTSE": ["boe", "uk_macro", "fed", "us_macro", "tariffs", "geopolitics", "risk", "eu_stocks"],
    "DOW": _US, "SPX": _US + ["tech"], "NQ": _US + ["tech"], "RUSSELL": _US, "NIKKEI": ["boj", "japan", "fed", "tariffs", "risk", "tech"],
    "HK50": ["china", "pboc", "tariffs", "risk", "tech"], "AUS200": ["china", "risk", "fed"],
    "GOLD": ["gold", "fed", "yields", "usd", "us_macro", "geopolitics"], "SILVER": ["gold", "fed", "yields", "usd"],
    "OIL": ["oil", "geopolitics", "china", "tariffs"], "BTC": ["crypto", "fed", "risk"], "ETH": ["crypto", "fed", "risk"],
}
CCY_THEMES = {"USD": ["fed", "us_macro", "yields", "usd"], "EUR": ["ecb", "eu_macro"], "JPY": ["boj", "japan"],
              "GBP": ["boe", "uk_macro"], "CHF": ["snb", "geopolitics"], "AUD": ["china", "risk"], "CAD": ["oil"], "NZD": ["china", "risk"]}


def themes_of(title: str) -> set[str]:
    return {name for name, rx in _THEMES.items() if rx.search(title or "")}


def themes_for_asset(asset: str) -> set[str]:
    if asset in ASSET_THEMES:
        return set(ASSET_THEMES[asset])
    if len(asset) == 6 and asset[:3] in FX:
        return set(CCY_THEMES.get(asset[:3], [])) | set(CCY_THEMES.get(asset[3:], []))
    return set()
