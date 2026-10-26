// The one stock table of the Markets tree: the same columns, filters, presets, grouping and CSV on every level
// (index members, a region, a sector, an industry, all stocks). Rows come from /api/stocks.
import { h, clear, table, num, pct, price, big, dir, note, asOf } from "./ui.js";

const FILTERS = [["chg1d", "Today %"], ["chg5d", "5 days %"], ["chg20d", "20 days %"], ["chg60d", "60 days %"], ["from_high", "From 52w high %"],
  ["dist200", "From 200-day avg %"], ["rsi14", "RSI 14"], ["vol20", "Volatility 20d %"], ["pe_fwd", "Forward P/E"], ["div_yield", "Dividend yield %"]];
export const PRESETS = {
  "": {},
  "Near 52-week high": { from_high: [-2, null] },
  "Within 3 % of the 52-week low": { _low: 3 },
  "RSI 14 at or below 30": { rsi14: [null, 30] },
  "RSI 14 at or above 70": { rsi14: [70, null] },
  "Above 200-day average, down today": { dist200: [0, null], chg1d: [null, 0] },
  "Below 200-day average, up 20 days": { dist200: [null, 0], chg20d: [0, null] },
  "Forward P/E 15 or less (cached)": { pe_fwd: [0, 15] },
};
const PERIOD_KEYS = [["chg1d", "today"], ["chg5d", "5 days"], ["chg20d", "20 days"], ["chg60d", "60 days"], ["chg1y", "1 year"]];

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

