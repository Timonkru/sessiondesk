// Sectors: performance heat map per region (US, Europe) over 1 day to 1 year, absolute or relative to the broad market.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, pct, dir, sparkline, note, loading, errorBox } from "../lib/ui.js";

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

function tileColor(v, scale) {
  if (v == null) return "var(--bg2)";
  const a = Math.min(1, Math.abs(v) / scale) * 0.75 + 0.08;
  return v >= 0 ? `rgba(22, 163, 74, ${a})` : `rgba(220, 38, 38, ${a})`;
}

export async function render(root, _params, ctx) {
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
        h("div", { class: "heat" }, rows.map((r) => h("a", { class: "heattile", href: "#/stock/" + encodeURIComponent(r.symbol), style: { background: tileColor(r[key], scale) },
          title: `${r.name} (${r.symbol})` }, h("div", { class: "hn" }, r.name), h("div", { class: "hv" }, pct(r[key], 1))))),
        h("details", null, h("summary", { class: "small" }, "all periods"), table([
          { label: "Sector", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.name) },
          ...PERIODS.map(([k, label]) => ({ label, num: true, cls: (r) => dir(r[(rel ? "rel_" : "") + k]), render: (r) => pct(r[(rel ? "rel_" : "") + k], 1) })),
          { label: "60 days", num: true, render: (r) => sparkline(r.spark) },
        ], rows)));
    }), note("Sector ETFs (free daily closes, refreshed every 15 minutes). 'Relative' = sector minus the broad market in percentage points. ETF fees and tracking make this the sector picture, not the exact index return."));
    ctx.setContext({ page: "Sectors", period, relative: rel, regions: data.filter((d) => !d.error).map((d) => ({ region: d.name, benchmark: d.benchmark,
      sectors: d.rows.map((r) => ({ name: r.name, symbol: r.symbol, "1d": r["1d"], "1w": r["1w"], "1m": r["1m"], "3m": r["3m"], ytd: r.ytd, "1y": r["1y"] })) })) });
  };
  draw();
}
