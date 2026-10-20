// Sectors: performance heat map per region (US, Europe) over 1 day to 1 year, absolute or relative to the broad market.
// A tile opens the sector: its ETF against the market, breadth, top and bottom movers, and every member stock.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, pct, dir, big, price, sparkline, note, loading, errorBox } from "../lib/ui.js";

// sector-ETF period key -> member metric key (screener metrics)
const MEMBER_PERIODS = [["1d", "chg1d", "1 day"], ["1w", "chg5d", "1 week"], ["1m", "chg20d", "1 month"], ["3m", "chg60d", "3 months"], ["1y", "chg1y", "1 year"]];

async function sectorPage(root, region, etf, ctx) {
  const body = h("div", null, loading("Loading the sector's members…"));
  root.append(h("p", { class: "small" }, h("a", { href: "#/sectors" }, "← all sectors")), body);
  const d = await api(`/api/sectors/${region}/${encodeURIComponent(etf)}`, { ttl: 300000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  let period = localStorage.getItem("sd.secPeriod") || "1m";
  if (!MEMBER_PERIODS.some((p) => p[0] === period)) period = "1m";
  const e = d.etf_row || {}, b = d.benchmark || {};
  const draw = () => {
    const [, mk, plabel] = MEMBER_PERIODS.find((p) => p[0] === period);
    const sorted = [...d.rows].filter((r) => r[mk] != null).sort((x, y) => y[mk] - x[mk]);
    const up = sorted.filter((r) => r[mk] > 0).length;
    const mini = (rows) => table([
      { label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
      { label: "", render: (r) => h("span", { class: "small" }, r.name) },
      { label: plabel, num: true, cls: (r) => dir(r[mk]), render: (r) => pct(r[mk], 1) }], rows);
    clear(body,
      h("div", { class: "pagehead" }, h("h1", null, d.sector), h("span", { class: "meta" }, `${region === "us" ? "United States" : "Europe"} · ${d.n} stocks · ETF `,
        h("a", { href: "#/stock/" + encodeURIComponent(d.etf) }, d.etf))),
      h("div", { class: "keystrip" }, MEMBER_PERIODS.map(([k, , label]) => h("div", null, h("span", { class: "k" }, label),
        h("span", { class: "v " + dir(e[k]) }, pct(e[k], 1)), h("span", { class: "small muted" }, ` vs ${pct(b[k], 1)}`)))),
      h("div", { class: "toolbar" }, MEMBER_PERIODS.map(([k, , label]) => h("button", { class: "linkish", style: { fontWeight: k === period ? 700 : 400 },
        onclick: () => { period = k; localStorage.setItem("sd.secPeriod", k); draw(); } }, label)),
        h("span", { class: "small muted", style: { marginLeft: "14px" } }, sorted.length ? `${up} of ${sorted.length} up over ${plabel} (${Math.round((up / sorted.length) * 100)}%)` : "")),
      h("div", { class: "cols" }, section("Top movers", mini(sorted.slice(0, 8))), section("Bottom movers", mini(sorted.slice(-8).reverse()))),
      section(`All ${d.n} members`, h("div", { class: "scroll" }, table([
        { label: "Symbol", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
        { label: "Name", render: (r) => r.name }, { label: "Industry", render: (r) => h("span", { class: "small muted" }, r.sub) },
        { label: "Last", num: true, render: (r) => price(r.last) },
        ...MEMBER_PERIODS.map(([, k, label]) => ({ label, num: true, cls: (r) => dir(r[k]), render: (r) => pct(r[k], 1) })),
        { label: "From 52w high", num: true, cls: (r) => dir(r.from_high), render: (r) => pct(r.from_high, 1) },
        { label: "Mkt cap", num: true, render: (r) => big(r.market_cap) },
        { label: "In", render: (r) => h("span", { class: "small muted" }, r.indices.join(", ")) },
      ], sorted.concat(d.rows.filter((r) => r[mk] == null)))), note(d.note)));
    ctx.setContext({ page: `Sector ${d.sector}`, region, etf: d.etf, period, etf_returns: e, benchmark: b,
      members_up: `${up} of ${sorted.length}`, top: sorted.slice(0, 8).map((r) => ({ symbol: r.symbol, name: r.name, move: r[mk] })),
      bottom: sorted.slice(-8).map((r) => ({ symbol: r.symbol, name: r.name, move: r[mk] })) });
  };
  draw();
}

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

function tileColor(v, scale) {
  if (v == null) return "var(--bg2)";
  const a = Math.min(1, Math.abs(v) / scale) * 0.75 + 0.08;
  return v >= 0 ? `rgba(22, 163, 74, ${a})` : `rgba(220, 38, 38, ${a})`;
}

export async function render(root, params, ctx) {
  if (params[0] && params[1]) return sectorPage(root, params[0], decodeURIComponent(params[1]), ctx);
  let period = localStorage.getItem("sd.secPeriod") || "1m", rel = localStorage.getItem("sd.secRel") === "1";
  const bar = h("div", { class: "toolbar" }), body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Sectors"), h("span", { class: "meta" }, "where the money went, by region")), bar, body);
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
