// Sectors: performance heat map per region (US, Europe) over 1 day to 1 year, absolute or relative to the broad market.
// A tile opens the sector: its ETF against the market, breadth, top and bottom movers, and every member stock.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, pct, dir, big, price, sparkline, note, loading, errorBox } from "../lib/ui.js";
import { stockTable, crumbs } from "../lib/stocktable.js";

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

function tileColor(v, scale) {
  if (v == null) return "var(--bg2)";
  const a = Math.min(1, Math.abs(v) / scale) * 0.75 + 0.08;
  return v >= 0 ? `rgba(22, 163, 74, ${a})` : `rgba(220, 38, 38, ${a})`;
}

// sector-ETF period key -> member metric key
const MEMBER_PERIODS = [["1d", "chg1d", "1 day"], ["1w", "chg5d", "1 week"], ["1m", "chg20d", "1 month"], ["3m", "chg60d", "3 months"], ["1y", "chg1y", "1 year"]];
const REGION_NAME = { us: "United States", eu: "Europe" };

// Sector page (and, with an industry, the industry inside it): ETF against the market, top and bottom movers,
// then the shared stock table - grouped by industry, a click on an industry goes one level down.
async function sectorPage(root, region, etf, industry, ctx) {
  const body = h("div", null, loading("Loading the sector's members…"));
  const head = h("div");
  root.append(head, body);
  const d = await api(`/api/sectors/${region}/${encodeURIComponent(etf)}`, { ttl: 300000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  const base = `#/sectors/${region}/${encodeURIComponent(etf)}`;
  clear(head, crumbs([["Markets", "#/markets"], ["Sectors", "#/sectors"], [REGION_NAME[region], "#/sectors"], [d.sector, base], ...(industry ? [[industry]] : [])]));
  const rows = industry ? d.rows.filter((r) => r.industry === industry) : d.rows;
  let period = localStorage.getItem("sd.secPeriod") || "1m";
  if (!MEMBER_PERIODS.some((p) => p[0] === period)) period = "1m";
  const e = d.etf_row || {}, b = d.benchmark || {};
  const movers = h("div");
  const drawMovers = () => {
    const [, mk, plabel] = MEMBER_PERIODS.find((p) => p[0] === period);
    const sorted = rows.filter((r) => r[mk] != null).sort((x, y) => y[mk] - x[mk]);
    const up = sorted.filter((r) => r[mk] > 0).length;
    const mini = (list) => table([
      { label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
      { label: "", render: (r) => h("span", { class: "small" }, r.name) },
      { label: plabel, num: true, cls: (r) => dir(r[mk]), render: (r) => pct(r[mk], 1) }], list);
    clear(movers,
      h("div", { class: "toolbar" }, MEMBER_PERIODS.map(([k, , label]) => h("button", { class: "linkish", style: { fontWeight: k === period ? 700 : 400 },
        onclick: () => { period = k; localStorage.setItem("sd.secPeriod", k); drawMovers(); } }, label)),
        h("span", { class: "small muted", style: { marginLeft: "14px" } }, sorted.length ? `${up} of ${sorted.length} up over ${plabel} (${Math.round((up / sorted.length) * 100)}%)` : "")),
      h("div", { class: "cols" }, section("Top movers", mini(sorted.slice(0, 6))), section("Bottom movers", mini(sorted.slice(-6).reverse()))));
  };
  drawMovers();
  clear(body,
    h("div", { class: "pagehead" }, h("h1", null, industry || d.sector), h("span", { class: "meta" }, `${industry ? d.sector + " · " : ""}${REGION_NAME[region]} · ${rows.length} stocks · sector ETF `,
      h("a", { href: "#/stock/" + encodeURIComponent(d.etf) }, d.etf))),
    industry ? null : h("div", { class: "keystrip" }, MEMBER_PERIODS.map(([k, , label]) => h("div", null, h("span", { class: "k" }, label),
      h("span", { class: "v " + dir(e[k]) }, pct(e[k], 1)), h("span", { class: "small muted" }, ` vs ${pct(b[k], 1)}`)))),
    movers,
    section(industry ? "Stocks" : "Industries and stocks", stockTable(rows, { ctx, name: `Sector ${d.sector}${industry ? " / " + industry : ""}`, lockGroup: true,
      group: industry ? "none" : "industry", onGroup: industry ? null : (_k, code) => ctx.go(`${base}/${encodeURIComponent(code)}`) })),
    note(d.note));
}

export async function render(root, params, ctx) {
  if (params[0] && params[1]) return sectorPage(root, params[0], decodeURIComponent(params[1]), params[2] ? decodeURIComponent(params[2]) : null, ctx);
  let period = localStorage.getItem("sd.secPeriod") || "1m", rel = localStorage.getItem("sd.secRel") === "1";
  const bar = h("div", { class: "toolbar" }), body = h("div", null, loading());
  root.append(crumbs([["Markets", "#/markets"], ["Sectors"]]), h("div", { class: "pagehead" }, h("h1", null, "Sectors"), h("span", { class: "meta" }, "where the money went, by region")), bar, body);
  const data = await Promise.all(["us", "eu"].map((r) => api("/api/sectors/" + r, { ttl: 300000 })));

  const draw = () => {
    clear(bar, PERIODS.map(([k, label]) => h("button", { class: "linkish", style: { fontWeight: k === period ? 700 : 400 },
      onclick: () => { period = k; localStorage.setItem("sd.secPeriod", k); draw(); } }, label)),
      h("label", { class: "small", style: { marginLeft: "18px" } }, h("input", { type: "checkbox", checked: rel,
        onchange: (e) => { rel = e.target.checked; localStorage.setItem("sd.secRel", rel ? "1" : "0"); draw(); } }), " relative to the broad market"));
    const key = (rel ? "rel_" : "") + period;
    const scale = { "1d": 2, "1w": 4, "1m": 8, "3m": 15, ytd: 25, "1y": 30 }[period];
    clear(body, data.map((d) => {
      if (d.error) return errorBox(d.error);
      const rows = [...d.rows].sort((a, b) => (b[key] ?? -1e9) - (a[key] ?? -1e9));
      const b = d.benchmark;
      return section(d.name,
        h("p", { class: "small" }, `${b.name}: ${pct(b[period], 1)} over ${PERIODS.find((p) => p[0] === period)[1]}`),
        h("div", { class: "heat" }, rows.map((r) => h("a", { class: "heattile", href: `#/sectors/${d.region}/${encodeURIComponent(r.symbol)}`, style: { background: tileColor(r[key], scale) },
          title: `${r.name} (${r.symbol})` }, h("div", { class: "hn" }, r.name), h("div", { class: "hv" }, pct(r[key], 1))))),
        h("details", null, h("summary", { class: "small" }, "all periods"), table([
          { label: "Sector", render: (r) => h("a", { href: `#/sectors/${d.region}/${encodeURIComponent(r.symbol)}` }, r.name) },
          ...PERIODS.map(([k, label]) => ({ label, num: true, cls: (r) => dir(r[(rel ? "rel_" : "") + k]), render: (r) => pct(r[(rel ? "rel_" : "") + k], 1) })),
          { label: "60 days", num: true, render: (r) => sparkline(r.spark) },
        ], rows)));
    }), note("Click a sector for its stocks and movers. Sector ETFs (free daily closes, refreshed every 15 minutes). 'Relative' = sector minus the broad market in percentage points. ETF fees and tracking make this the sector picture, not the exact index return."));
    ctx.setContext({ page: "Sectors", period, relative: rel, regions: data.filter((d) => !d.error).map((d) => ({ region: d.name, benchmark: d.benchmark,
      sectors: d.rows.map((r) => ({ name: r.name, symbol: r.symbol, "1d": r["1d"], "1w": r["1w"], "1m": r["1m"], "3m": r["3m"], ytd: r.ytd, "1y": r["1y"] })) })) });
  };
  draw();
}
