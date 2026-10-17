"""HTTP server: JSON API + the browser UI + one Server-Sent-Events stream for push updates.

Security model (local app):
  - listens on 127.0.0.1 by default
  - every /api call needs the per-start session token (sent as header X-SD-Token; the event stream
    takes it as ?t=). The token is injected into the page the server delivers, so other websites
    open in the same browser cannot call the API (they cannot read the page, and a custom header
    forces a CORS preflight that this server never approves)
  - the Host header must be a local name (blocks DNS-rebinding), extendable via SESSIONDESK_ALLOWED_HOSTS
  - keys entered in the UI are stored locally and never sent back to the browser
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import secrets as pysecrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import extensions as ext_mod
from .ai import assist
from .cache import Cache
from .connectors.registry import build_hub
from .connectors.base import Ctx
from .db import DB
from .events import Broker
from .features import broker as broker_view
from .features import calendar as calendar_mod
from .features import deep, flows, indices, jobs, levels, macro, markets, movers, news, research, risk, stocks, today, valuation
from .settings import Secrets, Settings, data_dir, load_dotenv

STATIC = Path(__file__).resolve().parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def allowed_host(host_header: str) -> bool:
    host = (host_header or "").rsplit(":", 1)[0] if not host_header.startswith("[") else host_header.split("]")[0] + "]"
    host = host.lower()
    if host in LOCAL_HOSTS:
        return True
    extra = [h.strip().lower() for h in os.environ.get("SESSIONDESK_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if os.environ.get("CODESPACES") == "true":
        extra.append("*.app.github.dev")
    for pattern in extra:
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
        if host == pattern:
            return True
    return False


def create_app(home: Path | None = None, *, start_background: bool = True, http: httpx.AsyncClient | None = None,
               token: str | None = None) -> FastAPI:
    home = home or data_dir()
    load_dotenv(Path.cwd() / ".env", home / ".env")
    token = token or os.environ.get("SESSIONDESK_TOKEN") or pysecrets.token_urlsafe(24)
    state: dict = {}

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        client = http or httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True,
                                           limits=httpx.Limits(max_connections=60, max_keepalive_connections=20))
        ctx = Ctx(settings=Settings(home), secrets=Secrets(home), cache=Cache(home / "cache"), http=client,
                  broker=Broker(), db=DB(home / "sessiondesk.db"), data_dir=home)
        build_hub(ctx)
        ctx.extras["calendar"] = calendar_mod.CalendarService(ctx)
        ctx.extras["jobs"] = jobs.JobManager(ctx)
        ctx.extras["started"] = time.time()
        ctx.extras["extensions"] = ext_mod.load_all(ctx)
        state["ctx"] = ctx
        tasks = []
        if start_background:
            tasks = [asyncio.ensure_future(t) for t in background(ctx)]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await ctx.extras["jobs"].shutdown()
            if http is None:
                await client.aclose()
            ctx.db.close()

    app = FastAPI(title="SessionDesk", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.app_state = state

    def C() -> Ctx:
        return state["ctx"]

    # ------------------------------------------------------------------ security
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not allowed_host(request.headers.get("host", "")):
            return JSONResponse({"error": "host not allowed"}, status_code=403)
        if request.url.path.startswith("/api/"):
            sent = request.headers.get("x-sd-token") or request.query_params.get("t") or ""
            if not pysecrets.compare_digest(sent, token):
                return JSONResponse({"error": "missing or wrong session token - reload the page"}, status_code=401)
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"     # revalidate (cheap 304) so updated modules load
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(Exception)
    async def crash(request: Request, exc: Exception):
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)

    # ------------------------------------------------------------------ page
    @app.get("/", response_class=HTMLResponse)
    async def index():
        html = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", token).replace("{{VERSION}}", __version__)
        return HTMLResponse(html, headers={"Cache-Control": "no-store",
                                           "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https:; "
                                                                      "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                                                                      "connect-src 'self'; frame-ancestors 'none'"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    async def health():
        ctx = C()
        return {"ok": True, "version": __version__, "uptime": time.time() - ctx.extras["started"],
                "data_dir": str(ctx.data_dir), "ai_provider": ctx.settings.get("ai.provider"),
                "ai_ready": bool(assist.pick_provider(ctx) and assist.pick_provider(ctx).active())}

    @app.get("/api/system")
    async def get_system():
        from .features import system
        return await system.snapshot(C())

    @app.get("/api/stream")
    async def stream(since: int = 0):
        return StreamingResponse(C().broker.stream(since), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/recent")
    async def recent(kind: str | None = None, limit: int = 50):
        return {"events": C().broker.recent(kind, limit)}

    # ------------------------------------------------------------------ markets & stocks
    @app.get("/api/overview")
    async def overview():
        return await markets.overview(C())

    @app.get("/api/quotes")
    async def quotes(symbols: str):
        syms = [s.strip() for s in symbols.split(",") if s.strip()][:200]

        async def build():
            return await markets.get_quotes(C(), syms, intraday=True)
        return await C().cache.get("quotes:" + ",".join(sorted(syms)), 15, build)

    @app.get("/api/search")
    async def search(q: str):
        return await stocks.search(C(), q)

    @app.get("/api/stock/{symbol}")
    async def stock(symbol: str):
        return await stocks.summary(C(), symbol.upper() if "." not in symbol else symbol)

    @app.get("/api/stock/{symbol}/history")
    async def stock_history(symbol: str, range: str = "1y"):
        return await stocks.history(C(), symbol, range)

    @app.get("/api/stock/{symbol}/news")
    async def stock_news(symbol: str):
        return await stocks.news(C(), symbol)

    @app.get("/api/stock/{symbol}/filings")
    async def stock_filings(symbol: str):
        return await stocks.filings(C(), symbol)

    @app.get("/api/stock/{symbol}/valuation")
    async def stock_valuation(symbol: str):
        return await valuation.valuation(C(), symbol)

    @app.get("/api/stock/{symbol}/deep/{block}")
    async def stock_deep(symbol: str, block: str):
        fn = {"statements": deep.statements, "street": deep.street, "ownership": deep.ownership, "options": deep.options,
              "performance": deep.performance, "earnings": deep.earnings, "dividends": deep.dividends,
              "peers": deep.peers_table}.get(block)
        if not fn:
            return {"error": "unknown block"}
        return await fn(C(), symbol)

    @app.get("/api/watchlist")
    async def watchlist():
        syms = C().settings.get("watchlist") or []

        async def build():
            return await markets.get_quotes(C(), syms, intraday=True)
        data = await C().cache.get("watch:" + ",".join(syms), 15, build)
        return {"symbols": syms, **data}

    @app.put("/api/watchlist")
    async def set_watchlist(request: Request):
        body = await request.json()
        syms = [str(s).strip() for s in body.get("symbols", []) if str(s).strip()][:200]
        C().settings.replace("watchlist", list(dict.fromkeys(syms)))
        return {"symbols": syms}

    # ------------------------------------------------------------------ movers & alerts
    @app.get("/api/movers")
    async def get_movers():
        ctx = C()
        last = ctx.cache.peek("movers:last")
        if last:
            return last
        return await ctx.cache.get("movers:last", 240, lambda_scan(ctx))

    @app.post("/api/movers/scan")
    async def scan_now():
        ctx = C()
        res = await movers.scan(ctx)
        ctx.cache.invalidate("movers:last")
        await ctx.cache.get("movers:last", 240, lambda_scan(ctx, res))
        return res

    @app.get("/api/alerts")
    async def get_alerts(limit: int = 100, kind: str | None = None):
        return {"items": await C().db.run(C().db.alerts, limit, kind)}

    @app.post("/api/alerts/{alert_id}/ack")
    async def ack(alert_id: str):
        await C().db.run(C().db.ack_alert, alert_id)
        return {"ok": True}

    @app.post("/api/alerts/{alert_id}/explain")
    async def explain_alert(alert_id: str):
        ctx = C()
        alert = await ctx.db.run(ctx.db.alert, alert_id)
        if not alert:
            return {"error": "unknown alert"}
        res = await assist.complete(ctx, "explain", "Explain this move.", alert["data"])
        if "text" in res:
            await ctx.db.run(ctx.db.set_alert_ai, alert_id, res["text"])
        return res

    # ------------------------------------------------------------------ news, calendar, flows, research, macro
    @app.get("/api/news")
    async def get_news(group: str | None = None, q: str | None = None, impact: str | None = None,
                       symbol: str | None = None, limit: int = 150):
        return await news.list_news(C(), group, q, impact, symbol, min(limit, 500))

    @app.get("/api/news/positions")
    async def get_news_positions(hours: int = 12, q: str | None = None, strict: bool = False):
        return await news.for_positions(C(), max(1, min(hours, 24 * 30)), q, strict)

    @app.get("/api/calendar")
    async def get_calendar(days: int = 7, back_hours: int = 12):
        now = time.time()
        return await C().extras["calendar"].events(now - back_hours * 3600, now + days * 86400)

    @app.get("/api/earnings")
    async def get_earnings(days: int = 7):
        ctx = C()

        async def build():
            res = await ctx.hub.first("earnings", "earnings", dt.date.today(), days)
            return {"items": res.get("data", []), "source": res.get("source"), "error_detail": res.get("error")}
        return await ctx.cache.get(f"earnings:{days}:{dt.date.today()}", 3 * 3600, build, disk=True)

    @app.get("/api/flows")
    async def get_flows(days: int = 120):
        return await flows.flows(C(), min(days, 400))

    @app.get("/api/research")
    async def get_research(q: str | None = None):
        return await research.feed(C(), q)

    @app.get("/api/research/article")
    async def get_article(url: str):
        return await research.read_article(C(), url)

    @app.post("/api/research/saved")
    async def save_article(request: Request):
        body = await request.json()
        if body.get("remove"):
            await C().db.run(C().db.unsave_article, body["url"])
        else:
            await C().db.run(C().db.save_article, body["url"], body.get("title", ""), body.get("source", ""))
        return {"saved": await C().db.run(C().db.saved)}

    @app.get("/api/indices/{key}")
    async def get_index(key: str):
        ctx = C()

        async def build():
            return await indices.index_view(ctx, key)
        return await ctx.cache.get(f"idxview:{key}", 120, build)

    # ------------------------------------------------------------------ local extensions (your own pages)
    @app.get("/api/extensions")
    async def get_extensions():
        ctx = C()
        return {"folder": str(ctx.data_dir / "extensions"), "enabled": ctx.settings.get("extensions_enabled") is not False,
                "items": [e.describe() for e in ctx.extras["extensions"].values()]}

    @app.post("/api/extensions/reload")
    async def reload_extensions():
        ctx = C()
        ctx.extras["extensions"] = await asyncio.to_thread(ext_mod.load_all, ctx)
        return await get_extensions()

    @app.get("/api/ext/{name}")
    async def get_ext_page(name: str):
        ctx = C()

        async def build():
            return await ext_mod.page(ctx, ctx.extras["extensions"], name)
        return await ctx.cache.get(f"ext:{name}", 3, build)

    @app.post("/api/ext/{name}/action")
    async def post_ext_action(name: str, request: Request):
        ctx = C()
        body = await request.json()
        res = await ext_mod.action(ctx, ctx.extras["extensions"], name, body if isinstance(body, dict) else {})
        ctx.cache.invalidate(f"ext:{name}")
        return res

    @app.get("/api/macro/{panel}")
    async def get_macro(panel: str):
        fn = {"rates": macro.rates, "fedpath": macro.fed_path, "vol": macro.vol, "risk": macro.risk_ratios, "cot": macro.cot,
              "putcall": indices.putcall, "factset": indices.factset}.get(panel)
        if not fn:
            return {"error": "unknown panel"}
        return await fn(C())

    @app.get("/api/broker")
    async def get_broker():
        return await broker_view.overview(C())

    @app.get("/api/book")
    async def get_book():
        ctx = C()
        b = await broker_view.overview(ctx)
        if not b.get("connected"):
            return {"positions": [], "note": b.get("note")}
        return await risk.book(ctx, [p for p in b.get("positions", []) if p.get("fresh", True)], b.get("accounts", []))

    @app.get("/api/specs")
    async def get_specs():
        return await risk.specs(C())

    @app.get("/api/fx/strength")
    async def fx_strength():
        ctx = C()
        mt5 = ctx.hub.get("mt5")
        quotes = {}
        if mt5 and mt5.active():
            try:
                quotes = await mt5.broker_quotes()
            except Exception:
                quotes = {}

        async def build():
            return await risk.currency_strength(ctx, quotes)
        return await ctx.cache.get("fx:strength", 60, build)

    @app.get("/api/calendar/history")
    async def calendar_history():
        ctx = C()

        async def build():
            return await risk.event_history(ctx)
        return await ctx.cache.get("cal:history", 3 * 3600, build)

    @app.get("/api/journal")
    async def get_journal(days: int = 30):
        from .features import journal
        return await journal.view(C(), min(days, 365))

    @app.post("/api/journal")
    async def set_journal(request: Request):
        body = await request.json()
        risk_value = body.get("risk")
        try:
            risk_value = float(risk_value) if risk_value not in (None, "") else None
        except (TypeError, ValueError):
            return {"error": "risk must be a number (money in account currency)"}
        await C().db.run(C().db.journal_set, str(body.get("account")), str(body.get("position_id")), risk_value,
                         body.get("note") if body.get("note") is not None else None)
        return {"ok": True}

    @app.get("/api/today")
    async def get_today():
        return await today.snapshot(C())

    @app.get("/api/activity")
    async def get_activity(limit: int = 100):
        return {"items": await C().db.run(C().db.activity, min(limit, 500))}

    @app.get("/api/notes")
    async def get_notes():
        return {"items": await C().db.run(C().db.notes, 60)}

    @app.post("/api/notes")
    async def add_note(request: Request):
        body = await request.json()
        text = str(body.get("text", "")).strip()[:500]
        if not text:
            return {"error": "empty note"}
        ctx = C()
        await ctx.db.run(ctx.db.add_note, text, str(body.get("symbol", ""))[:20], str(body.get("account", ""))[:20])
        await ctx.db.run(ctx.db.add_activity, "note", text[:120])
        return {"items": await ctx.db.run(ctx.db.notes, 60)}

    @app.get("/api/briefing")
    async def get_briefing(kind: str = "briefing"):
        return {"item": await C().db.run(C().db.briefing, kind)}

    @app.post("/api/briefing")
    async def make_briefing(request: Request):
        body = await request.json()
        kind = "review" if body.get("kind") == "review" else "briefing"
        return await run_briefing(C(), kind)

    @app.get("/api/levels")
    async def get_levels():
        ctx = C()
        snap = await levels.snapshot(ctx)
        snap["alerts"] = await ctx.db.run(ctx.db.alerts, 40, "level")
        return snap

    # ------------------------------------------------------------------ jobs
    @app.get("/api/jobs")
    async def get_jobs():
        jm = C().extras["jobs"]
        return {"jobs": [j.public() for j in jm.jobs.values()], "workflows": jm.workflows, "errors": jm.errors,
                "files": [{"path": str(p), "editable": e, "exists": p.exists()} for p, e in jm.files()],
                "flows": jm.flow_status}

    @app.get("/api/jobs/{job_id}/log")
    async def job_log(job_id: str):
        job = C().extras["jobs"].jobs.get(job_id)
        return {"lines": list(job.buffer)} if job else {"error": "unknown job"}

    @app.post("/api/jobs/{job_id}/run")
    async def job_run(job_id: str):
        return C().extras["jobs"].start(job_id)

    @app.post("/api/jobs/{job_id}/stop")
    async def job_stop(job_id: str):
        return C().extras["jobs"].stop(job_id)

    @app.put("/api/jobs")
    async def job_upsert(request: Request):
        return C().extras["jobs"].upsert(await request.json())

    @app.delete("/api/jobs/{job_id}")
    async def job_delete(job_id: str):
        return C().extras["jobs"].delete(job_id)

    @app.post("/api/jobs/reload")
    async def job_reload():
        C().extras["jobs"].reload()
        return {"ok": True}

    @app.post("/api/jobs/example")
    async def job_example():
        return C().extras["jobs"].install_example()

    @app.post("/api/workflows/run")
    async def wf_run(request: Request):
        body = await request.json()
        task = asyncio.ensure_future(C().extras["jobs"].run_workflow(body.get("name", "")))
        state.setdefault("tasks", set()).add(task)
        task.add_done_callback(state["tasks"].discard)
        return {"ok": True}

    @app.get("/api/artifacts")
    async def artifacts():
        return {"items": C().extras["jobs"].list_artifacts()}

    @app.post("/api/artifacts/read")
    async def artifact_read(request: Request):
        body = await request.json()
        jm = C().extras["jobs"]
        path = body.get("path", "")
        if not jm.artifact_allowed(path):
            return {"error": "not a registered artifact"}
        try:
            text = jobs.read_text(Path(path))
        except OSError as exc:
            return {"error": str(exc)}
        copied = jobs.copy_to_clipboard(text) if body.get("copy") else None
        return {"text": text[:300_000], "copied": copied}

    # ------------------------------------------------------------------ connectors & settings
    @app.get("/api/connectors")
    async def connectors():
        return {"items": C().hub.catalog()}

    @app.post("/api/connectors/{cid}")
    async def connector_update(cid: str, request: Request):
        ctx = C()
        conn = ctx.hub.get(cid)
        if not conn:
            return {"error": "unknown connector"}
        body = await request.json()
        patch: dict = {}
        if "enabled" in body:
            patch["enabled"] = bool(body["enabled"])
        for f in conn.fields:
            if f.key in body.get("fields", {}):
                value = body["fields"][f.key]
                if f.secret:
                    ctx.secrets.set(f"{cid}.{f.key}", value)
                else:
                    patch[f.key] = value
        if patch:
            ctx.settings.update({"connectors": {cid: patch}})
        ctx.cache.invalidate()
        return conn.describe()

    @app.post("/api/connectors/{cid}/test")
    async def connector_test(cid: str):
        conn = C().hub.get(cid)
        if not conn:
            return {"error": "unknown connector"}
        if not conn.configured():
            return {"ok": False, "detail": "fill in the required fields first"}
        try:
            return await asyncio.wait_for(conn.test(), timeout=60)
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    @app.get("/api/settings")
    async def get_settings():
        ctx = C()
        from .ai.providers import SUGGESTED_MODELS
        from .features.universe import UNIVERSES
        return {"settings": ctx.settings.data, "universes": UNIVERSES, "suggested_models": SUGGESTED_MODELS,
                "data_dir": str(ctx.data_dir)}

    @app.patch("/api/settings")
    async def patch_settings(request: Request):
        body = await request.json()
        body.pop("connectors", None)                   # connectors go through their own endpoint
        # Lists and whole-object settings are replaced, everything else is merged key by key.
        replace = {"prop_rules", "sessions", "round_steps", "magic_names", "asset_patterns"}
        lists = {k: body.pop(k) for k in list(body) if isinstance(body[k], list) or k in replace}
        ctx = C()
        if body:
            ctx.settings.update(body)
        for k, v in lists.items():
            ctx.settings.replace(k, v)
        if "jobs_files" in lists:
            ctx.extras["jobs"].reload()
        return {"settings": ctx.settings.data}

    # ------------------------------------------------------------------ AI
    @app.post("/api/ai/chat")
    async def ai_chat(request: Request):
        body = await request.json()
        ctx = C()

        async def gen():
            async for ev in assist.chat(ctx, body.get("mode", "ask"), body.get("question", ""), body.get("context"),
                                        body.get("history"), body.get("provider")):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @app.get("/api/ai/usage")
    async def ai_usage():
        ctx = C()
        return {"today": await ctx.db.run(ctx.db.usage_today), "days": await ctx.db.run(ctx.db.usage_days, 30),
                "cap": ctx.settings.get("ai.max_calls_per_day")}

    @app.get("/favicon.ico")
    async def favicon():
        return Response((STATIC / "sessiondesk.ico").read_bytes(), media_type="image/x-icon")

    return app


async def run_briefing(ctx, kind: str) -> dict:
    facts = await today.briefing_facts(ctx, kind)
    question = "Write today's briefing." if kind == "briefing" else "Write the weekly review."
    res = await assist.complete(ctx, kind, question, facts)
    if "text" in res:
        await ctx.db.run(ctx.db.add_briefing, kind, res["text"], res.get("provider", ""), res.get("model", ""))
        await ctx.db.run(ctx.db.add_activity, "briefing", f"{kind} written")
        ctx.broker.publish("briefing", {"kind": kind})
    return res


ACTIVITY_KINDS = {"alert": "move", "level": "level", "release": "release", "release_headline": "release", "event_warning": "event"}


def record_activity(ctx):
    """Broker listener: keep a durable log of what happened (shown on Today as 'Changes')."""
    def on_event(ev: dict) -> None:
        kind = ev.get("kind")
        title = body = ""
        if kind in ("alert", "level"):
            a = ev.get("alert") or {}
            title, body = a.get("title", ""), a.get("body", "")
        elif kind == "release":
            e = ev.get("event") or {}
            title = f"{e.get('currency')} {e.get('title')}: {e.get('actual')} (fcst {e.get('forecast')})"
        elif kind == "release_headline":
            title = (ev.get("headline") or {}).get("title", "")
        elif kind == "event_warning":
            e = ev.get("event") or {}
            title = f"{e.get('currency')} {e.get('title')} in {ev.get('minutes')} min"
        elif kind == "job":
            j = ev.get("job") or {}
            if j.get("status") not in ("ok", "failed"):
                return
            title, body = f"job {j.get('name')}: {j.get('status')}", j.get("issue") or ""
        elif kind == "news" and (ev.get("item") or {}).get("impact") == "high":
            title = (ev.get("item") or {}).get("title", "")
        else:
            return
        try:
            ctx.db.add_activity(ACTIVITY_KINDS.get(kind, kind), title[:300], body[:500])
        except Exception:
            pass
    return on_event


def lambda_scan(ctx, result: dict | None = None):
    async def build():
        return result if result is not None else await movers.scan(ctx)
    return build


# ---------------------------------------------------------------------- background loops
def market_hours(now: float | None = None) -> bool:
    t = dt.datetime.fromtimestamp(now or time.time(), dt.timezone.utc)
    return t.weekday() < 5 and 7 <= t.hour < 21          # Europe open .. US close (UTC), broad on purpose


def background(ctx) -> list:
    async def every(seconds_fn, fn, *, first_delay: float = 0.0, name: str = ""):
        stat = ctx.extras.setdefault("loops", {}).setdefault(name or fn.__name__, {
            "runs": 0, "errors": 0, "first_delay": first_delay, "registered": time.time()})
        await asyncio.sleep(first_delay)
        while True:
            stat["interval"] = seconds_fn()
            stat["last_start"] = time.time()
            try:
                await fn()
                stat["last_ok"] = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stat["errors"] += 1
                stat["last_error"] = f"{type(exc).__name__}: {exc}"
                stat["last_error_ts"] = time.time()
                ctx.extras.setdefault("loop_errors", {})[name] = f"{dt.datetime.now():%H:%M:%S} {type(exc).__name__}: {exc}"
            stat["runs"] += 1
            stat["last_end"] = time.time()
            stat["duration"] = stat["last_end"] - stat["last_start"]
            await asyncio.sleep(seconds_fn())

    async def warm_news():
        # First pass fills the archive silently (no notification storm after a restart).
        for group in ("squawk", "markets", "central_banks", "research"):
            try:
                await news.poll_group(ctx, group, push=False)
            except Exception:
                pass
        ctx.extras["news_warm"] = True

    async def squawk():
        if ctx.extras.get("news_warm"):
            await news.poll_group(ctx, "squawk")

    async def markets_news():
        if ctx.extras.get("news_warm"):
            await news.poll_group(ctx, "markets")
            await news.poll_group(ctx, "central_banks")
            await news.poll_keyed(ctx)

    async def research_news():
        if ctx.extras.get("news_warm"):
            await news.poll_group(ctx, "research", push=False)

    async def scan():
        if not market_hours() and ctx.cache.peek("movers:last"):
            return
        first = not ctx.extras.get("movers_ran")
        ctx.extras["movers_ran"] = True
        # The first scan after a start finds everything that moved today: one digest instead of a toast per stock.
        res = await movers.scan(ctx, publish=not first)
        if first and res.get("new"):
            ctx.broker.publish("alert_digest", {"count": len(res["new"]),
                                                "top": [f"{r['symbol']} {r['pct']:+.1f}%" for r in res.get("flagged", [])[:6]]})
        ctx.cache.invalidate("movers:last")
        await ctx.cache.get("movers:last", 10 ** 9, lambda_scan(ctx, res))
        if ctx.settings.get("alerts.ai_explain") and res.get("new"):
            for alert_id in res["new"][:5]:
                alert = await ctx.db.run(ctx.db.alert, alert_id)
                out = await assist.complete(ctx, "explain", "Explain this move.", alert["data"])
                if "text" in out:
                    await ctx.db.run(ctx.db.set_alert_ai, alert_id, out["text"])
                    ctx.broker.publish("alert_ai", {"id": alert_id, "text": out["text"]})

    async def prune():
        await ctx.db.run(ctx.db.prune_news, 120)

    ctx.broker.listen(record_activity(ctx))
    book_state: dict = {"open": None}

    async def watch_positions():
        """Position opened / closed -> activity feed + push; also feeds the journal."""
        from .features import broker as broker_view
        from .features import journal
        b = await broker_view.overview(ctx)
        if not b.get("connected"):
            return
        fresh = [p for p in b.get("positions", []) if p.get("fresh", True)]
        current = {(p.get("account"), p.get("ticket") or p.get("position_id") or f"{p.get('symbol')}{p.get('side')}{p.get('open_price')}"): p
                   for p in fresh}
        if book_state["open"] is not None:
            for key, p in current.items():
                if key not in book_state["open"]:
                    title = f"{p['account']} opened {p['symbol']} {p['side']} {p.get('volume')}" + ("" if p.get("sl") else " - NO STOP")
                    await ctx.db.run(ctx.db.add_activity, "position", title, "", str(key))
                    ctx.broker.publish("position", {"title": title, "position": p})
            for key, p in book_state["open"].items():
                if key not in current:
                    title = f"{p['account']} closed {p['symbol']} {p['side']}"
                    await ctx.db.run(ctx.db.add_activity, "position", title, "", str(key))
                    ctx.broker.publish("position", {"title": title, "position": p})
        book_state["open"] = current
        await journal.sync(ctx, b)

    async def warm_indices():
        """Member profiles for index valuation are slow the first time: build them in the background."""
        for key in ("dax40", "dow30", "nasdaq100"):
            await indices.index_view(ctx, key)

    async def scheduled_briefing():
        when = ctx.settings.get("briefing_time")
        if not when:
            return
        now = dt.datetime.now()
        if now.weekday() >= 5 or now.strftime("%H:%M") < when:
            return
        last = await ctx.db.run(ctx.db.briefing, "briefing")
        if last and dt.datetime.fromtimestamp(last["ts"]).date() == now.date():
            return
        await run_briefing(ctx, "briefing")

    alerter = levels.LevelAlerter(cooldown=600)
    level_state = {"next": 0.0}

    async def level_alerts():
        if not ctx.settings.get("level_alerts", True) or time.time() < level_state["next"]:
            return
        prices = await levels.price_sources(ctx)
        broker = any(q.get("source") == "broker" for q in prices.values())
        level_state["next"] = time.time() + (5 if broker else 30)
        files = levels.read_level_files(ctx.settings)["levels"]
        for hit in alerter.check(prices, files, ctx.settings):
            alert = {"id": hit["id"], "ts": hit["ts"], "kind": "level", "symbol": hit["symbol"],
                     "title": f"{hit['symbol']} {'above' if hit['direction'] == 'up' else 'below'} {hit['label']} {hit['level']:g}",
                     "body": f"{hit['asset']} at {hit['price']:g} crossed {hit['label']} {hit['level']:g} ({hit['src']}, price from {hit['source']}).",
                     "data": hit}
            if await ctx.db.run(ctx.db.add_alert, alert):
                ctx.broker.publish("level", {"alert": alert})

    news_cfg = lambda k, d: (ctx.settings.get("news") or {}).get(k, d)  # noqa: E731
    return [
        warm_news(),
        every(lambda: max(5, news_cfg("squawk_seconds", 20)), squawk, first_delay=8, name="squawk"),
        every(lambda: max(30, news_cfg("markets_seconds", 120)), markets_news, first_delay=15, name="news"),
        every(lambda: max(600, news_cfg("research_minutes", 60) * 60), research_news, first_delay=60, name="research"),
        every(lambda: max(60, (ctx.settings.get("alerts") or {}).get("scan_minutes", 5) * 60), scan, first_delay=20, name="movers"),
        every(lambda: 86400, prune, first_delay=300, name="prune"),
        every(lambda: 5, level_alerts, first_delay=25, name="levels"),
        every(lambda: 10, watch_positions, first_delay=12, name="positions"),
        every(lambda: 3600, warm_indices, first_delay=180, name="indices"),
        every(lambda: 60, scheduled_briefing, first_delay=90, name="briefing"),
        ctx.extras["calendar"].loop(),
        ctx.extras["jobs"].scheduler(),
    ]
