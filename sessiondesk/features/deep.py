"""Deep single-instrument data: financial statements, earnings history with price reactions, street
estimates and revisions, ownership/insiders/short interest, options (IV term structure, implied
move, put/call, max pain), performance and risk statistics, seasonality, dividends, peers.

Every block is computed here from raw vendor data and says what it is based on (periods, n).
Vendor data (Yahoo via yfinance) is unofficial: implausible values are flagged, not silently used.
Each block is cached on its own so a slow source never blocks the rest of the page.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
import statistics

from . import universe


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _div(a, b):
    a, b = _f(a), _f(b)
    return a / b if a is not None and b not in (None, 0) else None


def _growth(cur, prev):
    cur, prev = _f(cur), _f(prev)
    return cur / prev - 1 if cur is not None and prev not in (None, 0) and prev > 0 else None


# ------------------------------------------------------------------ statements
INCOME = [("revenue", ["Total Revenue", "Operating Revenue"]), ("gross_profit", ["Gross Profit"]),
          ("operating_income", ["Operating Income", "Total Operating Income As Reported"]), ("ebitda", ["EBITDA", "Normalized EBITDA"]),
          ("net_income", ["Net Income Common Stockholders", "Net Income"]), ("eps", ["Diluted EPS", "Basic EPS"]),
          ("shares", ["Diluted Average Shares", "Basic Average Shares"]), ("rnd", ["Research And Development"]),
          ("tax_rate", ["Tax Rate For Calcs"]), ("interest_expense", ["Interest Expense"])]
BALANCE = [("total_assets", ["Total Assets"]), ("cash", ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"]),
           ("total_debt", ["Total Debt"]), ("net_debt", ["Net Debt"]), ("equity", ["Stockholders Equity", "Common Stock Equity"]),
           ("working_capital", ["Working Capital"]), ("goodwill", ["Goodwill And Other Intangible Assets", "Goodwill"]),
           ("shares_out", ["Ordinary Shares Number", "Share Issued"])]
CASHFLOW = [("ocf", ["Operating Cash Flow"]), ("capex", ["Capital Expenditure"]), ("fcf", ["Free Cash Flow"]),
            ("buybacks", ["Repurchase Of Capital Stock"]), ("dividends_paid", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
            ("sbc", ["Stock Based Compensation"])]


def frame_rows(df, spec) -> list[dict]:
    """yfinance statement (rows = items, columns = period ends) -> [{period, key: value}] newest first."""
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for col in df.columns:
        row = {"period": str(getattr(col, "date", lambda: col)())}
        for key, names in spec:
            for name in names:
                if name in df.index:
                    v = _f(df.at[name, col])
                    if v is not None:
                        row[key] = v
                        break
        out.append(row)
    return out


def enrich_income(rows: list[dict], quarterly: bool) -> list[dict]:
    """Margins and growth. Annual: vs previous year. Quarterly: vs the same quarter a year earlier."""
    lag = 4 if quarterly else 1
    for i, r in enumerate(rows):
        rev = r.get("revenue")
        for k in ("gross_profit", "operating_income", "ebitda", "net_income"):
            r[k.replace("_profit", "").replace("_income", "") + "_margin"] = _div(r.get(k), rev)
        prev = rows[i + lag] if i + lag < len(rows) else None
        if prev:
            r["revenue_growth"] = _growth(rev, prev.get("revenue"))
            r["eps_growth"] = _growth(r.get("eps"), prev.get("eps"))
            r["net_income_growth"] = _growth(r.get("net_income"), prev.get("net_income"))
    return rows


def _statements(symbol: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(symbol)
    annual = enrich_income(frame_rows(t.income_stmt, INCOME), False)
    quarterly = enrich_income(frame_rows(t.quarterly_income_stmt, INCOME), True)
    balance = frame_rows(t.balance_sheet, BALANCE)
    qbalance = frame_rows(t.quarterly_balance_sheet, BALANCE)
    cash = frame_rows(t.cashflow, CASHFLOW)
    qcash = frame_rows(t.quarterly_cashflow, CASHFLOW)
    if not annual and not quarterly:
        return {"error": f"no financial statements for {symbol} (ETFs, indices and FX have none)"}
    by_period = {r["period"]: r for r in annual}
    for r in cash:
        a = by_period.get(r["period"], {})
        r["fcf_margin"] = _div(r.get("fcf"), a.get("revenue"))
        r["sbc_share"] = _div(r.get("sbc"), a.get("revenue"))
        r["fcf_conversion"] = _div(r.get("fcf"), a.get("net_income"))
    for r in balance:
        a = by_period.get(r["period"], {})
        r["debt_to_equity"] = _div(r.get("total_debt"), r.get("equity"))
        r["net_debt_to_ebitda"] = _div(r.get("net_debt"), a.get("ebitda"))
        tax = a.get("tax_rate") if a.get("tax_rate") is not None and 0 <= a.get("tax_rate") <= 0.5 else 0.21
        invested = (r.get("equity") or 0) + (r.get("total_debt") or 0) - (r.get("cash") or 0)
        r["roic"] = _div((a.get("operating_income") or 0) * (1 - tax), invested) if a.get("operating_income") and invested > 0 else None
        r["roe"] = _div(a.get("net_income"), r.get("equity"))
    ttm = {}
    if len(quarterly) >= 4:
        q4 = quarterly[:4]
        for k in ("revenue", "operating_income", "net_income", "ebitda"):
            if all(q.get(k) is not None for q in q4):
                ttm[k] = sum(q[k] for q in q4)
        if all(q.get("eps") is not None for q in q4):
            ttm["eps"] = sum(q["eps"] for q in q4)
        if len(qcash) >= 4 and all(q.get("fcf") is not None for q in qcash[:4]):
            ttm["fcf"] = sum(q["fcf"] for q in qcash[:4])
    # Share count trend: buybacks shrink it, stock comp and issuance grow it.
    shares = [(r["period"], r.get("shares")) for r in annual if r.get("shares")]
    share_change = _growth(shares[0][1], shares[-1][1]) if len(shares) >= 2 else None
    return {"annual": annual, "quarterly": quarterly, "balance": balance, "balance_latest": qbalance[:1],
            "cashflow": cash, "cashflow_quarterly": qcash, "ttm": ttm,
            "share_count_change": {"change": share_change, "from": shares[-1][0] if shares else None, "to": shares[0][0] if shares else None},
            "note": "Annual = last 4 fiscal years, quarterly = last 4-6 quarters (vendor limit). Growth: annual vs prior year, "
                    "quarterly vs the same quarter a year earlier. ROIC uses operating income after tax over equity + debt - cash."}


# ------------------------------------------------------------------ earnings history + price reaction
SESSION_HOURS = [("America/", (9, 30), (16, 0)), ("Europe/London", (8, 0), (16, 30)), ("Europe/", (9, 0), (17, 30)),
                 ("Asia/Tokyo", (9, 0), (15, 0)), ("Asia/Hong_Kong", (9, 30), (16, 0)), ("Australia/", (10, 0), (16, 0))]


def session_hours(tz: str | None) -> tuple[tuple, tuple]:
    for prefix, start, end in SESSION_HOURS:
        if tz and tz.startswith(prefix):
            return start, end
    return (9, 30), (16, 0)


def reaction(bars: list[dict], when: dt.datetime, tz: str | None = None) -> dict | None:
    """Price move around a report, judged in the EXCHANGE's local time:
    after the close -> next session vs report-day close; before the open or during the session ->
    report-day close vs previous close. Bars are daily, oldest first."""
    if not bars:
        return None
    try:
        from zoneinfo import ZoneInfo
        local = when.astimezone(ZoneInfo(tz)) if tz else when
    except Exception:
        local = when
    (oh, om), (ch, cm) = session_hours(tz)
    hm = (local.hour, local.minute)
    timing = "after close" if hm >= (ch, cm) else "before open" if hm < (oh, om) else "during session"
    day = local.date()
    idx = next((i for i, b in enumerate(bars) if dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).date() >= day), None)
    if idx is None:
        return None
    on_day = dt.datetime.fromtimestamp(bars[idx]["t"], dt.timezone.utc).date() == day
    if timing == "after close" and on_day:
        base, react = idx, idx + 1
    else:
        base, react = idx - 1, idx                 # pre-open, intraday, or reported on a non-trading day
    if base < 0 or react >= len(bars):
        return None
    b0, b1 = bars[base], bars[react]
    return {"move": b1["c"] / b0["c"] - 1, "gap": b1["o"] / b0["c"] - 1, "timing": timing}


def _earnings_dates(symbol: str) -> list[dict]:
    import yfinance as yf
    df = yf.Ticker(symbol).get_earnings_dates(limit=28)
    out = []
    if df is None or df.empty:
        return out
    for ts, row in df.iterrows():
        out.append({"when": ts.isoformat(), "eps_estimate": _f(row.get("EPS Estimate")), "eps_reported": _f(row.get("Reported EPS")),
                    "surprise_pct": _f(row.get("Surprise(%)"))})
    return out


def earnings_stats(rows: list[dict]) -> dict:
    done = [r for r in rows if r.get("move") is not None]
    if not done:
        return {}
    moves = [abs(r["move"]) for r in done]
    beats = [r for r in done if r.get("surprise_pct") is not None and r["surprise_pct"] > 0]
    misses = [r for r in done if r.get("surprise_pct") is not None and r["surprise_pct"] < 0]
    return {"n": len(done), "avg_abs_move": statistics.mean(moves), "median_abs_move": statistics.median(moves),
            "max_abs_move": max(moves), "up_share": sum(r["move"] > 0 for r in done) / len(done),
            "beat_share": len(beats) / len([r for r in done if r.get("surprise_pct") is not None]) if any(r.get("surprise_pct") is not None for r in done) else None,
            "avg_move_on_beat": statistics.mean(r["move"] for r in beats) if beats else None,
            "avg_move_on_miss": statistics.mean(r["move"] for r in misses) if misses else None}


# ------------------------------------------------------------------ street
def _street(symbol: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(symbol)

    def table(df, fields):
        if df is None or getattr(df, "empty", True):
            return []
        return [{"period": str(idx), **{f: (_f(df.at[idx, f]) if f in df.columns else None) for f in fields}} for idx in df.index]
    est = table(t.earnings_estimate, ["avg", "low", "high", "yearAgoEps", "numberOfAnalysts", "growth"])
    rev = table(t.revenue_estimate, ["avg", "low", "high", "yearAgoRevenue", "numberOfAnalysts", "growth"])
    trend = table(t.eps_trend, ["current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo"])
    revisions = table(t.eps_revisions, ["upLast7days", "upLast30days", "downLast30days", "downLast7Days"])
    growth = table(t.growth_estimates, ["stockTrend", "indexTrend"])
    recs = []
    rs = t.recommendations_summary
    if rs is not None and not rs.empty:
        for _, r in rs.iterrows():
            recs.append({"period": r.get("period"), **{k: int(r.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}})
    actions, counts = [], {"up": 0, "down": 0, "init": 0, "target_raised": 0, "target_lowered": 0}
    ud = t.upgrades_downgrades
    if ud is not None and not ud.empty:
        cutoff = dt.datetime.now() - dt.timedelta(days=90)
        for ts, r in ud.head(400).iterrows():
            when = ts.to_pydatetime().replace(tzinfo=None)
            rec = {"date": when.date().isoformat(), "firm": r.get("Firm"), "to": r.get("ToGrade"), "from": r.get("FromGrade"),
                   "action": r.get("Action"), "target_action": r.get("priceTargetAction"),
                   "target": _f(r.get("currentPriceTarget")), "prior_target": _f(r.get("priorPriceTarget"))}
            if len(actions) < 30:
                actions.append(rec)
            if when >= cutoff:
                a = (rec["action"] or "").lower()
                counts["up"] += a == "up"
                counts["down"] += a == "down"
                counts["init"] += a == "init"
                ta = (rec["target_action"] or "").lower()
                counts["target_raised"] += ta == "raises"
                counts["target_lowered"] += ta == "lowers"
    targets = {}
    try:
        targets = {k: _f(v) for k, v in (t.analyst_price_targets or {}).items()}
    except Exception:
        pass
    return {"eps_estimates": est, "revenue_estimates": rev, "eps_trend": trend, "eps_revisions": revisions, "growth": growth,
            "recommendations": recs, "actions": actions, "actions_90d": counts, "targets": targets,
            "note": "Periods: 0q = current quarter, +1q = next quarter, 0y = current fiscal year, +1y = next. "
                    "EPS trend shows how the consensus moved over the last 90 days - rising estimates are what moves prices, "
                    "not the level."}


# ------------------------------------------------------------------ ownership
def _ownership(symbol: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(symbol)
    major = {}
    mh = t.major_holders
    if mh is not None and not mh.empty:
        major = {str(i): _f(mh.iloc[n, 0]) for n, i in enumerate(mh.index)}

    def holders(df):
        if df is None or df.empty:
            return []
        return [{"holder": r.get("Holder"), "pct": _f(r.get("pctHeld")), "shares": _f(r.get("Shares")), "value": _f(r.get("Value")),
                 "change": _f(r.get("pctChange")), "reported": str(r.get("Date Reported"))[:10]} for _, r in df.iterrows()]
    insiders, net_shares, net_value, buys, sells = [], 0.0, 0.0, 0, 0
    it = t.insider_transactions
    if it is not None and not it.empty:
        cutoff = dt.datetime.now() - dt.timedelta(days=182)
        for _, r in it.iterrows():
            text = str(r.get("Text") or "")
            when = r.get("Start Date")
            try:
                when_dt = when.to_pydatetime().replace(tzinfo=None)
            except AttributeError:
                when_dt = None
            shares, value = _f(r.get("Shares")) or 0, _f(r.get("Value")) or 0
            kind = "buy" if "Purchase" in text or "Buy" in text else "sell" if "Sale" in text else "other"
            if len(insiders) < 30:
                insiders.append({"date": str(when)[:10], "insider": r.get("Insider"), "position": r.get("Position"),
                                 "kind": kind, "text": text[:120], "shares": shares, "value": value})
            if when_dt and when_dt >= cutoff and kind != "other":
                sign = 1 if kind == "buy" else -1
                net_shares += sign * shares
                net_value += sign * value
                buys += kind == "buy"
                sells += kind == "sell"
    return {"major": major, "institutions": holders(t.institutional_holders), "funds": holders(t.mutualfund_holders),
            "insiders": insiders, "insider_6m": {"buys": buys, "sells": sells, "net_shares": net_shares, "net_value": net_value},
            "note": "Insider sales are mostly planned (10b5-1) or tax-driven; open-market BUYS carry more information. "
                    "Institutional data is from the last 13F filings (quarterly, up to 45 days late)."}


# ------------------------------------------------------------------ options
def max_pain(calls, puts) -> float | None:
    strikes = sorted(set(calls["strike"]).union(puts["strike"]))
    if not strikes:
        return None
    coi = dict(zip(calls["strike"], calls["openInterest"].fillna(0)))
    poi = dict(zip(puts["strike"], puts["openInterest"].fillna(0)))
    best, best_pay = None, None
    for s in strikes:
        pay = sum(max(0, s - k) * oi for k, oi in coi.items()) + sum(max(0, k - s) * oi for k, oi in poi.items())
        if best_pay is None or pay < best_pay:
            best, best_pay = s, pay
    return best


def _options(symbol: str, spot: float | None, must_cover: str | None = None) -> dict:
    """must_cover: ISO date (next earnings) - the first expiry on/after it is always included."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    listed = list(t.options or [])
    expiries = listed[:8]
    if must_cover:
        after = next((e for e in listed if e >= must_cover), None)
        if after and after not in expiries:
            expiries.append(after)
    if not expiries:
        return {"error": "no listed options for this symbol"}
    if not spot:
        spot = _f((t.fast_info or {}).get("last_price"))
    rows, total = [], {"call_oi": 0.0, "put_oi": 0.0, "call_vol": 0.0, "put_vol": 0.0}
    nearest_pain = None
    for i, exp in enumerate(expiries):
        try:
            ch = t.option_chain(exp)
        except Exception:
            continue
        calls, puts = ch.calls, ch.puts
        if calls.empty or puts.empty or not spot:
            continue
        k = min(calls["strike"], key=lambda s: abs(s - spot))
        c = calls[calls["strike"] == k].iloc[0]
        p = puts[puts["strike"] == k].iloc[0] if (puts["strike"] == k).any() else None
        mid = lambda r: ((_f(r["bid"]) or 0) + (_f(r["ask"]) or 0)) / 2 if (_f(r["bid"]) or 0) > 0 and (_f(r["ask"]) or 0) > 0 else _f(r["lastPrice"])  # noqa: E731
        straddle = (mid(c) or 0) + (mid(p) or 0) if p is not None else None
        iv = statistics.mean([v for v in (_f(c["impliedVolatility"]), _f(p["impliedVolatility"]) if p is not None else None) if v])
        days = max(1, (dt.date.fromisoformat(exp) - dt.date.today()).days)
        # 25-delta proxies: OTM put ~ 0.95 spot, OTM call ~ 1.05 spot
        def iv_at(df, target):
            row = df.iloc[(df["strike"] - target).abs().argsort()[:1]]
            return _f(row["impliedVolatility"].iloc[0]) if len(row) else None
        put_wing, call_wing = iv_at(puts, spot * 0.95), iv_at(calls, spot * 1.05)
        co, po = float(calls["openInterest"].fillna(0).sum()), float(puts["openInterest"].fillna(0).sum())
        cv, pv = float(calls["volume"].fillna(0).sum()), float(puts["volume"].fillna(0).sum())
        for key, v in (("call_oi", co), ("put_oi", po), ("call_vol", cv), ("put_vol", pv)):
            total[key] += v
        if nearest_pain is None:
            nearest_pain = max_pain(calls, puts)
        rows.append({"expiry": exp, "days": days, "atm_strike": k, "atm_iv": iv, "straddle": straddle,
                     "implied_move": straddle / spot if straddle and spot else None,
                     "skew": (put_wing - call_wing) if put_wing and call_wing else None,
                     "put_call_oi": po / co if co else None, "put_call_volume": pv / cv if cv else None})
    return {"spot": spot, "expiries": rows, "max_pain_nearest": nearest_pain,
            "put_call_oi": total["put_oi"] / total["call_oi"] if total["call_oi"] else None,
            "put_call_volume": total["put_vol"] / total["call_vol"] if total["call_vol"] else None,
            "note": "Implied move = at-the-money straddle / spot for that expiry (market's expected absolute move, roughly one "
                    "standard deviation). Skew = IV of the ~5 % OTM put minus the ~5 % OTM call. Quotes are delayed; "
                    "outside US hours bid/ask can be empty and last prices stale."}


