"""Index internals: breadth, divergences, who drives the index, bottom-up valuation, S&P 500 FactSet anchor, put/call.

Breadth (from one year of member closes, refreshed hourly):
  % of members up today, above their 50- and 200-day averages, at new 20-day / 52-week highs and lows,
  plus a 60-day breadth line (% above the 50-day average per day) next to the index.
Divergence flag: index at or near a 20-day high while breadth has fallen by 10+ points over 20 days
  (or the mirror image at lows) - a description of narrowing participation, not a timing signal.
Drivers: price-weighted Dow - each member's dollar move is its share of the index's point move;
  cap-weighted indices - the move times market cap (from cached profiles) approximates the contribution.
Valuation: bottom-up forward P/E (sum of caps / sum of forward earnings), coverage shown, implausible
  vendor P/Es excluded and listed; recorded once a day so an own history builds up.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import re
import statistics
import time

from . import universe

INDEX_SYMBOL = universe.BENCHMARK            # every bundled universe has its index
PRICE_WEIGHTED = {"dow30"}
# Price-weighted with price adjustment factors that are not in free data (Nikkei 225): neither the Dow divisor logic
# nor market-cap weights describe it, so its drivers are plain movers and there is no bottom-up valuation.
UNWEIGHTED = {"nikkei225"}
NO_PROFILES = {"sp500", "nikkei225", "asx200"}      # too many members for the free profile source
MIN_PE, MAX_PE = 1.0, 400.0


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


# ------------------------------------------------------------------ breadth (pure, tested)
def breadth(closes: dict[str, list[float]], index_closes: list[float]) -> dict:
    rows = []
    for sym, c in closes.items():
        if len(c) < 60:
            continue
        last, prev = c[-1], c[-2]
        sma50 = statistics.mean(c[-50:])
        sma200 = statistics.mean(c[-200:]) if len(c) >= 200 else None
        rows.append({"symbol": sym, "pct": (last / prev - 1) * 100, "abs": last - prev, "last": last,
                     "above50": last > sma50, "above200": (last > sma200) if sma200 else None,
                     "high20": last >= max(c[-20:]), "low20": last <= min(c[-20:]),
                     "high52": last >= max(c[-252:]), "low52": last <= min(c[-252:])})
    if not rows:
        return {}
    n = len(rows)
    has200 = [r for r in rows if r["above200"] is not None]
    # breadth line: % above own 50-day average for each of the last 60 sessions
    line = []
    # recent listings join the count once they have 50 closes; they must not shorten the line for everyone
    span = min(60, max(len(c) for c in closes.values()) - 50)
    for k in range(span, 0, -1):
        above = total = 0
        for c in closes.values():
            if len(c) < 50 + k:
                continue
            window = c[-(50 + k): -k] if k > 0 else c[-50:]
            price = c[-k - 1] if k > 0 else c[-1]
            total += 1
            above += price > statistics.mean(window)
        if total:
            line.append(above / total * 100)
    line.append(sum(r["above50"] for r in rows) / n * 100)
    out = {"n": n, "up": sum(r["pct"] > 0 for r in rows), "down": sum(r["pct"] < 0 for r in rows),
           "up_pct": sum(r["pct"] > 0 for r in rows) / n * 100,
           "above50_pct": sum(r["above50"] for r in rows) / n * 100,
           "above200_pct": sum(r["above200"] for r in has200) / len(has200) * 100 if has200 else None,
           "new_high20": sum(r["high20"] for r in rows), "new_low20": sum(r["low20"] for r in rows),
           "new_high52": sum(r["high52"] for r in rows), "new_low52": sum(r["low52"] for r in rows),
           "equal_weight_move": statistics.mean(r["pct"] for r in rows), "line": line[-61:], "rows": rows}
    if len(index_closes) >= 21:
        out["index_line"] = [c for c in index_closes[-len(out["line"]):]]
        idx20 = index_closes[-1] / index_closes[-21] - 1
        near_high = index_closes[-1] >= max(index_closes[-20:]) * 0.99
        near_low = index_closes[-1] <= min(index_closes[-20:]) * 1.01
        b20 = out["line"][-1] - out["line"][-21] if len(out["line"]) >= 21 else None
        out["index_20d"] = idx20 * 100
        out["breadth_20d_pts"] = b20
        if b20 is not None and near_high and idx20 > 0 and b20 <= -10:
            out["divergence"] = "bearish: index near its 20-day high while the share above the 50-day average fell " \
                                f"{abs(b20):.0f} points - fewer stocks carry the advance"
        elif b20 is not None and near_low and idx20 < 0 and b20 >= 10:
            out["divergence"] = "bullish: index near its 20-day low while breadth improved " \
                                f"{b20:.0f} points - selling is narrowing"
    return out


def drivers(rows: list[dict], caps: dict[str, float], price_weighted: bool, divisor: float | None) -> list[dict]:
    """Contribution per member. Dow: dollar move / Dow divisor = index points (the index's own definition).
    Cap-weighted: move x cap share. (Live test 19.10.2026: sharing out the index's point move by dollar moves flipped
    every sign when the index quote and the member quotes were taken at slightly different times.)"""
    out = []
    if price_weighted:
        for r in rows:
            out.append({**r, "points": r["abs"] / divisor if divisor else None, "basis": "dollar move / divisor"})
    else:
        total_cap = sum(caps.get(r["symbol"], 0) for r in rows)
        for r in rows:
            cap = caps.get(r["symbol"])
            out.append({**r, "weight": cap / total_cap if cap and total_cap else None,
                        "contrib_pct": (cap / total_cap) * r["pct"] if cap and total_cap else None, "basis": "market cap"})
    key = "points" if price_weighted else "contrib_pct"
    return sorted([r for r in out if r.get(key) is not None], key=lambda r: r[key])


def class_caps(profiles: list[dict]) -> dict[str, float]:
    """Market cap per member. Share classes of one company (GOOG/GOOGL) each report the whole company's cap,
    which would count it twice - for those, the class's own shares x price is used instead."""
    names: dict[str, int] = {}
    for p in profiles:
        if p.get("name"):
            names[p["name"]] = names.get(p["name"], 0) + 1
    out = {}
    for p in profiles:
        cap, shares, px = _f(p.get("market_cap")), _f(p.get("shares")), _f(p.get("price") or p.get("market_price"))
        if names.get(p.get("name"), 0) > 1 and shares and px:
            cap = shares * px
        if cap:
            out[p["symbol"]] = cap
    return out


PERIODS = {"1d": 1, "1w": 5, "1m": 21}                # trading sessions per period


def period_rows(closes: dict[str, list[float]], k: int) -> list[dict]:
    """Per member: move over the last k sessions (percent and price units)."""
    out = []
    for sym, c in closes.items():
        if len(c) > k and c[-1 - k]:
            out.append({"symbol": sym, "pct": (c[-1] / c[-1 - k] - 1) * 100, "abs": c[-1] - c[-1 - k], "last": c[-1]})
    return out


def driver_block(rows: list[dict], caps: dict, price_weighted: bool, idx: list[float], k: int) -> dict:
    points = (idx[-1] - idx[-1 - k]) if len(idx) > k else None
    # Dow divisor from the data itself: sum of member prices / index level (exact by definition, up to quote timing)
    divisor = sum(r["last"] for r in rows) / idx[-1] if price_weighted and idx and idx[-1] else None
    drv = drivers(rows, caps, price_weighted, divisor)
    sort_key = "points" if price_weighted else "contrib_pct"
    if not drv:                                           # no caps (S&P 500 in the free set): plain movers instead
        drv, sort_key = sorted(rows, key=lambda r: r["pct"]), "pct"
    return {"sessions": k, "index_move_pct": (idx[-1] / idx[-1 - k] - 1) * 100 if len(idx) > k and idx[-1 - k] else None,
            "index_points": points, "contrib_total": sum(r[sort_key] for r in drv) if sort_key in ("contrib_pct", "points") else None,
            "divisor": divisor,
            "drivers_down": [r for r in drv if r[sort_key] < 0][:8], "drivers_up": [r for r in drv[::-1] if r[sort_key] > 0][:8]}


def aggregate_pe(profiles: list[dict], price_weighted: bool) -> dict | None:
    used, rejected = [], []
    for p in profiles:
        pe, cap = _f(p.get("pe_forward")), _f(p.get("market_cap"))
        if pe is None or not cap:
            continue
        if not MIN_PE <= abs(pe) <= MAX_PE:
            rejected.append(f"{p.get('symbol')} ({pe:.1f})")
            continue
        used.append({"symbol": p.get("symbol"), "pe": pe, "cap": cap, "price": _f(p.get("price") or p.get("market_price")),
                     "eps": _f(p.get("eps_forward"))})
    if not used:
        return None
    if price_weighted:
        rows = [u for u in used if u["price"] and u["eps"]]
        if not rows:
            return None
        pe = sum(u["price"] for u in rows) / sum(u["eps"] for u in rows)
    else:
        earnings = sum(u["cap"] / u["pe"] for u in used)
        if earnings <= 0:
            return None
        pe = sum(u["cap"] for u in used) / earnings
    return {"fwd_pe": pe, "earnings_yield": 100 / pe, "median_pe": statistics.median(u["pe"] for u in used),
            "used": len(used), "rejected": rejected}


def record_history(path, index: str, pe: float, day: str) -> dict:
    try:
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError):
        rows = []
    if not any(r.get("date") == day and r.get("index") == index for r in rows):
        rows.append({"date": day, "index": index, "fwd_pe": round(pe, 3)})
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rows[-1]) + "\n")
        except OSError:
            pass
    vals = [r["fwd_pe"] for r in rows if r.get("index") == index]
    return {"n": len(vals), "since": min((r["date"] for r in rows if r.get("index") == index), default=None),
            "avg": statistics.mean(vals) if vals else None,
            "percentile": 100 * sum(v <= pe for v in vals) / len(vals) if vals else None}


