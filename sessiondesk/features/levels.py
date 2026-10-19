"""Level ladder and level alerts.

Levels come from three places:
  1. level files you register (settings["level_files"]): e.g. dealer-gamma levels (flip, call wall,
     put wall) as written by the open-source gamma-seed / crypto-levels-seed projects, or any text file
     with lines "ASSET label value" ("DAX pivot 24510")
  2. round numbers per market (settings["round_steps"], e.g. DAX 1000, GOLD 100, FX 0.01)
  3. session levels: previous-day high/low and overnight range, from the broker export if it provides
     them, otherwise previous-day high/low from daily bars

An alert fires when the price CROSSES a level between two polls; each level is silenced for
`cooldown` seconds afterwards so a price chopping around it does not spam. Broker CFD prices and
futures/index levels can differ by the basis - the ladder shows which price it used.
"""
from __future__ import annotations

import math
import os
import re
import time
from pathlib import Path

from ..connectors.base import stable_id
from . import assets

GAMMA_LINE = re.compile(r"^\s*([A-Z0-9]{2,10})\s+(STRUKT|STRUCT|NAH|NEAR)\s*\|", re.I)
CRYPTO_LINE = re.compile(r"^\s*(BTC|ETH)\s")
GENERIC_LINE = re.compile(r"^\s*([A-Z][A-Z0-9:]{1,9})\s+([A-Za-z][\w .()/-]{0,40}?)\s+(-?\d+(?:\.\d+)?)\s*$")


