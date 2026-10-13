// Macro: US curve, Fed path, volatility structure, risk appetite ratios, COT positioning.
import { api } from "../lib/api.js";
import { lineChart, bars } from "../lib/chart.js";
import { h, clear, table, section, num, pct, signed, dir, note, loading, errorBox } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const a = h("div"), b = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Macro")), h("div", { class: "cols" }, a, b));
  const rates = h("div", null, loading()), fed = h("div", null, loading()), vol = h("div", null, loading()), risk = h("div", null, loading()), cot = h("div", null, loading());
  a.append(section("US Treasury curve", rates), section("Fed funds path (futures)", fed));
  b.append(section("Volatility", vol), section("Risk appetite", risk), section("Positioning (COT)", cot));
  const facts = {};
  const push = () => ctx.setContext({ page: "Macro", ...facts });

  const [r, f, v, k, c] = await Promise.all(["rates", "fedpath", "vol", "risk", "cot"].map((p) => api("/api/macro/" + p, { ttl: 120000 })));
  if (r.error) clear(rates, errorBox(r.error)); else {
    facts.curve = r.curve; facts.spreads_bp = r.spreads_bp; facts.rates_extras = r.extras;
    clear(rates,
      lineChart(r.curve.map((p) => ({ x: p.tenor, y: p.yield })), { height: 200, area: false, fmtY: (y) => y.toFixed(2) + "%", fmtX: (x) => x }),
      table([{ label: "Tenor", render: (p) => p.tenor }, { label: "Yield", num: true, render: (p) => num(p.yield, 2) + "%" },
        { label: "1-week Δ bp", num: true, cls: (p) => dir(p.chg_1w_bp), render: (p) => signed(p.chg_1w_bp, 0) }], r.curve),
      h("p", { class: "small" }, Object.entries(r.spreads_bp || {}).map(([k2, v2]) => `${k2}: ${signed(v2, 0)} bp`).join(" · ")),
      table([{ label: "Series", render: (x) => x.label }, { label: "Last", num: true, render: (x) => num(x.value, 2) },
        { label: "1-week Δ", num: true, cls: (x) => dir(x.chg_1w), render: (x) => signed(x.chg_1w, 2) }, { label: "Date", render: (x) => h("span", { class: "muted small" }, x.date) }], r.extras || []),
      note(r.source));
  }
  if (f.error) clear(fed, errorBox(f.error)); else {
    facts.fed_path = f.path;
    clear(fed, bars(f.path.map((p) => ({ label: p.month, value: p.vs_now_bp })), { fmt: (x) => x.toFixed(0) }),
      table([{ label: "Month", render: (p) => p.month }, { label: "Implied rate", num: true, render: (p) => num(p.implied, 3) + "%" },
        { label: "vs now bp", num: true, render: (p) => signed(p.vs_now_bp, 1) }, { label: "≈ 25 bp moves", num: true, render: (p) => signed(p.moves_25bp, 2) },
        { label: "Δ today bp", num: true, cls: (p) => dir(p.chg_bp), render: (p) => signed(p.chg_bp, 1) }], f.path), note(f.source));
  }
  if (v.error) clear(vol, errorBox(v.error)); else {
    facts.volatility = v;
    clear(vol, table([{ label: "Term", render: (x) => x.term }, { label: "Level", num: true, render: (x) => num(x.value, 2) },
      { label: "Δ", num: true, cls: (x) => dir(x.change), render: (x) => signed(x.change, 2) }], v.curve),
      h("p", null, `VIX curve: ${v.state || "–"} (3m − 30d = ${signed(v.slope, 2)}). S&P 500 realized vol 10d ${num(v.realized_10d, 1)} / 20d ${num(v.realized_20d, 1)} → implied minus realized ${signed(v.risk_premium, 1)} pts.`),
      note("Backwardation (short-dated VIX above longer-dated) marks acute stress; a large positive implied-minus-realized gap means options price more movement than the index has shown."));
  }
  if (k.error) clear(risk, errorBox(k.error)); else {
    facts.risk_ratios = k.rows;
    clear(risk, table([{ label: "Ratio", render: (x) => x.label }, { label: "Pair", render: (x) => h("span", { class: "muted small" }, x.pair) },
      { label: "1d", num: true, cls: (x) => dir(x.d1), render: (x) => pct(x.d1, 1) }, { label: "5d", num: true, cls: (x) => dir(x.d5), render: (x) => pct(x.d5, 1) },
      { label: "20d", num: true, cls: (x) => dir(x.d20), render: (x) => pct(x.d20, 1) }], k.rows),
      h("p", null, `${k.risk_on_5d} of ${k.n} ratios rose over 5 days.`), note(k.note));
  }
  if (c.error) clear(cot, errorBox(c.error)); else {
    facts.cot = c.rows;
    clear(cot, table([{ label: "Market", render: (x) => x.market }, { label: "Group", render: (x) => h("span", { class: "muted small" }, x.group) },
      { label: "Net", num: true, render: (x) => num(x.net, 0) }, { label: "Week Δ", num: true, cls: (x) => dir(x.week_change), render: (x) => signed(x.week_change, 0) },
      { label: "1y pctile", num: true, render: (x) => num(x.percentile, 0) }, { label: "As of", render: (x) => h("span", { class: "muted small" }, x.date) }], c.rows),
      note(c.source + ". Extremes (percentile near 0 or 100) describe crowding; they are not timing signals on their own."));
  }
  push();
}