# ------------------------------------------------------------------ performance & risk (pure, tested)
def perf_stats(bars: list[dict], bench: list[dict] | None) -> dict:
    """Returns, volatility, drawdown, trend and beta from daily bars (oldest first)."""
    closes = [b["c"] for b in bars]
    if len(closes) < 30:
        return {}
    t_last = bars[-1]["t"]
    by_days = lambda d: next((b["c"] for b in reversed(bars) if b["t"] <= t_last - d * 86400), None)  # noqa: E731
    last = closes[-1]
    year_start = next((b["c"] for b in reversed(bars) if dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).year
                       < dt.datetime.fromtimestamp(t_last, dt.timezone.utc).year), None)
    windows = {"1W": 7, "1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "10Y": 3652}
    returns = {k: (last / by_days(d) - 1) if by_days(d) else None for k, d in windows.items()}
    returns["YTD"] = last / year_start - 1 if year_start else None
    rel = {}
    if bench and len(bench) > 30:
        bt = bench[-1]["t"]
        b_by = lambda d: next((b["c"] for b in reversed(bench) if b["t"] <= bt - d * 86400), None)  # noqa: E731
        for k, d in windows.items():
            if returns.get(k) is not None and b_by(d):
                rel[k] = returns[k] - (bench[-1]["c"] / b_by(d) - 1)
        b_year = dt.datetime.fromtimestamp(bt, dt.timezone.utc).year
        b_start = next((b["c"] for b in reversed(bench) if dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).year < b_year), None)
        if returns.get("YTD") is not None and b_start:
            rel["YTD"] = returns["YTD"] - (bench[-1]["c"] / b_start - 1)
    logr = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    vol = {f"{n}d": statistics.stdev(logr[-n:]) * math.sqrt(252) for n in (20, 60, 252) if len(logr) >= n}
    peak, mdd_1y, mdd_all = closes[0], 0.0, 0.0
    for i, c in enumerate(closes):
        peak = max(peak, c)
        dd = c / peak - 1
        mdd_all = min(mdd_all, dd)
        if bars[i]["t"] >= t_last - 365 * 86400:
            mdd_1y = min(mdd_1y, dd)
    year = [b for b in bars if b["t"] >= t_last - 365 * 86400]
    hi52, lo52 = max(b["h"] for b in year), min(b["l"] for b in year)
    sma = lambda n: statistics.mean(closes[-n:]) if len(closes) >= n else None  # noqa: E731
    trs = [max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"])) for a, b in zip(bars[-15:], bars[-14:])]
    vols = [b.get("v") or 0 for b in bars]
    beta = corr = None
    if bench and len(bench) > 60:
        bmap = {dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).date(): b["c"] for b in bench}
        pairs = []
        prev = None
        for b in year:
            d = dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).date()
            if d in bmap and prev and prev[1] in bmap:
                pairs.append((b["c"] / prev[0] - 1, bmap[d] / bmap[prev[1]] - 1))
            prev = (b["c"], d)
        if len(pairs) > 60:
            xs, ys = [p[1] for p in pairs], [p[0] for p in pairs]
            mx, my = statistics.mean(xs), statistics.mean(ys)
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            vx = sum((x - mx) ** 2 for x in xs)
            vy = sum((y - my) ** 2 for y in ys)
            beta = cov / vx if vx else None
            corr = cov / math.sqrt(vx * vy) if vx and vy else None
    return {"last": last, "returns": returns, "relative": rel, "volatility": vol,
            "drawdown": {"current": last / max(closes) - 1, "max_1y": mdd_1y, "max_period": mdd_all},
            "range_52w": {"high": hi52, "low": lo52, "from_high": last / hi52 - 1, "from_low": last / lo52 - 1},
            "trend": {"sma50": sma(50), "sma200": sma(200), "vs_sma50": last / sma(50) - 1 if sma(50) else None,
                      "vs_sma200": last / sma(200) - 1 if sma(200) else None,
                      "golden": (sma(50) > sma(200)) if sma(50) and sma(200) else None},
            "atr14_pct": statistics.mean(trs) / last if trs else None,
            "volume": {"last": vols[-1], "avg20": statistics.mean(vols[-20:]) if len(vols) >= 20 else None,
                       "avg250": statistics.mean(vols[-250:]) if len(vols) >= 250 else None},
            "beta_1y": beta, "corr_1y": corr, "years": round((t_last - bars[0]["t"]) / (365.25 * 86400), 1)}


