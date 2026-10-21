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


def test_link_only_posts_are_dropped():
    assert news.is_junk("https://t.co/9ig93SSoTr") and news.is_junk("  https://a.b/c  https://d.e ") and news.is_junk("")
    assert not news.is_junk("French PM: state of emergency possible https://t.co/x")
    kept = news.prepare([{"id": "1", "title": "https://t.co/abc"}, {"id": "2", "title": "ECB hikes by 25 bp"}], "squawk")
    assert [k["id"] for k in kept] == ["2"]


def test_market_wire_for_instrument_pages(tmp_path):
    from sessiondesk.features import assets, stocks
    assert assets.asset_of_yahoo("^GDAXI") == "DAX" and assets.asset_of_yahoo("EURUSD=X") == "EURUSD"
    assert assets.asset_of_yahoo("GC=F") == "GOLD" and assets.asset_of_yahoo("AAPL") is None
    ctx = SimpleNamespace(db=DB(tmp_path / "t.db"))
    now = time.time()
    ctx.db.add_news(news.prepare([{"id": "a", "title": "Lagarde: ECB stays data dependent", "source": "wire", "published": now},
                                  {"id": "b", "title": "Copper demand in Chile rises", "source": "wire", "published": now},
                                  {"id": "c", "title": "Bundesbank sees German economy stagnating", "source": "wire", "published": now - 72 * 3600}], "squawk"))
    out = asyncio.run(stocks.market_wire(ctx, "^GDAXI"))
    assert [w["id"] for w in out["wire"]] == ["a"] and out["wire_market"] == "DAX"   # c is older than 48 h
    assert asyncio.run(stocks.market_wire(ctx, "AAPL")) == {"wire": [], "wire_themes": []}


def test_market_filter_tags():
    assert "energy" in news.markets_of("Europe gas prices jump as LNG cargoes divert")
    assert "europe" in news.markets_of("Europe gas prices jump as LNG cargoes divert")
    assert news.markets_of("Corn futures slide after USDA raises crop estimate") == ["agri"]
    assert {"japan", "fx"} <= set(news.markets_of("Yen weakens as BOJ holds"))
    assert news.markets_of("Company picnic was nice") == []
    assert [m["key"] for m in news.market_list()][:2] == ["us", "europe"]


def test_news_api_market_filter(client):
    d = client.get("/api/news?market=agri").json()
    assert d["items"] == [] and any(m["key"] == "agri" for m in d["markets"])


def test_alpaca_stream_frames():
    from sessiondesk.features import newsstream
    news, control = newsstream.parse_alpaca('[{"T":"success","msg":"authenticated"},{"T":"n","id":24918784,"headline":"Fed holds",'
                                            '"created_at":"2026-10-21T13:00:02Z","symbols":["SPY"],"source":"benzinga"}]')
    assert [n["headline"] for n in news] == ["Fed holds"] and control[0]["msg"] == "authenticated"
    assert newsstream.parse_alpaca("not json") == ([], [])
    assert newsstream.parse_alpaca('{"T":"error","code":402,"msg":"auth failed"}')[1][0]["code"] == 402
