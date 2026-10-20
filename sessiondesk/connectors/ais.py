"""aisstream.io: live AIS ship positions over a websocket (free key). Used for the tanker monitor at chokepoints.

AIS reaches aisstream through shore-based receivers run by volunteers: coverage is good near busy coasts and ports,
thin or absent in the middle of a strait far from land, and ships can switch AIS off ("dark fleet"). Counts
describe what was received, not every ship that passed.
"""
from __future__ import annotations

import asyncio
import json

from .base import Connector, ConnectorError, Field

STREAM_URL = "wss://stream.aisstream.io/v0/stream"
MESSAGE_TYPES = ["PositionReport", "ShipStaticData", "StandardClassBPositionReport"]


def subscription(key: str, boxes: list[list[list[float]]]) -> str:
    """The first message after connecting: key, bounding boxes [[lat, lon], [lat, lon]] and message types (pure, tested)."""
    return json.dumps({"APIKey": key, "BoundingBoxes": boxes, "FilterMessageTypes": MESSAGE_TYPES})


class AisStream(Connector):
    id = "aisstream"
    name = "aisstream.io (AIS ship positions)"
    tier = "free-key"
    kind = "data"
    capabilities = ("series",)
    fields = (Field("api_key", "API key", help="aisstream.io -> sign in -> API Keys. Free. Used only for the websocket to aisstream."),)
    homepage = "https://aisstream.io"
    description = ("Live AIS positions of ships. SessionDesk counts tankers at oil chokepoints (Hormuz, Bab el-Mandeb, Suez, "
                   "Bosporus, Danish straits, Gulf of Finland, Singapore, Cape, Panama). Shore-based coverage: thin far "
                   "from land, ships can switch AIS off.")
    verified = True                   # live run with a real key on 2026-10-20
    default_enabled = True

    async def test(self) -> dict:
        import websockets
        key = self.secret("api_key")
        if not key:
            return {"ok": False, "detail": "no key"}
        try:
            async with websockets.connect(STREAM_URL, open_timeout=15) as ws:
                await ws.send(subscription(key, [[[1.0, 103.4], [1.5, 104.4]]]))      # Singapore Strait: always busy
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
        except asyncio.TimeoutError:
            return {"ok": False, "detail": "connected, but no message within 20 s"}
        except Exception as e:                       # bad key: the server closes the socket with a reason
            raise ConnectorError(f"aisstream: {e}") from e
        msg = json.loads(raw)
        if "error" in msg:
            return {"ok": False, "detail": str(msg["error"])}
        return {"ok": True, "detail": f"first message: {msg.get('MessageType')} from {msg.get('MetaData', {}).get('ShipName', '?').strip()}"}