def seasonality(bars: list[dict]) -> dict:
    """Average return per calendar month and per year from monthly closes (last close of each month)."""
    month_close: dict[tuple, float] = {}
    for b in bars:
        d = dt.datetime.fromtimestamp(b["t"], dt.timezone.utc)
        month_close[(d.year, d.month)] = b["c"]
    keys = sorted(month_close)
    rets: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    years: dict[int, float] = {}
    for a, b in zip(keys, keys[1:]):
        r = month_close[b] / month_close[a] - 1
        rets[b[1]].append(r)
    year_end = {}
    for (y, m) in keys:
        year_end[y] = month_close[(y, m)]
    ys = sorted(year_end)
    for a, b in zip(ys, ys[1:]):
        years[b] = year_end[b] / year_end[a] - 1
    months = []
    for m in range(1, 13):
        r = rets[m]
        months.append({"month": m, "n": len(r), "avg": statistics.mean(r) if r else None,
                       "median": statistics.median(r) if r else None, "up_share": sum(x > 0 for x in r) / len(r) if r else None,
                       "se": statistics.stdev(r) / math.sqrt(len(r)) if len(r) > 2 else None})
    return {"months": months, "years": [{"year": y, "return": v} for y, v in sorted(years.items(), reverse=True)],
            "note": "Monthly seasonality from about 10 years = about 10 observations per month: almost never significant "
                    "(|avg / se| < 2 for most months). Shown as context, not as an edge."}