// opts: { ctx, name (for the AI context), group: "none"|"group"|"industry", lockGroup: hide the sector filter (already one sector),
//         showIndices: show the "In" column, onGroup(key): navigate into a group instead of filtering }
export function stockTable(rows, opts = {}) {
  const { ctx, name = "Stocks", lockGroup = false, showIndices = true } = opts;
  const boxes = {};
  const mk = (ph) => h("input", { type: "text", inputmode: "decimal", placeholder: ph, style: { width: "60px" } });
  for (const [k] of FILTERS) boxes[k] = [mk("min"), mk("max")];
  const groups = [...new Map(rows.filter((r) => r.group).map((r) => [r.group, r.group_label])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const sector = h("select", { hidden: lockGroup }, h("option", { value: "" }, "all sectors"), groups.map(([k, l]) => h("option", { value: k }, l)));
  const industry = h("select");
  const preset = h("select", null, Object.keys(PRESETS).map((p) => h("option", { value: p }, p || "preset…")));
  const search = h("input", { type: "search", placeholder: "symbol or name", style: { width: "150px" } });
  const groupBy = h("select", { title: "summary by group" }, [["none", "no grouping"], ...(lockGroup ? [] : [["group", "by sector"]]), ["industry", "by industry"]]
    .map(([v, l]) => h("option", { value: v, selected: v === (opts.group || "none") }, l)));
  const period = h("select", { title: "period for the group summary" }, PERIOD_KEYS.map(([k, l]) => h("option", { value: k }, l)));
  const filterBox = h("div", { class: "screenfilters", hidden: true }, FILTERS.map(([k, label]) => h("label", null, h("span", { class: "small muted" }, label), boxes[k][0], boxes[k][1])));
  const more = h("button", { class: "linkish", onclick: () => { filterBox.hidden = !filterBox.hidden; more.textContent = filterBox.hidden ? "more filters" : "fewer filters"; } }, "more filters");
  let lowWithin = null, sortKey = "chg1d", sortDir = -1;

  const fillIndustries = () => {
    const keep = industry.value;
    const inds = [...new Set(rows.filter((r) => !sector.value || r.group === sector.value).map((r) => r.industry).filter(Boolean))].sort();
    clear(industry, h("option", { value: "" }, "all industries"), inds.map((i) => h("option", { value: i, selected: i === keep }, i)));
  };
  const val = (i) => { const t = i.value.trim().replace(",", "."); return t === "" ? null : Number(t); };
  const pass = (r) => {
    if (sector.value && r.group !== sector.value) return false;
    if (industry.value && r.industry !== industry.value) return false;
    const q = search.value.trim().toLowerCase();
    if (q && !r.symbol.toLowerCase().includes(q) && !(r.name || "").toLowerCase().includes(q)) return false;
    if (lowWithin !== null && !(r.from_low != null && r.from_low <= lowWithin)) return false;
    for (const [k] of FILTERS) {
      const [lo, hi] = boxes[k].map(val);
      if (lo === null && hi === null) continue;
      const v = r[k];
      if (v === null || v === undefined) return false;
      if (lo !== null && v < lo) return false;
      if (hi !== null && v > hi) return false;
    }
    return true;
  };
  const cols = [
    ["symbol", "Symbol", (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol)],
    ["name", "Name", (r) => h("span", { class: "small" }, r.name)],
    ...(lockGroup ? [] : [["group_label", "Sector", (r) => h("span", { class: "small muted" }, r.group_label)]]),
    ["industry", "Industry", (r) => h("span", { class: "small muted" }, r.industry)],
    ["last", "Last", (r) => price(r.last), true],
    ["chg1d", "Today", (r) => h("span", { class: dir(r.chg1d) }, pct(r.chg1d, 2)), true],
    ["chg5d", "5 d", (r) => h("span", { class: dir(r.chg5d) }, pct(r.chg5d, 1)), true],
    ["chg20d", "20 d", (r) => h("span", { class: dir(r.chg20d) }, pct(r.chg20d, 1)), true],
    ["chg60d", "60 d", (r) => h("span", { class: dir(r.chg60d) }, pct(r.chg60d, 1)), true],
    ["chg1y", "1 y", (r) => h("span", { class: dir(r.chg1y) }, pct(r.chg1y, 0)), true],
    ["from_high", "From 52w high", (r) => pct(r.from_high, 1), true],
    ["dist200", "From 200d", (r) => h("span", { class: dir(r.dist200) }, pct(r.dist200, 1)), true],
    ["rsi14", "RSI", (r) => num(r.rsi14, 0), true],
    ["vol20", "Vol 20d", (r) => num(r.vol20, 0), true],
    ["market_cap", "Mkt cap", (r) => big(r.market_cap), true],
    ["pe_fwd", "Fwd P/E", (r) => num(r.pe_fwd, 1), true],
    ["div_yield", "Yield", (r) => (r.div_yield == null ? "–" : num(r.div_yield, 1) + "%"), true],
    ...(showIndices ? [["indices", "In", (r) => h("span", { class: "small muted" }, (r.indices || []).join(", "))]] : []),
  ];
  const summaryBox = h("div"), countLine = h("p", { class: "small" }), tableBox = h("div", { class: "scroll" });

  const summary = (list) => {
    if (groupBy.value === "none") return null;
    const key = groupBy.value, pk = period.value, plabel = PERIOD_KEYS.find((p) => p[0] === pk)[1];
    const by = new Map();
    for (const r of list) { const g = key === "group" ? r.group_label : r.industry || "–"; if (!by.has(g)) by.set(g, { name: g, code: key === "group" ? r.group : r.industry, rows: [] }); by.get(g).rows.push(r); }
    const out = [...by.values()].map((g) => {
      const vs = g.rows.map((r) => r[pk]).filter((v) => v != null);
      return { ...g, n: g.rows.length, avg: mean(vs), up: vs.length ? vs.filter((v) => v > 0).length / vs.length : null,
        best: [...g.rows].filter((r) => r[pk] != null).sort((a, b) => b[pk] - a[pk])[0] };
    }).sort((a, b) => (b.avg ?? -1e9) - (a.avg ?? -1e9));
    return h("div", null, h("p", { class: "small muted" }, `Equal-weighted average over ${plabel}; click a row to narrow the list to it.`), table([
      { label: key === "group" ? "Sector" : "Industry", render: (g) => h("strong", null, g.name) },
      { label: "Stocks", num: true, render: (g) => g.n },
      { label: `Avg ${plabel}`, num: true, cls: (g) => dir(g.avg), render: (g) => pct(g.avg, 1) },
      { label: "Share up", num: true, render: (g) => (g.up == null ? "–" : pct(g.up * 100, 0, false)) },
      { label: "Best", render: (g) => (g.best ? h("span", { class: "small" }, `${g.best.symbol} ${pct(g.best[pk], 1)}`) : "–") },
    ], out, { onRow: (g) => {
      if (opts.onGroup) { opts.onGroup(key, g.code); return; }
      if (key === "group") { sector.value = g.code; fillIndustries(); } else industry.value = g.code;
      groupBy.value = key === "group" ? "industry" : "none"; draw();
    } }));
  };

  const draw = () => {
    const list = rows.filter(pass).sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * sortDir;
    });
    period.hidden = groupBy.value === "none";
    clear(summaryBox, summary(list));
    const t = table(cols.map(([k, label, render, isNum]) => ({ label: label + (k === sortKey ? (sortDir < 0 ? " ▼" : " ▲") : ""), num: !!isNum, render })),
      list.slice(0, 400), { onRow: (r) => ctx && ctx.go("#/stock/" + encodeURIComponent(r.symbol)), empty: "No stock matches these filters." });
    t.querySelectorAll("thead th").forEach((th, i) => {
      th.style.cursor = "pointer";
      th.title = "sort";
      th.addEventListener("click", () => { const k = cols[i][0]; sortDir = k === sortKey ? -sortDir : (typeof rows[0]?.[k] === "string" ? 1 : -1); sortKey = k; draw(); });
    });
    clear(tableBox, t);
    countLine.textContent = `${list.length} of ${rows.length} stocks${list.length > 400 ? " (first 400 shown)" : ""}`;
    if (ctx) {
      const active = FILTERS.filter(([k]) => boxes[k].some((i) => i.value.trim())).map(([k, label]) => `${label} ${boxes[k][0].value || "…"} to ${boxes[k][1].value || "…"}`);
      ctx.setContext({ page: name, filters: { sector: sector.value || "all", industry: industry.value || "all", search: search.value, preset: preset.value, ranges: active, sorted_by: sortKey },
        matches: list.length, rows: list.slice(0, 40).map((r) => ({ symbol: r.symbol, sector: r.group_label, industry: r.industry, chg1d: r.chg1d, chg20d: r.chg20d,
          chg60d: r.chg60d, from_high: r.from_high, rsi14: r.rsi14 })) });
    }
  };
  preset.addEventListener("change", () => {
    const p = PRESETS[preset.value] || {};
    for (const [k] of FILTERS) { boxes[k][0].value = p[k] && p[k][0] !== null ? p[k][0] : ""; boxes[k][1].value = p[k] && p[k][1] !== null ? p[k][1] : ""; }
    lowWithin = p._low ?? null;
    if (Object.keys(p).some((k) => !k.startsWith("_"))) { filterBox.hidden = false; more.textContent = "fewer filters"; }
    draw();
  });
  sector.addEventListener("change", () => { fillIndustries(); industry.value = ""; draw(); });
  for (const el of [industry, groupBy, period]) el.addEventListener("change", draw);
  for (const el of [search, ...Object.values(boxes).flat()]) el.addEventListener("input", draw);
  fillIndustries();
  draw();
  return h("div", { class: "stocktable" },
    h("div", { class: "toolbar" }, preset, sector, industry, search, groupBy, period, more,
      h("button", { class: "linkish", onclick: () => { preset.value = ""; if (!lockGroup) sector.value = ""; industry.value = ""; search.value = ""; lowWithin = null;
        Object.values(boxes).flat().forEach((i) => { i.value = ""; }); fillIndustries(); draw(); } }, "clear")),
    filterBox, summaryBox, countLine, tableBox);
}

// Breadcrumb trail: [[label, href], ...]; the last item is the current page (no link).
export function crumbs(items) {
  return h("nav", { class: "crumbs small" }, items.map(([label, href], i) => [i ? h("span", { class: "muted" }, " › ") : null,
    href && i < items.length - 1 ? h("a", { href }, label) : h("span", null, label)]));
}

export function stockNote(text) { return note(text); }

// When the list was computed (live prices) and how old the cached year of daily closes behind it is.
export function listStamp(d) {
  return h("p", { class: "small" }, asOf(d.asof, { label: "prices as of", maxAgeHours: 0.25 }), " · ",
    asOf(d.closes_asof, { label: "daily history as of", maxAgeHours: 3, stale: d.closes_stale }));
}
