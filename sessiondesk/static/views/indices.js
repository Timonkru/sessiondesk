import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, pct, price, signed, dir, note, loading, errorBox, ago } from "../lib/ui.js";
import { stockTable, crumbs } from "../lib/stocktable.js";

// Indices: every index by region; an index with a bundled member list opens to its members (the shared stock
// table) and to breadth, drivers and valuation computed from those members.
const REGION_ORDER = ["Americas", "Europe", "Asia-Pacific", "Middle East & Africa"];

export async function render(root, params, ctx) {
  const uni = (await api("/api/universes", { ttl: 600000 })).items || [];
  const byKey = Object.fromEntries(uni.map((u) => [u.key, u]));
  if (params[0] && byKey[params[0]]) return indexPage(root, byKey[params[0]], params[1] || "members", ctx);
  return landing(root, uni, ctx);
}

async function landing(root, uni, ctx) {
  const bySym = Object.fromEntries(uni.map((u) => [u.symbol, u]));
  const body = h("div", null, loading());
  root.append(crumbs([["Markets", "#/markets"], ["Indices"]]),
    h("div", { class: "pagehead" }, h("h1", null, "Indices"), h("span", { class: "meta" }, "by region - open one for its members, breadth and drivers")), body);
  const d = await api("/api/overview", { ttl: 30000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  const groups = (d.groups || []).filter((g) => REGION_ORDER.includes(g.title));
  clear(body, h("div", { class: "cols" }, groups.map((g) => section(g.title, table([
    { label: "Index", render: (r) => h("a", { href: bySym[r.symbol] ? "#/indices/" + bySym[r.symbol].key : "#/stock/" + encodeURIComponent(r.symbol) }, r.label) },
    { label: "Last", num: true, render: (r) => price(r.price) },
    { label: "Today", num: true, cls: (r) => dir(r.change_pct), render: (r) => pct(r.change_pct) },
    { label: "", render: (r) => (bySym[r.symbol] ? h("span", { class: "small" }, `${bySym[r.symbol].members} members ›`) : h("span", { class: "small muted" }, "price & chart")) },
  ], g.rows, { onRow: (r) => ctx.go(bySym[r.symbol] ? "#/indices/" + bySym[r.symbol].key : "#/stock/" + encodeURIComponent(r.symbol)) })))),
  note(`Members, breadth, drivers and valuation need the list of an index's members; it is bundled for ${uni.length} indices (marked "members ›"). The others open their instrument page with price, chart, performance and options.`));
  ctx.setContext({ page: "Indices", regions: groups.map((g) => ({ region: g.title, indices: g.rows.map((r) => ({ name: r.label, change_pct: r.change_pct })) })) });
}

async function indexPage(root, u, tab, ctx) {
  const region = u.region || "Europe";
  const TABS = [["members", "Members"], ["breadth", "Breadth, drivers & valuation"]];
  const body = h("div", null, loading("Loading member history… (first load of an index takes up to a minute)"));
  root.append(crumbs([["Markets", "#/markets"], ["Indices", "#/indices"], [region, "#/indices"], [u.name]]),
    h("div", { class: "pagehead" }, h("h1", null, u.name), h("span", { class: "meta" }, `${u.members} members · `, h("a", { href: "#/stock/" + encodeURIComponent(u.symbol) }, "index chart"))),
    h("div", { class: "tabs" }, TABS.map(([k, label]) => h("button", { class: k === tab ? "on" : "", onclick: () => ctx.go(`#/indices/${u.key}/${k}`) }, label))), body);
  if (tab === "breadth") return breadthTab(body, u.key, ctx);
  const d = await api(`/api/stocks?scope=${encodeURIComponent("index:" + u.key)}`, { ttl: 60000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  clear(body, stockTable(d.rows, { ctx, name: `${u.name} members`, group: "group", showIndices: false }), note(d.note));
}

async function breadthTab(body, key, ctx) {
  const d = await api("/api/indices/" + key, { ttl: 60000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  const b = d.breadth || {};
  const strip = (items) => h("div", { class: "keystrip" }, items.map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v))));

  // ---------------------------------------------------------------- breadth
  const breadthBox = h("div", null,
    strip([
      [d.name, h("span", { class: dir(d.index_move_pct) }, `${pct(d.index_move_pct)} (${signed(d.index_points, 1)} pts)`)],
      ["Equal-weight move", h("span", { class: dir(b.equal_weight_move) }, pct(b.equal_weight_move))],
      ["Up / down", `${b.up} / ${b.down} of ${b.n}`],
      ["Above 50-day", pct(b.above50_pct, 0, false)],
      ["Above 200-day", pct(b.above200_pct, 0, false)],
      ["20-day highs / lows", `${b.new_high20} / ${b.new_low20}`],
      ["52-week highs / lows", `${b.new_high52} / ${b.new_low52}`],
    ]),
    b.divergence ? h("p", { class: "warn" }, "Divergence " + b.divergence + ".") : null);

  const xLabel = (x) => (x === 0 ? "today" : `${x}d`);
  const line = b.line || [];
  const chartBox = h("div", null,
    h("p", { class: "small muted" }, `Share of members above their own 50-day average, last ${line.length} sessions`),
    lineChart(line.map((y, i) => ({ x: i - (line.length - 1), y })), { height: 180, area: false, ref: 50, fmtY: (y) => y.toFixed(0) + "%", fmtX: xLabel }),
    b.index_line ? h("p", { class: "small muted" }, `${d.name} over the same sessions`) : null,
    b.index_line ? lineChart(b.index_line.map((y, i) => ({ x: i - (b.index_line.length - 1), y })), { height: 150, fmtY: (y) => price(y), fmtX: xLabel }) : null,
    h("p", { class: "small" }, `20 sessions: index ${pct(b.index_20d, 1)}, breadth ${signed(b.breadth_20d_pts, 0)} points.`));

  // ---------------------------------------------------------------- drivers
  const pw = d.key === "dow30";
  const cap = !pw && (d.drivers_up || []).some((r) => r.contrib_pct !== undefined && r.contrib_pct !== null);
  const sym = { label: "Member", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) };
  const move = { label: "Move", num: true, cls: (r) => dir(r.pct), render: (r) => pct(r.pct) };
  const cols = pw
    ? [sym, move, { label: "$ move", num: true, cls: (r) => dir(r.abs), render: (r) => signed(r.abs, 2) },
        { label: "Index pts", num: true, cls: (r) => dir(r.points), render: (r) => signed(r.points, 1) }]
    : cap
      ? [sym, move, { label: "Weight", num: true, render: (r) => pct((r.weight || 0) * 100, 2, false) },
          { label: "Contribution", num: true, cls: (r) => dir(r.contrib_pct), render: (r) => signed(r.contrib_pct, 3) + " pp" }]
      : [sym, move, { label: "Price", num: true, render: (r) => price(r.last) }];
  const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"]];
  let period = localStorage.getItem("sd.idxPeriod") || "1d";
  const periodBar = h("div", { class: "toolbar" });
  const driverBox = h("div");
  const drawDrivers = () => {
    const blk = (d.drivers_by_period || {})[period] || d;
    clear(periodBar, PERIODS.map(([k, label]) => h("button", { class: "linkish", style: { fontWeight: k === period ? 700 : 400 },
      onclick: () => { period = k; localStorage.setItem("sd.idxPeriod", k); drawDrivers(); } }, label)),
      h("span", { class: "muted small" }, `  ${d.name} ${pct(blk.index_move_pct)} (${signed(blk.index_points, 1)} pts) over ${blk.sessions || 1} session${(blk.sessions || 1) > 1 ? "s" : ""}`));
    const word = period === "1d" ? "today's" : period === "1w" ? "this week's" : "this month's";
    const driverNote = d.drivers_note ? d.drivers_note : pw
      ? `The Dow is price-weighted: index points = a member's dollar move / the Dow divisor${blk.divisor ? ` (${num(blk.divisor, 4)}, from prices and index level)` : ""}, so a $10 move in a $500 stock counts as much as a $10 move in a $50 stock.` +
        (blk.contrib_total != null ? ` Check: the members add up to ${signed(blk.contrib_total, 1)} pts against ${word} ${signed(blk.index_points, 1)} pts; a gap means the index quote and the member quotes are from slightly different times.` : "")
      : cap
        ? "Contribution ≈ market-cap weight × move, in percentage points of the index move. Weights from cached company profiles (free data), not the official index weights, caps or free-float factors" +
          (blk.contrib_total != null ? `. Check: the contributions of all members with a known cap add up to ${signed(blk.contrib_total, 2)} pp against an index move of ${pct(blk.index_move_pct)}.` : ".")
        : "No market caps for this index in the free set (500 profiles are too slow to fetch), so these are the biggest movers, not weighted contributions.";
    clear(driverBox, h("div", { class: "cols" },
      h("div", null, h("h3", null, pw || cap ? "Pulling up" : "Biggest gainers"), table(cols, blk.drivers_up || [], { onRow: (r) => ctx.go("#/stock/" + encodeURIComponent(r.symbol)) })),
      h("div", null, h("h3", null, pw || cap ? "Pulling down" : "Biggest losers"), table(cols, blk.drivers_down || [], { onRow: (r) => ctx.go("#/stock/" + encodeURIComponent(r.symbol)) }))),
      note(driverNote));
  };
  drawDrivers();

  // ---------------------------------------------------------------- valuation
  const v = d.valuation, fs = d.factset;
  const valBox = h("div");
  if (v) {
    const hist = v.history || {};
    valBox.append(
      h("h3", null, "Bottom-up from member data"),
      table([{ label: "Measure", render: (r) => r[0] }, { label: "Value", num: true, render: (r) => r[1] }], [
        ["Forward P/E (" + (pw ? "price-weighted: sum of prices / sum of forward EPS" : "sum of caps / sum of forward earnings") + ")", num(v.fwd_pe, 1)],
        ["Earnings yield", pct(v.earnings_yield, 2, false)],
        ["Median member forward P/E", num(v.median_pe, 1)],
        ["Members used", `${v.used} of ${b.n}`],
        ["Own history", hist.n > 1 ? `${hist.n} days since ${hist.since}, average ${num(hist.avg, 1)}, today at the ${num(hist.percentile, 0)}th percentile` : "starts today (one point per day)"],
      ]));
    if (v.rejected && v.rejected.length) valBox.append(note("Excluded as implausible vendor P/E: " + v.rejected.join(", ")));
  } else if (d.valuation_note) {
    valBox.append(note(d.valuation_note));
  }
  if (fs) {
    if (fs.error) valBox.append(h("h3", null, "FactSet Earnings Insight"), errorBox(fs.error));
    else {
      const g = Object.entries(fs.cy_growth || {}).map(([y, x]) => `CY${y} ${signed(x, 1)}%`).join(" · ");
      valBox.append(h("h3", null, `FactSet Earnings Insight (${fs.date})`),
        table([{ label: "Measure", render: (r) => r[0] }, { label: "Value", num: true, render: (r) => r[1] }], [
          ["Forward 12-month P/E", num(fs.fwd_pe, 1)],
          ["5-year average", num(fs.pe_avg5, 1)],
          ["10-year average", num(fs.pe_avg10, 1)],
          ["Trailing 12-month P/E", num(fs.trailing_pe, 1)],
          ["Implied forward EPS", num(fs.fwd_eps, 2)],
          ["Close used in the report", num(fs.close, 2)],
          ["Bottom-up target (analysts)", num(fs.target, 2)],
          ["Expected earnings growth", g || "–"],
        ]),
        note(`${fs.source}. Analyst targets and growth estimates are consensus opinions, historically too optimistic at the start of a year; shown as reported, not endorsed.`));
    }
  }

  clear(body,
    section("Breadth", breadthBox, chartBox),
    section("Who moves the index", periodBar, driverBox),
    section("Valuation", valBox.childNodes.length ? valBox : note("No valuation data.")),
    note(`${d.note} Updated ${ago(d.asof)} ago. Breadth describes participation; on its own it has not been a reliable timing signal.`));

  ctx.setContext({
    page: `Index ${d.name} - breadth, drivers, valuation`, index: d.name, index_move_pct: d.index_move_pct, index_points: d.index_points,
    breadth: { ...b, line: undefined, index_line: undefined, breadth_line_last5: line.slice(-5) },
    drivers_by_period: Object.fromEntries(Object.entries(d.drivers_by_period || {}).map(([k, x]) => [k, { index_move_pct: x.index_move_pct, index_points: x.index_points,
      up: (x.drivers_up || []).slice(0, 6).map((r) => ({ symbol: r.symbol, pct: r.pct, points: r.points, contrib_pct: r.contrib_pct })),
      down: (x.drivers_down || []).slice(0, 6).map((r) => ({ symbol: r.symbol, pct: r.pct, points: r.points, contrib_pct: r.contrib_pct })) }])),
    valuation: v, factset: fs,
  });
}
