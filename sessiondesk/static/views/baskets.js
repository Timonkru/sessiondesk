// Baskets: your own sets of symbols, followed like an index against a benchmark.
import { api } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, pct, price, dir, note, loading, errorBox, toast } from "../lib/ui.js";

const PERIODS = [["1d", "1 day"], ["1w", "1 week"], ["1m", "1 month"], ["3m", "3 months"], ["ytd", "YTD"], ["1y", "1 year"]];

export async function render(root, params, ctx) {
  const list = h("div"), view = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Baskets"), h("span", { class: "meta" }, "your own sets of stocks, followed like an index")),
    h("div", { class: "cols" }, view, list));

  // Editor: search with clickable suggestions, one row per member with its weight, remove per row.
  const form = (b) => {
    const rows = (b ? b.members : []).map((m) => ({ symbol: m.symbol, name: m.name || "", weight: b.members.every((x) => Math.abs(x.weight - b.members[0].weight) < 1e-9) ? "" : num(m.weight * 100, 1).replace(",", ".") }));
    const name = h("input", { type: "text", placeholder: "name, e.g. AI leaders", value: b ? b.name : "", style: { width: "100%" } });
    const bench = h("input", { type: "text", value: b ? b.benchmark : "SPY", style: { width: "110px" }, title: "benchmark symbol, e.g. SPY, QQQ, ^GDAXI, EXV3.DE" });
    const search = h("input", { type: "search", placeholder: "add a stock: type a name or symbol", style: { width: "100%" }, autocomplete: "off" });
    const sugg = h("ul", { class: "suggest", hidden: true });
    const tbl = h("div"), info = h("p", { class: "small muted" });
    const add = (it) => {
      if (!it || rows.some((r) => r.symbol === it.symbol)) { search.value = ""; sugg.hidden = true; return; }
      rows.push({ symbol: it.symbol, name: it.name || "", weight: "" });
      search.value = ""; sugg.hidden = true; draw(); search.focus();
    };
    const effective = () => {                     // same rule as the server: given weights, the rest shared by the blanks
      const given = rows.filter((r) => r.weight !== "" && !isNaN(parseFloat(r.weight)));
      const sum = given.reduce((a, r) => a + parseFloat(r.weight), 0), blanks = rows.length - given.length;
      const each = blanks ? (sum < 100 ? (100 - sum) / blanks : (given.length ? sum / given.length : 100 / blanks)) : 0;
      const raw = rows.map((r) => (r.weight !== "" && !isNaN(parseFloat(r.weight)) ? parseFloat(r.weight) : each));
      const tot = raw.reduce((a, x) => a + x, 0) || 1;
      return raw.map((x) => (x / tot) * 100);
    };
    let effCells = [];
    const refresh = () => { const eff = effective(); effCells.forEach((c, i) => { c.textContent = pct(eff[i], 1, false); }); info.textContent = summary(eff); };
    const draw = () => {
      const eff = effective();
      effCells = rows.map((_, i) => h("span", { class: "small muted" }, pct(eff[i], 1, false)));
      clear(tbl, rows.length ? table([
        { label: "Symbol", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol), target: "_blank" }, r.symbol) },
        { label: "Name", render: (r) => h("span", { class: "small" }, r.name) },
        { label: "Weight %", num: true, render: (r) => h("input", { type: "text", value: r.weight, placeholder: "auto", style: { width: "64px", textAlign: "right" },
          oninput: (e) => { r.weight = e.target.value.trim().replace(",", "."); refresh(); } }) },
        { label: "Effective", num: true, render: (r) => effCells[rows.indexOf(r)] },
        { label: "", render: (r) => h("button", { class: "linkish", title: "remove", onclick: () => { rows.splice(rows.indexOf(r), 1); draw(); } }, "✕") },
      ], rows) : note("No stocks yet - search above and click a suggestion."));
      info.textContent = summary(eff);
    };
    const summary = (eff) => rows.length ? `${rows.length} stocks · weights left empty share what is left of 100 % (effective weights are recalculated on save)` : "";
    let timer, last = [];
    search.addEventListener("input", () => {
      clearTimeout(timer);
      const q = search.value.trim();
      if (q.length < 1) { sugg.hidden = true; return; }
      timer = setTimeout(async () => {
        const d = await api("/api/search?q=" + encodeURIComponent(q), { ttl: 60000 });
        const seen = new Map();
        for (const it of d.items || []) {
          if (!["EQUITY", "ETF"].includes(it.type) && !(it.symbol || "").startsWith("^")) continue;
          const prev = seen.get(it.symbol);
          if (prev) { if (it.exchange && !prev.where.includes(it.exchange)) prev.where.push(it.exchange); }
          else seen.set(it.symbol, { ...it, where: it.exchange ? [it.exchange] : [] });
        }
        last = [...seen.values()].slice(0, 8);
        clear(sugg, last.length ? last.map((it) => h("li", { class: rows.some((r) => r.symbol === it.symbol) ? "muted" : "click", onmousedown: (e) => { e.preventDefault(); add(it); } },
          h("strong", null, it.symbol), " ", it.name || "", h("span", { class: "small muted" }, it.where.length ? " · " + it.where.join(", ") : "")))
          : h("li", { class: "muted" }, "no match"));
        sugg.hidden = false;
      }, 200);
    });
    search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); add(last[0] || (search.value.trim() ? { symbol: search.value.trim().toUpperCase(), name: "" } : null)); }
      if (e.key === "Escape") sugg.hidden = true;
    });
    search.addEventListener("blur", () => setTimeout(() => { sugg.hidden = true; }, 150));
    const save = async () => {
      if (!rows.length) { toast("Basket not saved", "add at least one stock"); return; }
      const members = rows.map((r) => (r.weight !== "" && !isNaN(parseFloat(r.weight)) ? `${r.symbol} ${parseFloat(r.weight)}` : r.symbol)).join(", ");
      const r = await api("/api/baskets", { method: "POST", body: { id: b ? b.id : null, name: name.value, members, benchmark: bench.value } });
      if (r.error) { toast("Basket not saved", r.error); return; }
      ctx.go("#/baskets/" + r.basket.id);
      loadList();
      show(r.basket.id);
    };
    draw();
    return section(b ? `Edit "${b.name}"` : "New basket", name,
      h("div", { class: "suggestwrap" }, search, sugg), tbl, info,
      h("div", { class: "toolbar" }, h("span", { class: "small muted" }, "benchmark"), bench, h("button", { onclick: save }, b ? "Save changes" : "Create basket"),
        b ? h("button", { class: "linkish", onclick: () => show(b.id) }, "cancel") : null));
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
          { label: "Name", render: (m) => h("span", { class: "small" }, m.name || "") },
          { label: "Weight", num: true, render: (m) => pct(m.weight * 100, 1, false) },
          { label: "Last", num: true, render: (m) => price(m.last) },
          ...PERIODS.slice(0, 4).map(([k, label]) => ({ label, num: true, cls: (m) => dir(m[k]), render: (m) => pct(m[k], 1) })),
          { label: "1-month contribution", num: true, cls: (m) => dir(m.contrib_1m), render: (m) => (m.contrib_1m == null ? "–" : `${m.contrib_1m > 0 ? "+" : ""}${num(m.contrib_1m, 2)} pp`) },
        ], d.members),
        h("div", { class: "toolbar" }, h("button", { onclick: () => clear(view, form({ ...b, members: b.members.map((m) => ({ ...m, name: (d.members.find((x) => x.symbol === m.symbol) || {}).name || "" })) })) }, "Edit basket"),
          h("a", { href: "#/hub/" + encodeURIComponent("basket:" + b.id) }, "in the data hub (early warnings)"),
          h("button", { class: "linkish", onclick: async () => { if (!confirm(`Delete basket ${b.name}?`)) return; await api(`/api/baskets/${b.id}`, { method: "DELETE" }); ctx.go("#/baskets"); } }, "delete")),
        note(d.note)));
    ctx.setContext({ page: `Basket ${b.name}`, basket: b, returns: r, benchmark_returns: br, members: d.members });
  };

  const d = await loadList();
  const id = params[0] || (d.baskets && d.baskets[0] && d.baskets[0].id);
  if (id) await show(id); else clear(view, note("Create a basket on the right - e.g. the stocks of a theme, your own sector, or a competitor group."));
}
