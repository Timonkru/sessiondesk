// Countries: one page per economy - main index and breadth, currency, macro, rates, releases, news.
import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, pct, price, dir, sparkline, note, loading, errorBox, day, clock } from "../lib/ui.js";
import { crumbs } from "../lib/stocktable.js";

const REGIONS = ["Americas", "Europe", "Asia-Pacific"];

export async function render(root, params, ctx) {
  if (params[0]) return countryPage(root, params[0], ctx);
  const body = h("div", null, loading());
  root.append(crumbs([["Markets", "#/markets"], ["Countries"]]),
    h("div", { class: "pagehead" }, h("h1", null, "Countries"), h("span", { class: "meta" }, "one page per economy: index, currency, macro, rates, releases, news")), body);
  const d = await api("/api/countries", { ttl: 60000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  clear(body, h("div", { class: "cols" }, REGIONS.map((reg) => section(reg, table([
    { label: "Country", render: (r) => h("a", { href: "#/country/" + r.key }, h("strong", null, r.name)) },
    { label: "Index", num: true, cls: (r) => dir(r.index_chg), render: (r) => pct(r.index_chg) },
    { label: "Currency", render: (r) => h("span", { class: "small" }, r.fx) },
    { label: "", num: true, cls: (r) => dir(r.fx_chg), render: (r) => pct(r.fx_chg) },
    { label: "10y", num: true, render: (r) => (r.y10 == null ? "–" : num(r.y10, 2)) },
  ], d.rows.filter((r) => r.region === reg), { onRow: (r) => ctx.go("#/country/" + r.key) })))),
  note("10y = government yield where a free official source exists (US, euro area AAA curve, UK, Japan)."));
  ctx.setContext({ page: "Countries", rows: d.rows });
}

async function countryPage(root, key, ctx) {
  const body = h("div", null, loading("Collecting everything about this country…"));
  const head = h("div");
  root.append(head, body);
  const d = await api("/api/country/" + key, { ttl: 60000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  clear(head, crumbs([["Markets", "#/markets"], ["Countries", "#/country"], [d.region, "#/country"], [d.name]]));
  const idx = d.indices[0] || {};
  const b = d.breadth;
  const y = (v) => (v == null ? "–" : num(v, 2));

  const markets = section("Markets",
    table([{ label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
      { label: "Last", num: true, render: (r) => price(r.price) },
      { label: "Today", num: true, cls: (r) => dir(r.change_pct), render: (r) => pct(r.change_pct) },
      { label: "", num: true, render: (r) => sparkline(r.spark, { ref: r.prev_close, width: 90 }) }],
      [...d.indices, { ...d.fx, symbol: d.fx.symbol }]),
    h("p", { class: "small muted" }, `${d.fx.label} is the currency line.`));

  const breadthBox = b ? section(`${d.universe_name}: participation today`,
    h("div", { class: "keystrip" }, [["Up today", b.before_open ? "before the open" : `${b.up} of ${b.n} (${Math.round((b.up / b.n) * 100)}%)`], ["Above 200-day", b.above200 == null ? "–" : `${Math.round(b.above200)}%`],
      ["Within 2% of 52w high", b.near_high]].map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v)))),
    b.before_open ? note("Today's session has not started yet for this index - participation and movers fill in after the open. The last sessions are in the members list (5 d, 20 d).") :
    h("div", { class: "cols" },
      table([{ label: "Best", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) }, { label: "", render: (r) => h("span", { class: "small" }, (r.name || "").slice(0, 24)) },
        { label: "", num: true, cls: (r) => dir(r.chg1d), render: (r) => pct(r.chg1d, 1) }], b.best),
      table([{ label: "Worst", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) }, { label: "", render: (r) => h("span", { class: "small" }, (r.name || "").slice(0, 24)) },
        { label: "", num: true, cls: (r) => dir(r.chg1d), render: (r) => pct(r.chg1d, 1) }], b.worst)),
    h("p", { class: "small" }, h("a", { href: `#/indices/${d.universe}/members` }, "all members →"), "  ", h("a", { href: `#/indices/${d.universe}/breadth` }, "breadth, drivers & valuation →"))) : null;

  const m = d.macro, labels = d.macro_labels || [];
  const macroBox = section("Economy",
    m ? table([{ label: "", render: (l) => l.label }, { label: "Latest", num: true, render: (l) => (m[l.key] ? num(m[l.key].value, 1) : "–") },
      { label: "Before", num: true, render: (l) => (m[l.key] && m[l.key].prev != null ? num(m[l.key].prev, 1) : "–") },
      { label: "Period", render: (l) => h("span", { class: "small muted" }, m[l.key] ? m[l.key].period : "") },
      { label: "", render: (l) => (m[l.key] ? h("a", { class: "small", href: m[l.key].url, target: "_blank", rel: "noopener noreferrer" }, m[l.key].source) : "") }], labels)
      : note("No free official macro source wired for this country yet."),
    h("p", { class: "small" }, h("a", { href: "#/macro" }, "all countries in Macro →")));

  const r = d.rates;
  const ratesBox = section(`Rates · ${d.bank}`,
    r ? [h("div", { class: "keystrip" }, [["Policy rate", r.policy == null ? "–" : y(r.policy)], ["2y", y(r["2y"])], ["10y", y(r["10y"])],
      ["2s10s", r.s2s10 == null ? "–" : `${Math.round(r.s2s10)} bp`], [`${r.gauge_tenor} - policy`, r.gauge_bp == null ? "–" : `${Math.round(r.gauge_bp)} bp`]]
      .map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v)))),
      lineChart(["3m", "1y", "2y", "5y", "10y", "30y"].filter((t) => r[t] != null).map((t) => ({ x: t, y: r[t] })), { height: 120, area: false, fmtY: (v) => v.toFixed(2) + "%", fmtX: (x) => x }),
      h("p", { class: "small muted" }, `${r.country} curve, ${r.date} · `, h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, r.source))]
      : note("No free official curve wired for this country yet."));

  const evRow = (e) => [h("span", { class: "small" }, `${day(e.ts)} ${clock(e.ts)}`), " ", h("span", { class: e.impact === "high" ? "warn" : "" }, e.title)];
  const calBox = section(`${d.ccy} releases`,
    table([{ label: "Next", render: evRow }, { label: "Fcst / prev", num: true, render: (e) => h("span", { class: "small" }, `${e.forecast ?? "–"} / ${e.previous ?? "–"}`) }],
      d.calendar.next, { empty: "Nothing medium or high impact in the next days." }),
    d.calendar.recent.length ? table([{ label: "Recent", render: evRow }, { label: "Actual vs fcst", num: true,
      render: (e) => h("span", { class: "small " + dir(e.surprise) }, `${e.actual} vs ${e.forecast ?? "–"}`) }], d.calendar.recent) : null);

  const newsBox = section(`News · ${d.market || "no market filter"}`, d.news.length ? h("ul", { class: "feed compact" }, d.news.map((n) => h("li", null,
    h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
    h("div", { class: "m" }, `${day(n.published)} ${clock(n.published)} · ${n.source}`)))) : note("No market filter for this country yet - see News."));

  clear(body, h("div", { class: "pagehead" }, h("h1", null, d.name), h("span", { class: "meta" }, `${idx.symbol || ""} ${pct(idx.change_pct)} · ${d.fx.label} ${pct(d.fx.change_pct)}`)),
    h("div", { class: "cols" }, h("div", null, markets, breadthBox), h("div", null, macroBox, ratesBox)),
    h("div", { class: "cols" }, calBox, newsBox), note(d.note));
  ctx.setContext({ page: `Country ${d.name}`, indices: d.indices.map((i) => ({ symbol: i.symbol, price: i.price, change_pct: i.change_pct })),
    fx: { label: d.fx.label, change_pct: d.fx.change_pct }, breadth: b && { up: b.up, n: b.n, above200: b.above200 }, macro: m, rates: r,
    next_releases: d.calendar.next.map((e) => e.title), headlines: d.news.slice(0, 8).map((n) => n.title) });
}
