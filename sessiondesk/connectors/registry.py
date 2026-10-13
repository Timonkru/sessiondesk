"""Connector registry. Add a new connector: write the class, append it to ALL, add a test."""
from __future__ import annotations

from ..ai.providers import PROVIDERS
from .base import Ctx, Hub, PlannedConnector
from .keyed import FMP, AlphaVantage, Alpaca, Finnhub, Polygon, TradingEconomics
from .mt5 import MT5Bridge
from .public import Cftc, FFCalendar, Fred, NasdaqEarnings, Sec
from .rss import Rss
from .yahoo import Yahoo

ALL = (Yahoo, Rss, FFCalendar, Fred, Cftc, Sec, NasdaqEarnings, MT5Bridge,
       Finnhub, FMP, Polygon, AlphaVantage, TradingEconomics, Alpaca) + PROVIDERS

PLANNED = [
    PlannedConnector("databento", "Databento", "paid", "data", ("history", "quotes"), "https://databento.com",
                     "Exchange-grade futures and equities data (CME, Eurex, Nasdaq TotalView): tick, depth, true futures volume."),
    PlannedConnector("ibkr", "Interactive Brokers (read-only)", "free-key", "broker", ("account", "positions", "quotes"),
                     "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/",
                     "Client Portal Web API: positions, account, market data. Read-only, like every broker connector here."),
    PlannedConnector("ctrader", "cTrader Open API (read-only)", "free-key", "broker", ("account", "positions"),
                     "https://help.ctrader.com/open-api/", "Account and positions from cTrader brokers."),
    PlannedConnector("ninjatrader", "NinjaTrader bridge (read-only)", "free", "broker", ("account", "positions", "eas"),
                     "https://ninjatrader.com", "File bridge like the MT5 one: accounts, positions, running strategies."),
    PlannedConnector("benzinga", "Benzinga Pro squawk", "paid", "news", ("news",), "https://www.benzinga.com/apis/",
                     "Low-latency newswire and audio squawk transcripts."),
    PlannedConnector("telegram", "Telegram channels", "free-key", "news", ("news",), "https://my.telegram.org",
                     "Read public squawk channels with your own Telegram API id/hash."),
    PlannedConnector("tiingo", "Tiingo", "free-key", "data", ("history", "news"), "https://www.tiingo.com",
                     "Clean end-of-day history and a curated news feed."),
    PlannedConnector("eodhd", "EODHD", "paid", "data", ("history", "profile", "calendar"), "https://eodhd.com",
                     "Global end-of-day data incl. European listings, fundamentals and calendars."),
]


def build_hub(ctx: Ctx) -> Hub:
    hub = Hub(ctx, [cls(ctx) for cls in ALL], PLANNED)
    ctx.hub = hub
    return hub
