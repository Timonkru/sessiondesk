// Asset monitor (oil, gas & power, gold): prices, futures curve, spreads, inventories and flows, IV, positioning,
// releases and headlines on one page.
import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, pct, price, dir, sparkline, note, loading, errorBox, day, clock } from "../lib/ui.js";
import { crumbs } from "../lib/stocktable.js";

const MONITORS = [["oil", "Crude oil"], ["gas", "Natural gas & power"], ["gold", "Gold & precious metals"]];

export async function render(root, params, ctx) {
  const key = MONITORS.some(([k]) => k === params[0]) ? params[0] : "oil";
  const body = h("div", null, loading("Collecting prices, the curve, inventories and positioning…"));
  root.append(crumbs([["Data", "#/hub"], ["Commodities & energy", "#/commodities"], [MONITORS.find(([k]) => k === key)[1]]]),
    h("div", { class: "tabs" }, MONITORS.map(([k, l]) => h("button", { class: k === key ? "on" : "", onclick: () => ctx.go("#/monitor/" + k) }, l))), body);
  const draw = async () => {
    const d = await api("/api/monitor/" + key, { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    const prices = section("Prices", table([
      { label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.label) },
      { label: "Last", num: true, render: (r) => price(r.price) },
      { label: "Today", num: true, cls: (r) => dir(r.change_pct), render: (r) => pct(r.change_pct) },
      { label: "", num: true, render: (r) => sparkline(r.spark, { ref: r.prev_close, width: 90 }) }], d.prices),
      d.spreads.length ? table([{ label: "Spread", render: (s) => s.name }, { label: "", num: true, render: (s) => num(s.value, 2) }], d.spreads) : null);
    const curves = section("Futures curve", d.curves.length ? d.curves.map((c) => h("div", null,
      h("p", { class: "small" }, h("strong", null, c.name), c.shape ? ` · ${c.shape.state}: 2nd month ${pct(c.shape.m2, 1)}, 6th ${pct(c.shape.m6, 1)}${c.shape.m12 != null ? `, 12th ${pct(c.shape.m12, 1)}` : ""} vs front` : " · no contract prices"),
      c.points.length > 1 ? lineChart(c.points.map(([x, y]) => ({ x, y })), { height: 130, area: false, fmtY: (v) => price(v), fmtX: (x) => x }) : null)) : note("No curve."));
    const hub = section("Inventories, flows and drivers", table([
      { label: "", render: (r) => h("a", { href: "#/hub/" + encodeURIComponent(r.id) }, r.name) },
      { label: "Latest", num: true, render: (r) => num(r.last, Math.abs(r.last) < 10 ? 2 : 1) },
      { label: "Change", num: true, cls: (r) => dir(r.change), render: (r) => (r.change == null ? "–" : (r.change > 0 ? "+" : "") + num(r.change, Math.abs(r.change) < 10 ? 2 : 1)) },
      { label: "vs a year ago", num: true, cls: (r) => dir(r.vs_year), render: (r) => (r.vs_year == null ? "–" : (r.vs_year > 0 ? "+" : "") + num(r.vs_year, Math.abs(r.vs_year) < 10 ? 2 : 0)) },
      { label: "", num: true, render: (r) => sparkline(r.spark, { width: 80 }) },
      { label: "Date", render: (r) => h("span", { class: "small muted" }, r.day) }], d.hub, { empty: "Not collected yet - Data hub → collect now." }));
    const side = [
      d.iv ? section("Implied volatility", h("p", null, `${d.iv.id.replace("iv:", "")} 30-day IV: `, h("strong", null, num(d.iv.last, 1) + "%"),
        h("span", { class: "small muted" }, ` (record since ${d.iv.since}, ${d.iv.n} sessions)`))) : null,
      d.cot.length ? section("Positioning (CFTC)", table([{ label: "", render: (r) => r.market }, { label: "Net", num: true, render: (r) => num(r.net, 0) },
        { label: "Week", num: true, cls: (r) => dir(r.week_change), render: (r) => num(r.week_change, 0) },
        { label: "1y percentile", num: true, render: (r) => num(r.percentile, 0) + "%" }, { label: "", render: (r) => h("span", { class: "small muted" }, `${r.group}, ${r.date}`) }], d.cot)) : null,
      d.tankers ? section("Tankers at chokepoints", table([{ label: "", render: (r) => r.name }, { label: "Now", num: true, render: (r) => r.tankers },
        { label: "slow", num: true, render: (r) => r.slow }, { label: "today", num: true, render: (r) => r.today }], d.tankers.chokepoints.filter((r) => r.vessels)),
        h("p", { class: "small" }, h("a", { href: "#/tankers" }, "tanker monitor →"))) : null,
      section("Releases", table([{ label: "", render: (e) => h("span", { class: "small" }, `${day(e.ts)} ${clock(e.ts)}`) },
        { label: "", render: (e) => h("span", { class: e.impact === "high" ? "warn" : "" }, `${e.currency} ${e.title}`) },
        { label: "Act / fcst", num: true, render: (e) => h("span", { class: "small" }, `${e.actual ?? "–"} / ${e.forecast ?? "–"}`) }], d.calendar, { empty: "None in the calendar window." })),
    ];
    const news = section("Headlines", d.news.length ? h("ul", { class: "feed compact" }, d.news.map((n) => h("li", null,
      h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
      h("div", { class: "m" }, `${day(n.published)} ${clock(n.published)} · ${n.source}`)))) : note("No matching headlines."));
    clear(body, h("div", { class: "pagehead" }, h("h1", null, d.name)),
      h("div", { class: "cols" }, h("div", null, prices, curves), h("div", null, hub, ...side)), news, note(d.note));
    ctx.setContext({ page: `Monitor ${d.name}`, prices: d.prices.map((p) => ({ label: p.label, price: p.price, change_pct: p.change_pct })),
      curves: d.curves.map((c) => ({ name: c.name, shape: c.shape })), spreads: d.spreads, inventories: d.hub.map((r) => ({ name: r.name, last: r.last, change: r.change, vs_year: r.vs_year })),
      cot: d.cot, headlines: d.news.slice(0, 8).map((n) => n.title) });
  };
  await draw();
  const t = setInterval(draw, 60000);
  return () => clearInterval(t);
}
