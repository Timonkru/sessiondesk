// Data hub: every series SessionDesk collects, with history, chart and CSV export, and the early warnings
// (a series moving unusually against its own past).
import { api, on } from "../lib/api.js";
import { lineChart } from "../lib/chart.js";
import { h, clear, table, section, num, dir, sparkline, stamp, note, loading, errorBox, ago, toast } from "../lib/ui.js";

export async function render(root, params, ctx) {
  const warnBox = h("div", null, loading()), listBox = h("div"), detail = h("div");
  const filter = h("input", { type: "search", placeholder: "filter series", style: { width: "200px" } });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Data hub"), h("span", { class: "meta" }, "everything collected, with history - and what is unusual"),
    h("button", { class: "linkish", onclick: async (e) => { e.target.textContent = "collecting…"; const r = await api("/api/hub/collect", { method: "POST" });
      e.target.textContent = "collect now"; toast("Data hub", r.error || `${Object.values(r.collected || {}).reduce((a, b) => a + b, 0)} series updated, ${r.warnings} unusual`); load(); } }, "collect now")),
    section("Early warnings (last 3 days)", warnBox), detail, section("All series", h("div", { class: "toolbar" }, filter), listBox));

  let data = null;
  const fmtChange = (s, v) => (v == null ? "–" : s.kind === "price" ? `${v > 0 ? "+" : ""}${num(v, 2)}%` : s.kind === "count" ? num(v, 0) : `${v > 0 ? "+" : ""}${num(v, Math.abs(v) < 1 ? 3 : 2)}`);

  const open = async (id) => {
    clear(detail, loading());
    const d = await api(`/api/hub/series/${encodeURIComponent(id)}`, { fresh: true });
    if (d.error) { clear(detail, errorBox(d.error)); return; }
    const pts = d.points.slice(-750);
    clear(detail, section(`${d.meta.name}`,
      lineChart(pts.map(([day, v]) => ({ x: day, y: v })), { height: 220, area: false, fmtY: (v) => num(v, Math.abs(v) < 10 ? 3 : 1), fmtX: (x) => x }),
      h("p", { class: "small" }, `${d.points.length} observations from ${d.points[0]?.[0] || "–"} · source: ${d.meta.source} · `,
        h("a", { href: `/api/hub/csv/${encodeURIComponent(id)}?t=${encodeURIComponent(document.querySelector('meta[name="sd-token"]').content)}` }, "download CSV"))));
    ctx.setContext({ page: `Data hub series ${d.meta.name}`, meta: d.meta, last_points: d.points.slice(-60) });
  };

  const drawList = () => {
    if (!data) return;
    const q = filter.value.trim().toLowerCase();
    const rows = data.series.filter((s) => !q || s.name.toLowerCase().includes(q) || (s.category || "").toLowerCase().includes(q));
    const cats = [...new Set(rows.map((s) => s.category))];
    clear(listBox, cats.map((c) => h("details", { open: !!q || cats.length < 4 }, h("summary", null, `${c} (${rows.filter((s) => s.category === c).length})`),
      table([
        { label: "Series", render: (s) => h("a", { href: "#", onclick: (e) => { e.preventDefault(); open(s.id); } }, s.name) },
        { label: "Last", num: true, render: (s) => num(s.last, Math.abs(s.last || 0) < 10 ? 3 : 2) },
        { label: "Change", num: true, cls: (s) => dir(s.change), render: (s) => fmtChange(s, s.change) },
        { label: "z", num: true, cls: (s) => (s.z != null && Math.abs(s.z) >= data.z_warn ? "warn" : ""), render: (s) => (s.z == null ? "–" : num(s.z, 1)) },
        { label: "Trend", num: true, render: (s) => sparkline(s.spark) },
        { label: "Date", render: (s) => h("span", { class: "muted small" }, s.day || "") },
        { label: "Obs.", num: true, render: (s) => s.n },
      ], rows.filter((s) => s.category === c)))),
      rows.length ? null : note(data.series.length ? "No series matches." : "Nothing collected yet - the collectors start a few minutes after launch, or press 'collect now'."));
  };

  const load = async () => {
    data = await api("/api/hub", { fresh: true });
    if (data.error) { clear(warnBox, errorBox(data.error)); return; }
    clear(warnBox, (data.warnings || []).length ? h("ul", { class: "feed" }, data.warnings.map((w) => h("li", { class: "click", onclick: () => open(w.symbol) },
      h("div", { class: "t warn" }, w.title), h("div", { class: "m" }, `${stamp(w.ts)} · ${w.body}`)))) : note("Nothing unusual in the last three days."),
      note(data.note));
    drawList();
    ctx.setContext({ page: "Data hub", warnings: (data.warnings || []).map((w) => ({ title: w.title, body: w.body, when: new Date(w.ts * 1000).toISOString() })),
      series: data.series.map((s) => ({ name: s.name, category: s.category, last: s.last, change: s.change, z: s.z, day: s.day })) });
  };
  filter.addEventListener("input", drawList);
  await load();
  if (params[0]) open(params[0]);
  const off = on("hub_warning", load);
  return () => off();
}