# ------------------------------------------------------------------ FactSet (S&P 500 forward P/E, weekly PDF)
FACTSET_URL = ("https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/"
               "EarningsInsight_{:%m%d%y}.pdf")
_NUM = r"(\d[\d, ]*\.\d+)"


def parse_factset(text: str) -> dict:
    t = re.sub(r"\s+", " ", text)
    num = lambda s: float(s.replace(",", "").replace(" ", ""))  # noqa: E731
    m = re.search(r"forward 12-month P/E ratio for the S&P 500 is " + _NUM + r"(.{0,260})", t)
    if not m:
        raise ValueError("forward P/E sentence not found (report wording changed?)")
    out = {"fwd_pe": num(m.group(1))}
    for key, label in (("pe_avg5", "5-year average"), ("pe_avg10", "10-year average")):
        a = re.search(label + r" (?:of |\()" + _NUM, m.group(2))
        out[key] = num(a.group(1)) if a else None
    for key, pattern in (("close", r"closing price of " + _NUM), ("target", r"bottom-up target price for the S&P 500 is " + _NUM),
                         ("trailing_pe", r"trailing 12-month P/E ratio is " + _NUM)):
        a = re.search(pattern, t)
        out[key] = num(a.group(1)) if a else None
    growth = {}
    for year, value in re.findall(r"For CY ?(\d{3} ?\d), analysts are (?:projecting|predicting|calling for)[^.]{0,40}?earnings growth of (-?\d+\.\d)%", t):
        growth.setdefault(year.replace(" ", ""), float(value))
    out["cy_growth"] = growth
    if out.get("close"):
        out["fwd_eps"] = out["close"] / out["fwd_pe"]
    return out


