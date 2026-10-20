// Stocks: every stock of the bundled index lists in the shared stock table - filter, sort, group by sector or
// industry. Replaces the former Screener (#/screener/<index> still lands here).
import { api } from "../lib/api.js";
import { h, clear, note, loading, errorBox, ago } from "../lib/ui.js";
import { stockTable, crumbs } from "../lib/stocktable.js";

export async function render(root, params, ctx) {
  const uni = (await api("/api/universes", { ttl: 600000 })).items || [];
  const scopes = [["all", "All"], ["region:us", "United States"], ["region:ca", "Canada"], ["region:eu", "Europe"], ["region:asia", "Asia-Pacific"], ...uni.map((u) => ["index:" + u.key, u.name])];
  let scope = params[0] ? decodeURIComponent(params[0]) : localStorage.getItem("sd.stocksScope") || "all";
  if (uni.some((u) => u.key === scope)) scope = "index:" + scope;                 // old #/screener/<key> links
  if (!scopes.some(([k]) => k === scope)) scope = "all";
  try { localStorage.setItem("sd.stocksScope", scope); } catch { /* storage blocked */ }
  const label = scopes.find(([k]) => k === scope)[1];
  const body = h("div", null, loading("Loading member history… (the first load of all indices takes up to a minute)"));
  root.append(crumbs([["Markets", "#/markets"], ["Stocks", "#/stocks/all"], ...(scope === "all" ? [] : [[label]])]),
    h("div", { class: "pagehead" }, h("h1", null, "Stocks"), h("span", { class: "meta" }, "every stock of the bundled indices - filter, sort, group")),
    h("div", { class: "toolbar" }, h("span", { class: "small muted" }, "universe"),
      h("select", { onchange: (e) => ctx.go("#/stocks/" + encodeURIComponent(e.target.value)) }, scopes.map(([k, l]) => h("option", { value: k, selected: k === scope }, l)))),
    body);
  const d = await api(`/api/stocks?scope=${encodeURIComponent(scope)}`, { ttl: 60000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  clear(body, stockTable(d.rows, { ctx, name: `Stocks - ${label}`, group: "none" }), note(d.note));
}
