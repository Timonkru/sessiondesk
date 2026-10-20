// Commodities & energy: futures by group with 1 day to 1 year, EIA oil and gas inventories, sources to connect for more.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, pct, price, dir, sparkline, note, loading, errorBox } from "../lib/ui.js";

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Commodities & energy"), h("span", { class: "meta" }, "prices, inventories, flows")), body);
  const d = await api("/api/commodities", { ttl: 300000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  const left = h("div"), right = h("div");
  for (const g of d.groups || []) {
    left.appendChild(section(g.group, table([
      { label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.name) },
      { label: "Last", num: true, render: (r) => price(r.last) },
      ...PERIODS.map(([k, label]) => ({ label, num: true, cls: (r) => dir(r[k]), render: (r) => pct(r[k], 1) })),
      { label: "60 days", num: true, render: (r) => sparkline(r.spark) },
    ], g.rows, { empty: "No prices." })));
  }
  right.append(
    section("Inventories (EIA weekly)", table([
      { label: "Series", render: (s) => h("a", { href: "#/hub/" + encodeURIComponent(s.id) }, s.name) },
      { label: "Latest", num: true, render: (s) => num(s.last, 1) },
      { label: "Week change", num: true, cls: (s) => dir(s.change), render: (s) => (s.change == null ? "–" : `${s.change > 0 ? "+" : ""}${num(s.change, 1)}`) },
      { label: "Week", render: (s) => h("span", { class: "muted small" }, s.day) },
    ], d.fundamentals || [], { empty: "Not collected yet - Data hub → collect now." }),
      note("Crude, products and US gas storage from the EIA weekly reports. Each series has its history, chart, CSV and early warnings in the Data hub.")),
    section("Connect for more", table([
      { label: "Source", render: (s) => s.name }, { label: "Access", render: (s) => h("span", { class: s.access === "paid" ? "warn" : "up" }, s.access) },
      { label: "Adds", render: (s) => h("span", { class: "small" }, s.what) },
    ], d.more_sources || []), note("Free-key sources are planned connectors; paid ones plug in the same way for those who have a subscription.")));
  clear(body, h("div", { class: "cols" }, left, right), note(d.note));
  ctx.setContext({ page: "Commodities & energy", prices: (d.groups || []).map((g) => ({ group: g.group, rows: g.rows.map((r) => ({ name: r.name, symbol: r.symbol, last: r.last, "1d": r["1d"], "1m": r["1m"], ytd: r.ytd, "1y": r["1y"] })) })),
    inventories: d.fundamentals });
}
