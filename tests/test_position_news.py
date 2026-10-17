"""Headlines that touch open positions: market/theme mapping, ticker matching, push of medium-impact matches."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from sessiondesk.db import DB
from sessiondesk.events import Broker
from sessiondesk.features import news


def test_held_map_markets_fx_and_single_stocks():
    held = news.held_map([{"symbol": "GER40.cash"}, {"symbol": "XAUUSD"}, {"symbol": "EURUSD"}, {"symbol": "NVDA.US"}])
    assert set(held) == {"DAX", "GOLD", "EURUSD", "NVDA"}
    assert "ecb" in held["DAX"] and "fed" in held["GOLD"] and {"ecb", "fed"} <= held["EURUSD"]
    assert held["NVDA"] == set()                                   # single stocks: ticker match only


def test_match_held_by_theme_and_ticker():
    held = news.held_map([{"symbol": "GER40.cash"}, {"symbol": "NVDA.US"}])
    assert news.match_held({"title": "ECB's Lagarde: inflation risks are balanced"}, held) == ["DAX"]
    assert news.match_held({"title": "Chipmaker beats", "symbols": ["NVDA"]}, held) == ["NVDA"]
    # a generic market word alone does not tie a headline to the position
    assert news.match_held({"title": "Stocks tumble in late trade"}, held) == []
    assert news.match_held({"title": "Bank of Japan keeps policy unchanged"}, held) == []
    # broad themes count for the list, not for pushes
    ukraine = {"title": "Talks on Ukraine resume in Geneva"}
    assert news.match_held(ukraine, held) == ["DAX"] and news.match_held(ukraine, held, strict=True) == []


def test_ingest_pushes_medium_headline_on_open_position(tmp_path, monkeypatch):
    ctx = SimpleNamespace(db=DB(tmp_path / "t.db"), broker=Broker())
    seen = []
    ctx.broker.listen(seen.append)

    async def fake_held(_ctx):
        return news.held_map([{"symbol": "GER40.cash"}])
    monkeypatch.setattr(news, "held", fake_held)
    now = time.time()
    items = [{"id": "a", "title": "Lagarde says the ECB will watch the euro closely", "source": "wire", "published": now},
             {"id": "b", "title": "Apple beats revenue estimates", "source": "wire", "published": now},
             {"id": "c", "title": "Ifo business climate improves", "source": "wire", "published": now - 8 * 3600}]
    pushed = asyncio.run(news.ingest(ctx, items, "markets", push=True))
    assert [p["id"] for p in pushed] == ["a"]                      # medium + touches DAX; b touches nothing; c is old
    assert seen[0]["kind"] == "news" and seen[0]["item"]["held"] == ["DAX"]
