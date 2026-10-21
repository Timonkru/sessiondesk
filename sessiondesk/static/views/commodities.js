// Commodities & energy: futures by group with 1 day to 1 year, power prices, EU gas imports (ENTSOG) and storage (AGSI+),
// EIA oil and gas inventories, sources to connect for more.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, pct, price, dir, sparkline, note, loading, errorBox } from "../lib/ui.js";

const FLOW_TOTALS = new Set(["entsog:total", "entsog:lng_total"]);
const flowName = (s) => s.name.replace(/ \(GWh\/d\)$/, "").replace(/^LNG send-out (?!EU total)/, "LNG · ");
const flowShort = (s) => flowName(s).replace(/ \((.*)\)$/, "");          // the detail in brackets goes to the tooltip
const flowDetail = (s) => (flowName(s).match(/ \((.*)\)$/) || [])[1] || "";
const pp = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${num(v, 2)}`);

function storageEmpty(agsi) {
  if (!agsi || !agsi.configured) return "Key needed: AGSI+ is free but needs your own key - create one at agsi.gie.eu, then Settings → Connectors → GIE AGSI+.";
  if (!agsi.active) return "The GIE AGSI+ connector is switched off (Settings → Connectors).";
  return "Not collected yet - Data hub → collect now (runs in the background), or wait for the next run.";
}

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Commodities & energy"), h("span", { class: "meta" }, "prices, inventories, flows")),
    h("p", null, "Monitors: ", h("a", { href: "#/monitor/oil" }, "Crude oil"), " · ", h("a", { href: "#/monitor/gas" }, "Natural gas & power"), " · ",
      h("a", { href: "#/monitor/gold" }, "Gold & precious metals"), h("span", { class: "small muted" }, " - curve, inventories, positioning, releases and headlines on one page")), body);
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
    section("Power day-ahead (EUR/MWh, daily base)", table([
      { label: "Zone", render: (s) => h("a", { href: "#/hub/" + encodeURIComponent(s.id) }, s.name.replace(/^Power day-ahead /, "").replace(/ \(EUR\/MWh, daily base\)$/, "")) },
      { label: "Day", render: (s) => h("span", { class: "muted small" }, s.day) },
      { label: "Price", num: true, render: (s) => num(s.last, 1) },
      { label: "Prev. day", num: true, cls: (s) => dir(s.last - s.prev), render: (s) => num(s.prev, 1) },
      { label: "30-day avg", num: true, render: (s) => num(s.avg30, 1) },
      { label: "1-year avg", num: true, render: (s) => num(s.avg365, 1) },
      { label: "60 days", num: true, render: (s) => sparkline(s.spark) },
    ], d.power || [], { empty: "Not collected yet - the power collector runs a few minutes after start (one zone every few seconds)." }),
      note("Day-ahead auction results, average of all hours of the delivery day; tomorrow's prices appear after the auction (~13:00 CET). "
        + "Source: Energy-Charts (Fraunhofer ISE), data Bundesnetzagentur | SMARD.de, licence CC BY 4.0."),
      (d.power || []).length ? h("p", { class: "small" }, h("a", { href: (d.power[0] || {}).url, target: "_blank", rel: "noopener noreferrer" }, "Energy-Charts ↗")) : null),
    section("EU gas imports by route (ENTSOG, GWh/d)", table([
      { label: "Route", render: (s) => { const a = h("a", { href: "#/hub/" + encodeURIComponent(s.id), title: flowDetail(s) }, flowShort(s)); return FLOW_TOTALS.has(s.id) ? h("strong", null, a) : a; } },
      { label: "Gas day", render: (s) => h("span", { class: "muted small", style: { whiteSpace: "nowrap" } }, s.day) },
      { label: "GWh/d", num: true, render: (s) => num(s.last, 0) },
      { label: "Prev. day", num: true, cls: (s) => dir(s.last - s.prev), render: (s) => num(s.prev, 0) },
      { label: "30-day avg", num: true, render: (s) => num(s.avg30, 0) },
      { label: "Year ago", num: true, render: (s) => num(s.year_ago, 0) },
      { label: "60 days", num: true, render: (s) => sparkline(s.spark) },
    ], d.gas_flows || [], { empty: "Not collected yet - the ENTSOG collector runs a few minutes after start (first run loads three years)." }),
      note("Physical flows at the EU entry points as reported by the gas transmission operators; the latest days are provisional "
        + "and get revised. Each source is counted once where it enters the EU (TurkStream at Strandzha 2, TAP at Kipoi). The Norway "
        + "route misses the Emden landing points, which publish no flows on ENTSOG. 1 GWh/d ≈ 0.095 million m³/d."),
      h("p", { class: "small" }, h("a", { href: "https://transparency.entsog.eu/", target: "_blank", rel: "noopener noreferrer" }, "ENTSOG Transparency Platform ↗"))),
    section("EU gas storage (GIE AGSI+)", table([
      { label: "", render: (s) => h("a", { href: "#/hub/" + encodeURIComponent(s.id) }, s.name) },
      { label: "Gas day", render: (s) => h("span", { class: "muted small", style: { whiteSpace: "nowrap" } }, s.day) },
      { label: "Full %", num: true, render: (s) => num(s.full, 1) },
      { label: "Day (pp)", num: true, cls: (s) => dir(s.full - s.full_prev), render: (s) => pp(s.full_prev == null ? null : s.full - s.full_prev) },
      { label: "Year ago %", num: true, render: (s) => num(s.full_year_ago, 1) },
      { label: "Injection", num: true, render: (s) => num(s.injection, 0) },
      { label: "Withdrawal", num: true, render: (s) => num(s.withdrawal, 0) },
      { label: "60 days", num: true, render: (s) => sparkline(s.spark) },
    ], d.gas_storage || [], { empty: storageEmpty(d.agsi) }),
      note("Fill level of working gas volume, injection and withdrawal in GWh/d, reported by the storage operators (daily, around 18:00 CET). "
        + "Free key from GIE, stored only on this machine."
        + (d.agsi && d.agsi.configured && !d.agsi.verified ? " The connector is new and marked unverified until a live call succeeded (Settings → Connectors → Test connection)." : "")),
      h("p", { class: "small" }, h("a", { href: "https://agsi.gie.eu/", target: "_blank", rel: "noopener noreferrer" }, "GIE AGSI+ ↗"))),
    section("Inventories (EIA weekly)", table([
      { label: "Series", render: (s) => h("a", { href: "#/hub/" + encodeURIComponent(s.id) }, s.name) },
      { label: "Latest", num: true, render: (s) => num(s.last, 1) },
      { label: "Week change", num: true, cls: (s) => dir(s.change), render: (s) => (s.change == null ? "–" : `${s.change > 0 ? "+" : ""}${num(s.change, 1)}`) },
      { label: "Week", render: (s) => h("span", { class: "muted small" }, s.day) },
      { label: "Source", render: (s) => (s.url ? h("a", { class: "small", href: s.url, target: "_blank", rel: "noopener noreferrer", title: s.source }, "EIA ↗") : "") },
    ], d.fundamentals || [], { empty: "Not collected yet - Data hub → collect now." }),
      note("Crude, products and US gas storage from the EIA weekly reports. Each series has its history, chart, CSV and early warnings in the Data hub.")),
    section("Connect for more", table([
      { label: "Source", render: (s) => s.name }, { label: "Access", render: (s) => h("span", { class: s.access === "paid" ? "warn" : "up" }, s.access) },
      { label: "Adds", render: (s) => h("span", { class: "small" }, s.what) },
    ], d.more_sources || []), note("Free-key sources are planned connectors; paid ones plug in the same way for those who have a subscription.")));
  clear(body, h("div", { class: "cols" }, left, right), note(d.note));
  ctx.setContext({ page: "Commodities & energy", power: (d.power || []).map((s) => ({ zone: s.name, day: s.day, price: s.last, prev: s.prev, avg30: s.avg30, avg365: s.avg365 })), prices: (d.groups || []).map((g) => ({ group: g.group, rows: g.rows.map((r) => ({ name: r.name, symbol: r.symbol, last: r.last, "1d": r["1d"], "1m": r["1m"], ytd: r.ytd, "1y": r["1y"] })) })),
    inventories: d.fundamentals,
    gas_imports: (d.gas_flows || []).map((s) => ({ route: flowName(s), day: s.day, gwh_d: s.last, prev: s.prev, avg30: s.avg30, year_ago: s.year_ago })),
    gas_storage: (d.gas_storage || []).map((s) => ({ area: s.name, day: s.day, full_pct: s.full, prev_pct: s.full_prev, year_ago_pct: s.full_year_ago, injection: s.injection, withdrawal: s.withdrawal })) });
}
