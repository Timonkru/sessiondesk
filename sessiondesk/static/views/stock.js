// Instrument detail: header with key strip, chart, and tabs that each load their own data block.
// Equities get the full set (financials, earnings, street, valuation, ownership, options ...);
// indices, FX, futures and crypto get the tabs that make sense for them.
import { api } from "../lib/api.js";
import { lineChart, candleChart } from "../lib/chart.js";
import { h, clear, price, pct, big, num, ratio, dir, stamp, note, loading, errorBox, toast } from "../lib/ui.js";
import * as T from "./stock_tabs.js";

const RANGES = [["1d", "1D"], ["5d", "5D"], ["1mo", "1M"], ["3mo", "3M"], ["6mo", "6M"], ["1y", "1Y"], ["5y", "5Y"], ["max", "Max"]];
const EQUITY_TABS = [["overview", "Overview"], ["financials", "Financials"], ["earnings", "Earnings"], ["street", "Estimates & analysts"],
  ["valuation", "Valuation"], ["ownership", "Ownership & short"], ["options", "Options"], ["performance", "Performance & risk"],
  ["peers", "Peers"], ["people", "People & indices"], ["network", "Network"], ["dividends", "Dividends"], ["news", "News"], ["filings", "Filings"]];
const OTHER_TABS = [["overview", "Overview"], ["performance", "Performance & risk"], ["options", "Options"], ["news", "News"]];

