"""Real-time news over websockets: Alpaca's Benzinga stream (free with an Alpaca account, paper is enough).

The REST poll of the same feed runs every two minutes; the stream delivers a headline within seconds of
publication. Both use the same ids, so a headline seen by both is stored once. Idle until keys are set;
reconnects with backoff. Read-only: the stream carries news only.
"""
from __future__ import annotations

import asyncio
import json
import time

ALPACA_NEWS_WS = "wss://stream.data.alpaca.markets/v1beta1/news"


def parse_alpaca(raw: str | bytes) -> tuple[list[dict], list[dict]]:
    """One websocket frame -> (news messages, control messages: success / subscription / error) (pure, tested)."""
    try:
        msgs = json.loads(raw)
    except ValueError:
        return [], []
    if isinstance(msgs, dict):
        msgs = [msgs]
    news = [m for m in msgs if isinstance(m, dict) and m.get("T") == "n"]
    control = [m for m in msgs if isinstance(m, dict) and m.get("T") in ("success", "subscription", "error")]
    return news, control


async def run_alpaca(ctx) -> None:
    import websockets
    from . import news as news_mod
    state = ctx.extras.setdefault("newsstream", {"alpaca": {"status": "idle", "received": 0, "last": None, "error": None}})["alpaca"]
    backoff = 30
    while True:
        conn = ctx.hub.get("alpaca") if ctx.hub else None
        if not conn or not conn.active():
            state["status"] = "idle (no keys)"
            await asyncio.sleep(60)
            continue
        try:
            async with websockets.connect(ALPACA_NEWS_WS, open_timeout=20, ping_interval=30) as ws:
                state["status"] = "connecting"
                await ws.send(json.dumps({"action": "auth", "key": conn.secret("key_id"), "secret": conn.secret("secret_key")}))
                await ws.send(json.dumps({"action": "subscribe", "news": ["*"]}))
                backoff = 30
                async for raw in ws:
                    items, control = parse_alpaca(raw)
                    for c in control:
                        if c.get("T") == "error":
                            raise RuntimeError(f"Alpaca stream: {c.get('code')} {c.get('msg')}")
                        if c.get("T") == "subscription":
                            state.update(status="live", error=None)
                    if items:
                        state["received"] += len(items)
                        state["last"] = time.time()
                        await news_mod.ingest(ctx, conn._news(items), "markets", push=True)
                    if not conn.active():
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state.update(status="reconnecting", error=str(e)[:200])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 600)
