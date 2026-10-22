"""Performance report of one trading account over a period, built from the broker's own deal history (the MetaTrader 5
export): summary, balance curve, days, symbols and every closed position - as a PDF to show and a CSV to check.

What such a report can prove, and what not:
- Every figure comes from the exported deals. Each report carries a SHA-256 fingerprint of its data block (account,
  period, balances, every position). The CSV holds the same block, so anyone with this open-source code can recompute
  the fingerprint and see whether a number was changed after the report was made (verify_csv).
- SessionDesk keeps a register of the reports it issued (file hashes); the Reports page checks a PDF or CSV byte for
  byte against it. The PDF opens without a password but is locked against editing (owner password, print allowed).
  Both are deterrents, not seals: a determined forger can rebuild any document.
- It remains the account holder's own software, not an audit. Independent proof is the broker's statement (the
  position IDs in the report are the broker's) or read-only access for the reader (investor password, a verified
  track record on Myfxbook or FX Blue, the prop firm's own metrics).

Balances: the export has no deposits or withdrawals, so the start balance is reconstructed as the balance now minus
every deal result since the start. A payout or deposit inside the period would make that wrong - the report says so.
Day boundaries are UTC.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import secrets
import time
from collections import defaultdict

VERSION = 1
UTC = dt.timezone.utc


def _day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _stamp(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M")


def _r2(v: float) -> float:
    return round(float(v) + 0.0, 2)


# ------------------------------------------------------------------ figures (pure, tested)
def closed_positions(deals: list[dict], start: float, end: float) -> list[dict]:
    """Positions whose closing deal falls in [start, end): open and close time, symbol, side, volume, net result
    (profit + costs of all its deals)."""
    pos: dict[str, dict] = {}
    for d in sorted(deals, key=lambda x: x.get("time") or 0):
        pid = str(d.get("position_id"))
        r = pos.setdefault(pid, {"position_id": pid, "symbol": d.get("symbol"), "side": None, "opened": None, "closed": None,
                                 "volume": 0.0, "net": 0.0, "exit": False})
        r["net"] += d.get("net") or 0.0
        if d.get("entry") == "0":
            if r["opened"] is None:
                r["opened"], r["side"] = d.get("time"), "long" if d.get("type") == "BUY" else "short"
            r["volume"] += d.get("volume") or 0.0
        elif d.get("entry") in ("1", "2", "3"):
            r["exit"], r["closed"] = True, d.get("time")
    out = [r for r in pos.values() if r["exit"] and r["closed"] is not None and start <= r["closed"] < end]
    return [{k: v for k, v in r.items() if k != "exit"} for r in sorted(out, key=lambda r: r["closed"])]


def max_drawdown(curve: list[float]) -> tuple[float, float]:
    """Largest peak-to-trough fall of a balance path: (money, percent of the peak)."""
    peak, dd, dd_pct = None, 0.0, 0.0
    for v in curve:
        peak = v if peak is None or v > peak else peak
        if peak - v > dd:
            dd, dd_pct = peak - v, (peak - v) / peak * 100 if peak > 0 else 0.0
    return dd, dd_pct


# Cash bookings (bridge 1.20+): what each type counts as. "result" = part of the trading result before tax (fees billed
# apart, financing interest, dividend adjustments on index CFDs); "tax" and "flow" (deposits, withdrawals, credit) are
# shown apart and never counted as result; "other" (corrections) moves the balance but is not counted either.
CASH_CLASS = {"TAX": "tax", "BALANCE": "flow", "CREDIT": "flow", "BONUS": "flow", "CHARGE": "result", "COMMISSION": "result",
              "INTEREST": "result", "DIVIDEND": "result", "CORRECTION": "other"}


def build(deals: list[dict], account: dict, start: float, end: float, now: float | None = None,
          cash: list[dict] | None = None) -> dict:
    """The report's figures. deals: this account's trades ({time, position_id, symbol, type BUY|SELL, entry 0|1|2|3,
    volume, net}); account: {label, currency, balance, server, company}; cash: its other balance bookings
    ({time, type, amount, comment, ticket}) or None when the export does not carry them."""
    now = now or time.time()
    balance = account.get("balance") or 0.0
    known = cash is not None
    cash = sorted(cash or [], key=lambda c: c.get("time") or 0)
    moves = [(d.get("time") or 0, d.get("net") or 0) for d in deals] + [(c.get("time") or 0, c.get("amount") or 0) for c in cash]
    start_bal = balance - sum(v for t, v in moves if t >= start)
    end_bal = balance - sum(v for t, v in moves if t >= end)
    in_cash = [c for c in cash if start <= (c.get("time") or 0) < end]
    sums = defaultdict(float)
    for c in in_cash:
        sums[CASH_CLASS.get(c.get("type"), "other")] += c.get("amount") or 0
    # the performance path: trades and result bookings only - taxes, deposits and withdrawals do not move it
    perf = sorted([(d["time"], d.get("net") or 0) for d in deals if start <= (d.get("time") or 0) < end]
                  + [(c["time"], c.get("amount") or 0) for c in in_cash if CASH_CLASS.get(c.get("type")) == "result"])
    curve, days = [(start, start_bal)], defaultdict(lambda: {"net": 0.0, "trades": 0, "tax": 0.0})
    run = start_bal
    for t, v in perf:
        run += v
        if curve[-1][0] == t and len(curve) > 1:
            curve[-1] = (t, run)                       # deals of the same second are one step: their order must not make a drawdown
        else:
            curve.append((t, run))
        days[_day(t)]["net"] += v
    for c in in_cash:
        if CASH_CLASS.get(c.get("type")) == "tax":
            days[_day(c["time"])]["tax"] += c.get("amount") or 0
    positions = closed_positions(deals, start, end)
    for p in positions:
        days[_day(p["closed"])]["trades"] += 1
    wins = [p["net"] for p in positions if p["net"] > 0]
    losses = [p["net"] for p in positions if p["net"] < 0]
    dd, dd_pct = max_drawdown([v for _, v in curve])
    bal = start_bal
    day_rows = []
    for k in sorted(days):
        bal += days[k]["net"]
        day_rows.append({"day": k, "trades": days[k]["trades"], "net": days[k]["net"], "tax": days[k]["tax"], "balance": bal,
                         "pct": days[k]["net"] / (bal - days[k]["net"]) * 100 if bal - days[k]["net"] else None})
    sym: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "net": 0.0})
    for p in positions:
        s_ = sym[p["symbol"]]
        s_["trades"] += 1
        s_["wins"] += p["net"] > 0
        s_["net"] += p["net"]
    if known:
        net = sum(v for _, v in perf)                  # result before tax
        # Modified Dietz: money deposited or withdrawn during the period counts for the share of the period it was there
        span = (end - start) or 1
        denom = start_bal + sum((c.get("amount") or 0) * (end - c["time"]) / span for c in in_cash if CASH_CLASS.get(c.get("type")) == "flow")
    else:
        net, denom = end_bal - start_bal, start_bal
    first_deal = min((d.get("time") or now for d in deals), default=None)
    return {
        "version": VERSION, "account": account.get("label"), "currency": account.get("currency") or "",
        "server": account.get("server") or "", "company": account.get("company") or "",
        "start": start, "end": end, "start_balance": start_bal, "end_balance": end_bal, "net": net,
        "net_pct": net / denom * 100 if denom else None,
        "cash_known": known, "cash": in_cash, "taxes": sums["tax"], "flows": sums["flow"], "cash_result": sums["result"],
        "cash_other": sums["other"], "deposits": sum(c["amount"] for c in in_cash if CASH_CLASS.get(c.get("type")) == "flow" and c["amount"] > 0),
        "withdrawals": sum(c["amount"] for c in in_cash if CASH_CLASS.get(c.get("type")) == "flow" and c["amount"] < 0),
        "after_tax": net + sums["tax"] if known else None,
        "after_tax_pct": (net + sums["tax"]) / denom * 100 if known and denom else None,
        "dietz": known and bool(sums["flow"]),
        "positions": positions, "trades": len(positions),
        "win_rate": len(wins) / len(positions) * 100 if positions else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "avg_win": sum(wins) / len(wins) if wins else None, "avg_loss": sum(losses) / len(losses) if losses else None,
        "best": max((p["net"] for p in positions), default=None), "worst": min((p["net"] for p in positions), default=None),
        "other": net - sum(p["net"] for p in positions),      # costs of positions still open, results of positions opened before, fees
        "max_dd": dd, "max_dd_pct": dd_pct, "curve": curve, "days": day_rows,
        "best_day": max(day_rows, key=lambda r: r["net"], default=None), "worst_day": min(day_rows, key=lambda r: r["net"], default=None),
        "symbols": sorted(({"symbol": k, **v} for k, v in sym.items()), key=lambda r: -abs(r["net"])),
        "first_deal": first_deal, "generated": now,
    }


def balance_check(deals: list[dict], balance_now: float, recorded: dict[str, float], tolerance: float = 1.0,
                  cash: list[dict] | None = None) -> dict:
    """Reconstructed balance (now minus every deal since) against the day-start balances SessionDesk recorded itself.
    A recorded day start may sit at UTC midnight or at the broker's midnight (UTC+2/+3): the closest of the three
    counts. Differences mean balance changes that are not trades (deposits, payouts, fees, dividend adjustments) or
    deals missing from the export (pure, tested)."""
    rows = []
    for day, rec in sorted(recorded.items()):
        base = dt.datetime.fromisoformat(day).replace(tzinfo=UTC)
        cands = []
        for h in (0, 2, 3):
            t = (base - dt.timedelta(hours=h)).timestamp()
            cands.append(balance_now - sum(d.get("net") or 0 for d in deals if (d.get("time") or 0) >= t)
                         - sum(c.get("amount") or 0 for c in cash or [] if (c.get("time") or 0) >= t))
        recon = min(cands, key=lambda v: abs(v - rec))
        rows.append({"day": day, "recorded": rec, "reconstructed": recon, "diff": recon - rec})
    bad = [r for r in rows if abs(r["diff"]) > tolerance]
    return {"days": len(rows), "matched": len(rows) - len(bad), "max_diff": max((abs(r["diff"]) for r in rows), default=None),
            "worst": max(bad, key=lambda r: abs(r["diff"])) if bad else None, "rows": rows, "tolerance": tolerance}


# ------------------------------------------------------------------ fingerprint (pure, tested)
def data_block(r: dict) -> dict:
    """What the fingerprint covers - exactly what the CSV carries, rounded the same way. units "percent": no money and
    no lot sizes and no balance - every figure in % of the start balance, the balance as the return since the start."""
    pct = r.get("units") == "percent"
    sb = r["start_balance"] or 1.0
    head = {"version": r["version"], "units": "percent" if pct else "money", "account": r["account"], "currency": r["currency"],
            "server": r["server"], "from": _stamp(r["start"]), "to": _stamp(r["end"])}
    if r.get("cash_known"):
        head["cash"] = [[str(c.get("ticket") or ""), _stamp(c["time"]), c.get("type") or "",
                         round((c.get("amount") or 0) / sb * 100, 4) if pct else _r2(c.get("amount") or 0)] for c in r["cash"]]
    if pct:
        return {**head, "return_pct": round((r["end_balance"] / sb - 1) * 100, 4),
                "positions": [[p["position_id"], _stamp(p["opened"]) if p["opened"] else "", _stamp(p["closed"]), p["symbol"] or "",
                               p["side"] or "", "", round(p["net"] / sb * 100, 4)] for p in r["positions"]]}
    return {**head, "start_balance": _r2(r["start_balance"]), "end_balance": _r2(r["end_balance"]),
            "positions": [[p["position_id"], _stamp(p["opened"]) if p["opened"] else "", _stamp(p["closed"]), p["symbol"] or "",
                           p["side"] or "", round(p["volume"], 2), _r2(p["net"])] for p in r["positions"]]}


def fingerprint(block: dict) -> str:
    return hashlib.sha256(json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def report_id(r: dict, fp: str) -> str:
    return f"SD-{dt.datetime.fromtimestamp(r['generated'], UTC):%Y%m%d}-{fp[:8].upper()}"


POS_HEADER = ["position_id", "opened_utc", "closed_utc", "symbol", "side", "volume", "net"]
CASH_HEADER = ["booking_id", "time_utc", "type", "amount"]


def to_csv(r: dict, rid: str, fp: str) -> str:
    """Block 1: field,value (the fingerprinted fields first, then the figures for reading); empty line; block 2: positions."""
    b = data_block(r)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["field", "value"])
    for k in ("version", "units", "account", "currency", "server", "from", "to", "start_balance", "end_balance", "return_pct"):
        if k in b:
            w.writerow([k, b[k]])
    w.writerow(["sha256", fp])
    w.writerow(["report_id", rid])
    w.writerow(["generated_utc", _stamp(r["generated"])])
    chk = r.get("check") or {}
    pct = b["units"] == "percent"
    worst = chk.get("worst")
    w.writerow(["balance_check", f"{chk.get('matched', 0)} of {chk.get('days', 0)} recorded day starts agree"
                + ((f"; largest difference {worst['diff'] / (r['start_balance'] or 1) * 100:+.3f} % of the start balance" if pct
                    else f"; largest difference {worst['diff']:+.2f}") + f" on {worst['day']}" if worst else "")])
    for k in (("net_pct", "after_tax_pct", "trades", "win_rate", "profit_factor", "max_dd_pct") if pct
              else ("net", "net_pct", "taxes", "after_tax", "after_tax_pct", "deposits", "withdrawals", "trades", "win_rate",
                    "profit_factor", "max_dd", "max_dd_pct")):
        v = r.get(k)
        w.writerow([k, "" if v is None else round(v, 4) if isinstance(v, float) else v])
    w.writerow([])
    w.writerow(POS_HEADER)
    for row in b["positions"]:
        w.writerow(row)
    if "cash" in b:                                    # block 3: balance bookings that are not trades (tax, deposits, fees)
        w.writerow([])
        w.writerow(CASH_HEADER)
        for row in b["cash"]:
            w.writerow(row)
    return out.getvalue()


def verify_csv(text: str) -> dict:
    """Recompute the fingerprint from a report CSV: {ok, stated, recomputed, report_id} (pure, tested)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    try:
        cut = rows.index([])
    except ValueError:
        cut = next((i for i, r in enumerate(rows) if not any(r)), None)
    if cut is None or not rows or rows[0][:2] != ["field", "value"]:
        return {"ok": False, "error": "not a SessionDesk report CSV"}
    meta = {r[0]: r[1] for r in rows[1:cut] if len(r) >= 2}
    rest = rows[cut + 1:]
    cut2 = next((i for i, r in enumerate(rest) if not any(r)), None)
    table = [r for r in (rest[:cut2] if cut2 is not None else rest) if r]
    cash_rows = [r for r in rest[cut2 + 1:] if r] if cut2 is not None else []
    if not table or table[0] != POS_HEADER:
        return {"ok": False, "error": "position table missing"}
    if cash_rows and cash_rows[0] != CASH_HEADER:
        return {"ok": False, "error": "booking table unreadable"}
    try:
        block = {"version": int(meta["version"]), "units": meta.get("units", "money"), "account": meta["account"], "currency": meta["currency"],
                 "server": meta["server"], "from": meta["from"], "to": meta["to"],
                 **({"return_pct": float(meta["return_pct"])} if meta.get("units") == "percent"
                    else {"start_balance": float(meta["start_balance"]), "end_balance": float(meta["end_balance"])}),
                 "positions": [[p[0], p[1], p[2], p[3], p[4], float(p[5]) if p[5] != "" else "", float(p[6])] for p in table[1:]],
                 **({"cash": [[c[0], c[1], c[2], float(c[3])] for c in cash_rows[1:]]} if cash_rows else {})}
    except (KeyError, ValueError, IndexError) as e:
        return {"ok": False, "error": f"unreadable field: {e}"}
    got = fingerprint(block)
    return {"ok": got == meta.get("sha256"), "stated": meta.get("sha256"), "recomputed": got, "report_id": meta.get("report_id")}


