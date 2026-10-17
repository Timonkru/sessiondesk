"""Phone push: forwards selected events to your phone - via ntfy (free app for iOS/Android, ntfy.sh or your
own server) or your own Telegram bot. Off until you switch it on and enter your own topic or bot.

The ntfy topic acts like a password (anyone who knows it can read the messages on a public server), so it is
stored with the keys in secrets.json, and a long random name is suggested.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import secrets as pysecrets
import time
from collections import deque

EVENTS = {   # key: (label, on by default)
    "news_high": ("High-impact headlines", True),
    "news_positions": ("Headlines that touch your open positions", True),
    "event_warning": ("Release warnings before high-impact data", True),
    "release": ("Released values (actual vs forecast)", True),
    "position": ("Positions opened or closed (also during quiet hours)", True),
    "price_alert": ("Your price alerts", True),
    "level": ("Level crossings", False),
    "alert": ("Unusual moves (watchlist + index scan)", False),
    "job_failed": ("Failed jobs", True),
}
DEFAULTS = {"enabled": False, "service": "ntfy", "ntfy_server": "https://ntfy.sh", "telegram_chat": "",
            "events": {k: v[1] for k, v in EVENTS.items()}, "warn_minutes": [5], "quiet_from": "", "quiet_to": "",
            "max_per_hour": 30}


def config(settings) -> dict:
    raw = settings.get("push") or {}
    out = {**DEFAULTS, **raw}
    out["events"] = {**DEFAULTS["events"], **(raw.get("events") or {})}
    return out


def suggest_topic() -> str:
    return "sd-" + pysecrets.token_urlsafe(18).replace("_", "").replace("-", "").lower()[:22]


# ------------------------------------------------------------------ pure formatting (tested)
def format_event(event: dict, cfg: dict) -> dict | None:
    """Event from the broker -> {"key", "kind", "title", "body", "priority"} or None if it is not pushed."""
    kind, on = event.get("kind"), cfg["events"]
    if kind == "news":
        it = event.get("item") or {}
        held = it.get("held") or []
        if held and on.get("news_positions"):
            return {"key": "news:" + str(it.get("id")), "kind": "news_positions", "priority": 4 if it.get("impact") == "high" else 3,
                    "title": f"{it.get('source')} - touches your open {', '.join(held)}", "body": it.get("title", ""), "url": it.get("url")}
        if it.get("impact") == "high" and on.get("news_high"):
            tag = (it.get("tags") or [""])[0]
            return {"key": "news:" + str(it.get("id")), "kind": "news_high", "priority": 4,
                    "title": f"{it.get('source')}" + (f" - {tag}" if tag else ""), "body": it.get("title", ""), "url": it.get("url")}
        return None
    if kind == "event_warning" and on.get("event_warning"):
        if event.get("minutes") not in (cfg.get("warn_minutes") or [5]):
            return None
        ev = event.get("event") or {}
        return {"key": f"warn:{ev.get('id')}:{event.get('minutes')}", "kind": "event_warning", "priority": 4,
                "title": f"{ev.get('currency')} {ev.get('title')} in {event.get('minutes')} min",
                "body": f"forecast {ev.get('forecast') or '-'} · previous {ev.get('previous') or '-'}"}
    if kind == "release" and on.get("release"):
        ev = event.get("event") or {}
        s = ev.get("surprise")
        return {"key": f"release:{ev.get('id')}", "kind": "release", "priority": 4,
                "title": f"Released: {ev.get('currency')} {ev.get('title')}",
                "body": f"actual {ev.get('actual')} · forecast {ev.get('forecast') or '-'} · previous {ev.get('previous') or '-'}"
                        + (f" · surprise {s:+.3g}" if isinstance(s, (int, float)) else "")}
    if kind == "position" and on.get("position"):
        p = event.get("position") or {}
        no_stop = "NO STOP" in (event.get("title") or "")
        return {"key": f"pos:{event.get('id')}", "kind": "position", "priority": 5 if no_stop else 3,
                "title": event.get("title", "Position change"), "body": f"{p.get('symbol', '')} {p.get('side', '')}".strip()}
    if kind == "price_alert" and on.get("price_alert"):
        a = event.get("alert") or {}
        return {"key": f"price:{a.get('id')}:{(a.get('data') or {}).get('triggered')}", "kind": "price_alert", "priority": 4,
                "title": "Price alert: " + a.get("title", ""), "body": a.get("body", "")}
    if kind in ("level", "alert") and on.get(kind):
        a = event.get("alert") or {}
        return {"key": f"{kind}:{a.get('id')}", "kind": kind, "priority": 3, "title": a.get("title", kind),
                "body": (a.get("body") or "")[:300]}
    if kind == "job" and on.get("job_failed"):
        j = event.get("job") or {}
        if j.get("status") != "failed":
            return None
        return {"key": f"job:{j.get('id')}:{j.get('last_end')}", "kind": "job_failed", "priority": 3,
                "title": f"Job failed: {j.get('name')}", "body": f"exit code {j.get('exit_code')} {j.get('issue') or ''}".strip()}
    return None


def in_quiet_hours(cfg: dict, now: dt.datetime) -> bool:
    a, b = (cfg.get("quiet_from") or "").strip(), (cfg.get("quiet_to") or "").strip()
    if not a or not b:
        return False
    try:
        t0 = dt.time.fromisoformat(a)
        t1 = dt.time.fromisoformat(b)
    except ValueError:
        return False
    t = now.time()
    return (t0 <= t < t1) if t0 < t1 else (t >= t0 or t < t1)


# ------------------------------------------------------------------ sender
class PhonePush:
    def __init__(self, ctx):
        self.ctx = ctx
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.sent: deque = deque(maxlen=500)          # send times (rate limit)
        self.keys: deque = deque(maxlen=500)          # recent keys (dedupe)
        self.log: deque = deque(maxlen=50)            # last results for the settings page
        self.dropped = 0

    def on_event(self, event: dict) -> None:
        """Broker listener: must be quick and never raise."""
        cfg = config(self.ctx.settings)
        if not cfg["enabled"]:
            return
        msg = format_event(event, cfg)
        if not msg or msg["key"] in self.keys:
            return
        if in_quiet_hours(cfg, dt.datetime.now()) and msg["kind"] != "position":
            return
        now = time.time()
        if sum(1 for t in self.sent if now - t < 3600) >= int(cfg.get("max_per_hour") or 30):
            self.dropped += 1
            return
        self.keys.append(msg["key"])
        self.sent.append(now)
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            self.dropped += 1

    async def run(self) -> None:
        while True:
            msg = await self.queue.get()
            res = await self.send(msg)
            self.log.appendleft({"ts": time.time(), "title": msg["title"], **res})

    async def send(self, msg: dict) -> dict:
        cfg = config(self.ctx.settings)
        try:
            if cfg["service"] == "telegram":
                token, chat = self.ctx.secrets.get("push.telegram_token"), (cfg.get("telegram_chat") or "").strip()
                if not token or not chat:
                    return {"ok": False, "error": "Telegram bot token or chat id missing"}
                resp = await self.ctx.http.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=10,
                                                json={"chat_id": chat, "text": f"{msg['title']}\n{msg.get('body', '')}".strip(),
                                                      "disable_web_page_preview": True})
            else:
                topic = self.ctx.secrets.get("push.ntfy_topic")
                if not topic:
                    return {"ok": False, "error": "ntfy topic missing"}
                headers = {}
                if self.ctx.secrets.get("push.ntfy_token"):
                    headers["Authorization"] = "Bearer " + self.ctx.secrets.get("push.ntfy_token")
                body = {"topic": topic, "title": msg["title"][:200], "message": (msg.get("body") or " ")[:1000],
                        "priority": int(msg.get("priority", 3)), "tags": [msg.get("kind", "info")]}
                if msg.get("url"):
                    body["click"] = msg["url"]
                resp = await self.ctx.http.post((cfg.get("ntfy_server") or "https://ntfy.sh").rstrip("/"), json=body,
                                                headers=headers, timeout=10)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:160]}"}
        return {"ok": True}

    def status(self) -> dict:
        cfg = config(self.ctx.settings)
        return {"config": cfg, "events": [{"key": k, "label": v[0]} for k, v in EVENTS.items()],
                "secrets": {k: self.ctx.secrets.describe(f"push.{k}") for k in ("ntfy_topic", "ntfy_token", "telegram_token")},
                "log": list(self.log), "dropped": self.dropped, "queued": self.queue.qsize(), "suggested_topic": suggest_topic()}