def parse_level_text(text: str) -> dict[str, list[tuple[str, float]]]:
    """{asset: [(label, price)]} from gamma-seed, crypto-levels-seed or generic 'ASSET label value' lines."""
    out: dict[str, list[tuple[str, float]]] = {}

    def add(asset, label, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if math.isfinite(v) and v > 0:
            out.setdefault(asset.upper(), []).append((label, v))
    for ln in text.splitlines():
        m = GAMMA_LINE.match(ln)
        if m:
            near = "near " if m.group(2).upper() in ("NAH", "NEAR") else ""
            for key, label in (("Flip", "gamma flip"), ("CW", "call wall"), ("PW", "put wall")):
                hit = re.search(rf"\b{key} ([\d.]+)(?: \(2nd ([\d.]+)\))?", ln)
                if hit:
                    add(m.group(1), near + label, hit.group(1))
                    if hit.group(2):
                        add(m.group(1), near + label + " 2nd", hit.group(2))
            continue
        m = CRYPTO_LINE.match(ln)
        if m and "|" in ln:
            flip = re.search(r"Flip (\d+(?:\.\d+)?)", ln)
            if flip:
                add(m.group(1), "gamma flip", flip.group(1))
            for key, label in (("CW", "call wall"), ("PW", "put wall")):
                hit = re.search(rf"{key} (\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", ln)
                if hit:
                    add(m.group(1), label, hit.group(1))
                    add(m.group(1), label + " 2nd", hit.group(2))
            continue
        m = GENERIC_LINE.match(ln)
        if m:
            add(m.group(1), m.group(2).strip().lower(), m.group(3))
    return out


def read_level_files(settings) -> dict:
    """{'levels': {asset: [(label, value, source)]}, 'files': [{title, path, age_h, fresh, error}]}"""
    max_age = float(settings.get("level_max_age_hours") or 96) * 3600
    levels: dict[str, list[tuple[str, float, str]]] = {}
    files = []
    for spec in settings.get("level_files") or []:
        path = Path(os.path.expandvars(str(spec.get("path", "")))).expanduser()
        info = {"title": spec.get("title") or path.name, "path": str(path)}
        try:
            age = time.time() - path.stat().st_mtime
            info["age_h"] = age / 3600
            info["fresh"] = age <= max_age
            parsed = parse_level_text(path.read_text(encoding="utf-8", errors="replace"))
            info["assets"] = sorted(parsed)
            if info["fresh"]:
                for asset, rows in parsed.items():
                    levels.setdefault(asset, []).extend((label, v, info["title"]) for label, v in rows)
        except OSError as exc:
            info["error"] = str(exc)
            info["fresh"] = False
        files.append(info)
    return {"levels": levels, "files": files}


def round_levels(price: float, step: float) -> list[tuple[str, float, str]]:
    if not price or not step or step <= 0 or not math.isfinite(price):
        return []
    below = math.floor(price / step) * step
    fmt = (lambda v: f"{v:.4f}".rstrip("0").rstrip(".")) if step < 1 else (lambda v: f"{v:.0f}")
    return [(f"round {fmt(v)}", v, "round numbers") for v in (below, below + step) if v > 0]


def session_levels(quote: dict) -> list[tuple[str, float, str]]:
    out = []
    for key, label in (("prev_high", "prev day high"), ("prev_low", "prev day low"),
                       ("overnight_high", "overnight high"), ("overnight_low", "overnight low")):
        v = quote.get(key)
        if v and v > 0:
            out.append((label, float(v), "session"))
    return out


def levels_for(asset: str, price: float, quote: dict, files: dict, settings) -> list[tuple[str, float, str]]:
    lv = list(files.get(asset, [])) + session_levels(quote) + round_levels(price, assets.round_step(asset, settings))
    seen, out = set(), []
    for label, v, src in lv:
        key = (label, round(v, 6))
        if key not in seen:
            seen.add(key)
            out.append((label, v, src))
    return out


async def price_sources(ctx) -> dict[str, dict]:
    """{key: {symbol, asset, price, source, prev_high...}} - broker quotes when fresh, else free quotes for the level markets."""
    out: dict[str, dict] = {}
    mt5 = ctx.hub.get("mt5")
    if mt5 and mt5.active():
        try:
            for sym, q in (await mt5.broker_quotes()).items():
                asset = assets.asset_of(sym, ctx.settings)
                if asset:
                    out[f"mt5:{sym}"] = {**q, "symbol": sym, "asset": asset, "source": "broker"}
        except Exception:
            pass
    covered = {q["asset"] for q in out.values()}
    wanted = [a for a in (ctx.settings.get("level_markets") or []) if a not in covered]
    tickers = {assets.yahoo_ticker(a): a for a in wanted if assets.yahoo_ticker(a)}
    if tickers:
        from .markets import get_quotes
        res = await get_quotes(ctx, list(tickers), intraday=False)
        for t, q in (res.get("quotes") or {}).items():
            out[f"yahoo:{t}"] = {**q, "symbol": t, "asset": tickers[t], "source": "yahoo (delayed)"}
    return out


def ladder(prices: dict[str, dict], files: dict, settings) -> list[dict]:
    rows = []
    for key, q in sorted(prices.items(), key=lambda kv: kv[1]["asset"]):
        price = q.get("price")
        if not price:
            continue
        lv = levels_for(q["asset"], price, q, files, settings)
        above = sorted([x for x in lv if x[1] > price], key=lambda x: x[1])
        below = sorted([x for x in lv if x[1] <= price], key=lambda x: -x[1])
        rows.append({"key": key, "symbol": q["symbol"], "asset": q["asset"], "price": price, "source": q.get("source"),
                     "change_pct": q.get("change_pct"),
                     "above": [{"label": l, "level": v, "src": s, "dist": v - price, "dist_pct": (v / price - 1) * 100} for l, v, s in above[:4]],
                     "below": [{"label": l, "level": v, "src": s, "dist": v - price, "dist_pct": (v / price - 1) * 100} for l, v, s in below[:4]],
                     "has_file_levels": q["asset"] in files})
    return rows


class LevelAlerter:
    """Crossing alerts with two noise guards (live test 19.10.2026: one FTSE level fired 6 times in 50 minutes,
    each time twice because two accounts quote the same market under two symbols):
      - one market, one alert: the same level label on GER40 and GER40.cash counts once (keyed by asset);
      - re-arm only after the price moved away from the level by `level_rearm_pct` (default 0.1 %),
        so a price chopping around a level does not fire again and again. The cooldown stays as a backstop."""

    def __init__(self, cooldown: float = 600):
        self.cooldown = cooldown
        self.last: dict[str, float] = {}
        self.fired: dict[tuple, float] = {}
        self.disarmed: dict[tuple, float] = {}           # (asset, label) -> level it fired at

    def _rearm(self, asset: str, price: float, pct: float) -> None:
        for mark, level in list(self.disarmed.items()):
            if mark[0] == asset and level and abs(price - level) / abs(level) * 100 >= pct:
                del self.disarmed[mark]

    def check(self, prices: dict[str, dict], files: dict, settings, now: float | None = None) -> list[dict]:
        now = now or time.time()
        out = []
        rearm_pct = float(settings.get("level_rearm_pct") or 0.1)
        self.last = {k: v for k, v in self.last.items() if k in prices}      # reconnect = new baseline, no alert across gaps
        for key, q in prices.items():
            price, before = q.get("price"), self.last.get(key)
            if not price:
                continue
            self.last[key] = price
            self._rearm(q["asset"], price, rearm_pct)
            if before is None or before == price:
                continue
            lv = levels_for(q["asset"], before, q, files, settings)
            step = assets.round_step(q["asset"], settings)
            if step > 0:                                   # every round number jumped over, not just the neighbours
                lo, hi = sorted((before, price))
                k0, k1 = math.floor(lo / step) + 1, math.floor(hi / step)
                for k in range(k0, min(k1, k0 + 50) + 1):
                    lv.append((f"round {k * step:g}", k * step, "round numbers"))
            for label, level, src in dict.fromkeys(lv):
                if (before - level) * (price - level) < 0 or (price == level != before):
                    mark = (q["asset"], label)
                    if mark in self.disarmed or now - self.fired.get(mark, 0) < self.cooldown:
                        continue
                    self.fired[mark] = now
                    self.disarmed[mark] = level
                    out.append({"id": stable_id("level", key, label, round(level, 6), int(now // self.cooldown)), "ts": now,
                                "symbol": q["symbol"], "asset": q["asset"], "label": label, "level": level, "src": src,
                                "price": price, "direction": "up" if price > before else "down", "source": q.get("source")})
        return out


async def snapshot(ctx) -> dict:
    files = read_level_files(ctx.settings)
    prices = await price_sources(ctx)
    return {"rows": ladder(prices, files["levels"], ctx.settings), "files": files["files"],
            "markets": ctx.settings.get("level_markets") or [], "asof": time.time()}
