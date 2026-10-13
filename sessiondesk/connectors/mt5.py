"""MetaTrader 5 via the read-only SessionDeskBridge EA (bridge/SessionDeskBridge.mq5).

The bridge writes TSV files into MT5's common data folder; this connector only reads them. No
socket, no DLL, no order path - the bridge has no code that could trade, and neither does this.

  account_<login>.tsv    balance, equity, margin, AutoTrading state           every 2 s
  positions_<login>.tsv  open positions incl. money at risk to the stop        every 2 s
  quotes_<login>.tsv     Market Watch bid/ask, previous daily close            every 2 s
  eas_<login>.tsv        which Expert Advisor runs on which chart              every 60 s
  deals_<login>.tsv      closed deals of the last 30 days                      every 60 s
  calendar.tsv           MetaQuotes economic calendar WITH actual values       on change (<= 2 s) + every 60 s

Every file starts with "#sessiondesk  version  kind  utc_epoch  server_offset  login". A file older
than its freshness limit is reported as stale instead of being shown as current.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .base import Connector, Field, stable_id

FRESH = {"account": 30, "positions": 30, "quotes": 30, "eas": 300, "deals": 600, "calendar": 900}
IMPORTANCE = {1: "low", 2: "medium", 3: "high"}


def default_folder() -> str:
    if sys.platform.startswith("win"):
        return os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\Common\Files\SessionDesk")
    return str(Path.home() / ".wine/drive_c/users" / os.environ.get("USER", "user") / "AppData/Roaming/MetaQuotes/Terminal/Common/Files/SessionDesk")


def read_tsv(path: Path) -> dict | None:
    """{'version', 'kind', 'ts', 'offset', 'login', 'rows': [dict]} or None if missing/garbled."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2 or not lines[0].startswith("#sessiondesk"):
        return None
    head = lines[0].split("\t")
    cols = lines[1].split("\t")
    rows = []
    for ln in lines[2:]:
        parts = ln.split("\t")
        if len(parts) < len(cols):
            parts += [""] * (len(cols) - len(parts))
        rows.append(dict(zip(cols, parts)))
    try:
        return {"version": head[1], "kind": head[2], "ts": int(head[3]), "offset": int(head[4]), "login": head[5], "rows": rows}
    except (IndexError, ValueError):
        return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mask(login: str, on: bool) -> str:
    return ("…" + login[-3:]) if on and login and len(login) > 3 else login