def dividend_history(series) -> dict:
    if series is None or len(series) == 0:
        return {"years": []}
    per_year: dict[int, float] = {}
    last = []
    for ts, v in series.items():
        per_year[ts.year] = per_year.get(ts.year, 0.0) + float(v)
        last.append({"date": ts.date().isoformat(), "amount": float(v)})
    years = sorted(per_year.items(), reverse=True)[:12]
    rows = []
    for i, (y, total) in enumerate(years):
        prev = years[i + 1][1] if i + 1 < len(years) else None
        rows.append({"year": y, "total": total, "growth": total / prev - 1 if prev else None})
    return {"years": rows, "recent": last[-8:][::-1]}


# ------------------------------------------------------------------ async entry points (cached per block)
async def statements(ctx, symbol: str) -> dict:
    return await ctx.cache.get(f"deep:stmt:{symbol}", 12 * 3600, lambda: _statements(symbol), disk=True)


async def street(ctx, symbol: str) -> dict:
    return await ctx.cache.get(f"deep:street:{symbol}", 6 * 3600, lambda: _street(symbol), disk=True)


async def ownership(ctx, symbol: str) -> dict:
    return await ctx.cache.get(f"deep:own:{symbol}", 12 * 3600, lambda: _ownership(symbol), disk=True)


