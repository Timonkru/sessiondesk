"""MQL5 Virtual Hosting (VPS) status, read from the logs your local MetaTrader 5 terminal syncs.

The hosted terminal cannot write files SessionDesk could read, but the local terminal downloads the VPS
journals into <terminal data dir>/Logs/hosting.<id>.terminal and .experts (UTF-16 text, one file per day).
From them: the hourly heartbeat ("8 charts, 8 EAs"), which EAs were loaded or removed, deals, connection
drops, and warnings the EAs print. Read-only, and only as fresh as the last sync of the local terminal.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

LINE = re.compile(r"^\w{2}\t(\d)\t(\d\d:\d\d:\d\d)\.\d+\t([^\t]+)\t(.*)$")
HEARTBEAT = re.compile(r"'(\d+)': (\d+) charts?, (\d+) EAs?")
DEAL = re.compile(r"'(\d+)': deal #(\d+) (buy|sell) ([\d.]+) (\S+) at ([\d.]+) done")
EXPERT = re.compile(r"expert (\S+) \((\S+?),(\w+)\) (loaded successfully|removed)")
SOURCE = re.compile(r"^(\S+) \((\S+?),(\w+)\)$")
TZ = re.compile(r"\b(GMT[+-]\d{1,2})\b")
WARN = re.compile(r"\b(error|failed|failure|missing|cannot|invalid|rejected|denied|not enough|no connection)\b", re.I)
RECENT_DAYS = 14


def hosting_dirs(settings) -> list[Path]:
    """Terminal data dirs from the MT5 connector folders (…/MQL5/Files) plus the standard Windows location."""
    roots: set[Path] = set()
    for folder in str(settings.get("connectors.mt5.folder") or "").replace("\n", ";").split(";"):
        if not folder.strip():
            continue
        p = Path(os.path.expandvars(folder.strip())).expanduser()
        for parent in [p, *p.parents][:4]:
            if (parent / "Logs").is_dir():
                roots.add(parent)
                break
    appdata = os.environ.get("APPDATA")
    if appdata and (Path(appdata) / "MetaQuotes" / "Terminal").is_dir():
        roots.update(d for d in (Path(appdata) / "MetaQuotes" / "Terminal").iterdir() if (d / "Logs").is_dir())
    out = []
    for root in roots:
        out += [d for d in (root / "Logs").glob("hosting.*.terminal") if d.is_dir()]
    return sorted(out)


def read_tail(path: Path, max_bytes: int = 400_000) -> list[str]:
    """Last lines of a UTF-16 log without reading huge files whole."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        start = max(0, size - max_bytes)
        start -= start % 2                          # stay on a UTF-16 code unit
        fh.seek(start)
        raw = fh.read()
    text = raw.decode("utf-16-le", errors="ignore").lstrip("\ufeff")
    lines = text.splitlines()
    return lines[1:] if start else lines            # the first line may be cut


def day_files(folder: Path, n: int = 3) -> list[Path]:
    return sorted(folder.glob("*.log"))[-n:] if folder.is_dir() else []


def parse_terminal(files: list[tuple[str, list[str]]]) -> dict:
    out = {"heartbeat": None, "deals": [], "eas": {}, "drops": 0, "restarts": 0, "warnings": [], "tz": None, "last": None}
    for day, lines in files:
        for ln in lines:
            m = LINE.match(ln)
            if not m:
                continue
            flag, hms, src, msg = m.groups()
            stamp = f"{day[:4]}-{day[4:6]}-{day[6:]} {hms}"
            out["last"] = stamp
            if (t := TZ.search(msg)) and "started" not in msg:
                out["tz"] = t.group(1)
            if (h := HEARTBEAT.search(msg)) and src == "Terminal":
                out["heartbeat"] = {"time": stamp, "account": h.group(1), "charts": int(h.group(2)), "eas": int(h.group(3))}
            elif (d := DEAL.search(msg)):
                out["deals"].append({"time": stamp, "account": d.group(1), "deal": d.group(2), "side": d.group(3),
                                     "volume": float(d.group(4)), "symbol": d.group(5), "price": float(d.group(6))})
            elif (e := EXPERT.search(msg)):
                key = (e.group(1), e.group(2), e.group(3))
                if e.group(4) == "removed":
                    out["eas"].pop(key, None)
                else:
                    out["eas"][key] = {"ea": e.group(1), "symbol": e.group(2), "timeframe": e.group(3), "loaded": stamp}
            elif "connection to" in msg and "lost" in msg:
                out["drops"] += 1
            elif msg.startswith("MetaTrader 5") and "started" in msg:
                out["restarts"] += 1
            if flag != "0" and "connection to" not in msg:
                out["warnings"].append({"time": stamp, "source": src, "text": msg[:240]})
    out["deals"] = out["deals"][-15:][::-1]
    out["warnings"] = out["warnings"][-10:][::-1]
    return out


def parse_experts(files: list[tuple[str, list[str]]]) -> dict:
    last, warnings = {}, []
    for day, lines in files:
        for ln in lines:
            m = LINE.match(ln)
            if not m:
                continue
            _flag, hms, src, msg = m.groups()
            stamp = f"{day[:4]}-{day[4:6]}-{day[6:]} {hms}"
            s = SOURCE.match(src)
            if s:
                last[(s.group(1), s.group(2), s.group(3))] = {"time": stamp, "message": msg[:240]}
            if WARN.search(msg):
                warnings.append({"time": stamp, "source": src, "text": msg[:240]})
    return {"last": last, "warnings": warnings[-10:][::-1]}


def status(settings, now: float | None = None) -> dict:
    now = now or time.time()
    out = []
    for term_dir in hosting_dirs(settings):
        files = day_files(term_dir)
        if not files or now - files[-1].stat().st_mtime > RECENT_DAYS * 86400:
            continue                                                   # an old hosting subscription
        exp_dir = term_dir.with_name(term_dir.name.replace(".terminal", ".experts"))
        term = parse_terminal([(f.stem, read_tail(f)) for f in files])
        exp = parse_experts([(f.stem, read_tail(f)) for f in day_files(exp_dir, 2)])
        loaded = term["eas"] or {k: {"ea": k[0], "symbol": k[1], "timeframe": k[2], "loaded": None} for k in exp["last"]}
        eas = []                     # loads seen in the last days; otherwise the EAs that wrote to the journal recently
        for key, ea in sorted(loaded.items()):
            info = exp["last"].get(key, {})
            eas.append({**ea, "last_message": info.get("message"), "last_time": info.get("time")})
        out.append({"id": term_dir.name.split(".")[1], "synced_ago": now - max(f.stat().st_mtime for f in files),
                    "heartbeat": term["heartbeat"], "timezone": term["tz"], "last_line": term["last"], "eas": eas,
                    "deals": term["deals"], "drops": term["drops"], "restarts": term["restarts"],
                    "warnings": (exp["warnings"] + term["warnings"])[:12]})
    return {"hostings": out, "note": "Read from the VPS journals your local MetaTrader 5 terminal synchronises (Logs/hosting.*). "
                                     "As fresh as the last sync; times are the VPS clock. Read-only."}