class MT5Bridge(Connector):
    id = "mt5"
    name = "MetaTrader 5 (bridge EA)"
    tier = "free"
    kind = "broker"
    capabilities = ("account", "positions", "eas", "calendar", "broker_quotes", "deals")
    fields = (Field("folder", "Bridge folder", secret=False, required=False,
                    help="Where SessionDeskBridge writes its files. Default: MT5 common folder \\Files\\SessionDesk.",
                    placeholder=default_folder()),)
    homepage = "https://www.metatrader5.com"
    description = ("Read-only: accounts, open positions with risk to stop, running EAs, Market Watch quotes, closed deals and "
                   "the MetaQuotes calendar with actual values within ~2 s of release. Needs bridge/SessionDeskBridge.mq5 on one chart.")

    def folder(self) -> Path:
        return Path(self.option("folder") or default_folder())

    def configured(self) -> bool:
        return self.folder().is_dir()

    def _files(self, prefix: str) -> list[dict]:
        out = []
        for path in sorted(self.folder().glob(f"{prefix}_*.tsv")):
            data = read_tsv(path)
            if data:
                data["age"] = time.time() - data["ts"]
                data["fresh"] = data["age"] <= FRESH.get(data["kind"], 60)
                out.append(data)
        return out

    async def test(self) -> dict:
        if not self.folder().is_dir():
            return {"ok": False, "detail": f"folder not found: {self.folder()} - attach SessionDeskBridge to a chart"}
        acc = self._files("account")
        if not acc:
            return {"ok": False, "detail": "folder exists but no account file yet"}
        fresh = [a for a in acc if a["fresh"]]
        return {"ok": bool(fresh), "detail": f"{len(fresh)}/{len(acc)} terminal(s) fresh"}

    async def account(self) -> list[dict]:
        hide = bool(self.ctx.settings.get("privacy.mask_accounts", True))
        out = []
        for f in self._files("account"):
            for r in f["rows"]:
                out.append({"login": mask(r.get("login", ""), hide), "server": r.get("server"), "company": r.get("company"),
                            "currency": r.get("currency"), "balance": num(r.get("balance")), "equity": num(r.get("equity")),
                            "margin": num(r.get("margin")), "free_margin": num(r.get("free_margin")),
                            "profit": num(r.get("profit")), "leverage": num(r.get("leverage")),
                            "trade_allowed": r.get("trade_allowed") == "1", "connected": r.get("connected") == "1",
                            "age": f["age"], "fresh": f["fresh"], "bridge": f["version"]})
        return out

    async def positions(self) -> list[dict]:
        hide = bool(self.ctx.settings.get("privacy.mask_accounts", True))
        out = []
        for f in self._files("positions"):
            for r in f["rows"]:
                out.append({"account": mask(f["login"], hide), "ticket": r.get("ticket"), "symbol": r.get("symbol"),
                            "side": r.get("side"), "volume": num(r.get("volume")), "open_price": num(r.get("open_price")),
                            "open_time": num(r.get("open_time_utc")), "sl": num(r.get("sl")) or None, "tp": num(r.get("tp")) or None,
                            "price": num(r.get("price")), "profit": num(r.get("profit")), "swap": num(r.get("swap")),
                            "magic": r.get("magic"), "comment": r.get("comment"),
                            "risk_to_stop": num(r.get("risk_to_stop")), "manual": r.get("magic") in ("0", ""),
                            "fresh": f["fresh"], "age": f["age"]})
        return out

    async def eas(self) -> list[dict]:
        hide = bool(self.ctx.settings.get("privacy.mask_accounts", True))
        out = []
        for f in self._files("eas"):
            for r in f["rows"]:
                out.append({"account": mask(f["login"], hide), "symbol": r.get("symbol"), "timeframe": r.get("timeframe"),
                            "expert": r.get("expert"), "fresh": f["fresh"], "age": f["age"]})
        return out

    async def broker_quotes(self) -> dict:
        out = {}
        for f in self._files("quotes"):
            if not f["fresh"]:
                continue
            for r in f["rows"]:
                bid, ask, prev = num(r.get("bid")), num(r.get("ask")), num(r.get("prev_close"))
                if bid is None or ask is None:
                    continue
                mid = (bid + ask) / 2
                out[r["symbol"]] = {"symbol": r["symbol"], "bid": bid, "ask": ask, "price": mid, "prev_close": prev,
                                    "change_pct": (mid / prev - 1) * 100 if prev else None, "time": num(r.get("time_utc"))}
        return out

    async def deals(self) -> list[dict]:
        hide = bool(self.ctx.settings.get("privacy.mask_accounts", True))
        out = []
        for f in self._files("deals"):
            for r in f["rows"]:
                out.append({"account": mask(f["login"], hide), "ticket": r.get("ticket"), "time": num(r.get("time_utc")),
                            "symbol": r.get("symbol"), "type": r.get("type"), "entry": r.get("entry"),
                            "volume": num(r.get("volume")), "price": num(r.get("price")),
                            "net": (num(r.get("profit")) or 0) + (num(r.get("commission")) or 0) + (num(r.get("swap")) or 0),
                            "magic": r.get("magic"), "position_id": r.get("position_id")})
        return out

    async def calendar(self, start: float | None = None, end: float | None = None) -> list[dict]:
        data = read_tsv(self.folder() / "calendar.tsv")
        if not data or time.time() - data["ts"] > FRESH["calendar"]:
            return []
        return parse_mt5_calendar(data["rows"], start, end)


def parse_mt5_calendar(rows: list[dict], start: float | None = None, end: float | None = None) -> list[dict]:
    out = []
    for r in rows:
        ts = num(r.get("time_utc"))
        if ts is None or (start is not None and ts < start) or (end is not None and ts > end):
            continue
        unit = r.get("unit") or ""

        def fmt(v):
            return (v + unit) if v not in (None, "") else None
        out.append({"id": stable_id("mt5", r.get("value_id")), "ts": ts, "currency": r.get("currency", ""),
                    "country": r.get("country"), "title": r.get("name", ""),
                    "impact": IMPORTANCE.get(int(num(r.get("importance")) or 0), "low"),
                    "actual": fmt(r.get("actual")), "forecast": fmt(r.get("forecast")),
                    "previous": fmt(r.get("revised_previous") or r.get("previous")),
                    "actual_value": num(r.get("actual")), "forecast_value": num(r.get("forecast")),
                    "source": "mt5"})
    return out
