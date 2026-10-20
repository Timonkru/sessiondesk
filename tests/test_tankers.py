"""Tanker monitor: AIS message handling, chokepoint counting, subscription message, API without a key."""
from __future__ import annotations

import json

from sessiondesk.connectors.ais import subscription
from sessiondesk.features import tankers


def pos(mmsi, lat, lon, sog=10.0):
    return {"MessageType": "PositionReport", "MetaData": {"MMSI": mmsi, "ShipName": f"SHIP {mmsi} ", "latitude": lat, "longitude": lon},
            "Message": {"PositionReport": {"Sog": sog, "Latitude": lat, "Longitude": lon}}}


def static(mmsi, ship_type, dest="FUJAIRAH"):
    return {"MessageType": "ShipStaticData", "MetaData": {"MMSI": mmsi, "ShipName": f"SHIP {mmsi}"},
            "Message": {"ShipStaticData": {"Type": ship_type, "Destination": dest, "MaximumStaticDraught": 21.5, "ImoNumber": 9000000 + mmsi}}}


def test_subscription_message():
    m = json.loads(subscription("k", [[[1, 2], [3, 4]]]))
    assert m["APIKey"] == "k" and m["BoundingBoxes"] == [[[1, 2], [3, 4]]] and "ShipStaticData" in m["FilterMessageTypes"]


def test_counting_at_chokepoints():
    now = 1_790_000_000.0
    st = tankers.TankerState()
    assert tankers.box_of(26.5, 56.3) == "hormuz" and tankers.box_of(0, 0) is None
    st.handle(pos(1, 26.5, 56.3, sog=12), now)          # tanker, moving
    st.handle(static(1, 84), now)
    st.handle(pos(2, 26.4, 56.1, sog=0.2), now)          # tanker at anchor; static before the position
    st.handle(static(2, 80), now - 10)
    st.handle(pos(2, 26.4, 56.1, sog=0.2), now)
    st.handle(pos(3, 26.6, 56.5), now)                   # container ship
    st.handle(static(3, 70), now)
    st.handle(pos(4, 26.6, 56.6), now)                   # no static data yet
    st.handle(pos(5, 10.0, 10.0), now)                   # outside every box
    h = next(r for r in st.snapshot(now) if r["key"] == "hormuz")
    assert (h["vessels"], h["tankers"], h["moving"], h["slow"], h["type_unknown"], h["today"]) == (4, 2, 1, 1, 1, 2)
    assert h["ships"][0]["destination"] == "FUJAIRAH"
    later = next(r for r in st.snapshot(now + 7 * 3600) if r["key"] == "hormuz")
    assert later["tankers"] == 0                         # not seen for 7 h = gone
    copy = tankers.TankerState()
    copy.load(json.loads(json.dumps(st.dump())))
    assert copy.daily == st.daily


def test_tanker_api_without_key(client):
    d = client.get("/api/tankers").json()
    assert d["configured"] is False and len(d["chokepoints"]) == len(tankers.CHOKEPOINTS)
    assert all(c["tankers"] == 0 for c in d["chokepoints"])
