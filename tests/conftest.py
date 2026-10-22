"""Shared fixtures. Every test runs offline: the app's HTTP client is an httpx.MockTransport that
answers from canned payloads, and each test gets its own empty data directory."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from sessiondesk.app import create_app

TOKEN = "test-token"
HDR = {"X-SD-Token": TOKEN, "Host": "127.0.0.1:8765"}


def spark_payload(symbols):
    out = {}
    for i, s in enumerate(symbols):
        base = 100.0 + i
        out[s] = {"symbol": s, "timestamp": [1, 2, 3, 4], "close": [base, base * 1.01, base * 1.02, base * 1.03],
                  "chartPreviousClose": base, "previousClose": None}
    return out


FF_WEEK = [
    {"title": "Core CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "0.2%", "previous": "0.3%"},
    {"title": "CPI y/y", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "2.9%", "previous": "2.8%"},
    {"title": "German ZEW Economic Sentiment", "country": "EUR", "date": "2026-10-13T05:00:00-04:00", "impact": "Medium", "forecast": "40.1", "previous": "38.2"},
]

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Fed holds rates steady, signals patience</title><link>https://example.com/a</link><pubDate>Mon, 12 Oct 2026 18:00:00 GMT</pubDate><description>Policy unchanged.</description></item>
<item><title>Apple shares rise after $AAPL product event</title><link>https://example.com/b</link><pubDate>Mon, 12 Oct 2026 17:00:00 GMT</pubDate></item>
</channel></rss>"""


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "finance/spark" in url:
        syms = request.url.params.get("symbols", "").split(",")
        return httpx.Response(200, json=spark_payload([s for s in syms if s]))
    if "ff_calendar_thisweek" in url:
        return httpx.Response(200, json=FF_WEEK)
    if "ff_calendar_nextweek" in url:
        return httpx.Response(404)
    if url.endswith(".xml") or "rss" in url or "feed" in url:
        return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})
    return httpx.Response(404, json={"error": "not mocked: " + url})


@pytest.fixture
def mock_http():
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def client(tmp_path, mock_http, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))      # the MT5 default folder must not find a real terminal's export
    app = create_app(tmp_path, start_background=False, http=mock_http, token=TOKEN)
    with TestClient(app) as c:
        c.headers.update(HDR)
        c.app_state = app.state.app_state
        yield c


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