async def options(ctx, symbol: str) -> dict:
    from .stocks import history

    async def build():
        from .valuation import profile
        day, prof = await asyncio.gather(history(ctx, symbol, "1d"), profile(ctx, symbol))
        earn = prof.get("earnings_ts") or prof.get("earnings_start") if "error" not in prof else None
        cover = dt.datetime.fromtimestamp(earn, dt.timezone.utc).date().isoformat() if earn and earn > dt.datetime.now().timestamp() else None
        return await asyncio.to_thread(_options, symbol, day.get("price") if "error" not in day else None, cover)
    return await ctx.cache.get(f"deep:opt:{symbol}", 900, build)


def benchmark_for(symbol: str) -> str:
    m = universe.lookup(symbol)
    if m:
        return universe.BENCHMARK.get(m["universe"], "^GSPC")
    if symbol.endswith(".DE"):
        return "^GDAXI"
    return "^GSPC"


async def performance(ctx, symbol: str) -> dict:
    from .stocks import history

    async def build():
        bench_sym = benchmark_for(symbol)
        own, bench = await asyncio.gather(history(ctx, symbol, "10y-d"), history(ctx, bench_sym, "10y-d") if bench_sym != symbol else asyncio.sleep(0, {}))
        if "error" in own:
            return own
        bars = own.get("bars", [])
        stats = perf_stats(bars, (bench or {}).get("bars"))
        if not stats:
            return {"error": "not enough price history"}
        return {"benchmark": bench_sym if bench_sym != symbol else None, "stats": stats, "seasonality": seasonality(bars),
                "source": own.get("source")}
    return await ctx.cache.get(f"deep:perf:{symbol}", 900, build)


