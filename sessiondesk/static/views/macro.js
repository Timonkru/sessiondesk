// Macro in five tabs: rates (curve, Fed path), inflation & growth, credit & liquidity (incl. euro spreads),
// volatility & risk appetite (VIX structure, ratios, put/call), positioning (COT). All panels load once; the
// tabs only show and hide them, so the AI context always holds everything.
import { api } from "../lib/api.js";
import { lineChart, bars } from "../lib/chart.js";
import { h, clear, table, section, num, pct, signed, dir, note, loading, errorBox, big, asOf, stamp } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const mk = () => h("div", null, loading());
  const rates = mk(), fed = mk(), vol = mk(), risk = mk(), pc = mk(), cot = mk(), growth = mk(), credit = mk(), euro = mk(), intl = mk(), world = mk();
  const TABS = [
    ["rates", "Rates", h("div", null, section("Government yields and policy rates by country", world),
      h("div", { class: "cols" }, section("US Treasury curve", rates), section("Fed funds path (futures)", fed)))],
    ["growth", "Inflation & growth", h("div", null, section("By country", intl), section("United States in detail", growth))],
    ["credit", "Credit & liquidity", h("div", { class: "cols" }, section("US credit and liquidity", credit), section("Euro area: 10-year yields and spreads to Germany", euro))],
    ["risk", "Volatility & risk", h("div", { class: "cols" }, h("div", null, section("Volatility", vol), section("Put/call (SPY, QQQ options)", pc)), section("Risk appetite", risk))],
    ["pos", "Positioning", section("Positioning (COT)", cot)],
  ];
  let tab = localStorage.getItem("sd.macroTab") || "rates";
  const bar = h("div", { class: "tabs" });
  const panes = h("div", null, TABS.map(([k, , el]) => h("div", { dataset: { tab: k } }, el)));
  const show = () => {
    clear(bar, TABS.map(([k, label]) => h("button", { class: k === tab ? "on" : "", onclick: () => { tab = k; localStorage.setItem("sd.macroTab", k); show(); } }, label)));
    [...panes.children].forEach((el) => { el.hidden = el.dataset.tab !== tab; });
  };
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Macro")), bar, panes);
  show();

  const fredTable = (rows, fmt) => table([{ label: "Series", render: (x) => x.label },
    { label: "Latest", num: true, render: (x) => fmt(x, x.value) }, { label: "Before", num: true, render: (x) => (x.prev == null ? "–" : fmt(x, x.prev)) },
    { label: "Change", num: true, cls: (x) => dir(x.change), render: (x) => (x.change == null ? "–" : (x.change > 0 ? "+" : "") + fmt(x, x.change)) },
    { label: "Period", render: (x) => h("span", { class: "small " + (x.late ? "warn" : "muted"),
      title: x.late ? `${x.age_days} days old - later than this series normally publishes` : "" }, x.date + (x.late ? " (late)" : "")) }], rows);
  const fetched = (x) => h("p", { class: "small" }, asOf(x.asof, { label: "fetched", maxAgeHours: 7, stale: x.stale }),
    (x.rows || []).some((r) => r.late) ? h("span", { class: "warn" }, " · amber = the source has not published a newer value yet") : null);
  const fmtVal = (x, v) => (x.id === "ICSA" ? big(v) : x.id === "PAYEMS" ? num(v, 0) + " k" : num(v, Math.abs(v) >= 100 ? 0 : 2));
  const facts = {};
  const push = () => ctx.setContext({ page: "Macro", ...facts });

  // put/call reads option chains (slow on first load): fill it in on its own so the other panels do not wait
  api("/api/macro/putcall", { ttl: 120000 }).then((o) => {
    if (o.error) { clear(pc, errorBox(o.error)); return; }
    facts.put_call = o.rows;
    clear(pc, table([{ label: "ETF", render: (x) => x.symbol }, { label: "P/C volume", num: true, render: (x) => num(x.pc_volume, 2) },
      { label: "P/C open interest", num: true, render: (x) => num(x.pc_oi, 2) },
      { label: "Expiries", render: (x) => h("span", { class: "muted small" }, (x.expiries || []).join(", ")) }], o.rows), note(o.note));
    push();
  });
  // inflation & growth, credit & liquidity: FRED, loaded on their own
  api("/api/macro/growth", { ttl: 600000 }).then((g) => {
    if (g.error) { clear(growth, errorBox(g.error)); return; }
    facts.inflation_growth = g.rows;
    clear(growth, fetched(g), fredTable(g.rows, fmtVal), note(`${g.source}. Changes are against the previous release of each series.`));
    push();
  });
  api("/api/macro/world", { ttl: 600000 }).then((d) => {
    if (d.error) { clear(world, errorBox(d.error)); return; }
    facts.rates_by_country = d.rows;
    const y = (v) => (v == null ? "–" : num(v, 2));
    clear(world, h("div", { class: "scroll" }, table([
      { label: "", render: (r) => h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer", title: r.source, style: { color: "inherit" } }, h("strong", null, r.country)) },
      { label: "Policy rate", num: true, render: (r) => (r.policy == null ? h("span", { class: "muted", title: r.policy_name }, "–") : h("span", { title: r.policy_name }, y(r.policy))) },
      ...d.tenors.map((t) => ({ label: t, num: true, render: (r) => y(r[t]) })),
      { label: "2s10s bp", num: true, cls: (r) => dir(r.s2s10), render: (r) => (r.s2s10 == null ? "–" : signed(r.s2s10, 0)) },
      { label: "2y - policy bp", num: true, cls: (r) => dir(r.gauge_bp), render: (r) => (r.gauge_bp == null ? "–" : signed(r.gauge_bp, 0) + (r.gauge_tenor !== "2y" ? ` (${r.gauge_tenor})` : "")) },
      { label: "Date", render: (r) => h("span", { class: "small muted" }, r.date || "–") },
    ], d.rows)), note(d.note + " The UK row: 3m = SONIA overnight, 30y = 20-year point. Each country links to its source; the 2y/5y/10y and policy rates are also Data hub series (Rates by country)."));
    push();
  });
  api("/api/macro/international", { ttl: 600000 }).then((d) => {
    if (d.error) { clear(intl, errorBox(d.error)); return; }
    facts.inflation_growth_by_country = d.table;
    const cell = (c, k) => {
      const x = (d.table[c] || {})[k];
      if (!x) return h("span", { class: "muted" }, "–");
      const chg = x.prev != null ? x.value - x.prev : null;
      return h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer", title: `${x.source} · ${x.period}` + (x.prev != null ? ` · before ${num(x.prev, 1)}` : ""),
        style: { color: "inherit" } }, num(x.value, 1), h("span", { class: "small muted" }, ` ${x.period.slice(2)}`),
        chg ? h("span", { class: "small muted" }, chg > 0 ? " ▲" : " ▼") : null);
    };
    clear(intl, h("div", { class: "scroll" }, table([{ label: "", render: (i) => i.label },
      ...d.countries.map((c) => ({ label: c, num: true, render: (i) => cell(c, i.key) }))], d.indicators)),
      note(d.note + " Each number links to its source; ▲/▼ = up or down against the release before."));
    push();
  });
  api("/api/macro/credit", { ttl: 600000 }).then((x) => {
    if (x.error) { clear(credit, errorBox(x.error)); clear(euro); return; }
    facts.credit_liquidity = x.rows;
    clear(credit, fetched(x), fredTable(x.rows, fmtVal), note(`${x.source}. Spreads in percentage points over Treasuries; NFCI is a weekly index of US financial conditions.`));
    const e = x.euro || {}, el = x.euro_live || {};
    facts.euro_spreads = e.rows; facts.euro_spreads_today = el.rows;
    const liveBox = el.error ? note("Today's euro yields unavailable (" + el.error + ").") : h("div", null, h("h3", null, "Today"), table([
      { label: "Country", render: (r) => r.country }, { label: "10y yield", num: true, render: (r) => num(r.yield, 3) + "%" },
      { label: "Spread to Germany", num: true, render: (r) => (r.country === "Germany" || r.spread_bp == null ? "–" : num(r.spread_bp, 0) + " bp") },
      { label: "Δ today bp", num: true, cls: (r) => dir(r.spread_chg_bp), render: (r) => (r.country === "Germany" || r.spread_chg_bp == null ? "–" : signed(r.spread_chg_bp, 1)) },
      { label: "", render: (r) => h("span", { class: "muted small" }, r.time ? stamp(r.time) : "") }], el.rows || []),
      note(el.source + "; spread change against both bonds' previous close."), h("h3", null, "Monthly averages"));
    clear(euro, liveBox, e.error ? errorBox(e.error) : h("div", null, table([{ label: "Country", render: (r) => r.country },
      { label: "10y yield", num: true, render: (r) => num(r.yield, 2) + "%" },
      { label: "Spread to Germany", num: true, render: (r) => (r.spread_bp == null ? "–" : num(r.spread_bp, 0) + " bp") },
      { label: "Month", render: (r) => h("span", { class: "muted small" }, r.date) }], e.rows || []), note(e.note)));
    push();
  });
  const [r, f, v, k, c] = await Promise.all(["rates", "fedpath", "vol", "risk", "cot"].map((p) => api("/api/macro/" + p, { ttl: 120000 })));
  if (r.error) clear(rates, errorBox(r.error)); else {
    facts.curve = r.curve; facts.spreads_bp = r.spreads_bp; facts.rates_extras = r.extras;
    clear(rates,
      lineChart(r.curve.map((p) => ({ x: p.tenor, y: p.yield })), { height: 200, area: false, fmtY: (y) => y.toFixed(2) + "%", fmtX: (x) => x }),
      h("p", { class: "small" }, asOf(r.curve.length ? r.curve[r.curve.length - 1].date : null, { label: "official close", maxAgeHours: 96 }), " · ",
        asOf(r.asof, { label: "fetched", maxAgeHours: 1, stale: r.stale })),
      table([{ label: "Tenor", render: (p) => p.tenor }, { label: "Close", num: true, render: (p) => num(p.yield, 2) + "%" },
        { label: "Date", render: (p) => h("span", { class: "muted small" }, p.date) },
        { label: "1-week Δ bp", num: true, cls: (p) => dir(p.chg_1w_bp), render: (p) => signed(p.chg_1w_bp, 0) },
        { label: "Now", num: true, render: (p) => p.now != null ? num(p.now, 3) + "%" : "–" },
        { label: "Δ today bp", num: true, cls: (p) => dir(p.now_chg_bp), render: (p) => p.now_chg_bp != null ? signed(p.now_chg_bp, 1) : "–" },
        { label: "", render: (p) => h("span", { class: "muted small", title: p.now_source || "" }, p.now_time ? stamp(p.now_time) : "") }], r.curve),
      note("Close = official end-of-day curve (Treasury par yields, else FRED). Now = live on-the-run yield (CNBC, trades around the clock; "
        + "Cboe on Yahoo as fallback, US hours only); Δ today against that source's own previous close."),
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
