// Baskets: your own sets of symbols, followed like an index against a benchmark.
import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, pct, price, dir, note, loading, errorBox, toast } from "../lib/ui.js";

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

export async function render(root, params, ctx) {
  const list = h("div"), view = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Baskets"), h("span", { class: "meta" }, "your own sets of stocks, followed like an index")),
    h("div", { class: "cols" }, view, list));

  const form = (b) => {
    const name = h("input", { type: "text", placeholder: "name, e.g. AI leaders", value: b ? b.name : "", style: { width: "100%" } });
    const members = h("textarea", { rows: 4, style: { width: "100%" }, placeholder: "symbols with optional weights, e.g.\nNVDA 30, MSFT 25, AVGO, AMD, SAP.DE" },
      b ? b.members.map((m) => `${m.symbol} ${num(m.weight * 100, 1).replace(",", ".")}`).join(", ") : "");
    const bench = h("input", { type: "text", value: b ? b.benchmark : "SPY", style: { width: "120px" }, title: "benchmark symbol" });
    const save = async () => {
      const r = await api("/api/baskets", { method: "POST", body: { id: b ? b.id : null, name: name.value, members: members.value, benchmark: bench.value } });
      if (r.error) { toast("Basket not saved", r.error); return; }
      ctx.go("#/baskets/" + r.basket.id);
      loadList();
    };
    return section(b ? "Edit basket" : "New basket", name, members, h("div", { class: "toolbar" }, h("span", { class: "small muted" }, "benchmark"), bench,
      h("button", { onclick: save }, "Save")), note("Weights in percent; symbols without a weight share what is left of 100 (or all equal if no weight is given)."));
  };

  const loadList = async () => {
    const d = await api("/api/baskets", { fresh: true });
    clear(list, section("Your baskets", (d.baskets || []).length ? h("ul", { class: "feed" }, d.baskets.map((b) => h("li", { class: "click", onclick: () => ctx.go("#/baskets/" + b.id) },
      h("div", { class: "t" }, b.name), h("div", { class: "m" }, b.members.map((m) => m.symbol).join(", "))))) : note("No basket yet.")),
      form(null));
    return d;
  };

  const show = async (id) => {
    clear(view, loading("Loading prices…"));
    const d = await api(`/api/baskets/${encodeURIComponent(id)}`, { fresh: true });
    if (d.error) { clear(view, errorBox(d.error)); return; }
    const b = d.basket, r = d.returns || {}, br = d.benchmark_returns || {};
    const bm = new Map(d.benchmark_line.map(([day, v]) => [day, v]));
    clear(view,
      section(b.name,
        h("div", { class: "keystrip" }, PERIODS.map(([k, label]) => h("div", null, h("span", { class: "k" }, label),
          h("span", { class: "v " + dir(r[k]) }, pct(r[k], 1)), h("span", { class: "small muted" }, ` vs ${pct(br[k], 1)}`)))),
        lineChart(d.line.map(([day, v]) => ({ x: day, y: v })), { height: 240, ref: 100, area: false, fmtY: (v) => num(v, 1), fmtX: (x) => x,
          extra: [{ values: d.line.map(([day]) => bm.get(day) ?? null), label: `${b.benchmark} (benchmark)` }] }),
        table([
          { label: "Member", render: (m) => h("a", { href: "#/stock/" + encodeURIComponent(m.symbol) }, m.symbol + (m.missing ? " (no prices)" : "")) },
          { label: "Weight", num: true, render: (m) => pct(m.weight * 100, 1, false) },
          { label: "Last", num: true, render: (m) => price(m.last) },
          ...PERIODS.slice(0, 4).map(([k, label]) => ({ label, num: true, cls: (m) => dir(m[k]), render: (m) => pct(m[k], 1) })),
          { label: "1-month contribution", num: true, cls: (m) => dir(m.contrib_1m), render: (m) => (m.contrib_1m == null ? "–" : `${m.contrib_1m > 0 ? "+" : ""}${num(m.contrib_1m, 2)} pp`) },
        ], d.members),
        h("div", { class: "toolbar" }, h("a", { href: "#/hub/" + encodeURIComponent("basket:" + b.id) }, "in the data hub (early warnings)"),
          h("button", { class: "linkish", onclick: async () => { if (!confirm(`Delete basket ${b.name}?`)) return; await api(`/api/baskets/${b.id}`, { method: "DELETE" }); ctx.go("#/baskets"); } }, "delete")),
        note(d.note)),
      form(b));
    ctx.setContext({ page: `Basket ${b.name}`, basket: b, returns: r, benchmark_returns: br, members: d.members });
  };

  const d = await loadList();
  const id = params[0] || (d.baskets && d.baskets[0] && d.baskets[0].id);
  if (id) await show(id); else clear(view, note("Create a basket on the right - e.g. the stocks of a theme, your own sector, or a competitor group."));
}
