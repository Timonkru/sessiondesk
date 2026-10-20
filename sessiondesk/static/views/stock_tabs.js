// Tab renderers for the instrument page. Each returns one element; data comes from /api/stock/<sym>/deep/<block>.
import { api } from "../lib/api.js";
import { bars } from "../lib/chart.js";
import { h, svg, table, section, price, pct, big, num, ratio, dir, ago, stamp, note, loading, errorBox, ext, clear } from "../lib/ui.js";

const fr = (v, d = 1) => (v == null ? "–" : pct(v * 100, d));          // signed percent from a fraction
const fp = (v, d = 1) => (v == null ? "–" : ratio(v, d));             // unsigned percent from a fraction
const n1 = (v, d = 2) => (v == null ? "–" : num(v, d));
const cls = (v) => dir(v);
const isEquity = (c) => !c.state.summary || !c.state.summary.type || c.state.summary.type === "EQUITY";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function grid(...cols) { return h("div", { class: "cols" }, ...cols.map((c) => h("div", null, c))); }
function kv(pairs) { return h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v, c]) => [h("dt", null, k), h("dd", { class: c || "" }, v)])); }
function fail(d) { return errorBox(d && d.error ? d.error : "no data"); }

// ================================================================== overview
async function overview(c) {
  const s = c.state.summary || {}, p = s.profile || {}, q = s.quote || {};
  const glance = h("div", null, loading("Collecting the key facts…"));
  const wireBox = h("div", null, loading("Looking for headlines…"));
  api(`/api/stock/${c.enc}/news`, { ttl: 60000 }).then((d) => {
    const items = [...(d.wire || []), ...(d.items || [])].sort((x, y) => (y.published || 0) - (x.published || 0)).slice(0, 5);
    c.state.blocks.headlines_latest = items.map((n) => ({ title: n.title, source: n.source, published: n.published, impact: n.impact }));
    clear(wireBox, items.length ? headlineList(items) : note("No recent headlines for this instrument."),
      h("p", { class: "small" }, h("a", { href: `#/stock/${c.enc}/news` , onclick: (e) => { e.preventDefault(); c.open && c.open("news"); } }, "all headlines →")));
    c.pushContext();
  });
  const earn = p.earnings_ts || p.earnings_start;
  const root = grid(
    h("div", null,
      section("Key data", kv([
        ["Market cap", big(p.market_cap)], ["Enterprise value", big(p.enterprise_value)],
        ["Day range", q.day_low ? `${price(q.day_low)} – ${price(q.day_high)}` : "–"], ["52-week range", p.low_52w ? `${price(p.low_52w)} – ${price(p.high_52w)}` : "–"],
        ["Volume", big(q.volume)], ["Avg volume", big(p.avg_volume)],
        ["P/E trailing / forward", `${n1(p.pe_trailing, 1)} / ${n1(p.pe_forward, 1)}`], ["EV / EBITDA", n1(p.ev_ebitda, 1)],
        ["Revenue growth", fr(p.revenue_growth)], ["Operating margin", fp(p.operating_margin)],
        ["Beta", n1(p.beta)], ["Dividend yield", p.dividend_yield != null ? fp(p.dividend_yield, 2) : "–"],
        ["Float", big(p.float_shares)], ["Short % of float", fp(p.short_pct_float)],
        ["Next earnings", earn ? stamp(earn) : "–"], ["Employees", p.employees ? big(p.employees) : "–"],
      ].filter(([, v]) => isEquity(c) || v !== "–"))),
      s.profile_pending ? note("Fundamentals are still loading…", "loading") : null),
    h("div", null, section("At a glance", glance), section("Latest headlines", wireBox), p.summary ? section("About", h("p", { class: "small", style: { color: "var(--fg2)" } }, p.summary),
      p.website ? ext(p.website, p.website.replace(/^https?:\/\//, "")) : null) : null));
  // Facts from the other blocks, loaded in parallel.
  (async () => {
    const want = isEquity(c) ? ["performance", "earnings", "street", "ownership", "options"] : ["performance", "options"];
    const res = await Promise.all(want.map((b) => c.block(b)));
    const got = Object.fromEntries(want.map((b, i) => [b, res[i]]));
    const lines = [];
    const perf = got.performance && got.performance.stats;
    if (perf) {
      lines.push(["1 year", fr(perf.returns["1Y"]), cls(perf.returns["1Y"])]);
      if (perf.relative["1Y"] != null) lines.push([`vs ${got.performance.benchmark}`, fr(perf.relative["1Y"]), cls(perf.relative["1Y"])]);
      lines.push(["From 52w high", fr(perf.range_52w.from_high), cls(perf.range_52w.from_high)]);
      lines.push(["Volatility 60d", fp(perf.volatility["60d"], 0)]);
      lines.push(["Trend", perf.trend.vs_sma200 == null ? "–" : `${fr(perf.trend.vs_sma200)} vs 200-day`, cls(perf.trend.vs_sma200)]);
    }
    const e = got.earnings;
    if (e && e.stats && e.stats.n) lines.push(["Earnings move", `±${fp(e.stats.avg_abs_move)} avg over ${e.stats.n} reports`]);
    if (e && e.upcoming) lines.push(["Next report", `${e.upcoming.when.slice(0, 10)} (in ${e.upcoming.days} d)`]);
    const st = got.street;
    const y0 = st && (st.eps_trend || []).find((t) => t.period === "0y");
    if (y0 && y0.current && y0["90daysAgo"]) lines.push(["EPS consensus 90d", fr(y0.current / y0["90daysAgo"] - 1), cls(y0.current - y0["90daysAgo"])]);
    if (st && st.actions_90d) lines.push(["Analysts 90d", `${st.actions_90d.up} up / ${st.actions_90d.down} down · targets ${st.actions_90d.target_raised}↑ ${st.actions_90d.target_lowered}↓`]);
    const own = got.ownership;
    if (own && own.insider_6m) lines.push(["Insiders 6m", `${own.insider_6m.buys} buys / ${own.insider_6m.sells} sells (${big(own.insider_6m.net_value)})`, cls(own.insider_6m.net_value)]);
    const opt = got.options;
    if (opt && opt.expiries && opt.expiries.length) {
      const nx = opt.expiries.find((x) => x.days >= 5) || opt.expiries[0];
      lines.push([`Implied move to ${nx.expiry}`, `±${fp(nx.implied_move)} · IV ${fp(nx.atm_iv, 0)}`]);
      if (opt.put_call_oi != null) lines.push(["Put/call (open interest)", n1(opt.put_call_oi)]);
    }
    clear(glance, lines.length ? kv(lines) : note("No additional data for this instrument."));
    c.pushContext();
  })();
  return root;
}

// ================================================================== financials
async function financials(c) {
  const d = await c.block("statements");
  if (d.error) return fail(d);
  const ann = d.annual || [], qtr = d.quarterly || [];
  const cur = c.state.summary && c.state.summary.quote && c.state.summary.quote.currency;
  const incomeCols = [
    { label: "Period", render: (r) => r.period },
    { label: "Revenue", num: true, render: (r) => big(r.revenue) }, { label: "growth", num: true, cls: (r) => cls(r.revenue_growth), render: (r) => fr(r.revenue_growth) },
    { label: "Gross margin", num: true, render: (r) => fp(r.gross_margin) }, { label: "Op. margin", num: true, render: (r) => fp(r.operating_margin) },
    { label: "Net margin", num: true, render: (r) => fp(r.net_margin) }, { label: "Net income", num: true, render: (r) => big(r.net_income) },
    { label: "EPS", num: true, render: (r) => n1(r.eps) }, { label: "EPS growth", num: true, cls: (r) => cls(r.eps_growth), render: (r) => fr(r.eps_growth) },
    { label: "R&D", num: true, render: (r) => big(r.rnd) },
  ];
  const ttm = d.ttm || {};
  return h("div", null,
    note(`All amounts in the reporting currency${cur ? " (quote currency " + cur + ")" : ""}. ${d.note}`),
    grid(section("Revenue (annual)", bars(ann.slice().reverse().map((r) => ({ label: r.period.slice(0, 4), value: r.revenue == null ? null : r.revenue / 1e9 })), { height: 150, fmt: (v) => v.toFixed(1) + " B" })),
         section("EPS (quarterly)", bars(qtr.slice().reverse().map((r) => ({ label: r.period.slice(2, 7), value: r.eps == null ? null : r.eps })), { height: 150, fmt: (v) => v.toFixed(2) }))),
    section("Income statement - annual", h("div", { class: "scroll" }, table(incomeCols, ann))),
    section("Income statement - quarterly (growth vs same quarter last year)", h("div", { class: "scroll" }, table(incomeCols, qtr))),
    section("Trailing twelve months", kv([["Revenue", big(ttm.revenue)], ["Operating income", big(ttm.operating_income)], ["Net income", big(ttm.net_income)],
      ["EBITDA", big(ttm.ebitda)], ["EPS", n1(ttm.eps)], ["Free cash flow", big(ttm.fcf)]])),
    section("Cash flow - annual", h("div", { class: "scroll" }, table([
      { label: "Period", render: (r) => r.period }, { label: "Operating CF", num: true, render: (r) => big(r.ocf) },
      { label: "Capex", num: true, render: (r) => big(r.capex) }, { label: "Free CF", num: true, render: (r) => big(r.fcf) },
      { label: "FCF margin", num: true, render: (r) => fp(r.fcf_margin) }, { label: "FCF / net income", num: true, render: (r) => n1(r.fcf_conversion) },
      { label: "Buybacks", num: true, render: (r) => big(r.buybacks) }, { label: "Dividends", num: true, render: (r) => big(r.dividends_paid) },
      { label: "Stock comp", num: true, render: (r) => big(r.sbc) }, { label: "SBC / revenue", num: true, render: (r) => fp(r.sbc_share) },
    ], d.cashflow || []))),
    section("Balance sheet - annual", h("div", { class: "scroll" }, table([
      { label: "Period", render: (r) => r.period }, { label: "Cash + ST inv.", num: true, render: (r) => big(r.cash) },
      { label: "Total debt", num: true, render: (r) => big(r.total_debt) }, { label: "Net debt", num: true, render: (r) => big(r.net_debt) },
      { label: "Equity", num: true, render: (r) => big(r.equity) }, { label: "Debt / equity", num: true, render: (r) => n1(r.debt_to_equity) },
      { label: "Net debt / EBITDA", num: true, render: (r) => n1(r.net_debt_to_ebitda) }, { label: "ROIC", num: true, render: (r) => fp(r.roic) },
      { label: "ROE", num: true, render: (r) => fp(r.roe) }, { label: "Goodwill + intang.", num: true, render: (r) => big(r.goodwill) },
    ], d.balance || []))),
    d.share_count_change && d.share_count_change.change != null
      ? note(`Diluted share count ${fr(d.share_count_change.change)} from ${d.share_count_change.from} to ${d.share_count_change.to} - negative = buybacks outweigh stock compensation.`) : null);
}

// ================================================================== earnings
async function earnings(c) {
  const [d, opt] = await Promise.all([c.block("earnings"), c.block("options")]);
  if (d.error) return fail(d);
  const st = d.stats || {};
  let implied = null;
  if (d.upcoming && opt && opt.expiries) {
    const when = d.upcoming.when.slice(0, 10);
    const ex = opt.expiries.find((x) => x.expiry >= when);
    if (ex) implied = `±${fp(ex.implied_move)} by ${ex.expiry} (straddle ${price(ex.straddle)})`;
  }
  const hist = d.history || [];
  return h("div", null,
    grid(section("Next report", d.upcoming ? kv([["Date", d.upcoming.when.replace("T", " ").slice(0, 16)], ["In", `${d.upcoming.days} days`],
        ["EPS estimate", n1(d.upcoming.eps_estimate)], ["Options imply", implied || "–"]]) : note("No upcoming date known.")),
      section("Earnings temperament", st.n ? kv([["Reports measured", st.n], ["Average move", `±${fp(st.avg_abs_move)}`], ["Median move", `±${fp(st.median_abs_move)}`],
        ["Largest move", `±${fp(st.max_abs_move)}`], ["Up after report", fp(st.up_share, 0)], ["Beat consensus", fp(st.beat_share, 0)],
        ["Avg move on beats", fr(st.avg_move_on_beat), cls(st.avg_move_on_beat)], ["Avg move on misses", fr(st.avg_move_on_miss), cls(st.avg_move_on_miss)]])
        : note("Not enough reports with price data."))),
    hist.length ? section("Reaction per report", bars(hist.filter((r) => r.move != null).slice(0, 24).reverse().map((r) => ({ label: r.date.slice(2, 7), value: r.move * 100 })), { height: 150, fmt: (v) => v.toFixed(1) })) : null,
    section("History", h("div", { class: "scroll" }, table([
      { label: "Date", render: (r) => r.date }, { label: "Timing", render: (r) => h("span", { class: "muted small" }, r.timing || "") },
      { label: "EPS est.", num: true, render: (r) => n1(r.eps_estimate) }, { label: "Reported", num: true, render: (r) => n1(r.eps_reported) },
      { label: "Surprise", num: true, cls: (r) => cls(r.surprise_pct), render: (r) => (r.surprise_pct == null ? "–" : pct(r.surprise_pct, 1)) },
      { label: "Gap", num: true, cls: (r) => cls(r.gap), render: (r) => fr(r.gap) },
      { label: "Close-to-close", num: true, cls: (r) => cls(r.move), render: (r) => fr(r.move) },
    ], hist))),
    note(d.note));
}

// ================================================================== street
async function street(c) {
  const d = await c.block("street");
  if (d.error) return fail(d);
  const per = { "0q": "This quarter", "+1q": "Next quarter", "0y": "This year", "+1y": "Next year", LTG: "Long term" };
  const s = c.state.summary || {}, px = s.quote && s.quote.price;
  const t = d.targets || {};
  const a90 = d.actions_90d || {};
  return h("div", null,
    grid(
      section("EPS consensus", table([{ label: "", render: (r) => per[r.period] || r.period }, { label: "Avg", num: true, render: (r) => n1(r.avg) },
        { label: "Low", num: true, render: (r) => n1(r.low) }, { label: "High", num: true, render: (r) => n1(r.high) },
        { label: "Year ago", num: true, render: (r) => n1(r.yearAgoEps) }, { label: "Growth", num: true, cls: (r) => cls(r.growth), render: (r) => fr(r.growth) },
        { label: "Analysts", num: true, render: (r) => r.numberOfAnalysts ?? "–" }], d.eps_estimates || [])),
      section("Revenue consensus", table([{ label: "", render: (r) => per[r.period] || r.period }, { label: "Avg", num: true, render: (r) => big(r.avg) },
        { label: "Low", num: true, render: (r) => big(r.low) }, { label: "High", num: true, render: (r) => big(r.high) },
        { label: "Growth", num: true, cls: (r) => cls(r.growth), render: (r) => fr(r.growth) }, { label: "Analysts", num: true, render: (r) => r.numberOfAnalysts ?? "–" }], d.revenue_estimates || []))),
    grid(
      section("How the EPS consensus moved", table([{ label: "", render: (r) => per[r.period] || r.period }, { label: "Now", num: true, render: (r) => n1(r.current) },
        { label: "7 d", num: true, cls: (r) => cls(r.current - r["7daysAgo"]), render: (r) => (r["7daysAgo"] ? fr(r.current / r["7daysAgo"] - 1, 2) : "–") },
        { label: "30 d", num: true, cls: (r) => cls(r.current - r["30daysAgo"]), render: (r) => (r["30daysAgo"] ? fr(r.current / r["30daysAgo"] - 1, 2) : "–") },
        { label: "90 d", num: true, cls: (r) => cls(r.current - r["90daysAgo"]), render: (r) => (r["90daysAgo"] ? fr(r.current / r["90daysAgo"] - 1, 2) : "–") }], d.eps_trend || []),
        table([{ label: "Revisions", render: (r) => per[r.period] || r.period }, { label: "Up 7d", num: true, render: (r) => r.upLast7days ?? "–" },
          { label: "Up 30d", num: true, render: (r) => r.upLast30days ?? "–" }, { label: "Down 7d", num: true, render: (r) => r.downLast7Days ?? "–" },
          { label: "Down 30d", num: true, render: (r) => r.downLast30days ?? "–" }], d.eps_revisions || [])),
      section("Price targets & ratings", kv([["Current price", price(px)], ["Mean target", price(t.mean), ""], ["Median target", price(t.median)],
        ["Range", t.low ? `${price(t.low)} – ${price(t.high)}` : "–"], ["Upside to mean", px && t.mean ? fr(t.mean / px - 1) : "–", px && t.mean ? cls(t.mean - px) : ""],
        ["Last 90 days", `${a90.up ?? 0} upgrades, ${a90.down ?? 0} downgrades, ${a90.init ?? 0} initiations`],
        ["Target changes 90d", `${a90.target_raised ?? 0} raised, ${a90.target_lowered ?? 0} lowered`]]),
        table([{ label: "Ratings", render: (r) => ({ "0m": "this month", "-1m": "1 month ago", "-2m": "2 months ago", "-3m": "3 months ago" }[r.period] || r.period) },
          { label: "Strong buy", num: true, render: (r) => r.strongBuy }, { label: "Buy", num: true, render: (r) => r.buy }, { label: "Hold", num: true, render: (r) => r.hold },
          { label: "Sell", num: true, render: (r) => r.sell }, { label: "Strong sell", num: true, render: (r) => r.strongSell }], d.recommendations || []))),
    section("Growth expectations vs index", table([{ label: "", render: (r) => per[r.period] || r.period },
      { label: c.symbol, num: true, render: (r) => fr(r.stockTrend) }, { label: "Index", num: true, render: (r) => fr(r.indexTrend) }], d.growth || [])),
    section("Latest analyst actions", h("div", { class: "scroll" }, table([{ label: "Date", render: (r) => r.date }, { label: "Firm", render: (r) => r.firm },
      { label: "Action", render: (r) => h("span", { class: r.action === "up" ? "up" : r.action === "down" ? "down" : "" }, r.action || "") },
      { label: "Rating", render: (r) => (r.from && r.from !== r.to ? `${r.from} → ${r.to}` : r.to || "") },
      { label: "Target", num: true, render: (r) => (r.target ? (r.prior_target && r.prior_target !== r.target ? `${price(r.prior_target)} → ${price(r.target)}` : price(r.target)) : "–") }],
      d.actions || []))),
    note(d.note));
}

// ================================================================== valuation (multiples, reverse DCF)
async function valuation(c) {
  const v = await api(`/api/stock/${c.enc}/valuation`, { ttl: 600000 });
  if (v.error) return fail(v);
  c.state.blocks.valuation = { multiples: v.multiples, quality: v.quality, peers: v.peers, reverse_dcf: v.reverse_dcf, street: v.street, inputs: v.inputs };
  const med = (v.peers && v.peers.medians) || {};
  const multiples = table([
    { label: "Multiple", render: (m) => h("span", { title: m.meaning }, m.label) },
    { label: c.symbol, num: true, render: (m) => (m.flag ? h("span", { class: "muted", title: m.flag }, m.value != null ? num(m.value, 1) + " *" : "–") : num(m.value, 1)) },
    { label: "Peer median", num: true, render: (m) => (med[m.key] && med[m.key].median != null ? `${num(med[m.key].median, 1)} (n ${med[m.key].n})` : "–") },
    { label: "vs peers", num: true, render: (m) => { const pm = med[m.key] && med[m.key].median; if (m.flag || m.value == null || !pm) return ""; const dd = (m.value / pm - 1) * 100; return h("span", { class: dd > 0 ? "warn" : "" }, pct(dd, 0)); } },
    { label: "Meaning", render: (m) => h("span", { class: "muted small" }, m.meaning) },
  ], v.multiples);
  const quality = table([{ label: "Quality & growth", render: (q) => q.label },
    { label: c.symbol, num: true, render: (q) => (q.value == null ? "–" : q.percent ? ratio(q.value) : num(q.value, 2)) },
    { label: "Peer median", num: true, render: (q) => (med[q.key] && med[q.key].median != null ? (q.percent ? ratio(med[q.key].median) : num(med[q.key].median, 2)) : "–") }], v.quality);
  const flags = v.multiples.filter((m) => m.flag && m.flag !== "missing");
  return h("div", null, grid(
    h("div", null, section("Multiples vs peers", multiples, flags.length ? note("* " + flags.map((m) => `${m.label}: ${m.flag}`).join(" · ")) : null,
      note(v.peers && v.peers.symbols && v.peers.symbols.length ? `Peers: ${v.peers.symbols.join(", ")}` : "No peer group.")), section("Quality vs peers", quality)),
    h("div", null, reverseDcf(v), v.vendor_dcf ? note(`${v.vendor_dcf.source} DCF value: ${price(v.vendor_dcf.value)} (vendor model, assumptions not disclosed).`) : null)));
}

function reverseDcf(v) {
  const box = h("div");
  const inp = v.inputs || {};
  if (!v.reverse_dcf) { box.appendChild(section("What the price implies (reverse DCF)", note((v.caveats || []).slice(2).join(" ") || "Not computable (needs positive free cash flow, shares and price in one currency)."))); return box; }
  const f = { discount: v.defaults.discount * 100, terminal: v.defaults.terminal * 100, years: v.defaults.years };
  const out = h("div");
  const mk = (key, label, step) => h("label", null, label, h("input", { type: "number", value: f[key], step, style: { width: "72px" }, oninput: (e) => { f[key] = parseFloat(e.target.value); update(); } }));
  const update = () => {
    const g = impliedGrowth(inp.price, inp.fcf, f.discount / 100, f.terminal / 100, Math.round(f.years), inp.net_debt, inp.shares);
    clear(out, h("p", { style: { fontSize: "16px", margin: "8px 0" } }, "Today's price assumes free cash flow grows ",
      h("strong", null, g == null ? "faster than 150 % a year (not reachable)" : pct(g * 100, 1, false) + " a year"),
      ` for ${Math.round(f.years)} years, then ${num(f.terminal, 1)} % forever, discounted at ${num(f.discount, 1)} %.`),
      h("p", { class: "note" }, `Start: ${inp.fcf_note}: ${big(inp.fcf)}. FCF yield ${ratio(v.reverse_dcf.fcf_yield, 2)} · net debt ${big(inp.net_debt)} · ${big(inp.shares)} shares.`));
  };
  const grid2 = v.reverse_dcf.grid;
  box.appendChild(section("What the price implies (reverse DCF)", h("div", { class: "toolbar" }, mk("discount", "Discount %", 0.5), mk("terminal", "Terminal growth %", 0.25), mk("years", "Years", 1)), out,
    table([{ label: "Discount \\ terminal", render: (r) => pct(r.discount * 100, 1, false) },
      ...grid2[0].cells.map((cc, i) => ({ label: pct(cc.terminal * 100, 1, false), num: true, render: (r) => (r.cells[i].growth == null ? "–" : pct(r.cells[i].growth * 100, 1, false)) }))], grid2),
    note(v.caveats.join(" "))));
  update();
  return box;
}

function dcfPerShare(fcf0, g, r, t, years, netDebt, shares) {
  let pv = 0, fcf = fcf0;
  for (let i = 1; i <= years; i++) { fcf *= 1 + g; pv += fcf / Math.pow(1 + r, i); }
  pv += (fcf * (1 + t) / (r - t)) / Math.pow(1 + r, years);
  return (pv - netDebt) / shares;
}
function impliedGrowth(px, fcf0, r, t, years, netDebt, shares) {   // same model as features/valuation.py
  if (!(fcf0 > 0) || !(px > 0) || !(r > t) || !(shares > 0) || !(years >= 1)) return null;
  let lo = -0.5, hi = 1.5;
  const f = (g) => dcfPerShare(fcf0, g, r, t, years, netDebt, shares) - px;
  if (f(lo) > 0) return lo;
  if (f(hi) < 0) return null;
  for (let k = 0; k < 80; k++) { const m = (lo + hi) / 2; if (f(m) > 0) hi = m; else lo = m; }
  return (lo + hi) / 2;
}

// ================================================================== ownership & short
async function ownership(c) {
  const d = await c.block("ownership");
  if (d.error) return fail(d);
  const p = (c.state.summary && c.state.summary.profile) || {};
  const m = d.major || {};
  const chg = p.shares_short && p.shares_short_prior ? p.shares_short / p.shares_short_prior - 1 : null;
  const ins = d.insider_6m || {};
  const holders = (rows) => table([{ label: "Holder", render: (r) => r.holder }, { label: "% held", num: true, render: (r) => fp(r.pct, 2) },
    { label: "Shares", num: true, render: (r) => big(r.shares) }, { label: "Value", num: true, render: (r) => big(r.value) },
    { label: "Change", num: true, cls: (r) => cls(r.change), render: (r) => fr(r.change) }, { label: "Reported", render: (r) => h("span", { class: "muted small" }, r.reported) }], rows);
  return h("div", null,
    grid(section("Who owns it", kv([["Insiders", fp(m.insidersPercentHeld)], ["Institutions", fp(m.institutionsPercentHeld)],
        ["Institutions (of float)", fp(m.institutionsFloatPercentHeld)], ["Institutional holders", m.institutionsCount ? big(m.institutionsCount) : "–"]])),
      section("Short interest", kv([["Short % of float", fp(p.short_pct_float)], ["Days to cover", n1(p.short_ratio, 1)],
        ["Shares short", big(p.shares_short)], ["vs prior month", fr(chg), cls(-(chg || 0))],
        ["As of", p.short_date ? new Date(p.short_date * 1000).toLocaleDateString() : "–"]]),
        note("Exchange short-interest data is published twice a month with a delay. Rising short interest into falling prices = conviction; into rising prices = squeeze fuel."))),
    section("Insider transactions", kv([["Last 6 months", `${ins.buys ?? 0} buys / ${ins.sells ?? 0} sales`], ["Net shares", big(ins.net_shares), cls(ins.net_shares)], ["Net value", big(ins.net_value), cls(ins.net_value)]]),
      h("div", { class: "scroll" }, table([{ label: "Date", render: (r) => r.date }, { label: "Insider", render: (r) => r.insider }, { label: "Position", render: (r) => h("span", { class: "small" }, r.position || "") },
        { label: "Type", render: (r) => h("span", { class: r.kind === "buy" ? "up" : r.kind === "sell" ? "down" : "muted" }, r.kind) },
        { label: "Shares", num: true, render: (r) => big(r.shares) }, { label: "Value", num: true, render: (r) => big(r.value) },
        { label: "Detail", render: (r) => h("span", { class: "muted small" }, r.text) }], d.insiders || [], { empty: "No insider transactions reported." }))),
    grid(section("Top institutions", holders(d.institutions || [])), section("Top funds", holders(d.funds || []))),
    note(d.note));
}

// ================================================================== options
async function options(c) {
  const d = await c.block("options");
  if (d.error) return fail(d);
  const ex = d.expiries || [];
  return h("div", null,
    kv([["Spot", price(d.spot)], ["Put/call open interest", n1(d.put_call_oi)], ["Put/call volume", n1(d.put_call_volume)], ["Max pain (nearest expiry)", price(d.max_pain_nearest)]]),
    ex.length ? section("Implied volatility term structure", bars(ex.map((x) => ({ label: x.expiry.slice(5), value: (x.atm_iv || 0) * 100 })), { height: 150, fmt: (v) => v.toFixed(0) + "%" })) : null,
    section("Per expiry", h("div", { class: "scroll" }, table([{ label: "Expiry", render: (x) => x.expiry }, { label: "Days", num: true, render: (x) => x.days },
      { label: "ATM strike", num: true, render: (x) => price(x.atm_strike) }, { label: "ATM IV", num: true, render: (x) => fp(x.atm_iv) },
      { label: "Straddle", num: true, render: (x) => price(x.straddle) }, { label: "Implied move", num: true, render: (x) => (x.implied_move == null ? "–" : "±" + fp(x.implied_move)) },
      { label: "Skew (put - call IV)", num: true, render: (x) => (x.skew == null ? "–" : pct(x.skew * 100, 1)) },
      { label: "P/C OI", num: true, render: (x) => n1(x.put_call_oi) }, { label: "P/C volume", num: true, render: (x) => n1(x.put_call_volume) }], ex))),
    note(d.note + " Max pain = strike where option holders' total payout at expiry is smallest; a popular but weak pinning theory."));
}

// ================================================================== performance & risk
async function performance(c) {
  const d = await c.block("performance");
  if (d.error) return fail(d);
  const s = d.stats, sea = d.seasonality || {};
  const windows = ["1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y"];
  return h("div", null,
    section("Returns", h("div", { class: "scroll" }, table([{ label: "", render: (r) => r }, ...windows.map((w) => ({ label: w, num: true, cls: (r) => cls(r === "Return" ? s.returns[w] : s.relative[w]), render: (r) => fr(r === "Return" ? s.returns[w] : s.relative[w]) }))],
      d.benchmark ? ["Return", `vs ${d.benchmark}`] : ["Return"]))),
    grid(
      section("Risk", kv([["Volatility 20d / 60d / 1y", `${fp(s.volatility["20d"], 0)} / ${fp(s.volatility["60d"], 0)} / ${fp(s.volatility["252d"], 0)}`],
        ["Beta / correlation 1y", `${n1(s.beta_1y)} / ${n1(s.corr_1y)}`], ["Drawdown now", fr(s.drawdown.current), cls(s.drawdown.current)],
        ["Max drawdown 1y", fr(s.drawdown.max_1y), "down"], [`Max drawdown ${s.years}y`, fr(s.drawdown.max_period), "down"], ["ATR 14 (of price)", fp(s.atr14_pct, 2)]])),
      section("Trend & range", kv([["52w high / low", `${price(s.range_52w.high)} / ${price(s.range_52w.low)}`], ["From 52w high", fr(s.range_52w.from_high), cls(s.range_52w.from_high)],
        ["From 52w low", fr(s.range_52w.from_low), cls(s.range_52w.from_low)], ["50-day / 200-day avg", `${price(s.trend.sma50)} / ${price(s.trend.sma200)}`],
        ["vs 50-day / 200-day", `${fr(s.trend.vs_sma50)} / ${fr(s.trend.vs_sma200)}`], ["50 above 200", s.trend.golden == null ? "–" : s.trend.golden ? "yes" : "no"],
        ["Volume vs 20-day avg", s.volume.avg20 ? n1(s.volume.last / s.volume.avg20) + "×" : "–"]]))),
    section("Seasonality by month", h("div", { class: "scroll" }, table([{ label: "", render: (r) => r }, ...MONTHS.map((mn, i) => ({ label: mn, num: true,
      cls: (r) => (r === "Average" ? cls((sea.months || [])[i] && sea.months[i].avg) : ""),
      render: (r) => { const m = (sea.months || [])[i] || {}; if (r === "Average") return fr(m.avg); if (r === "Up share") return fp(m.up_share, 0); if (r === "t") return m.se ? num(m.avg / m.se, 1) : "–"; return m.n ?? "–"; } }))],
      ["Average", "Up share", "t", "n"]))),
    section("Calendar years", h("div", { class: "scroll" }, table((sea.years || []).slice(0, 11).map((y) => ({ label: String(y.year), num: true, cls: () => cls(y.return), render: () => fr(y.return) })), [0]))),
    note(sea.note || ""));
}

// ================================================================== peers, dividends, news, filings
async function peers(c) {
  const d = await c.block("peers");
  if (d.error) return fail(d);
  return h("div", null, section(`Peer group${d.group ? ": " + d.group : ""}`, h("div", { class: "scroll" }, table([
    { label: "Symbol", render: (r) => (r.self ? h("strong", null, r.symbol) : h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol)) },
    { label: "Name", render: (r) => h("span", { class: "small" }, r.name || "") }, { label: "Mkt cap", num: true, render: (r) => big(r.market_cap) },
    { label: "P/E fwd", num: true, render: (r) => n1(r.pe_forward, 1) }, { label: "P/E ttm", num: true, render: (r) => n1(r.pe_trailing, 1) },
    { label: "EV/EBITDA", num: true, render: (r) => n1(r.ev_ebitda, 1) }, { label: "P/S", num: true, render: (r) => n1(r.ps, 1) },
    { label: "Rev. growth", num: true, cls: (r) => cls(r.revenue_growth), render: (r) => fr(r.revenue_growth) },
    { label: "Op. margin", num: true, render: (r) => fp(r.operating_margin) }, { label: "ROE", num: true, render: (r) => fp(r.roe) },
    { label: "Div. yield", num: true, render: (r) => fp(r.dividend_yield, 2) }, { label: "1y return", num: true, cls: (r) => cls(r.return_1y), render: (r) => fr(r.return_1y) },
  ], d.rows || [], { rowClass: (r) => (r.self ? "hl" : ""), empty: d.note }))), note(d.note));
}

async function dividends(c) {
  const d = await c.block("dividends");
  if (d.error) return fail(d);
  if (!(d.years || []).length) return note("No dividend history.");
  return h("div", null, grid(
    section("Dividends per year", bars(d.years.slice().reverse().map((y) => ({ label: String(y.year).slice(2), value: y.total })), { height: 150, fmt: (v) => v.toFixed(2) }),
      table([{ label: "Year", render: (y) => y.year }, { label: "Total", num: true, render: (y) => n1(y.total, 3) }, { label: "Growth", num: true, cls: (y) => cls(y.growth), render: (y) => fr(y.growth) }], d.years)),
    h("div", null, section("Recent payments", table([{ label: "Ex-date", render: (r) => r.date }, { label: "Amount", num: true, render: (r) => n1(r.amount, 4) }], d.recent || [])),
      section("Splits", table([{ label: "Date", render: (r) => r.date }, { label: "Ratio", num: true, render: (r) => `${r.ratio}:1` }], d.splits || [], { empty: "None." })))),
    note("The current calendar year is incomplete until its last payment."));
}

function headlineList(items) {
  return h("ul", { class: "feed" }, items.map((n) => h("li", { class: n.impact === "high" ? "high" : "" },
    h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
    h("div", { class: "m" }, `${ago(n.published)} ago · ${n.source}` + (n.impact && n.impact !== "normal" ? ` · ${n.impact}` : "") + (n.sentiment ? ` · ${n.sentiment}` : ""), "  ",
      n.url ? h("a", { href: "#/research/read/" + encodeURIComponent(n.url) }, "read here") : null))));
}

async function news(c) {
  const d = await api(`/api/stock/${c.enc}/news`, { ttl: 60000 });
  c.state.blocks.headlines = (d.items || []).slice(0, 20).map((n) => ({ title: n.title, source: n.source, published: n.published }));
  c.state.blocks.live_wire = (d.wire || []).slice(0, 25).map((n) => ({ title: n.title, source: n.source, published: n.published, impact: n.impact }));
  const wire = d.wire_market ? section(`From your live feeds · ${d.wire_market}, last ${d.wire_hours} h`,
    (d.wire || []).length ? headlineList(d.wire) : note("Nothing in your feeds touched this market."),
    note(`Matched by market themes (${(d.wire_themes || []).join(", ")}): squawk, wires and central banks you receive, newest first. A match means the topic is relevant, not that it moved the price.`)) : null;
  return h("div", null, wire, section(d.wire_market ? "Ticker news" : null, headlineList((d.items || []).slice(0, 60))),
    (d.items || []).length ? null : note("No headlines from the active news sources."),
    note("Sources: " + ((d.sources || []).join(", ") || "none") + (d.errors && Object.keys(d.errors).length ? " · failed: " + Object.keys(d.errors).join(", ") : "")));
}

async function filings(c) {
  const d = await api(`/api/stock/${c.enc}/filings`, { ttl: 600000 });
  return h("div", null, d.note ? note(d.note) : null, table([{ label: "Date", render: (f) => f.date }, { label: "Form", render: (f) => ext(f.url, f.form) },
    { label: "What", render: (f) => [f.kind, f.description, f.items ? "items " + f.items : ""].filter(Boolean).join(" · ") }],
    d.items || [], { empty: d.error ? d.error : "No filings (US listings only)." }));
}


// ================================================================== people & indices, network
async function people(c) {
  const d = await c.block("structure");
  if (d.error) return fail(d);
  c.state.blocks.structure = { board: d.board, officers: d.officers, indices: d.indices };
  const w = (x) => (x.weight == null ? "–" : pct(x.weight * 100, 2, false));
  return grid(
    h("div", null,
      section("Index membership", table([
        { label: "Index", render: (x) => h("a", { href: "#/indices/" + x.key }, x.index) },
        { label: "Weight (est.)", num: true, render: w },
        { label: "Rank", num: true, render: (x) => (x.rank ? `#${x.rank} of ${x.members}` : "–") },
        { label: "Basis", render: (x) => h("span", { class: "muted small" }, `${x.basis}, ${x.coverage} of ${x.members} members known`) },
      ], d.indices || [], { empty: "Not a member of the bundled indices (S&P 500, Nasdaq-100, Dow 30, DAX 40, FTSE 100, CAC 40, SMI, Euro Stoxx 50)." }),
        note("Estimates: the official weights use free-float factors and caps. Membership lists are refreshed with each index review.")),
      section("Board (directors)", table([
        { label: "Name", render: (b) => b.name }, { label: "Role", render: (b) => b.position || "" },
        { label: "Shares held", num: true, render: (b) => big(b.shares) },
        { label: "Last filing", render: (b) => h("span", { class: "muted small" }, `${b.last_date} ${b.last_transaction || ""}`) },
      ], d.board || [], { empty: "No board list in the free data (usual for non-US companies)." }))),
    h("div", null,
      section("Executives", table([
        { label: "Name", render: (o) => o.name }, { label: "Title", render: (o) => o.title || "" },
        { label: "Age", num: true, render: (o) => o.age ?? "–" },
        { label: "Pay", num: true, render: (o) => (o.pay ? big(o.pay) + (o.pay_year ? ` (${o.pay_year})` : "") : "–") },
      ], d.officers || [], { empty: "No executives listed." })),
      note(d.note + " Changes to board, executives and index membership of your watchlist and held stocks are checked every 6 hours and raised as alerts.")));
}

async function network(c) {
  const sym = c.symbol;
  const [st, own] = await Promise.all([c.block("structure"), isEquity(c) ? c.block("ownership") : Promise.resolve({})]);
  const s = c.state.summary || {}, p = s.profile || {};
  const W = 1000, H = 700, cx = W / 2, cy = 330;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "netgraph", role: "img" });
  const short = (t, n) => (t.length > n ? t.slice(0, n - 1) + "…" : t);
  // rows (top / bottom) and columns (left / right): every label gets its own lane, nothing overlaps
  const groups = [
    ["Indices", "top", (st.indices || []).map((x) => ({ label: x.index, sub: x.weight != null ? pct(x.weight * 100, 1, false) : "", size: x.weight, href: "#/indices/" + x.key }))],
    ["Peers", "right", (s.peers || []).slice(0, 8).map((x) => ({ label: x, href: "#/stock/" + encodeURIComponent(x) }))],
    ["People", "bottom", [...(st.board || []).slice(0, 5).map((b) => ({ label: b.name, sub: "director" })),
      ...(st.officers || []).slice(0, 5).map((o) => ({ label: o.name.replace(/^(Mr|Ms|Mrs|Dr)\.\s+/, ""), sub: (o.title || "").slice(0, 24) }))].slice(0, 10)],
    ["Holders", "left", ((own && own.institutions) || []).slice(0, 7).map((x) => ({ label: x.holder, sub: x.pct != null ? pct(x.pct * 100, 1, false) : "", size: x.pct }))],
  ];
  const HUB = { top: [cx, cy - 115], bottom: [cx, cy + 105], left: [cx - 175, cy], right: [cx + 175, cy] };
  const facts = {};
  for (const [name, side, nodes] of groups) {
    facts[name] = nodes.map((n) => n.label + (n.sub ? ` (${n.sub})` : ""));
    if (!nodes.length) continue;
    const [gx, gy] = HUB[side];
    root.appendChild(svg("line", { x1: cx, y1: cy, x2: gx, y2: gy, class: "netedge strong" }));
    root.appendChild(svg("text", { x: gx, y: side === "bottom" ? gy + 18 : gy - 8, class: "netgroup", "text-anchor": "middle" }, name));
    nodes.forEach((n, i) => {
      let x, y, anchor;
      if (side === "left" || side === "right") {
        const step = Math.min(50, 330 / Math.max(1, nodes.length - 1));     // columns end above the people rows
        x = side === "left" ? 205 : 795;
        y = cy + (i - (nodes.length - 1) / 2) * step;
        anchor = side === "left" ? "end" : "start";
      } else if (side === "top") {
        const step = Math.min(190, 760 / Math.max(1, nodes.length - 1));
        x = cx + (i - (nodes.length - 1) / 2) * step; y = 70; anchor = "middle";
      } else {                                      // bottom: two staggered rows
        const cols = Math.ceil(nodes.length / 2), col = Math.floor(i / 2), step = Math.min(185, 900 / Math.max(1, cols));
        x = cx + (col - (cols - 1) / 2) * step + (i % 2 ? step / 2 : 0) - (cols > 1 ? step / 4 : 0);
        y = i % 2 ? 610 : 530; anchor = "middle";
      }
      const r = 5 + Math.min(14, Math.sqrt(Math.max(0, n.size || 0)) * 40);
      root.appendChild(svg("line", { x1: gx, y1: gy, x2: x, y2: y, class: "netedge" }));
      const g = svg("g", { class: "netnode" + (n.href ? " link" : "") });
      g.appendChild(svg("circle", { cx: x, cy: y, r }));
      const dx = anchor === "start" ? r + 6 : anchor === "end" ? -r - 6 : 0;
      const dy = anchor === "middle" ? (side === "top" ? -r - 18 : r + 14) : 4;
      g.appendChild(svg("text", { x: x + dx, y: y + dy, "text-anchor": anchor }, short(n.label, side === "bottom" ? 22 : 24)));
      if (n.sub) g.appendChild(svg("text", { x: x + dx, y: y + dy + 13, "text-anchor": anchor, class: "netsub" }, n.sub));
      if (n.href) g.addEventListener("click", () => c.go(n.href));
      root.appendChild(g);
    });
  }
  const center = svg("g", { class: "netcenter" });
  center.appendChild(svg("circle", { cx, cy, r: 34 }));
  center.appendChild(svg("text", { x: cx, y: cy + 4, "text-anchor": "middle" }, sym));
  if (p.sector) center.appendChild(svg("text", { x: cx, y: cy + 52, "text-anchor": "middle", class: "netsub" }, `${p.sector}${p.industry ? " · " + p.industry : ""}`));
  root.appendChild(center);
  c.state.blocks.network = facts;
  return h("div", null, h("div", { class: "netwrap" }, root),
    note("Indices sized by estimated weight, holders by share held (latest 13F), peers from the same index and industry. Click an index or a peer to open it. Supplier and customer links follow once they can be read from filings."));
}

export const TABS = { overview, financials, earnings, street, valuation, ownership, options, performance, peers, people, network, dividends, news, filings };
export { loading };
