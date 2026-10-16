// Indices & breadth: participation (breadth, new highs/lows, breadth line vs index), who moves the index,
// bottom-up valuation with its own history, and the FactSet anchor for the S&P 500.
import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, pct, price, signed, dir, note, loading, errorBox, ago } from "../lib/ui.js";

const INDICES = [["sp500", "S&P 500"], ["nasdaq100", "Nasdaq-100"], ["dax40", "DAX 40"], ["dow30", "Dow 30"]];

export async function render(root, params, ctx) {
  const key = INDICES.some(([k]) => k === params[0]) ? params[0] : "sp500";
  const tabBar = h("div", { class: "tabs" }, INDICES.map(([k, label]) =>
    h("button", { class: k === key ? "on" : "", onclick: () => ctx.go("#/indices/" + k) }, label)));
  const body = h("div", null, loading("Loading member history… (first load of an index takes up to a minute)"));
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Indices & breadth"),
    h("span", { class: "meta" }, "participation, contributions and valuation from member data")), tabBar, body);

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
  const driverBox = h("div", { class: "cols" },
    h("div", null, h("h3", null, pw || cap ? "Pulling up" : "Biggest gainers"), table(cols, d.drivers_up || [], { onRow: (r) => ctx.go("#/stock/" + encodeURIComponent(r.symbol)) })),
    h("div", null, h("h3", null, pw || cap ? "Pulling down" : "Biggest losers"), table(cols, d.drivers_down || [], { onRow: (r) => ctx.go("#/stock/" + encodeURIComponent(r.symbol)) })));
  const driverNote = pw
    ? "The Dow is price-weighted: each member's dollar move times the same divisor, so a $10 move in a $500 stock counts as much as a $10 move in a $50 stock. Points are the member's share of today's point move."
    : cap
      ? "Contribution ≈ market-cap weight × move, in percentage points of the index move. Weights from cached company profiles (free data), not the official index weights, caps or free-float factors" +
        (d.contrib_total != null ? `. Check: the contributions of all members with a known cap add up to ${signed(d.contrib_total, 2)} pp against an index move of ${pct(d.index_move_pct)}.` : ".")
      : "No market caps for this index in the free set (500 profiles are too slow to fetch), so these are the biggest movers, not weighted contributions.";

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
  } else if (d.key !== "sp500") {
    valBox.append(note("No member profiles yet - valuation appears once the profiles are cached (background refresh hourly)."));
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
    section("Who moves the index", driverBox, note(driverNote)),
    section("Valuation", valBox.childNodes.length ? valBox : note("No valuation data.")),
    note(`${d.note} Updated ${ago(d.asof)} ago. Breadth describes participation; on its own it has not been a reliable timing signal.`));

  ctx.setContext({
    page: `Indices & breadth - ${d.name}`, index: d.name, index_move_pct: d.index_move_pct, index_points: d.index_points,
    breadth: { ...b, line: undefined, index_line: undefined, breadth_line_last5: line.slice(-5) },
    drivers_up: (d.drivers_up || []).slice(0, 8), drivers_down: (d.drivers_down || []).slice(0, 8),
    valuation: v, factset: fs,
  });
}
