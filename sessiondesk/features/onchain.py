"""Bitcoin on-chain levels for the Data hub: the short-term holder realized price (STH-RP, the average on-chain cost
basis of coins that moved within the last 155 days). A daily value; it moves slowly, a few hundred dollars a day.

Sources, both free and without an account (checked 27.10.2026):
  checkonchain   "STH Cost Basis" trace of the public chart charts.checkonchain.com (Plotly HTML on charts-cdn), updated
                 daily for the same day. Unofficial: SessionDesk reads the chart file like a browser does; the layout can
                 change without notice. robots.txt allows it (Content-Signal: search=yes, ai-train=no).
  BGeometrics    official free API bitcoin-data.com, but the free tier ends seven days back ("real-time data (last 7
                 days) requires an active subscription"). Used as the second opinion and as the fallback.
The two differ by about 0.2 % (20.10.2026: 74,612.94 vs 74,736.27) - different UTXO-age cut-offs and price sources.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import struct

COC_URL = "https://charts-cdn.checkonchain.com/btconchain/pricing/quantiles_realizedprice_sth/quantiles_realizedprice_sth_light.html"
COC_PAGE = "https://charts.checkonchain.com/btconchain/pricing/quantiles_realizedprice_sth/quantiles_realizedprice_sth_light.html"
BGEO_URL = "https://bitcoin-data.com/v1/sth-realized-price"
BGEO_PAGE = "https://charts.bgeometrics.com/sth_realized_price.html"
CATEGORY = "On-chain (Bitcoin)"
SERIES = {"onchain:sth_rp": ("BTC short-term holder realized price (checkonchain)", "checkonchain STH Cost Basis (unofficial chart data)"),
          "onchain:sth_rp_bgeo": ("BTC short-term holder realized price (BGeometrics, 7 days delayed)", "BGeometrics free API")}
UA = {"User-Agent": "Mozilla/5.0 (SessionDesk)"}


def _trace_values(html: str, name: str) -> list[tuple[str, float]]:
    """Dates and values of one named Plotly trace; y may be a plain list or Plotly's base64 'bdata' (pure, tested)."""
    i = html.find(f'"name":"{name}"')
    if i < 0:
        return []
    k = html.find('"x":[', i)
    xe = html.find("]", k)
    if k < 0 or xe < 0:
        return []
    xs = json.loads(html[k + 4:xe + 1])
    yk = html.find('"y":', xe)
    m = re.match(r'"y":\{"dtype":"(f8|f4)","bdata":("[^"]+")', html[yk:yk + 20_000_000])
    if m:
        raw = base64.b64decode(json.loads(m.group(2)))
        fmt = "d" if m.group(1) == "f8" else "f"
        ys = struct.unpack(f"<{len(raw) // struct.calcsize(fmt)}{fmt}", raw)
    else:
        ye = html.find("]", yk)
        ys = json.loads(html[yk + 4:ye + 1])
    return [(str(x)[:10], float(y)) for x, y in zip(xs, ys) if y is not None and y == y and y > 0]


def parse_checkonchain(html: str) -> list[tuple[str, float]]:
    return _trace_values(html, "STH Cost Basis")


def parse_bgeometrics(rows) -> list[tuple[str, float]]:
    """bitcoin-data.com rows [{"d": "YYYY-MM-DD", "sthRealizedPrice": "74736.27"}, ...] (pure, tested)."""
    out = []
    for r in rows if isinstance(rows, list) else [rows]:
        try:
            out.append((r["d"], float(r["sthRealizedPrice"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(dict(out).items())


async def collect(ctx) -> int:
    """Data hub collector: both sources into their own series. Each failing source is skipped, not fatal."""
    from .datahub import _meta
    got = 0
    try:
        resp = await ctx.http.get(COC_URL, headers=UA, timeout=60, follow_redirects=True)
        pts = parse_checkonchain(resp.text) if resp.status_code == 200 else []
    except Exception:
        pts = []
    if pts:
        await ctx.db.run(ctx.db.upsert_series, _meta("onchain:sth_rp", SERIES["onchain:sth_rp"][0], CATEGORY,
                                                     SERIES["onchain:sth_rp"][1], "price", "$"), pts[-3000:])
        got += 1
    try:
        start = (dt.date.today() - dt.timedelta(days=800)).isoformat()
        resp = await ctx.http.get(BGEO_URL, params={"startday": start}, headers=UA, timeout=30)
        pts = parse_bgeometrics(resp.json()) if resp.status_code == 200 else []
    except Exception:
        pts = []
    if pts:
        await ctx.db.run(ctx.db.upsert_series, _meta("onchain:sth_rp_bgeo", SERIES["onchain:sth_rp_bgeo"][0], CATEGORY,
                                                     SERIES["onchain:sth_rp_bgeo"][1], "price", "$"), pts)
        got += 1
    return got
