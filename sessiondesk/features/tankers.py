"""Tanker monitor: tankers seen at oil chokepoints, from live AIS (aisstream.io, the user's free key).

Per chokepoint: tankers present now (seen in the last 6 hours), how many are moving vs. slow/at anchor (queues
show up as slow ships), and distinct tankers per day - written to the Data hub, so the early warnings flag an
unusual day like for any other series. A ship counts as a tanker once its static data (AIS type 80-89) arrived;
ships seen only by position stay "type unknown" until then.

Honest limits: shore-based receivers, so coverage of a strait far from land is partial; ships can switch AIS off;
counts are what was received, compared with the same box's own history - not the official traffic.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time

from ..connectors.ais import STREAM_URL, subscription

# name, [[lat, lon], [lat, lon]], what flows there
CHOKEPOINTS = [
    ("hormuz", "Strait of Hormuz", [[25.4, 55.6], [27.0, 57.4]], "Gulf crude and LNG out to Asia and Europe"),
    ("bab_el_mandeb", "Bab el-Mandeb", [[12.2, 42.9], [13.2, 43.7]], "Red Sea route to Suez"),
    ("suez", "Suez Canal / Gulf of Suez", [[29.7, 32.2], [31.4, 32.7]], "Europe <-> Asia, SUMED pipeline area"),
    ("bosporus", "Bosporus", [[40.95, 28.9], [41.3, 29.2]], "Black Sea crude (CPC, Russian ports)"),
    ("danish_straits", "Danish straits (Great Belt / Skaw)", [[54.8, 10.5], [57.9, 11.2]], "Baltic exports incl. Russian crude"),
    ("gulf_of_finland", "Gulf of Finland (Primorsk / Ust-Luga)", [[59.4, 27.5], [60.6, 29.2]], "Russian Baltic oil ports"),
    ("singapore", "Singapore Strait", [[1.0, 103.4], [1.5, 104.4]], "Middle East -> East Asia"),
    ("cape", "Cape of Good Hope", [[-35.6, 17.4], [-33.6, 20.6]], "rerouted Red Sea traffic"),
    ("panama", "Panama Canal approaches", [[8.7, -80.1], [9.5, -79.4]], "US Gulf <-> Asia/West Coast"),
]
PRESENT_H = 6
SLOW_KN = 1.0


def is_tanker(ship_type) -> bool:
    try:
        return 80 <= int(ship_type) <= 89
    except (TypeError, ValueError):
        return False


def box_of(lat: float, lon: float) -> str | None:
    for key, _, ((a, b), (c, d)), _ in CHOKEPOINTS:
        if min(a, c) <= lat <= max(a, c) and min(b, d) <= lon <= max(b, d):
            return key
    return None


class TankerState:
    """Everything received, kept in memory; pure enough to test with fake messages."""

    def __init__(self):
        self.ships: dict[int, dict] = {}                         # mmsi -> last position, box, type, name, ...
        self.daily: dict[str, dict[str, set]] = {}               # day -> box -> mmsi set (tankers only)
        self.received = 0
        self.last_message = 0.0

    def handle(self, msg: dict, now: float | None = None) -> None:
        now = now or time.time()
        meta = msg.get("MetaData") or {}
        mmsi = meta.get("MMSI")
        if not mmsi:
            return
        self.received += 1
        self.last_message = now
        s = self.ships.setdefault(mmsi, {"mmsi": mmsi})
        kind = msg.get("MessageType")
        body = (msg.get("Message") or {}).get(kind) or {}
        if meta.get("ShipName"):
            s["name"] = meta["ShipName"].strip()
        if kind == "ShipStaticData":
            s["type"] = body.get("Type")
            s["destination"] = (body.get("Destination") or "").strip() or None
            s["draught"] = body.get("MaximumStaticDraught")
            s["imo"] = body.get("ImoNumber")
        else:
            lat, lon = meta.get("latitude", body.get("Latitude")), meta.get("longitude", body.get("Longitude"))
            if lat is None or lon is None:
                return
            box = box_of(lat, lon)
            if not box:
                return
            s.update({"lat": lat, "lon": lon, "sog": body.get("Sog"), "box": box, "seen": now})
        if is_tanker(s.get("type")) and s.get("box") and now - s.get("seen", 0) < PRESENT_H * 3600:
            day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
            self.daily.setdefault(day, {}).setdefault(s["box"], set()).add(mmsi)

    def snapshot(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
        out = []
        for key, name, box, flow in CHOKEPOINTS:
            here = [s for s in self.ships.values() if s.get("box") == key and now - s.get("seen", 0) < PRESENT_H * 3600]
            tankers = [s for s in here if is_tanker(s.get("type"))]
            slow = [s for s in tankers if (s.get("sog") or 0) < SLOW_KN]
            out.append({"key": key, "name": name, "flow": flow, "box": box, "vessels": len(here),
                        "type_unknown": sum(1 for s in here if s.get("type") is None),
                        "tankers": len(tankers), "moving": len(tankers) - len(slow), "slow": len(slow),
                        "today": len(self.daily.get(day, {}).get(key, ())),
                        "ships": sorted(({k: s.get(k) for k in ("mmsi", "name", "sog", "destination", "draught", "imo")} for s in tankers),
                                        key=lambda x: x.get("name") or "")[:60]})
        return out

    def dump(self) -> dict:
        return {"daily": {d: {b: sorted(m) for b, m in v.items()} for d, v in self.daily.items()}}

    def load(self, data: dict, keep_days: int = 3) -> None:
        days = sorted((data or {}).get("daily", {}))[-keep_days:]
        for d in days:
            for b, ms in data["daily"][d].items():
                self.daily.setdefault(d, {}).setdefault(b, set()).update(ms)


def _state(ctx) -> TankerState:
    st = ctx.extras.get("tankers")
    if st is None:
        st = ctx.extras["tankers"] = TankerState()
        try:
            st.load(json.loads((ctx.data_dir / "ais_daily.json").read_text(encoding="utf-8")))
        except Exception:                            # first run or unreadable file: start empty
            pass
    return st


async def flush(ctx) -> None:
    """Distinct tankers per chokepoint and day -> Data hub series (early warnings apply); state file for restarts."""
    st = _state(ctx)
    for day, boxes in st.daily.items():
        for key, name, _, _ in CHOKEPOINTS:
            await ctx.db.run(ctx.db.upsert_series, {"id": f"ais:{key}", "name": f"Tankers seen per day: {name}",
                                                    "category": "Tanker traffic (AIS)", "kind": "count",
                                                    "source": "aisstream.io (shore-based AIS; coverage varies)"},
                             [(day, float(len(boxes.get(key, ()))))])
    for d in sorted(st.daily)[:-3]:
        st.daily.pop(d, None)
    try:
        (ctx.data_dir / "ais_daily.json").write_text(json.dumps(st.dump()), encoding="utf-8")
    except Exception:
        pass


async def run(ctx) -> None:
    """Background loop: idle until a key is set, then keep one websocket open, reconnecting with backoff."""
    import websockets
    st = _state(ctx)
    backoff = 30
    while True:
        conn = ctx.hub.get("aisstream") if ctx.hub else None
        if not conn or not conn.active():
            await asyncio.sleep(60)
            continue
        try:
            async with websockets.connect(STREAM_URL, open_timeout=20, ping_interval=30) as ws:
                await ws.send(subscription(conn.secret("api_key"), [box for _, _, box, _ in CHOKEPOINTS]))
                ctx.extras["tankers_error"] = None
                backoff = 30
                last_flush = time.time()
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    st.handle(msg)
                    if time.time() - last_flush > 600:
                        await flush(ctx)
                        last_flush = time.time()
                    if not conn.active():                # key removed or connector switched off
                        break
        except asyncio.CancelledError:
            await flush(ctx)
            raise
        except Exception as e:
            ctx.extras["tankers_error"] = str(e)[:200]
            await flush(ctx)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 600)


async def view(ctx) -> dict:
    conn = ctx.hub.get("aisstream") if ctx.hub else None
    st = _state(ctx)
    week = {}
    for key, *_ in CHOKEPOINTS:
        pts = await ctx.db.run(ctx.db.observations, f"ais:{key}", 8)
        past = [v for d, v in pts if d < dt.date.today().isoformat()]
        week[key] = sum(past[-7:]) / len(past[-7:]) if past else None
    rows = st.snapshot()
    for r in rows:
        r["avg7"] = week.get(r["key"])
    return {"configured": bool(conn and conn.configured()), "active": bool(conn and conn.active()),
            "connected_recently": time.time() - st.last_message < 300, "received": st.received,
            "error": ctx.extras.get("tankers_error"), "chokepoints": rows,
            "note": "Live AIS via aisstream.io. Tankers = AIS ship type 80-89, known once a ship's static data arrived "
                    "(sent every few minutes). 'Slow' = under 1 knot: anchored, waiting or loading. Shore-based receivers: "
                    "coverage far from land is partial and ships can switch AIS off - compare a chokepoint with its own "
                    "history, not with official transit statistics."}
