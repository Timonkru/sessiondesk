"""System status: is every part of SessionDesk doing its job? Background loops, connectors, feeds, calendar
sources, broker exporters, jobs, extensions, level files - condensed into one list of problems.

Levels: "error" = something that should work does not; "warn" = stale or degraded, often harmless
(exports are stale on weekends, a feed pauses after a rate limit).
"""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

from .. import __version__


def loop_state(stat: dict, now: float) -> str:
    if "last_end" not in stat:
        return "waiting" if now - stat.get("registered", now) < stat.get("first_delay", 0) + 300 else "stuck"
    if stat.get("last_error_ts", 0) >= stat.get("last_ok", 0) and stat.get("last_error_ts"):
        return "error"
    if now - stat["last_end"] > 3 * float(stat.get("interval") or 60) + 120:
        return "late"
    return "ok"


def _dir_size(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def human(seconds: float) -> str:
    s = max(0.0, float(seconds))
    return f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h" if s < 172800 else f"{s / 86400:.0f} days"


def _age(ts: float | None, now: float) -> float | None:
    return now - ts if ts else None


async def snapshot(ctx) -> dict:
    now = time.time()
    issues: list[dict] = []

    def issue(level: str, area: str, text: str) -> None:
        issues.append({"level": level, "area": area, "text": text})

    # background loops
    loops = []
    for name, st in sorted((ctx.extras.get("loops") or {}).items()):
        state = loop_state(st, now)
        loops.append({"name": name, "state": state, "interval": st.get("interval"), "runs": st.get("runs", 0),
                      "errors": st.get("errors", 0), "last_ok_ago": _age(st.get("last_ok"), now),
                      "duration": st.get("duration"), "last_error": st.get("last_error")})
        if state in ("error", "stuck"):
            issue("error", "loop", f"{name}: {st.get('last_error') or 'never finished a run'}")
        elif state == "late":
            issue("warn", "loop", f"{name}: last run {human(now - st['last_end'])} ago")

    # connectors (active ones) with their last success / error
    conns = []
    for c in ctx.hub.connectors.values():
        if not c.active():
            continue
        h = ctx.hub.health.get(c.id, {})
        failing = h.get("last_error_ts", 0) > h.get("last_ok", 0)
        conns.append({"id": c.id, "name": c.name, "tier": c.tier, "verified": c.verified, "ok": h.get("ok", 0),
                      "errors": h.get("errors", 0), "last_ok_ago": _age(h.get("last_ok"), now),
                      "last_error": h.get("last_error"), "last_error_ago": _age(h.get("last_error_ts"), now),
                      "state": "error" if failing else "ok" if h.get("ok") else "unused"})
        if failing and now - h["last_error_ts"] < 3600:
            issue("warn", "connector", f"{c.name}: {h['last_error']}")

    # feeds and calendar sources
    rss = ctx.hub.get("rss")
    feeds = dict(getattr(rss, "errors", {}) or {}) if rss else {}
    for name, err in feeds.items():
        issue("warn", "feed", f"{name}: {err}")
    cal = ctx.extras.get("calendar")
    cal_errors = dict(getattr(cal, "last_errors", {}) or {}) if cal else {}
    for name, err in cal_errors.items():
        issue("warn", "calendar", f"{name}: {err}")

    # broker exporters
    exporters = []
    try:
        from . import broker
        b = await broker.overview(ctx)
        for acc in b.get("accounts", []):
            exporters.append({"account": acc.get("login"), "bridge": acc.get("bridge"), "fresh": acc.get("fresh"), "age": acc.get("age")})
            if acc.get("fresh") is False:
                issue("warn", "broker", f"account {acc.get('login')}: export {human(acc.get('age') or 0)} old")
    except Exception as exc:
        issue("error", "broker", f"{type(exc).__name__}: {exc}")

    # jobs
    jm = ctx.extras.get("jobs")
    jobs = []
    if jm:
        for j in jm.jobs.values():
            jobs.append({"id": j.id, "name": j.name, "status": j.status, "service": j.service, "running": j.running,
                         "last_end_ago": _age(j.last_end, now), "issue": j.issue})
            if j.status == "failed":
                issue("warn", "job", f"{j.name}: failed (exit {j.exit_code}){' - ' + j.issue if j.issue else ''}")
            if j.service and j.autostart and not j.running:
                issue("error", "job", f"{j.name}: service is not running")
        for err in getattr(jm, "errors", []) or []:
            issue("warn", "job", str(err))

    # extensions
    exts = [e.describe() for e in (ctx.extras.get("extensions") or {}).values()]
    for e in exts:
        if e["error"]:
            issue("error", "extension", f"{e['title']}: {e['error']}")

    # level files
    from .levels import read_level_files
    lf = read_level_files(ctx.settings).get("files", [])
    for f in lf:
        if f.get("error"):
            issue("warn", "levels", f"{f['title']}: {f['error']}")
        elif not f.get("fresh"):
            issue("warn", "levels", f"{f['title']}: {f.get('age_h', 0):.0f} h old, ignored")

    # AI
    from ..ai import assist
    prov = assist.pick_provider(ctx)
    ai = {"provider": ctx.settings.get("ai.provider"), "ready": bool(prov and prov.active())}

    app = {"version": __version__, "python": sys.version.split()[0], "platform": platform.platform(terse=True),
           "uptime": now - ctx.extras.get("started", now), "data_dir": str(ctx.data_dir),
           "db_bytes": (ctx.data_dir / "sessiondesk.db").stat().st_size if (ctx.data_dir / "sessiondesk.db").exists() else 0,
           "cache_bytes": _dir_size(ctx.data_dir / "cache"), "stream_clients": len(getattr(ctx.broker, "_subs", ())),
           "news_archive": await ctx.db.run(ctx.db.count_news)}
    order = {"error": 0, "warn": 1}
    issues.sort(key=lambda i: (order.get(i["level"], 2), i["area"]))
    return {"asof": now, "app": app, "ai": ai, "issues": issues,
            "counts": {"error": sum(i["level"] == "error" for i in issues), "warn": sum(i["level"] == "warn" for i in issues)},
            "loops": loops, "connectors": conns, "feeds": feeds, "calendar": cal_errors, "exporters": exporters,
            "jobs": jobs, "extensions": exts, "level_files": lf}
