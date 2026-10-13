"""One local SQLite file: news archive (full-text search), alerts, reading list, AI usage log.

Writes are tiny and serialized through one lock; reads run in a worker thread so the event loop
never waits on disk. WAL mode lets the UI read while the pollers write.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT, source TEXT, grp TEXT, provider TEXT,
  published INTEGER, seen INTEGER, summary TEXT, symbols TEXT, impact TEXT, tags TEXT);
CREATE INDEX IF NOT EXISTS news_published ON news(published DESC);
CREATE INDEX IF NOT EXISTS news_grp ON news(grp, published DESC);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY, ts REAL, kind TEXT, symbol TEXT, title TEXT, body TEXT, data TEXT,
  ai TEXT, acked INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS alerts_ts ON alerts(ts DESC);
CREATE TABLE IF NOT EXISTS saved (
  url TEXT PRIMARY KEY, title TEXT, source TEXT, saved REAL, note TEXT);
CREATE TABLE IF NOT EXISTS ai_usage (
  ts REAL, day TEXT, task TEXT, provider TEXT, model TEXT, tok_in INTEGER, tok_out INTEGER, cost REAL);
"""


class DB:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self.fts = self._try_fts()

    def _try_fts(self) -> bool:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(id UNINDEXED, title, summary)")
            return True
        except sqlite3.OperationalError:       # SQLite built without FTS5 -> LIKE search
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ sync core
    def _exec(self, sql: str, params=()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            self._conn.commit()
            return rows

    async def run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    # ------------------------------------------------------------ news
    def add_news(self, items: list[dict]) -> list[dict]:
        """Insert unseen items; return only the NEW ones (for push)."""
        new = []
        now = int(time.time())
        with self._lock:
            for it in items:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO news(id,title,url,source,grp,provider,published,seen,summary,symbols,impact,tags) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (it["id"], it["title"], it.get("url"), it.get("source"), it.get("group"), it.get("provider"),
                     int(it.get("published") or now), now, it.get("summary", ""), json.dumps(it.get("symbols") or []),
                     it.get("impact", "normal"), json.dumps(it.get("tags") or [])))
                if cur.rowcount:
                    new.append(it)
                    if self.fts:
                        self._conn.execute("INSERT INTO news_fts(id,title,summary) VALUES (?,?,?)",
                                           (it["id"], it["title"], it.get("summary", "")))
            self._conn.commit()
        return new

    def query_news(self, group: str | None = None, q: str | None = None, impact: str | None = None,
                   symbol: str | None = None, limit: int = 150, since: int | None = None) -> list[dict]:
        where, params = [], []
        if group:
            groups = group.split(",")
            where.append("grp IN (%s)" % ",".join("?" * len(groups)))
            params += groups
        if impact:
            where.append("impact = ?")
            params.append(impact)
        if symbol:
            where.append("symbols LIKE ?")
            params.append(f'%"{symbol}"%')
        if since:
            where.append("published >= ?")
            params.append(since)
        if q:
            if self.fts:
                where.append("id IN (SELECT id FROM news_fts WHERE news_fts MATCH ?)")
                params.append(_fts_query(q))
            else:
                where.append("(title LIKE ? OR summary LIKE ?)")
                params += [f"%{q}%", f"%{q}%"]
        sql = "SELECT * FROM news" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY published DESC LIMIT ?"
        try:
            rows = self._exec(sql, params + [limit])
        except sqlite3.OperationalError:
            return []
        for r in rows:
            r["symbols"] = json.loads(r.get("symbols") or "[]")
            r["tags"] = json.loads(r.get("tags") or "[]")
            r["group"] = r.pop("grp")
        return rows

    def prune_news(self, keep_days: int = 120) -> None:
        cutoff = int(time.time()) - keep_days * 86400
        with self._lock:
            if self.fts:
                self._conn.execute("DELETE FROM news_fts WHERE id IN (SELECT id FROM news WHERE published < ?)", (cutoff,))
            self._conn.execute("DELETE FROM news WHERE published < ?", (cutoff,))
            self._conn.commit()

    # ------------------------------------------------------------ alerts
    def add_alert(self, alert: dict) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO alerts(id,ts,kind,symbol,title,body,data) VALUES (?,?,?,?,?,?,?)",
                (alert["id"], alert["ts"], alert["kind"], alert.get("symbol"), alert["title"], alert.get("body", ""),
                 json.dumps(alert.get("data") or {}, default=str)))
            self._conn.commit()
            return bool(cur.rowcount)

    def alerts(self, limit: int = 100, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM alerts" + (" WHERE kind = ?" if kind else "") + " ORDER BY ts DESC LIMIT ?"
        rows = self._exec(sql, ([kind] if kind else []) + [limit])
        for r in rows:
            r["data"] = json.loads(r.get("data") or "{}")
        return rows

    def alert(self, alert_id: str) -> dict | None:
        rows = self._exec("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        if not rows:
            return None
        rows[0]["data"] = json.loads(rows[0].get("data") or "{}")
        return rows[0]

    def set_alert_ai(self, alert_id: str, text: str) -> None:
        self._exec("UPDATE alerts SET ai = ? WHERE id = ?", (text, alert_id))

    def ack_alert(self, alert_id: str) -> None:
        self._exec("UPDATE alerts SET acked = 1 WHERE id = ?", (alert_id,))

    # ------------------------------------------------------------ reading list
    def save_article(self, url: str, title: str, source: str) -> None:
        self._exec("INSERT OR REPLACE INTO saved(url,title,source,saved) VALUES (?,?,?,?)", (url, title, source, time.time()))

    def unsave_article(self, url: str) -> None:
        self._exec("DELETE FROM saved WHERE url = ?", (url,))

    def saved(self) -> list[dict]:
        return self._exec("SELECT * FROM saved ORDER BY saved DESC")

    # ------------------------------------------------------------ AI usage
    def log_usage(self, task: str, provider: str, usage: dict, cost: float | None) -> None:
        self._exec("INSERT INTO ai_usage VALUES (?,?,?,?,?,?,?,?)",
                   (time.time(), time.strftime("%Y-%m-%d"), task, provider, usage.get("model"), usage.get("in", 0),
                    usage.get("out", 0), cost))

    def usage_today(self) -> dict:
        rows = self._exec("SELECT COUNT(*) AS calls, COALESCE(SUM(tok_in),0) AS tok_in, COALESCE(SUM(tok_out),0) AS tok_out, "
                          "COALESCE(SUM(cost),0) AS cost FROM ai_usage WHERE day = ?", (time.strftime("%Y-%m-%d"),))
        return rows[0]

    def usage_days(self, days: int = 30) -> list[dict]:
        return self._exec("SELECT day, COUNT(*) AS calls, SUM(tok_in) AS tok_in, SUM(tok_out) AS tok_out, SUM(cost) AS cost "
                          "FROM ai_usage GROUP BY day ORDER BY day DESC LIMIT ?", (days,))


def _fts_query(q: str) -> str:
    """User text -> safe FTS5 query: every word as a prefix term, AND-ed."""
    words = [w for w in "".join(c if c.isalnum() else " " for c in q).split() if w]
    return " ".join(f'"{w}"*' for w in words) or '""'
