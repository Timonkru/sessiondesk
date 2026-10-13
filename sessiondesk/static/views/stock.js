// Single stock: quote, chart, key stats, valuation (multiples vs peers, reverse DCF you can steer), news, filings.
import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, price, pct, big, num, ratio, dir, ago, stamp, clock, note, loading, errorBox, ext } from "../lib/ui.js";

const RANGES = [["1d", "1D"], ["5d", "5D"], ["1mo", "1M"], ["3mo", "3M"], ["6mo", "6M"], ["1y", "1Y"], ["5y", "5Y"], ["max", "Max"]];

export async function render(root, params, ctx) {
  const symbol = (params[0] || "").trim();
  if (!symbol) { root.appendChild(note("Type a symbol or company name in the search bar.")); return; }
  const head = h("div"), chartBox = h("div"), stats = h("div"), val = h("div"), newsBox = h("div"), filingsBox = h("div"), about = h("div");
  const tabs = h("div", { class: "tabs" });
  root.append(head, chartBox, h("div", { class: "cols" }, h("div", null, stats, val), h("div", null, tabs, newsBox, filingsBox, about)));
  head.appendChild(loading(`Loading ${symbol}…`));

  const state = { summary: null, valuation: null, news: null, range: localStorage.getItem("sd.range") || "1y" };
  const pushContext = () => ctx.setContext({
    page: `Stock ${symbol}`, symbol,
    quote: state.summary && state.summary.quote, profile: state.summary && { ...state.summary.profile, summary: undefined },
    index: state.summary && state.summary.index,
    valuation: state.valuation && { multiples: state.valuation.multiples, quality: state.valuation.quality, peers: state.valuation.peers,
                                   reverse_dcf: state.valuation.reverse_dcf, street: state.valuation.street, inputs: state.valuation.inputs },
    headlines: state.news && (state.news.items || []).slice(0, 15).map((n) => ({ title: n.title, source: n.source, published: n.published })),
  });

  // ---------------------------------------------------------------- header + chart
  const loadSummary = async () => {
    const s = await api(`/api/stock/${encodeURIComponent(symbol)}`, { fresh: true });
    if (s.error) { clear(head, h("h1", null, symbol), errorBox(s.error)); return null; }
    state.summary = s;
    const q = s.quote || {}, p = s.profile || {};
    clear(head,
      h("div", { class: "pagehead" },
        h("h1", null, p.name || symbol), h("span", { class: "muted" }, symbol),
        h("span", { class: "meta" }, [q.exchange, q.currency, s.index ? "member of " + s.index : null].filter(Boolean).join(" · "))),
      h("div", { class: "pagehead" },
        h("span", { style: { fontSize: "26px", fontWeight: 600 } }, price(q.price)),
        h("span", { class: dir(q.change_pct), style: { fontSize: "17px" } }, `${q.change != null ? (q.change > 0 ? "+" : "") + price(q.change) : ""}  ${pct(q.change_pct)}`),
        h("span", { class: "meta" }, q.time ? `last trade ${stamp(q.time)} · source ${q.source || "?"}` : ""),
        h("button", { class: "linkish", onclick: () => ctx.ask(`What explains ${symbol}'s recent price action and how is it valued compared to its peers?`) }, "Ask AI about this stock")));
    renderStats(s);
    return s;
  };

  const rangeBar = h("div", { class: "toolbar" }, RANGES.map(([r, label]) =>
    h("button", { class: "linkish", style: { fontWeight: r === state.range ? 700 : 400 }, onclick: () => { state.range = r; localStorage.setItem("sd.range", r); loadChart(); } }, label)));
  const chartHolder = h("div");
  chartBox.append(rangeBar, chartHolder);

  const loadChart = async () => {
    [...rangeBar.children].forEach((b, i) => { b.style.fontWeight = RANGES[i][0] === state.range ? 700 : 400; });
    clear(chartHolder, loading("Loading chart…"));
    const d = await api(`/api/stock/${encodeURIComponent(symbol)}/history?range=${state.range}`, { ttl: 30000 });
    if (d.error) { clear(chartHolder, errorBox(d.error)); return; }
    const intraday = state.range === "1d" || state.range === "5d";
    const pts = (d.bars || []).map((b) => ({ x: b.t, y: b.c }));
    const ref = state.range === "1d" && state.summary ? state.summary.quote.prev_close : null;
    const fmtX = (t) => intraday ? new Date(t * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })
                                 : new Date(t * 1000).toLocaleDateString([], { day: "2-digit", month: "short", year: "2-digit" });
    const first = pts.length ? pts[0].y : null, last = pts.length ? pts[pts.length - 1].y : null;
    clear(chartHolder, lineChart(pts, { ref, fmtY: (v) => price(v), fmtX }),
      h("p", { class: "note" }, first ? `Range change ${pct((last / (ref || first) - 1) * 100)} · ${pts.length} bars · source ${d.source}` : ""));
  };

  // ---------------------------------------------------------------- stats
  const renderStats = (s) => {
    const q = s.quote || {}, p = s.profile || {};
    const earn = p.earnings_ts || p.earnings_start;
    const rows = [
      ["Market cap", big(p.market_cap)], ["Enterprise value", big(p.enterprise_value)],
      ["Day range", q.day_low ? `${price(q.day_low)} – ${price(q.day_high)}` : "–"], ["52-week range", p.low_52w ? `${price(p.low_52w)} – ${price(p.high_52w)}` : "–"],
      ["Volume", big(q.volume)], ["Avg volume", big(p.avg_volume)],
      ["Beta", p.beta != null ? num(p.beta, 2) : "–"], ["Dividend yield", p.dividend_yield != null ? ratio(p.dividend_yield, 2) : "–"],
      ["Next earnings", earn ? stamp(earn) : "–"], ["Employees", p.employees ? big(p.employees) : "–"],
      ["Sector", p.sector || "–"], ["Industry", p.industry || "–"],
    ];
    clear(stats, section("Key data", h("dl", { class: "kv" }, rows.map(([k, v]) => [h("dt", null, k), h("dd", null, v)]))),
      s.profile_pending ? note("Fundamentals are still loading…", "loading") : s.profile_error ? note("Fundamentals unavailable: " + s.profile_error) : null);
    if (p.summary) clear(about, section("About", h("p", { class: "small", style: { color: "var(--fg2)" } }, p.summary),
      p.website ? ext(p.website, p.website.replace(/^https?:\/\//, "")) : null));
  };

  // ---------------------------------------------------------------- valuation
  const loadValuation = async () => {
    clear(val, section("Valuation", loading("Computing valuation (fundamentals + peers)…")));
    const v = await api(`/api/stock/${encodeURIComponent(symbol)}/valuation`, { ttl: 600000 });
    if (v.error) { clear(val, section("Valuation", errorBox(v.error))); return; }
    state.valuation = v;
    const med = (v.peers && v.peers.medians) || {};
    const peerNote = v.peers && v.peers.symbols && v.peers.symbols.length ? `Peers: ${v.peers.symbols.join(", ")} (same index, industry first).` : "No peer group (symbol not in the bundled index lists).";
    const multiples = table([
      { label: "Multiple", render: (m) => h("span", { title: m.meaning }, m.label) },
      { label: symbol, num: true, render: (m) => m.flag ? h("span", { class: "muted", title: m.flag }, m.value != null ? num(m.value, 1) + " *" : "–") : num(m.value, 1) },
      { label: "Peer median", num: true, render: (m) => med[m.key] && med[m.key].median != null ? `${num(med[m.key].median, 1)} (n ${med[m.key].n})` : "–" },
      { label: "vs peers", num: true, render: (m) => {
        const pm = med[m.key] && med[m.key].median;
        if (m.flag || m.value == null || !pm) return "";
        const d = (m.value / pm - 1) * 100;
        return h("span", { class: d > 0 ? "warn" : "" }, pct(d, 0));
      } },
    ], v.multiples);
    const quality = table([
      { label: "Quality & growth", render: (q) => q.label },
      { label: symbol, num: true, render: (q) => q.value == null ? "–" : q.percent ? ratio(q.value) : num(q.value, 2) },
      { label: "Peer median", num: true, render: (q) => med[q.key] && med[q.key].median != null ? (q.percent ? ratio(med[q.key].median) : num(med[q.key].median, 2)) : "–" },
    ], v.quality);
    const flags = v.multiples.filter((m) => m.flag && m.flag !== "missing");
    clear(val, section("Valuation", multiples, flags.length ? note("* " + flags.map((m) => `${m.label}: ${m.flag}`).join(" · ")) : null, note(peerNote), quality),
      reverseDcf(v), street(v));
    pushContext();
  };

  const reverseDcf = (v) => {
    const box = h("div");
    const inp = v.inputs || {};
    if (!v.reverse_dcf) {
      box.appendChild(section("What the price implies (reverse DCF)", note((v.caveats || []).slice(2).join(" ") || "Not computable for this stock (needs positive free cash flow, shares and price in one currency).")));
      return box;
    }
    const fields = { discount: v.defaults.discount * 100, terminal: v.defaults.terminal * 100, years: v.defaults.years };
    const out = h("div");
    const mk = (key, label, step) => h("label", null, label, h("input", { type: "number", value: fields[key], step, style: { width: "72px" },
      oninput: (e) => { fields[key] = parseFloat(e.target.value); update(); } }));
    const update = () => {
      const g = impliedGrowth(inp.price, inp.fcf, fields.discount / 100, fields.terminal / 100, Math.round(fields.years), inp.net_debt, inp.shares);
      clear(out,
        h("p", { style: { fontSize: "16px", margin: "8px 0" } }, "Today's price assumes free cash flow grows ",
          h("strong", null, g == null ? "faster than 150 % a year (not reachable)" : pct(g * 100, 1, false) + " a year"),
          ` for ${Math.round(fields.years)} years, then ${num(fields.terminal, 1)} % forever, discounted at ${num(fields.discount, 1)} %.`),
        h("p", { class: "note" }, `Starting point: ${inp.fcf_note}: ${big(inp.fcf)} ${v.financial_currency || v.currency || ""}. ` +
          `FCF yield ${ratio(v.reverse_dcf.fcf_yield, 2)} · net debt ${big(inp.net_debt)} · ${big(inp.shares)} shares.`),
        fcfHistory(inp.fcf_history));
    };
    box.appendChild(section("What the price implies (reverse DCF)",
      h("div", { class: "toolbar" }, mk("discount", "Discount rate %", 0.5), mk("terminal", "Terminal growth %", 0.25), mk("years", "Years", 1)),
      out, sensitivity(v.reverse_dcf.grid), note(v.caveats.join(" "))));
    update();
    return box;
  };

  const sensitivity = (grid) => table([
    { label: "Discount \\ terminal", render: (r) => pct(r.discount * 100, 1, false) },
    ...grid[0].cells.map((c, i) => ({ label: pct(c.terminal * 100, 1, false), num: true, render: (r) => r.cells[i].growth == null ? "–" : pct(r.cells[i].growth * 100, 1, false) })),
  ], grid);

  const fcfHistory = (hist) => !hist || !hist.length ? null :
    h("p", { class: "note" }, "Free cash flow history: " + hist.slice().sort((a, b) => a.year.localeCompare(b.year)).map((x) => `${x.year} ${big(x.fcf)}`).join(" · "));

  const street = (v) => {
    const s = v.street || {};
    if (!s.target_mean && !s.recommendation) return null;
    return section("Analysts (vendor consensus)", h("dl", { class: "kv" },
      h("dt", null, "Mean target"), h("dd", null, s.target_mean ? price(s.target_mean) : "–"),
      h("dt", null, "Upside to mean"), h("dd", { class: dir(s.upside_to_mean) }, s.upside_to_mean != null ? pct(s.upside_to_mean * 100, 1) : "–"),
      h("dt", null, "Range"), h("dd", null, s.target_low ? `${price(s.target_low)} – ${price(s.target_high)}` : "–"),
      h("dt", null, "Analysts / rating"), h("dd", null, `${s.analysts ?? "–"} / ${s.recommendation || "–"}`)),
      v.vendor_dcf ? note(`${v.vendor_dcf.source} DCF value: ${price(v.vendor_dcf.value)} (vendor model, assumptions not disclosed).`) : null,
      note("Consensus targets lag the price and cluster; treat them as sentiment, not as a valuation."));
  };

  // ---------------------------------------------------------------- news + filings
  let tab = "news";
  const drawTabs = () => clear(tabs, ["news", "filings"].map((t) => h("button", { class: t === tab ? "on" : "", onclick: () => { tab = t; drawTabs(); show(); } }, t === "news" ? "News" : "Filings")));
  const show = () => { newsBox.hidden = tab !== "news"; filingsBox.hidden = tab !== "filings"; if (tab === "filings" && !filingsBox.dataset.loaded) loadFilings(); };
  const loadNews = async () => {
    clear(newsBox, loading());
    const d = await api(`/api/stock/${encodeURIComponent(symbol)}/news`, { ttl: 120000 });
    state.news = d;
    clear(newsBox, h("ul", { class: "feed" }, (d.items || []).slice(0, 40).map((n) => h("li", null,
      h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
      h("div", { class: "m" }, `${ago(n.published)} ago · ${n.source}` + (n.sentiment ? ` · ${n.sentiment}` : ""))))),
      (d.items || []).length ? null : note("No headlines from the active news sources."),
      note("Sources: " + ((d.sources || []).join(", ") || "none") + (d.errors && Object.keys(d.errors).length ? " · failed: " + Object.keys(d.errors).join(", ") : "")));
    pushContext();
  };
  const loadFilings = async () => {
    filingsBox.dataset.loaded = "1";
    clear(filingsBox, loading());
    const d = await api(`/api/stock/${encodeURIComponent(symbol)}/filings`, { ttl: 600000 });
    clear(filingsBox, d.note ? note(d.note) : null, table([
      { label: "Date", render: (f) => f.date }, { label: "Form", render: (f) => ext(f.url, f.form) },
      { label: "What", render: (f) => [f.kind, f.description, f.items ? "items " + f.items : ""].filter(Boolean).join(" · ") },
    ], d.items || [], { empty: d.error ? d.error : "No filings (US listings only)." }));
  };
  drawTabs(); show();

  const s = await loadSummary();
  if (!s) return;
  pushContext();
  loadChart(); loadNews(); loadValuation();
  // Cold fundamentals take a few seconds (yfinance); poll until they are in, then stop.
  let tries = 0;
  const retry = async () => { const again = await loadSummary(); pushContext(); if (again && again.profile_pending && ++tries < 6) setTimeout(retry, 2500); };
  if (s.profile_pending) setTimeout(retry, 2500);
  const timer = setInterval(async () => { await loadSummary(); if (state.range === "1d") loadChart(); }, 30000);
  return () => clearInterval(timer);
}

// Same two-stage model as sessiondesk/features/valuation.py (kept in sync by tests on the Python side).
function dcfPerShare(fcf0, g, r, t, years, netDebt, shares) {
  let pv = 0, fcf = fcf0;
  for (let i = 1; i <= years; i++) { fcf *= 1 + g; pv += fcf / Math.pow(1 + r, i); }
  pv += (fcf * (1 + t) / (r - t)) / Math.pow(1 + r, years);
  return (pv - netDebt) / shares;
}
function impliedGrowth(price, fcf0, r, t, years, netDebt, shares) {
  if (!(fcf0 > 0) || !(price > 0) || !(r > t) || !(shares > 0) || !(years >= 1)) return null;
  let lo = -0.5, hi = 1.5;
  const f = (g) => dcfPerShare(fcf0, g, r, t, years, netDebt, shares) - price;
  if (f(lo) > 0) return lo;
  if (f(hi) < 0) return null;
  for (let k = 0; k < 80; k++) { const m = (lo + hi) / 2; if (f(m) > 0) hi = m; else lo = m; }
  return (lo + hi) / 2;
}
