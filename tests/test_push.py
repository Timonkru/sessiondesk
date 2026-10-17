"""Phone push: event formatting, quiet hours, dedupe + hourly limit, ntfy/Telegram requests, no secret leaks."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import httpx

from sessiondesk import push
from sessiondesk.settings import Secrets, Settings

CFG = push.config(SimpleNamespace(get=lambda k, d=None: None))


def test_format_selected_events():
    news = {"kind": "news", "item": {"id": "n1", "title": "Fed hikes by 50 bp", "source": "wire", "impact": "high", "tags": ["central bank decision"]}}
    assert push.format_event(news, CFG)["title"] == "wire - central bank decision"
    held = {"kind": "news", "item": {"id": "n2", "title": "Lagarde speaks", "source": "wire", "impact": "medium", "held": ["DAX"]}}
    assert "touches your open DAX" in push.format_event(held, CFG)["title"]
    assert push.format_event({"kind": "news", "item": {"id": "n3", "title": "x", "impact": "medium"}}, CFG) is None
    ev = {"id": "e1", "currency": "USD", "title": "CPI", "forecast": "0.3%", "previous": "0.2%", "actual": "0.5%", "surprise": 0.2}
    assert push.format_event({"kind": "event_warning", "event": ev, "minutes": 30}, CFG) is None      # only 5 min by default
    assert push.format_event({"kind": "event_warning", "event": ev, "minutes": 5}, CFG)["title"] == "USD CPI in 5 min"
    assert "actual 0.5%" in push.format_event({"kind": "release", "event": ev}, CFG)["body"]
    no_stop = push.format_event({"kind": "position", "id": 7, "title": "123 opened DAX buy 1 - NO STOP", "position": {}}, CFG)
    assert no_stop["priority"] == 5
    assert push.format_event({"kind": "alert", "alert": {"id": "a", "title": "NVDA +5%"}}, CFG) is None   # off by default
    assert push.format_event({"kind": "job", "job": {"id": "j", "name": "x", "status": "ok"}}, CFG) is None


def test_quiet_hours_over_midnight():
    cfg = {**CFG, "quiet_from": "22:00", "quiet_to": "07:00"}
    assert push.in_quiet_hours(cfg, dt.datetime(2026, 10, 17, 23, 30))
    assert push.in_quiet_hours(cfg, dt.datetime(2026, 10, 17, 6, 59))
    assert not push.in_quiet_hours(cfg, dt.datetime(2026, 10, 17, 12, 0))
    assert not push.in_quiet_hours(CFG, dt.datetime(2026, 10, 17, 23, 30))


def _ctx(tmp_path, seen):
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    ctx = SimpleNamespace(settings=Settings(tmp_path), secrets=Secrets(tmp_path), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return ctx


def test_dedupe_limit_and_ntfy_request(tmp_path):
    seen = []
    ctx = _ctx(tmp_path, seen)
    ctx.settings.update({"push": {"enabled": True, "max_per_hour": 2}})
    ctx.secrets.set("push.ntfy_topic", "sd-secret-topic")
    pp = push.PhonePush(ctx)
    ev = {"kind": "release", "id": 1, "event": {"id": "e1", "currency": "USD", "title": "CPI", "actual": "0.5%"}}
    pp.on_event(ev)
    pp.on_event(ev)                                                   # duplicate: ignored
    pp.on_event({**ev, "event": {**ev["event"], "id": "e2"}})
    pp.on_event({**ev, "event": {**ev["event"], "id": "e3"}})         # over the hourly limit
    assert pp.queue.qsize() == 2 and pp.dropped == 1
    res = asyncio.run(pp.send(pp.queue.get_nowait()))
    assert res == {"ok": True}
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://ntfy.sh" and body["topic"] == "sd-secret-topic" and body["title"].startswith("Released")


def test_disabled_sends_nothing_and_telegram_shape(tmp_path):
    seen = []
    ctx = _ctx(tmp_path, seen)
    pp = push.PhonePush(ctx)
    pp.on_event({"kind": "release", "id": 1, "event": {"id": "e1"}})
    assert pp.queue.qsize() == 0                                      # off by default
    ctx.settings.update({"push": {"enabled": True, "service": "telegram", "telegram_chat": "4242"}})
    assert asyncio.run(pp.send({"title": "t"}))["ok"] is False        # no token yet
    ctx.secrets.set("push.telegram_token", "123:abc")
    assert asyncio.run(pp.send({"title": "Hello", "body": "world"}))["ok"] is True
    assert "/bot123:abc/sendMessage" in str(seen[-1].url) and json.loads(seen[-1].content)["chat_id"] == "4242"


def test_api_never_returns_push_secrets(client):
    r = client.post("/api/push", json={"config": {"enabled": True, "evil": 1}, "secrets": {"ntfy_topic": "sd-very-secret-topic-1234"}}).json()
    text = json.dumps(r)
    assert "sd-very-secret-topic" not in text and r["secrets"]["ntfy_topic"]["set"] is True
    assert r["config"]["enabled"] is True and "evil" not in r["config"]
    assert "sd-very-secret-topic" not in json.dumps(client.get("/api/settings").json())