export async function render(root, params, ctx) {
  const symbol = (params[0] || "").trim();
  const wantedTab = params[1] || null;
  if (!symbol) { root.appendChild(note("Type a symbol or company name in the search bar.")); return; }
  const head = h("div"), strip = h("div", { class: "keystrip" }), chartBox = h("div"), tabBar = h("div", { class: "tabs" }), body = h("div");
  root.append(head, strip, chartBox, tabBar, body);
  head.appendChild(loading(`Loading ${symbol}…`));

  const state = { summary: null, range: localStorage.getItem("sd.range") || "1y", tab: wantedTab || "overview", blocks: {} };
  const enc = encodeURIComponent(symbol);
  const pushContext = () => {
    const s = state.summary || {};
    ctx.setContext({ page: `Instrument ${symbol} - ${state.tab} tab`, symbol, type: s.type, quote: s.quote && { ...s.quote, intraday: undefined },
      profile: s.profile && { ...s.profile, summary: (s.profile.summary || "").slice(0, 600) }, index: s.index, ...state.blocks });
  };
  // Shared loader: each tab asks for its blocks; results are kept for the AI context and other tabs.
  const block = async (name) => {
    if (state.blocks[name]) return state.blocks[name];
    const d = await api(`/api/stock/${enc}/deep/${name}`, { ttl: 600000 });
    if (!d.error) state.blocks[name] = d;
    return d;
  };
  const tabCtx = { symbol, enc, state, block, ask: ctx.ask, go: ctx.go, pushContext, open: (k) => openTab(k) };

  // ---------------------------------------------------------------- header + key strip
  const loadSummary = async () => {
    const s = await api(`/api/stock/${enc}`, { fresh: true });
    if (s.error) { clear(head, h("h1", null, symbol), errorBox(s.error)); return null; }
    state.summary = s;
    const q = s.quote || {}, p = s.profile || {};
    clear(head,
      h("div", { class: "pagehead" },
        h("h1", null, p.name || symbol), h("span", { class: "muted" }, symbol),
        h("span", { class: "meta" }, [q.exchange, q.currency, s.type ? s.type.toLowerCase() : null, s.index ? "member of " + s.index : null, p.sector, p.industry].filter(Boolean).join(" · "))),
      h("div", { class: "pagehead" },
        h("span", { style: { fontSize: "28px", fontWeight: 600 } }, price(q.price)),
        h("span", { class: dir(q.change_pct), style: { fontSize: "17px" } }, `${q.change != null ? (q.change > 0 ? "+" : "") + price(q.change) : ""}  ${pct(q.change_pct)}`),
        h("span", { class: "meta" }, q.time ? `last trade ${stamp(q.time)} · ${q.source || "?"}` : ""),
        h("button", { class: "linkish", onclick: () => ctx.ask(`Give me a compact but deep read of ${symbol}: what moved it recently, how it is valued against peers and its own history, what the street expects, and the main risks visible in this data.`) }, "Ask AI about this"),
        h("button", { class: "linkish", onclick: async () => {
          const raw = prompt(`Price alert for ${symbol} (now ${price(q.price)}). Enter a price: above the current price alerts when it rises to it, below when it falls to it.`);
          if (!raw) return;
          const level = Number(raw.replace(",", "."));
          if (!Number.isFinite(level) || !q.price) { toast("Alert not set", "Enter a number."); return; }
          const r = await api("/api/price_alerts", { method: "POST", body: { symbol, op: level >= q.price ? "above" : "below", level } });
          if (r.error) toast("Alert not set", r.error); else toast("Price alert set", `${symbol} ${level >= q.price ? "≥" : "≤"} ${price(level)} - manage on the Levels page`);
        } }, "Set price alert")));
    drawStrip(s);
    drawTabs();
    return s;
  };
  const drawStrip = (s) => {
    const q = s.quote || {}, p = s.profile || {};
    const pos52 = p.high_52w && p.low_52w && q.price ? (q.price - p.low_52w) / (p.high_52w - p.low_52w) : null;
    const earn = p.earnings_ts || p.earnings_start;
    const items = [
      ["Market cap", big(p.market_cap)], ["P/E fwd", p.pe_forward ? num(p.pe_forward, 1) : "–"], ["EV/EBITDA", p.ev_ebitda ? num(p.ev_ebitda, 1) : "–"],
      ["Div. yield", p.dividend_yield != null ? ratio(p.dividend_yield, 2) : "–"], ["Beta", p.beta != null ? num(p.beta, 2) : "–"],
      ["52w position", pos52 != null ? pct(pos52 * 100, 0, false) : "–"], ["Short % float", p.short_pct_float != null ? ratio(p.short_pct_float, 1) : "–"],
      ["Next earnings", earn ? new Date(earn * 1000).toLocaleDateString([], { day: "2-digit", month: "short" }) : "–"],
      ["Consensus", p.recommendation ? `${p.recommendation} (${p.analysts ?? "?"})` : "–"],
    ].filter(([, v]) => v !== "–" || (s.type || "EQUITY") === "EQUITY");
    clear(strip, items.map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v))));
  };

  // ---------------------------------------------------------------- chart
  let chartType = localStorage.getItem("sd.chartType") || "candles";
  const typeBtn = h("button", { class: "linkish", onclick: () => { chartType = chartType === "candles" ? "line" : "candles"; localStorage.setItem("sd.chartType", chartType); loadChart(); } });
  const rangeBar = h("div", { class: "toolbar" }, RANGES.map(([r, label]) =>
    h("button", { class: "linkish", onclick: () => { state.range = r; localStorage.setItem("sd.range", r); loadChart(); } }, label)), h("span", { class: "muted" }, " | "), typeBtn);
  const chartHolder = h("div");
  chartBox.append(rangeBar, chartHolder);
  const loadChart = async () => {
    [...rangeBar.children].slice(0, RANGES.length).forEach((b, i) => { b.style.fontWeight = RANGES[i][0] === state.range ? 700 : 400; });
    typeBtn.textContent = chartType === "candles" ? "line chart" : "candles";
    clear(chartHolder, loading("Loading chart…"));
    const d = await api(`/api/stock/${enc}/history?range=${state.range}`, { ttl: 30000 });
    if (d.error) { clear(chartHolder, errorBox(d.error)); return; }
    const intraday = state.range === "1d" || state.range === "5d";
    const pts = (d.bars || []).map((b) => ({ x: b.t, y: b.c }));
    const ref = state.range === "1d" && state.summary ? state.summary.quote.prev_close : null;
    const fmtX = (t) => intraday ? new Date(t * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })
                                 : new Date(t * 1000).toLocaleDateString([], { day: "2-digit", month: "short", year: "2-digit" });
    const first = pts.length ? pts[0].y : null, last = pts.length ? pts[pts.length - 1].y : null;
    const hi = pts.length ? Math.max(...pts.map((p) => p.y)) : null, lo = pts.length ? Math.min(...pts.map((p) => p.y)) : null;
    // candles only when the source has real OHLC (some feeds give closes only)
    const ohlc = (d.bars || []).some((b) => b.h !== b.l);
    const chart = chartType === "candles" && ohlc
      ? candleChart(d.bars, { fmtY: (v) => price(v), fmtX, height: 280 })
      : lineChart(pts, { ref, fmtY: (v) => price(v), fmtX, height: 240 });
    clear(chartHolder, chart,
      h("p", { class: "note" }, first ? `Range ${pct((last / (ref || first) - 1) * 100)} · high ${price(hi)} · low ${price(lo)} · ${pts.length} bars · ${d.source}` : ""));
  };

  // ---------------------------------------------------------------- tabs
  const tabsFor = () => ((state.summary && state.summary.type && state.summary.type !== "EQUITY") ? OTHER_TABS : EQUITY_TABS);
  const drawTabs = () => clear(tabBar, tabsFor().map(([k, label]) => h("button", { class: k === state.tab ? "on" : "", onclick: () => openTab(k) }, label)));
  let seq = 0;
  const openTab = async (k) => {
    state.tab = k;
    history.replaceState(null, "", `#/stock/${enc}/${k}`);
    drawTabs();
    const my = ++seq;
    clear(body, loading());
    const renderer = T.TABS[k] || T.TABS.overview;
    try {
      const el = await renderer(tabCtx);
      if (my === seq) clear(body, el);
    } catch (err) {
      if (my === seq) clear(body, errorBox(`${k}: ${err.message}`));
    }
    pushContext();
  };

  const s = await loadSummary();
  if (!s) return;
  if (!tabsFor().some(([k]) => k === state.tab)) state.tab = "overview";
  loadChart();
  openTab(state.tab);
  let tries = 0;
  const retry = async () => { const again = await loadSummary(); pushContext(); if (again && again.profile_pending && ++tries < 6) setTimeout(retry, 2500); };
  if (s.profile_pending) setTimeout(retry, 2500);
  const timer = setInterval(async () => { await loadSummary(); if (state.range === "1d") loadChart(); }, 30000);
  return () => clearInterval(timer);
}