async def earnings(ctx, symbol: str) -> dict:
    from .stocks import history

    async def build():
        dates, hist = await asyncio.gather(asyncio.to_thread(_earnings_dates, symbol), history(ctx, symbol, "10y-d"))
        bars = hist.get("bars", []) if "error" not in hist else []
        rows, upcoming = [], None
        now = dt.datetime.now(dt.timezone.utc)
        for r in dates:
            when = dt.datetime.fromisoformat(r["when"])
            if when > now and r.get("eps_reported") is None:
                upcoming = {**r, "days": (when - now).days}
                continue
            rx = reaction(bars, when, hist.get("timezone")) if bars else None
            rows.append({**r, **(rx or {}), "date": when.date().isoformat()})
        rows = [r for r in rows if r.get("eps_reported") is not None or r.get("move") is not None]
        return {"history": rows, "upcoming": upcoming, "stats": earnings_stats(rows),
                "note": "Reaction = close after the report vs the close before it (after-close reports: next session). "
                        "Surprise = reported vs consensus EPS. Small n - read it as the stock's typical earnings temperament."}
    return await ctx.cache.get(f"deep:earn:{symbol}", 12 * 3600, build, disk=True)


async def dividends(ctx, symbol: str) -> dict:
    def build():
        import yfinance as yf
        t = yf.Ticker(symbol)
        out = dividend_history(t.dividends)
        try:
            out["splits"] = [{"date": ts.date().isoformat(), "ratio": float(v)} for ts, v in t.splits.items()][-6:][::-1]
        except Exception:
            out["splits"] = []
        return out
    return await ctx.cache.get(f"deep:div:{symbol}", 24 * 3600, build, disk=True)