async def factset(ctx) -> dict:
    async def build():
        today = dt.date.today()
        friday = today - dt.timedelta(days=(today.weekday() - 4) % 7)
        for k in range(6):
            day = friday - dt.timedelta(days=7 * k)
            resp = await ctx.http.get(FACTSET_URL.format(day), headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            if resp.status_code in (403, 404):
                continue
            if resp.status_code != 200:
                return {"error": f"FactSet HTTP {resp.status_code}"}
            try:
                from pypdf import PdfReader
            except ImportError:
                return {"error": "install 'pypdf' to read the FactSet report"}

            def parse(raw=resp.content):
                reader = PdfReader(io.BytesIO(raw))
                return parse_factset(" ".join((pg.extract_text() or "") for pg in reader.pages[:18]))
            data = await asyncio.to_thread(parse)
            return {**data, "date": day.isoformat(), "source": "FactSet Earnings Insight (weekly, free PDF)"}
        return {"error": "no FactSet Earnings Insight report in the last six weeks"}
    return await ctx.cache.get("factset:latest", 12 * 3600, build, disk=True)


# ------------------------------------------------------------------ put/call
def _putcall(symbols=("SPY", "QQQ")) -> dict:
    import yfinance as yf
    rows = []
    for sym in symbols:
        t = yf.Ticker(sym)
        calls = puts = coi = poi = 0.0
        exps = list(t.options[:3])
        for exp in exps:
            ch = t.option_chain(exp)
            calls += float(ch.calls["volume"].fillna(0).sum())
            puts += float(ch.puts["volume"].fillna(0).sum())
            coi += float(ch.calls["openInterest"].fillna(0).sum())
            poi += float(ch.puts["openInterest"].fillna(0).sum())
        if calls:
            rows.append({"symbol": sym, "pc_volume": puts / calls, "pc_oi": poi / coi if coi else None, "expiries": exps})
    return {"rows": rows, "note": "Put/call by volume and open interest over the three nearest expiries (delayed). Extremes "
                                  "describe hedging demand; as a contrarian signal the evidence is weak."} if rows else {"error": "no option data"}


async def putcall(ctx) -> dict:
    return await ctx.cache.get("putcall", 1800, _putcall)


# ------------------------------------------------------------------ assembly
async def member_closes(ctx, key: str) -> dict:
    """{"closes": {member: [1y daily closes, last = live price]}, "index": [...]} - shared with the screener.
    The year of closes is cached for an hour (disk too); today's value comes from the live quote service."""
    members = [m["symbol"] for m in universe.members(key)]
    yahoo = ctx.hub.get("yahoo")

    async def build_closes():
        closes, last = await yahoo.daily_closes(members + [INDEX_SYMBOL[key]], "1y", with_time=True)
        return {"closes": closes, "last_bar": last} if closes else {"error": "no member history"}
    data = await ctx.cache.get(f"idx:closes:{key}", 3600, build_closes, disk=True)
    if "error" in data:
        return data
    closes = {k: list(v) for k, v in data["closes"].items()}          # copy: the cached lists stay untouched
    last_bar = data.get("last_bar") or {}
    from .markets import get_quotes
    live = await get_quotes(ctx, members + [INDEX_SYMBOL[key]], intraday=False)
    q = live.get("quotes", {})
    for sym in list(closes):
        closes[sym] = with_live(closes[sym], last_bar.get(sym), q.get(sym))
    idx = closes.pop(INDEX_SYMBOL[key], [])
    return {"closes": closes, "index": idx, "closes_asof": data.get("asof"), "closes_stale": bool(data.get("stale"))}


NEW_SESSION_HOURS = 20


def with_live(closes: list[float], last_bar_ts: float | None, quote: dict | None) -> list[float]:
    """Daily closes with the live price as today's value (pure, tested). The live price replaces the last close
    only when it belongs to the same session; a quote from a later session (the cached year ends yesterday)
    is appended - replacing would compare today's price with the day before yesterday."""
    if not closes or not quote or quote.get("price") is None:
        return closes
    t = quote.get("time")
    if last_bar_ts and t and t - last_bar_ts > NEW_SESSION_HOURS * 3600:
        return closes + [quote["price"]]
    return closes[:-1] + [quote["price"]]


async def index_view(ctx, key: str) -> dict:
    if key not in INDEX_SYMBOL:
        return {"error": "unknown index"}
    members = [m["symbol"] for m in universe.members(key)]
    data = await member_closes(ctx, key)
    if "error" in data:
        return data
    closes, idx = data["closes"], data["index"]
    b = breadth(closes, idx)
    if not b:
        return {"error": "not enough member history"}
    from .valuation import profile
    profiles = []
    if key not in NO_PROFILES and key not in UNWEIGHTED:  # hundreds of profiles are too slow for the free source
        res = await asyncio.gather(*(profile(ctx, s) for s in members))
        profiles = [{**p, "symbol": s} for s, p in zip(members, res) if "error" not in p]
    caps = class_caps(profiles)
    profiles = [{**p, "market_cap": caps.get(p["symbol"], p.get("market_cap"))} for p in profiles]
    b.pop("rows")
    pw = key in PRICE_WEIGHTED
    by_period = {name: driver_block(period_rows(closes, k), {} if key in UNWEIGHTED else caps, pw, idx, k) for name, k in PERIODS.items()}
    today_block = by_period["1d"]
    val = aggregate_pe(profiles, key in PRICE_WEIGHTED) if profiles else None
    if val:
        val["history"] = record_history(ctx.data_dir / "valuation_history.jsonl", universe.UNIVERSES[key], val["fwd_pe"],
                                        dt.date.today().isoformat())
    out = {"key": key, "name": universe.UNIVERSES[key], "symbol": INDEX_SYMBOL[key], "breadth": b,
           **{k: today_block[k] for k in ("index_move_pct", "index_points", "contrib_total", "drivers_down", "drivers_up")},
           "drivers_by_period": by_period, "valuation": val, "asof": time.time(),
           "note": "Breadth and the breadth line use one year of daily closes (free data, refreshed hourly, today's value live). "
                   "Contributions for cap-weighted indices are approximations from today's market caps (over a week or a month "
                   "the true weights drift a little)."}
    if key in UNWEIGHTED:
        out["drivers_note"] = ("The Nikkei 225 is price-weighted with price adjustment factors that are not in free data, so "
                               "neither points nor weights can be computed honestly here: these are the biggest movers, unweighted.")
    if not val and key != "sp500":
        out["valuation_note"] = ("No bottom-up valuation: the Nikkei 225 is not cap-weighted." if key in UNWEIGHTED else
                                 "No bottom-up valuation: too many members for the free company-profile source." if key in NO_PROFILES else
                                 "No member profiles yet - valuation appears once the profiles are cached (background refresh hourly).")
    if key == "tsx60":
        out["note"] += " The S&P/TSX 60 has no free index quote: the iShares S&P/TSX 60 ETF (XIU) stands in for the index line."
    if key == "sp500":
        out["factset"] = await factset(ctx)
    return out
