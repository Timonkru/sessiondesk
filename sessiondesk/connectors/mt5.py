"""MetaTrader 5 via exported files - read-only.

Two file formats are understood, from any number of folders (setting "folder", several paths
separated by ";"):

1. SessionDeskBridge (bridge/SessionDeskBridge.mq5), first line "#sessiondesk  version  kind  utc  offset  login":
     account_<login>.tsv  positions_<login>.tsv  quotes_<login>.tsv  eas_<login>.tsv  deals_<login>.tsv  calendar.tsv
2. The earlier "#updated" export format (headerless columns), as written by older exporter EAs:
     status_<login>.tsv    key/value lines (balance, equity, currency, server, connected, algo flags, any extra keys)
                           plus "chart  SYMBOL  PERIOD_X  ExpertName" lines = running EAs
     pos_<login>.tsv       symbol side lots open stop profit risk magic ticket money_per_pct position_id opened_utc
     px_<login>.tsv        symbol bid ask prev_close tick_server_time [prev_high prev_low overnight_high overnight_low]
                           (header field 4 = server offset in seconds)
     deals_<login>.tsv     time position_id symbol magic BUY|SELL entry volume profit cost
     calendar*.tsv         utc currency importance name actual forecast previous unit impact

No socket, no DLL, no order path. Files older than their freshness limit are reported as stale
instead of being shown as current.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .base import Connector, Field, stable_id

FRESH = {"account": 30, "positions": 30, "quotes": 30, "eas": 300, "deals": 900, "calendar": 900, "specs": 3600, "calhist": 3600}
LEGACY_FRESH = {"status": 120, "pos": 120, "px": 120, "deals": 900, "calendar": 900, "sym": 3600, "calhist": 3600}
WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
IMPORTANCE = {1: "low", 2: "medium", 3: "high"}
STATUS_CORE = {"balance", "equity", "currency", "server", "connected", "algo_terminal", "algo_account", "margin",
               "free_margin", "profit", "company", "leverage"}


def default_folder() -> str:
    if sys.platform.startswith("win"):
        return os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\Common\Files\SessionDesk")
    return str(Path.home() / ".wine/drive_c/users" / os.environ.get("USER", "user") / "AppData/Roaming/MetaQuotes/Terminal/Common/Files/SessionDesk")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mask(login: str, on: bool) -> str:
    return ("…" + login[-3:]) if on and login and len(login) > 3 else login


# ------------------------------------------------------------------ readers (pure, tested)
def read_tsv(path: Path) -> dict | None:
    """SessionDeskBridge format -> {'version', 'kind', 'ts', 'offset', 'login', 'rows': [dict]} or None."""
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


def read_legacy(path: Path) -> dict | None:
    """'#updated' format -> {'ts', 'head': [...], 'rows': [[...]]} or None."""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    if not lines or not lines[0].startswith("#updated"):
        return None
    head = lines[0].split("\t")
    ts = num(head[1]) if len(head) > 1 else None
    if ts is None:
        return None
    return {"ts": ts, "head": head, "rows": [ln.split("\t") for ln in lines[1:] if ln.strip()]}


def legacy_status(data: dict, login: str) -> tuple[dict, list[dict]]:
    """status_<login>.tsv -> (account fields, running EAs)."""
    kv, eas = {}, []
    for f in data["rows"]:
        if f[0] == "chart" and len(f) >= 4:
            eas.append({"symbol": f[1], "timeframe": f[2].replace("PERIOD_", ""), "expert": f[3]})
        elif len(f) >= 2:
            kv[f[0]] = f[1]
    acc = {"login": login, "server": kv.get("server"), "company": kv.get("company"), "currency": kv.get("currency"),
           "balance": num(kv.get("balance")), "equity": num(kv.get("equity")), "margin": num(kv.get("margin")),
           "free_margin": num(kv.get("free_margin")), "profit": num(kv.get("profit")),
           "connected": kv.get("connected") in ("1", "true", "True"),
           "trade_allowed": kv.get("algo_terminal", "1") in ("1", "true", "True") and kv.get("algo_account", "1") in ("1", "true", "True"),
           "extra": {k: v for k, v in kv.items() if k not in STATUS_CORE}}
    if acc["profit"] is None and acc["equity"] is not None and acc["balance"] is not None:
        acc["profit"] = acc["equity"] - acc["balance"]
    return acc, eas


def legacy_positions(data: dict, login: str) -> list[dict]:
    head = data["head"]
    equity = num(head[3]) if len(head) > 3 else None
    out = []
    for f in data["rows"]:
        if len(f) < 6 or f[1] not in ("LONG", "SHORT") or num(f[2]) is None:
            continue
        stop = num(f[4])
        risk = num(f[6]) if len(f) > 6 and f[6] else None
        out.append({"login": login, "symbol": f[0], "side": f[1], "volume": num(f[2]), "open_price": num(f[3]),
                    "sl": stop if stop and stop > 0 else None, "tp": None, "price": None, "profit": num(f[5]),
                    "risk_to_stop": risk if stop and stop > 0 else None, "magic": f[7] if len(f) > 7 else None,
                    "ticket": f[8] if len(f) > 8 else None, "money_per_pct": num(f[9]) if len(f) > 9 else None,
                    "position_id": f[10] if len(f) > 10 else None, "open_time": num(f[11]) if len(f) > 11 else None,
                    "equity": equity})
    return out


def legacy_quotes(data: dict) -> dict:
    head = data["head"]
    offset = num(head[3]) if len(head) > 3 else None
    out = {}
    for f in data["rows"]:
        if len(f) < 5:
            continue
        bid, ask, prev, ts = num(f[1]), num(f[2]), num(f[3]), num(f[4])
        if not bid or not ask or ask < bid:
            continue
        mid = (bid + ask) / 2
        levels = {k: num(f[i]) for i, k in ((5, "prev_high"), (6, "prev_low"), (7, "overnight_high"), (8, "overnight_low"))
                  if len(f) > i and num(f[i])}
        out[f[0]] = {"symbol": f[0], "bid": bid, "ask": ask, "price": mid, "prev_close": prev if prev and prev > 0 else None,
                     "change_pct": (mid / prev - 1) * 100 if prev and prev > 0 else None,
                     "time": ts - offset if ts is not None and offset is not None else None, **levels}
    return out


def legacy_deals(data: dict, login: str) -> list[dict]:
    out = []
    for f in data["rows"]:
        if len(f) < 9 or f[4] not in ("BUY", "SELL"):
            continue
        out.append({"login": login, "ticket": None, "time": num(f[0]), "position_id": f[1], "symbol": f[2], "magic": f[3],
                    "type": f[4], "entry": f[5], "volume": num(f[6]), "price": None,
                    "net": (num(f[7]) or 0) + (num(f[8]) or 0)})
    return out


def legacy_calendar(data: dict) -> list[dict]:
    rows = []
    for f in data["rows"]:
        if len(f) < 9:
            continue
        rows.append({"value_id": f"{f[0]}|{f[1]}|{f[3]}", "time_utc": f[0], "currency": f[1], "importance": f[2],
                     "name": f[3], "actual": f[4], "forecast": f[5], "previous": f[6], "unit": f[7]})
    return rows


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
                    "country": r.get("country"), "title": (r.get("name") or "").replace(" [time tentative]", ""),
                    "impact": IMPORTANCE.get(int(num(r.get("importance")) or 0), "low"),
                    "actual": fmt(r.get("actual")), "forecast": fmt(r.get("forecast")),
                    "previous": fmt(r.get("revised_previous") or r.get("previous")),
                    "actual_value": num(r.get("actual")), "forecast_value": num(r.get("forecast")),
                    "source": "mt5"})
    return out


# ------------------------------------------------------------------ connector
class MT5Bridge(Connector):
    id = "mt5"
    name = "MetaTrader 5 (bridge EA)"
    tier = "free"
    kind = "broker"
    capabilities = ("account", "positions", "eas", "calendar", "broker_quotes", "deals", "specs", "calhist")
    fields = (Field("folder", "Export folder(s)", secret=False, required=False,
                    help="Where the exporter writes. Several folders separated by ';'. Default: MT5 common folder \\Files\\SessionDesk.",
                    placeholder=default_folder()),)
    homepage = "https://www.metatrader5.com"
    description = ("Read-only: accounts, open positions with risk to stop, running EAs, Market Watch quotes, closed deals and "
                   "the MetaQuotes calendar with actual values within ~2 s of release. Reads SessionDeskBridge files and the "
                   "earlier '#updated' export format.")

    def folders(self) -> list[Path]:
        raw = self.option("folder") or default_folder()
        out = []
        for part in str(raw).replace("\n", ";").split(";"):
            part = os.path.expandvars(part.strip())
            if part:
                out.append(Path(part))
        return out

    def configured(self) -> bool:
        return any(f.is_dir() for f in self.folders())

    def _hide(self) -> bool:
        return bool(self.ctx.settings.get("privacy.mask_accounts", True))

    def _new(self, prefix: str) -> list[dict]:
        out = []
        for folder in self.folders():
            for path in sorted(folder.glob(f"{prefix}_*.tsv")):
                data = read_tsv(path)
                if data:
                    data["age"] = time.time() - data["ts"]
                    data["fresh"] = data["age"] <= FRESH.get(data["kind"], 60)
                    out.append(data)
        return out

    def _old(self, prefix: str, kind: str) -> list[tuple[str, dict]]:
        """[(login, data)] for '#updated' files; a fresher copy of the same login in another folder wins."""
        best: dict[str, dict] = {}
        for folder in self.folders():
            for path in sorted(folder.glob(f"{prefix}_*.tsv")):
                data = read_legacy(path)
                if not data:
                    continue
                login = path.stem.split("_", 1)[1]
                data["age"] = time.time() - data["ts"]
                data["fresh"] = data["age"] <= LEGACY_FRESH[kind]
                if login not in best or data["ts"] > best[login]["ts"]:
                    best[login] = data
        return sorted(best.items())

    async def test(self) -> dict:
        folders = [f for f in self.folders() if f.is_dir()]
        if not folders:
            return {"ok": False, "detail": "no export folder found - attach SessionDeskBridge to a chart or set the folder"}
        accounts = await self.account()
        fresh = [a for a in accounts if a["fresh"]]
        if not accounts:
            return {"ok": False, "detail": f"{len(folders)} folder(s), but no account files yet"}
        return {"ok": True, "detail": f"{len(accounts)} account(s), {len(fresh)} fresh" + ("" if fresh else " - is MetaTrader running?")}

    async def account(self) -> list[dict]:
        hide, out, seen = self._hide(), [], set()
        for f in self._new("account"):
            for r in f["rows"]:
                seen.add(r.get("login"))
                out.append({"login": mask(r.get("login", ""), hide), "server": r.get("server"), "company": r.get("company"),
                            "currency": r.get("currency"), "balance": num(r.get("balance")), "equity": num(r.get("equity")),
                            "margin": num(r.get("margin")), "free_margin": num(r.get("free_margin")),
                            "profit": num(r.get("profit")), "leverage": num(r.get("leverage")),
                            "trade_allowed": r.get("trade_allowed") == "1", "connected": r.get("connected") == "1",
                            "age": f["age"], "fresh": f["fresh"], "bridge": f["version"], "extra": {}})
        for login, data in self._old("status", "status"):
            if login in seen:
                continue
            acc, _eas = legacy_status(data, login)
            acc.update({"login": mask(login, hide), "age": data["age"], "fresh": data["fresh"], "bridge": "export v0"})
            out.append(acc)
        return out

    async def positions(self) -> list[dict]:
        hide, out, seen = self._hide(), [], set()
        for f in self._new("positions"):
            seen.add(f["login"])
            for r in f["rows"]:
                out.append({"account": mask(f["login"], hide), "ticket": r.get("ticket"), "symbol": r.get("symbol"),
                            "side": r.get("side"), "volume": num(r.get("volume")), "open_price": num(r.get("open_price")),
                            "open_time": num(r.get("open_time_utc")), "sl": num(r.get("sl")) or None, "tp": num(r.get("tp")) or None,
                            "price": num(r.get("price")), "profit": num(r.get("profit")), "swap": num(r.get("swap")),
                            "magic": r.get("magic"), "comment": r.get("comment"),
                            "risk_to_stop": num(r.get("risk_to_stop")), "manual": r.get("magic") in ("0", ""),
                            "money_per_pct": num(r.get("money_per_pct")), "fresh": f["fresh"], "age": f["age"]})
        for login, data in self._old("pos", "pos"):
            if login in seen:
                continue
            for p in legacy_positions(data, login):
                p.update({"account": mask(login, hide), "manual": p.get("magic") in ("0", "", None),
                          "fresh": data["fresh"], "age": data["age"]})
                p.pop("login", None)
                out.append(p)
        return out

    async def eas(self) -> list[dict]:
        hide, out, seen = self._hide(), [], set()
        for f in self._new("eas"):
            seen.add(f["login"])
            for r in f["rows"]:
                out.append({"account": mask(f["login"], hide), "symbol": r.get("symbol"), "timeframe": r.get("timeframe"),
                            "expert": r.get("expert"), "fresh": f["fresh"], "age": f["age"]})
        for login, data in self._old("status", "status"):
            if login in seen:
                continue
            for e in legacy_status(data, login)[1]:
                out.append({"account": mask(login, hide), **e, "fresh": data["fresh"], "age": data["age"]})
        return out

    async def broker_quotes(self) -> dict:
        out = {}
        for f in self._new("quotes"):
            if not f["fresh"]:
                continue
            for r in f["rows"]:
                bid, ask, prev = num(r.get("bid")), num(r.get("ask")), num(r.get("prev_close"))
                if bid is None or ask is None:
                    continue
                mid = (bid + ask) / 2
                out[r["symbol"]] = {"symbol": r["symbol"], "bid": bid, "ask": ask, "price": mid, "prev_close": prev,
                                    "change_pct": (mid / prev - 1) * 100 if prev else None, "time": num(r.get("time_utc"))}
        for _login, data in self._old("px", "px"):
            if data["fresh"]:
                for sym, q in legacy_quotes(data).items():
                    out.setdefault(sym, q)
        return out

    async def deals(self) -> list[dict]:
        hide, out, seen = self._hide(), [], set()
        for f in self._new("deals"):
            seen.add(f["login"])
            for r in f["rows"]:
                out.append({"account": mask(f["login"], hide), "ticket": r.get("ticket"), "time": num(r.get("time_utc")),
                            "symbol": r.get("symbol"), "type": r.get("type"), "entry": r.get("entry"),
                            "volume": num(r.get("volume")), "price": num(r.get("price")),
                            "net": (num(r.get("profit")) or 0) + (num(r.get("commission")) or 0) + (num(r.get("swap")) or 0),
                            "magic": r.get("magic"), "position_id": r.get("position_id")})
        for login, data in self._old("deals", "deals"):
            if login in seen:
                continue
            for d in legacy_deals(data, login):
                d["account"] = mask(login, hide)
                d.pop("login", None)
                out.append(d)
        return out

    async def calendar(self, start: float | None = None, end: float | None = None) -> list[dict]:
        rows = []
        for folder in self.folders():
            for path in sorted(folder.glob("calendar*.tsv")):
                new = read_tsv(path)
                if new and time.time() - new["ts"] <= FRESH["calendar"]:
                    rows += new["rows"]
                    continue
                old = read_legacy(path)
                if old and time.time() - old["ts"] <= LEGACY_FRESH["calendar"]:
                    rows += legacy_calendar(old)
        seen, unique = set(), []
        for r in rows:
            key = (r.get("time_utc"), r.get("currency"), r.get("name"))
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return parse_mt5_calendar(unique, start, end)

    async def specs(self) -> list[dict]:
        """Instrument sheet per account: spread, money per point, swaps, triple-swap day, sizes."""
        hide, out, seen = self._hide(), [], set()
        for f in self._new("specs"):
            seen.add(f["login"])
            for r in f["rows"]:
                point = num(r.get("point")) or 0
                per_unit = num(r.get("money_per_unit"))
                out.append({"account": mask(f["login"], hide), "symbol": r.get("symbol"),
                            "spread_points": num(r.get("spread_points")),
                            "spread_price": (num(r.get("spread_points")) or 0) * point if point else None,
                            "money_per_unit": per_unit, "contract": num(r.get("contract_size")),
                            "min_lot": num(r.get("volume_min")), "lot_step": num(r.get("volume_step")),
                            "swap_long": num(r.get("swap_long")), "swap_short": num(r.get("swap_short")),
                            "swap_mode": r.get("swap_mode"), "triple_day": WEEKDAYS[int(num(r.get("triple_day")) or 0) % 7],
                            "currency": r.get("currency_profit"), "fresh": f["fresh"]})
        for login, data in self._old("sym", "sym"):
            if login in seen:
                continue
            for f in data["rows"]:
                if len(f) < 12:
                    continue
                out.append({"account": mask(login, hide), "symbol": f[0], "spread_points": num(f[1]), "spread_bp": num(f[2]),
                            "money_per_unit": num(f[3]), "swap_long": num(f[4]), "swap_short": num(f[5]), "swap_mode": f[6],
                            "swap_long_money": num(f[7]), "swap_short_money": num(f[8]),
                            "triple_day": WEEKDAYS[int(num(f[9]) or 0) % 7], "min_lot": num(f[10]), "contract": num(f[11]),
                            "currency": data["head"][3] if len(data["head"]) > 3 else "", "fresh": data["fresh"]})
        return out

    async def calhist(self) -> dict[str, dict]:
        """{event key: {currency, name, unit, releases: [{ts, actual, forecast, previous, surprise}]}}"""
        events: dict[str, dict] = {}

        def add(key, currency, name, unit, ts, actual, forecast, previous):
            ts, a, fc = num(ts), num(actual), num(forecast)
            if ts is None or a is None:
                return
            ev = events.setdefault(key, {"currency": currency, "name": name.replace(" [time tentative]", ""), "unit": unit, "releases": []})
            if any(r["ts"] == ts for r in ev["releases"]):
                return
            ev["releases"].append({"ts": ts, "actual": a, "forecast": fc, "previous": num(previous),
                                   "surprise": a - fc if fc is not None else None})
        for folder in self.folders():
            path = folder / "calhist.tsv"
            new = read_tsv(path)
            if new:
                for r in new["rows"]:
                    add(f"{r.get('currency')}|{r.get('name')}", r.get("currency", ""), r.get("name", ""), r.get("unit", ""),
                        r.get("time_utc"), r.get("actual"), r.get("forecast"), r.get("previous"))
                continue
            old = read_legacy(path)
            if old:
                for f in old["rows"]:
                    if len(f) >= 8:
                        add(f"{f[1]}|{f[2]}", f[1], f[2], f[7], f[3], f[4], f[5], f[6])
        for ev in events.values():
            ev["releases"].sort(key=lambda r: -r["ts"])
        return events