# ------------------------------------------------------------------ PDF
def _money(v, cur: str = "", sign: bool = False) -> str:
    if v is None:
        return "-"
    s = f"{v:+,.2f}" if sign else f"{v:,.2f}"
    return s + (f" {cur}" if cur else "")


def _pct(v, sign: bool = True) -> str:
    return "-" if v is None else (f"{v:+.2f} %" if sign else f"{v:.2f} %")


def to_pdf(r: dict, rid: str, fp: str) -> bytes:
    from ..pdfwriter import A4, PDF
    cur = r["currency"]
    period = f"{_day(r['start'])} to {_day(r['end'] - 1)} (UTC)"
    pdf = PDF(title=f"Trading performance report {rid}", author="SessionDesk", subject=f"Account {r['account']}, {period}")
    L, R, TOP = 42.0, A4[0] - 42.0, 52.0
    grey, dark, blue = (0.45, 0.45, 0.45), (0.1, 0.1, 0.1), (0.12, 0.36, 0.7)
    up, down = (0.09, 0.5, 0.27), (0.75, 0.17, 0.15)
    pct = r.get("units") == "percent"
    sb = r["start_balance"] or 1.0

    def M(v, sign: bool = True, unit: bool = False) -> str:
        """A money result - or, in percent mode, the same result in % of the start balance."""
        if v is None:
            return "-"
        return f"{v / sb * 100:+.2f} %" if pct else _money(v, cur if unit else "", sign)

    def B(v) -> str:
        """A balance - or, in percent mode, the return since the start of the period."""
        return "-" if v is None else f"{(v / sb - 1) * 100:+.2f} %" if pct else _money(v)

    def new_page():
        pdf.add_page()
        pdf.watermark(f"SessionDesk  {rid}  account {r['account']}")
        return TOP

    def heading(y, s):
        pdf.text(L, y, s, 11, bold=True, color=dark)
        pdf.line(L, y + 4, R, y + 4, 0.6, (0.75, 0.75, 0.75))
        return y + 18

    def table(y, cols, rows, bottom=780.0):
        """cols: (label, x, align, width-ish); returns y after the table; continues on a new page when full."""
        def head(yy):
            for label, x, align in cols:
                pdf.text(x, yy, label, 7.5, bold=True, color=grey, align=align)
            pdf.line(L, yy + 3, R, yy + 3, 0.4, (0.8, 0.8, 0.8))
            return yy + 13
        y = head(y)
        for row in rows:
            if y > bottom:
                y = head(new_page())
            for (label, x, align), (val, color) in zip(cols, row):
                pdf.text(x, y, val, 8, color=color or dark, align=align)
            y += 11.5
        return y + 6

    # ---- page 1: title, key figures, balance curve
    y = new_page()
    pdf.text(L, y, "Trading performance report", 18, bold=True, color=dark)
    pdf.text(R, y, rid, 9, bold=True, color=blue, align="right")
    y += 18
    pdf.text(L, y, f"Account {r['account']}" + (f"  ·  {r['server']}" if r["server"] else "") + (f"  ·  {r['company']}" if r["company"] else "")
             + ("  ·  all figures in % of the start balance" if pct else f"  ·  {cur}"), 9.5, color=dark)
    y += 13
    pdf.text(L, y, f"Period {period}  ·  generated {_stamp(r['generated'])} UTC from the MetaTrader 5 deal history", 8.5, color=grey)
    chk = r.get("check") or {}
    if chk.get("worst"):
        y += 13
        worst_txt = f"{chk['max_diff'] / sb * 100:.2f} % of the start balance" if pct else f"{chk['max_diff']:,.2f} {cur}"
        pdf.text(L, y, f"Balance check failed on {chk['days'] - chk['matched']} of {chk['days']} days (up to {worst_txt}): "
                       "see 'Data, method and limits'.", 8.5, bold=True, color=down)
    y += 22
    col = lambda v: up if (v or 0) > 0 else down if (v or 0) < 0 else dark  # noqa: E731
    known = r.get("cash_known")
    ret_label = "Return (Modified Dietz)" if r.get("dietz") else "Return on start balance"
    kpis = [
        ("Net result before tax" if known else "Net result", M(r["net"], unit=True), col(r["net"])),
        (ret_label + (" before tax" if known else ""), _pct(r["net_pct"]), col(r["net_pct"])),
        *([("Taxes withheld (-) / refunded (+)", M(r["taxes"], unit=True), col(r["taxes"])),
           ("Return after tax", _pct(r["after_tax_pct"]), col(r["after_tax_pct"]))] if known else []),
        *([("Deposits / withdrawals", f"{M(r['deposits'])} / {M(r['withdrawals'])}", dark)] if known and (r["deposits"] or r["withdrawals"]) else []),
        *([("Trading days", str(len(r["days"])), dark), ("Positions per trading day", f"{r['trades'] / len(r['days']):.1f}" if r["days"] else "-", dark)]
          if pct else [("Start balance", B(r["start_balance"]) + f" {cur}", dark), ("End balance", B(r["end_balance"]) + f" {cur}", dark)]),
        ("Closed positions", str(r["trades"]), dark), ("Win rate", _pct(r["win_rate"], False), dark),
        ("Profit factor", "-" if r["profit_factor"] is None else f"{r['profit_factor']:.2f}", dark),
        ("Max drawdown (closed balance, of its peak)", f"{r['max_dd_pct']:.2f} %" if pct else f"{_money(r['max_dd'], cur)}  ({r['max_dd_pct']:.2f} %)",
         down if r["max_dd"] else dark),
        ("Average win / loss", f"{M(r['avg_win'], sign=False)} / {M(r['avg_loss'], sign=False)}", dark),
        ("Best / worst position", f"{M(r['best'])} / {M(r['worst'])}", dark),
        ("Best day", f"{r['best_day']['day']}  {M(r['best_day']['net'])}" if r["best_day"] else "-", dark),
        ("Worst day", f"{r['worst_day']['day']}  {M(r['worst_day']['net'])}" if r["worst_day"] else "-", dark),
    ]
    bw, bh = (R - L - 10) / 2, 34
    for i, (k, v, c) in enumerate(kpis):
        x, yy = L + (i % 2) * (bw + 10), y + (i // 2) * (bh + 6)
        pdf.rect(x, yy, bw, bh, fill=(0.965, 0.97, 0.975))
        pdf.text(x + 8, yy + 13, k, 7.5, color=grey)
        pdf.text(x + 8, yy + 27, v, 11, bold=True, color=c)
    y += (len(kpis) + 1) // 2 * (bh + 6) + 16
    y = heading(y, "Return since the start of the period, after each deal" if pct else "Balance after each deal")
    pts = [(t, (v / sb - 1) * 100) for t, v in r["curve"]] if pct else r["curve"]
    ch_h = 170.0
    pdf.rect(L, y, R - L, ch_h, stroke=(0.85, 0.85, 0.85))
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or max(abs(hi) * 0.01, 1)
    lo, hi = lo - pad, hi + pad
    t0, t1 = r["start"], r["end"]
    X = lambda t: L + 50 + (t - t0) / ((t1 - t0) or 1) * (R - L - 60)  # noqa: E731
    Y = lambda v: y + 8 + (1 - (v - lo) / (hi - lo)) * (ch_h - 26)    # noqa: E731
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        pdf.line(L + 50, Y(v), R - 10, Y(v), 0.3, (0.9, 0.9, 0.9))
        pdf.text(L + 46, Y(v) + 3, f"{v:+.1f} %" if pct else f"{v:,.0f}", 7, color=grey, align="right")
    base = 0.0 if pct else r["start_balance"]
    pdf.line(L + 50, Y(base), R - 10, Y(base), 0.5, (0.6, 0.6, 0.6))
    steps = []
    for i, (t, v) in enumerate(pts):                     # a balance moves in steps: hold each level until the next deal
        if i:
            steps.append((X(t), Y(pts[i - 1][1])))
        steps.append((X(t), Y(v)))
    steps.append((X(t1), Y(pts[-1][1])))
    pdf.polyline(steps, 1.1, up if r["net"] >= 0 else down)
    pdf.text(L + 50, y + ch_h - 5, _day(t0), 7, color=grey)
    pdf.text(R - 10, y + ch_h - 5, _day(t1 - 1), 7, color=grey, align="right")
    y += ch_h + 14
    if r["other"] and abs(r["other"]) >= 0.01:
        pdf.text(L, y, f"Net result {M(r['net'], unit=True)} = closed positions {M(r['net'] - r['other'])} "
                       f"+ other balance changes {M(r['other'])} (costs of positions still open, entry costs paid before the period).",
                 7.5, color=grey)

    # ---- days and symbols
    y = heading(new_page(), "Result per day (UTC)")
    y = table(y, [("Day", L, "left"), ("Positions closed", L + 160, "right"), ("Net, % of start" if pct else "Net", L + 270, "right"),
                  ("Day %", L + 340, "right"), ("Since start" if pct else "Balance", R, "right")],
              [[(d["day"], None), (str(d["trades"]), None), (M(d["net"]), col(d["net"])), (_pct(d["pct"]), col(d["net"])),
                (B(d["balance"]), None)] for d in r["days"]])
    y = heading(y + 6, "Result per symbol")
    y = table(y, [("Symbol", L, "left"), ("Positions", L + 160, "right"), ("Win rate", L + 250, "right"), ("Net, % of start" if pct else "Net", R, "right")],
              [[(s["symbol"] or "-", None), (str(s["trades"]), None), (_pct(s["wins"] / s["trades"] * 100, False), None),
                (M(s["net"]), col(s["net"]))] for s in r["symbols"]])

    # ---- taxes and the other balance bookings
    if known:
        y = heading(y + 6, "Taxes and other balance bookings")
        totals = [("Taxes withheld", sum(c["amount"] for c in r["cash"] if c.get("type") == "TAX" and c["amount"] < 0)),
                  ("Tax refunds", sum(c["amount"] for c in r["cash"] if c.get("type") == "TAX" and c["amount"] > 0)),
                  ("Net tax", r["taxes"]), ("Fees, interest, dividend adjustments (counted in the result)", r["cash_result"]),
                  ("Deposits", r["deposits"]), ("Withdrawals", r["withdrawals"]), ("Corrections (not counted)", r["cash_other"])]
        y = table(y, [("", L, "left"), ("Net, % of start" if pct else f"Amount {cur}", R, "right")],
                  [[(k, None), (M(v), col(v))] for k, v in totals])
        if r["cash"]:
            y = table(y, [("Booking (broker)", L, "left"), ("Time UTC", L + 110, "left"), ("Type", L + 210, "left"),
                          ("Comment", L + 290, "left"), ("% of start" if pct else "Amount", R, "right")],
                      [[(str(c.get("ticket") or ""), None), (_stamp(c["time"]), None), (c.get("type") or "", None),
                        ((c.get("comment") or "")[:40], None), (M(c.get("amount") or 0), col(c.get("amount")))] for c in r["cash"]])
        else:
            pdf.text(L, y, "No tax, deposit, fee or other booking in this period.", 8, color=grey)
            y += 14

    # ---- every position
    y = heading(new_page(), f"Closed positions ({r['trades']})")
    y = table(y, [("Position ID (broker)", L, "left"), ("Opened UTC", L + 110, "left"), ("Closed UTC", L + 200, "left"),
                  ("Symbol", L + 290, "left"), ("Side", L + 370, "left"), ("" if pct else "Volume", L + 440, "right"),
                  ("Net, % of start" if pct else "Net", R, "right")],
              [[(p["position_id"], None), (_stamp(p["opened"]) if p["opened"] else "-", None), (_stamp(p["closed"]), None),
                (p["symbol"] or "", None), (p["side"] or "", None), ("" if pct else f"{p['volume']:.2f}", None), (M(p["net"]), col(p["net"]))]
               for p in r["positions"]])

    # ---- method, limits, integrity
    if y > 560:
        y = new_page()
    y = heading(y + 4, "Data, method and limits")
    notes = [
        "Source: the deal history of the MetaTrader 5 terminal, exported read-only by SessionDesk; no figure was typed in by hand.",
        *(["Start balance = balance at report time minus every deal and every balance booking since the start (exact).",
           "Result before tax = closed trades plus fees, interest and dividend adjustments. Taxes, deposits and withdrawals are",
           "shown apart and never counted as result" + ("; with money moved in or out the return is time-weighted (Modified Dietz)." if r.get("dietz") else ".")]
          if known else
          ["Start balance = balance at report time minus every deal result since the start of the period. This export carries no",
           "balance bookings (taxes, deposits, payouts, fees): any inside the period makes start balance and return wrong.",
           "SessionDeskBridge exports them from version 1.2 on."]),
        "A position counts in the period in which it was closed; its result includes the costs of all its deals (commission, swap).",
        "Positions still open at the end of the period are not included. Times and day boundaries are UTC.",
        "Shown in percent: every figure is a share of the start balance; no amounts, no balances, no lot sizes." if pct else "",
        f"The deal export available to this report starts on {_day(r['first_deal'])}." if r.get("first_deal") else "",
    ]
    chk = r.get("check") or {}
    if not chk.get("days"):
        notes.append("Balance check: no day-start balances recorded by SessionDesk for this account yet - the reconstruction is unchecked.")
    elif not chk.get("worst"):
        notes.append(f"Balance check: on all {chk['days']} days with a recorded day-start balance the reconstruction agrees"
                     + ("." if pct else f" within {chk['tolerance']:.2f} {cur}."))
    else:
        w = chk["worst"]
        notes += [f"Balance check: {chk['matched']} of {chk['days']} recorded day-start balances agree; the largest difference is "
                  + (f"{w['diff'] / sb * 100:+.2f} % of the start balance" if pct else f"{w['diff']:+,.2f} {cur}") + f" on {w['day']}.",
                  "The account has balance changes that are not trades (deposits, payouts, fees, dividend adjustments) or deals the",
                  "export misses: start balance, return and drawdown can be off by about that much. A day start that SessionDesk",
                  "only recorded after the first deals of that day (weekend, late start) shows up here as well."]
    for line_ in filter(None, notes):
        pdf.text(L, y, line_, 8, color=dark)
        y += 11.5
    y = heading(y + 10, "Integrity")
    for line_ in [
        f"Report ID {rid}",
        f"SHA-256 fingerprint of the report data (account, period, balances, every position):",
        fp,
        "The CSV of this report carries the same data. Recomputing the fingerprint from it (SessionDesk, Reports > Verify,",
        "or the open-source code at github.com/Timonkru/sessiondesk) shows whether any number was changed afterwards.",
        "This PDF is locked against editing. It is generated by the account holder's own software and is not an audit:",
        "for independent proof compare the position IDs with the broker's statement or ask for read-only (investor) access.",
    ]:
        pdf.text(L, y, line_, 8, bold=line_ in (fp, f"Report ID {rid}"), color=blue if line_ == fp else dark)
        y += 11.5

    # ---- footer on every page
    n = len(pdf.pages)
    for i in range(n):
        pdf.goto(i)
        pdf.line(L, 812, R, 812, 0.4, (0.8, 0.8, 0.8))
        pdf.text(L, 824, f"{rid}  ·  SHA-256 {fp[:16]}…  ·  account {r['account']}  ·  {period}", 7, color=grey)
        pdf.text(R, 824, f"page {i + 1} of {n}", 7, color=grey, align="right")
    return pdf.output()


def lock(raw: bytes) -> bytes:
    """Owner password (random, thrown away) + print-only permissions: opens without a password, edits need tools that
    ignore the flags. RC4-128 because pypdf needs no extra package for it."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.constants import UserAccessPermissions as P
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(raw)))
    w.encrypt(user_password="", owner_password=secrets.token_hex(16), permissions_flag=P.PRINT | P.PRINT_TO_REPRESENTATION,
              algorithm="RC4-128")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


# ------------------------------------------------------------------ issuing (I/O)
async def _account_data(ctx, account: str, full_number: bool):
    conns = list(ctx.hub.candidates("account"))
    for c in conns:
        kw = {"masked": not full_number} if c.id == "mt5" else {}
        try:
            accs = await c.account(**kw)
        except TypeError:
            accs = await c.account()
        for a in accs or []:
            label = a.get("login")
            masked = ("…" + str(label)[-3:]) if label and len(str(label)) > 3 else label
            if account in (label, masked):
                deals = await c.deals(**kw) if hasattr(c, "deals") else []
                book = await c.cash(**kw) if hasattr(c, "cash") else {"rows": [], "covered": []}
                cash = [x for x in book["rows"] if x.get("account") == label] if label in book["covered"] else None
                return {**a, "label": label, "cash": cash}, [d for d in deals if d.get("account") == label]
    return None, []


async def accounts(ctx) -> dict:
    """Accounts with deals, and how far back each export reaches."""
    out = []
    for c in ctx.hub.candidates("account"):
        if not hasattr(c, "deals"):
            continue
        accs, deals = await c.account(), await c.deals()
        for a in accs or []:
            mine = [d.get("time") for d in deals if d.get("account") == a.get("login") and d.get("time")]
            out.append({"account": a.get("login"), "currency": a.get("currency"), "server": a.get("server"),
                        "from": _day(min(mine)) if mine else None, "to": _day(max(mine)) if mine else None, "deals": len(mine)})
    return {"accounts": out}


def period_bounds(kind: str, today: dt.date, frm: str | None = None, to: str | None = None) -> tuple[float, float]:
    """[start, end) in UTC seconds for 'last_month', 'this_month', 'last_30' or 'custom' (inclusive dates) (pure, tested)."""
    def ts(d: dt.date) -> float:
        return dt.datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()
    first = today.replace(day=1)
    if kind == "last_month":
        prev = (first - dt.timedelta(days=1)).replace(day=1)
        return ts(prev), ts(first)
    if kind == "this_month":
        return ts(first), ts(today + dt.timedelta(days=1))
    if kind == "custom" and frm and to:
        a, b = dt.date.fromisoformat(frm), dt.date.fromisoformat(to)
        return ts(min(a, b)), ts(max(a, b) + dt.timedelta(days=1))
    return ts(today - dt.timedelta(days=29)), ts(today + dt.timedelta(days=1))


async def issue(ctx, account: str, kind: str, frm: str | None, to: str | None, full_number: bool, units: str = "money") -> dict:
    acc, deals = await _account_data(ctx, account, full_number)
    if not acc:
        return {"error": f"account {account} not found among the connected MetaTrader 5 accounts"}
    if not deals:
        return {"error": "no deals exported for this account"}
    start, end = period_bounds(kind, dt.date.today(), frm, to)
    end = min(end, time.time() // 60 * 60)               # whole minutes: the report states its end to the minute
    first = min(d["time"] for d in deals if d.get("time"))
    trimmed = None
    if first > start:                                   # the export does not reach back far enough
        cover = dt.datetime.fromtimestamp(first, UTC).date() + dt.timedelta(days=1)
        new_start = dt.datetime(cover.year, cover.month, cover.day, tzinfo=UTC).timestamp()
        if new_start >= end:
            return {"error": f"the deal export of this account starts on {_day(first)} - too late for this period"}
        trimmed, start = _day(start), new_start
    r = build(deals, {"label": acc["label"], "currency": acc.get("currency"), "balance": acc.get("balance"), "server": acc.get("server"),
                      "company": acc.get("company")}, start, end, cash=acc.get("cash"))
    stored = await ctx.db.run(ctx.db.day_starts)
    tail = str(acc["label"])[-3:]
    recorded = {day: b for (a, day), b in stored.items() if str(a)[-3:] == tail and str(a)[:-3] in ("…", "", str(acc["label"])[:-3])}
    r["check"] = balance_check(deals, acc.get("balance") or 0.0, recorded, cash=acc.get("cash"))
    r["units"] = "percent" if units == "percent" else "money"
    fp = fingerprint(data_block(r))
    rid = report_id(r, fp)
    pdf = lock(to_pdf(r, rid, fp))
    text = to_csv(r, rid, fp)
    folder = ctx.data_dir / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{rid}.pdf").write_bytes(pdf)
    (folder / f"{rid}.csv").write_text(text, encoding="utf-8", newline="")
    row = {"id": rid, "created": r["generated"], "account": r["account"], "period_from": _day(start), "period_to": _day(end - 1),
           "data_sha": fp, "pdf_sha": hashlib.sha256(pdf).hexdigest(), "csv_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
           "net": None if r["units"] == "percent" else r["net"], "net_pct": r["net_pct"], "currency": r["currency"], "trades": r["trades"],
           "units": r["units"]}
    await ctx.db.run(ctx.db.report_add, row)
    return {**row, "trimmed_from": trimmed, "check": {k: v for k, v in r["check"].items() if k != "rows"},
            "summary": {k: r[k] for k in (("net_pct", "trades", "win_rate", "profit_factor", "max_dd_pct") if r["units"] == "percent"
                                          else ("start_balance", "end_balance", "net", "net_pct", "trades", "win_rate", "profit_factor", "max_dd", "max_dd_pct"))}}


def compare_blocks(old: dict, new: dict) -> list[str]:
    """Differences between an issued report's data and the same report built again (pure, tested)."""
    out = []
    for k in ("account", "currency", "from", "to", "start_balance", "end_balance", "return_pct"):
        if old.get(k) != new.get(k):
            out.append(f"{k}: report {old.get(k)} - rebuilt {new.get(k)}")
    po, pn = {p[0]: p for p in old.get("positions", [])}, {p[0]: p for p in new.get("positions", [])}
    missing, extra = sorted(set(po) - set(pn)), sorted(set(pn) - set(po))
    changed = [k for k in po.keys() & pn.keys() if po[k] != pn[k]]
    if missing:
        out.append(f"{len(missing)} position(s) in the report but not in the broker export: {', '.join(missing[:5])}")
    if extra:
        out.append(f"{len(extra)} position(s) in the broker export but not in the report: {', '.join(extra[:5])}")
    if changed:
        out.append(f"{len(changed)} position(s) with other values: {', '.join(sorted(changed)[:5])}")
    if old.get("cash") != new.get("cash"):
        out.append("balance bookings differ")
    return out


def explain(old: dict, new: dict) -> str | None:
    """The one benign cause of a difference: a balance booking after the report that the export does not carry (tax,
    fee, payout). Then every trade is the same and only the reconstructed start balance moved - in money both balances
    move by the same amount, in percent every figure scales by the same factor (pure, tested)."""
    po, pn = {p[0]: p for p in old.get("positions", [])}, {p[0]: p for p in new.get("positions", [])}
    if set(po) != set(pn) or not po:
        return None
    if all(po[k][:6] == pn[k][:6] for k in po) and "start_balance" in old:
        d1, d2 = new["start_balance"] - old["start_balance"], new["end_balance"] - old["end_balance"]
        if [x[6] for x in po.values()] == [x[6] for x in pn.values()] and abs(d1 - d2) < 0.011 and abs(d1) >= 0.01:
            return (f"Every position is identical; start and end balance both moved by {d1:+,.2f}: a balance booking after the "
                    "report (tax, fee, payout) that this export does not carry. The trades in the report are correct.")
    if "return_pct" in old and all(po[k][:6] == pn[k][:6] for k in po):
        ratios = [pn[k][6] / po[k][6] for k in po if abs(po[k][6]) >= 0.05]      # small values are too rounded to compare
        if ratios and max(ratios) - min(ratios) < 0.01 and abs(ratios[0] - 1) > 1e-4:
            return (f"Every position is identical; all percentages scale by the same factor ({ratios[0]:.4f}), so only the "
                    "reconstructed start balance moved: a balance booking after the report (tax, fee, payout) that this export "
                    "does not carry. The trades in the report are correct.")
    return None


async def recheck(ctx, rid: str) -> dict:
    """Build an issued report again from the broker export as it is now - same account, same minutes, same units -
    and compare it with what the report states. Identical = the report was made correctly from the broker's data."""
    path = ctx.data_dir / "reports" / f"{rid}.csv"
    if not path.is_file():
        return {"error": f"no CSV of {rid} in this SessionDesk"}
    text = path.read_text(encoding="utf-8")
    v = verify_csv(text)
    if not v.get("ok"):
        return {"error": "the stored CSV does not match its own fingerprint - it was changed", "detail": v}
    rows = list(csv.reader(io.StringIO(text)))
    meta = {r[0]: r[1] for r in rows[1:rows.index([])] if len(r) >= 2}
    full = not str(meta["account"]).startswith("…")
    acc, deals = await _account_data(ctx, meta["account"], full)
    if not acc:
        return {"error": f"account {meta['account']} is not connected now"}
    start = dt.datetime.strptime(meta["from"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp()
    end = dt.datetime.strptime(meta["to"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp()
    first = min((d["time"] for d in deals if d.get("time")), default=None)
    if first is None or first > start:
        return {"report_id": rid, "reproducible": False,
                "detail": f"the broker export now starts {_day(first) if first else 'nowhere'} - after the report's start, so it cannot be rebuilt"}
    old = _block_from_csv(text)
    if "cash" in old and acc.get("cash") is None:
        return {"report_id": rid, "reproducible": False, "detail": "the report counted balance bookings; the export now carries none"}
    r = build(deals, {"label": acc["label"], "currency": acc.get("currency"), "balance": acc.get("balance"), "server": acc.get("server"),
                      "company": acc.get("company")}, start, end, cash=acc.get("cash") if "cash" in old else None)
    r["units"] = meta.get("units", "money")
    new = data_block(r)
    diffs = compare_blocks(old, new)
    return {"report_id": rid, "reproducible": True, "identical": not diffs, "differences": diffs, "explained": explain(old, new),
            "checked": f"{len(new.get('positions', []))} positions, {len(new.get('cash', []))} bookings"}


def _block_from_csv(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    cut = rows.index([])
    meta = {r[0]: r[1] for r in rows[1:cut] if len(r) >= 2}
    rest = rows[cut + 1:]
    cut2 = next((i for i, r in enumerate(rest) if not any(r)), None)
    table = [r for r in (rest[:cut2] if cut2 is not None else rest) if r]
    cash_rows = [r for r in rest[cut2 + 1:] if r] if cut2 is not None else []
    out = {k: meta.get(k) for k in ("account", "currency", "from", "to")}
    for k in ("start_balance", "end_balance", "return_pct"):
        if meta.get(k) not in (None, ""):
            out[k] = float(meta[k])
    out["positions"] = [[p[0], p[1], p[2], p[3], p[4], float(p[5]) if p[5] != "" else "", float(p[6])] for p in table[1:]]
    if cash_rows:
        out["cash"] = [[c[0], c[1], c[2], float(c[3])] for c in cash_rows[1:]]
    return out


async def verify(ctx, data: bytes) -> dict:
    """A PDF or CSV checked against the register (byte for byte) and, for a CSV, its fingerprint recomputed."""
    sha = hashlib.sha256(data).hexdigest()
    hit = await ctx.db.run(ctx.db.report_find, sha)
    out = {"sha256": sha, "registered": hit}
    if data[:5] == b"%PDF-":
        out["kind"] = "pdf"
    else:
        out["kind"] = "csv"
        out["csv"] = verify_csv(data.decode("utf-8", "replace"))
    return out