async def peers_table(ctx, symbol: str) -> dict:
    from .valuation import profile
    syms = [symbol] + universe.peers(symbol, 10)
    if len(syms) == 1:
        return {"rows": [], "note": "No peer group: the symbol is not in the bundled index lists."}
    profiles = await asyncio.gather(*(profile(ctx, s) for s in syms))
    yahoo = ctx.hub.get("yahoo")
    closes = await yahoo.daily_closes(syms, "1y") if yahoo else {}
    rows = []
    for s, p in zip(syms, profiles):
        if "error" in p:
            continue
        c = closes.get(s) or []
        rows.append({"symbol": s, "name": p.get("short_name") or p.get("name"), "market_cap": p.get("market_cap"),
                     "pe_forward": p.get("pe_forward"), "pe_trailing": p.get("pe_trailing"), "ev_ebitda": p.get("ev_ebitda"),
                     "ps": p.get("ps"), "revenue_growth": p.get("revenue_growth"), "operating_margin": p.get("operating_margin"),
                     "net_margin": p.get("net_margin"), "roe": p.get("roe"), "dividend_yield": p.get("dividend_yield"),
                     "return_1y": c[-1] / c[0] - 1 if len(c) > 200 else None, "self": s == symbol})
    m = universe.lookup(symbol) or {}
    return {"rows": rows, "group": m.get("industry") or m.get("sector"),
            "note": "Peers = same index, same industry first, then same sector. Vendor multiples; implausible values are not filtered here."}
