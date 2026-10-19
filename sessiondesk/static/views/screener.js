// Screener: filter and sort an index universe by price behaviour (and cached fundamentals). Describes, never signals.
// The universes are the same list the Movers scan and the Indices page use (/api/universes).
import { api } from "../lib/api.js";
import { h, clear, table, num, pct, price, big, dir, note, loading, errorBox, ago } from "../lib/ui.js";

// [key, label, step] - each gets a min and a max box
const FILTERS = [["chg1d", "Today %"], ["chg20d", "20 days %"], ["chg60d", "60 days %"], ["from_high", "From 52w high %"],
  ["dist200", "From 200-day avg %"], ["rsi14", "RSI 14"], ["vol20", "Volatility 20d %"], ["pe_fwd", "Forward P/E"], ["div_yield", "Dividend yield %"]];
const PRESETS = {
  "": {},
  "Near 52-week high": { from_high: [-2, null] },
  "Within 3 % of the 52-week low": { _low: 3 },
  "RSI 14 at or below 30": { rsi14: [null, 30] },
  "RSI 14 at or above 70": { rsi14: [70, null] },
  "Above 200-day average, down today": { dist200: [0, null], chg1d: [null, 0] },
  "Below 200-day average, up 20 days": { dist200: [null, 0], chg20d: [0, null] },
  "Forward P/E 15 or less (cached)": { pe_fwd: [0, 15] },
};

export async function render(root, params, ctx) {
  const UNIVERSES = ((await api("/api/universes", { ttl: 600000 })).items || []).map((u) => [u.key, u.name]);
  const key = UNIVERSES.some(([k]) => k === params[0]) ? params[0] : (localStorage.getItem("sd.screenU") || "sp500");
  localStorage.setItem("sd.screenU", key);
  const tabBar = h("div", { class: "tabs" }, UNIVERSES.map(([k, label]) => h("button", { class: k === key ? "on" : "", onclick: () => ctx.go("#/screener/" + k) }, label)));
  const body = h("div", null, loading("Loading member history… (first load of a universe takes up to a minute)"));
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Screener"), h("span", { class: "meta" }, "filter and sort index members")), tabBar, body);

  const d = await api("/api/screener/" + key, { ttl: 60000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }

  const boxes = {};
  const mk = (ph) => h("input", { type: "text", inputmode: "decimal", placeholder: ph, style: { width: "64px" } });
  for (const [k] of FILTERS) boxes[k] = [mk("min"), mk("max")];
  const sectors = [...new Set(d.rows.map((r) => r.sector).filter(Boolean))].sort();
  const sector = h("select", null, h("option", { value: "" }, "all sectors"), sectors.map((s) => h("option", { value: s }, s)));
  const preset = h("select", null, Object.keys(PRESETS).map((p) => h("option", { value: p }, p || "preset…")));
  const search = h("input", { type: "search", placeholder: "symbol or name", style: { width: "160px" } });
  let lowWithin = null, sortKey = "chg1d", sortDir = -1;

  const val = (i) => { const t = i.value.trim().replace(",", "."); return t === "" ? null : Number(t); };
  const pass = (r) => {
    if (sector.value && r.sector !== sector.value) return false;
    const q = search.value.trim().toLowerCase();
    if (q && !r.symbol.toLowerCase().includes(q) && !(r.name || "").toLowerCase().includes(q)) return false;
    if (lowWithin !== null && !(r.from_low !== null && r.from_low <= lowWithin)) return false;
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

  const out = h("div");
  const cols = [
    ["symbol", "Symbol", (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol)],
    ["name", "Name", (r) => h("span", { class: "small" }, r.name)],
    ["sector", "Sector", (r) => h("span", { class: "small muted" }, r.sector)],
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
  ];
  const draw = () => {
    const rows = d.rows.filter(pass).sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * sortDir;
    });
    const t = table(cols.map(([k, label, render, isNum]) => ({ label: label + (k === sortKey ? (sortDir < 0 ? " ▼" : " ▲") : ""), num: !!isNum, render })),
      rows.slice(0, 300), { onRow: (r) => ctx.go("#/stock/" + encodeURIComponent(r.symbol)), empty: "No member matches these filters." });
    t.querySelectorAll("th").forEach((th, i) => {
      th.style.cursor = "pointer";
      th.addEventListener("click", () => { const k = cols[i][0]; sortDir = k === sortKey ? -sortDir : (typeof d.rows[0]?.[k] === "string" ? 1 : -1); sortKey = k; draw(); });
    });
    clear(out, h("p", { class: "small" }, `${rows.length} of ${d.rows.length} members${rows.length > 300 ? " (first 300 shown)" : ""}`), h("div", { class: "scroll" }, t));
    const active = FILTERS.filter(([k]) => boxes[k].some((i) => i.value.trim())).map(([k, label]) => `${label} ${boxes[k][0].value || "…"} to ${boxes[k][1].value || "…"}`);
    ctx.setContext({ page: `Screener ${d.name}`, filters: { sector: sector.value || "all", search: search.value, preset: preset.value, ranges: active, sorted_by: sortKey },
      matches: rows.length, rows: rows.slice(0, 40).map((r) => ({ ...r, name: undefined })) });
  };
  preset.addEventListener("change", () => {
    const p = PRESETS[preset.value] || {};
    for (const [k] of FILTERS) { boxes[k][0].value = p[k] && p[k][0] !== null ? p[k][0] : ""; boxes[k][1].value = p[k] && p[k][1] !== null ? p[k][1] : ""; }
    lowWithin = p._low ?? null;
    draw();
  });
  for (const el of [sector, search, ...Object.values(boxes).flat()]) el.addEventListener("input", draw);
  sector.addEventListener("change", draw);

  clear(body,
    h("div", { class: "toolbar" }, preset, sector, search, h("button", { class: "linkish", onclick: () => { preset.value = ""; sector.value = ""; search.value = ""; lowWithin = null; Object.values(boxes).flat().forEach((i) => { i.value = ""; }); draw(); } }, "clear")),
    h("div", { class: "screenfilters" }, FILTERS.map(([k, label]) => h("label", null, h("span", { class: "small muted" }, label), boxes[k][0], boxes[k][1]))),
    out,
    note(`${d.note} Updated ${ago(d.asof)} ago.`));
  draw();
}
