// Data hub: every series SessionDesk collects, with history, chart and CSV export, the early warnings
// (a series moving unusually against its own past), and a comparison of up to six series on one chart.
import { api, on } from "../lib/api.js";
import { lineChart, multiChart } from "../lib/chart.js";
import { h, clear, table, tableCsv, section, num, dir, sparkline, stamp, note, loading, errorBox, ago, toast } from "../lib/ui.js";

const MAX_COMPARE = 6;
const RANGES = [["1y", 1], ["3y", 3], ["5y", 5], ["max", 0]];
const MODES = [["rebased", "Rebased to 100"], ["z", "Standardized (z)"], ["raw", "Raw values"]];

// Align series on the union of their dates; a weekly series keeps its last value until the next print.
function align(series, start) {
  const days = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort();
  return {
    days: days.filter((d) => d >= start),
    values: series.map((s) => {
      let k = -1, last = null;
      const out = [];
      for (const d of days) {
        while (k + 1 < s.points.length && s.points[k + 1][0] <= d) { k += 1; last = s.points[k][1]; }
        if (d >= start) out.push(last);
      }
      return out;
    }),
  };
}

function transform(values, mode) {
  const vals = values.filter((v) => v != null);
  if (mode === "rebased") {
    const base = vals[0];
    return base > 0 ? values.map((v) => (v == null ? null : (v / base) * 100)) : null;   // rebasing needs a positive start
  }
  if (mode === "z") {
    const m = vals.reduce((a, b) => a + b, 0) / (vals.length || 1);
    const sd = Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, vals.length - 1));
    return sd ? values.map((v) => (v == null ? null : (v - m) / sd)) : null;
  }
  return values;
}

export async function render(root, params, ctx) {
  const warnBox = h("div", null, loading()), listBox = h("div"), detail = h("div"), compareBox = h("div");
  let picked = [];
  try { picked = JSON.parse(localStorage.getItem("sd.hubCompare") || "[]").slice(0, MAX_COMPARE); } catch { picked = []; }
  let cmpRange = "3y", cmpMode = "rebased";
  const filter = h("input", { type: "search", placeholder: "filter series", style: { width: "200px" } });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Data hub"), h("span", { class: "meta" }, "everything collected, with history - and what is unusual"),
    h("button", { class: "linkish", onclick: async (e) => { e.target.textContent = "collecting…"; const r = await api("/api/hub/collect", { method: "POST" });
      e.target.textContent = "collect now"; toast("Data hub", r.error || `${Object.values(r.collected || {}).reduce((a, b) => a + b, 0)} series updated, ${r.warnings} unusual`); load(); } }, "collect now")),
    section("Early warnings (last 3 days)", warnBox), compareBox, detail,
    section("All series", h("div", { class: "toolbar" }, filter, h("span", { class: "small muted" }, `tick up to ${MAX_COMPARE} series to compare them on one chart`)), listBox));

  let data = null;
  const fmtChange = (s, v) => (v == null ? "–" : s.kind === "price" ? `${v > 0 ? "+" : ""}${num(v, 2)}%` : s.kind === "count" ? num(v, 0) : `${v > 0 ? "+" : ""}${num(v, Math.abs(v) < 1 ? 3 : 2)}`);

  const open = async (id) => {
    clear(detail, loading());
    const d = await api(`/api/hub/series/${encodeURIComponent(id)}`, { fresh: true });
    if (d.error) { clear(detail, errorBox(d.error)); return; }
    const pts = d.points.slice(-750);
    clear(detail, section(`${d.meta.name}`,
      lineChart(pts.map(([day, v]) => ({ x: day, y: v })), { height: 220, area: false, fmtY: (v) => num(v, Math.abs(v) < 10 ? 3 : 1), fmtX: (x) => x }),
      h("p", { class: "small" }, `${d.points.length} observations from ${d.points[0]?.[0] || "–"} · source: `,
        d.meta.url ? h("a", { href: d.meta.url, ...(d.meta.url.startsWith("#") ? {} : { target: "_blank", rel: "noopener noreferrer" }) }, d.meta.source) : d.meta.source, " · ",
        h("a", { href: `/api/hub/csv/${encodeURIComponent(id)}?t=${encodeURIComponent(document.querySelector('meta[name="sd-token"]').content)}` }, "download CSV"))));
    ctx.setContext({ page: `Data hub series ${d.meta.name}`, meta: d.meta, last_points: d.points.slice(-60) });
  };

  const savePicked = () => { try { localStorage.setItem("sd.hubCompare", JSON.stringify(picked)); } catch { /* storage blocked */ } };
  const togglePick = (id, on) => {
    picked = on ? [...new Set([...picked, id])].slice(0, MAX_COMPARE) : picked.filter((x) => x !== id);
    savePicked(); drawCompare(); drawList();
  };
  let gen = 0;                                  // a newer draw supersedes one still loading
  const drawCompare = async () => {
    const mine = ++gen;
    if (!picked.length) { clear(compareBox); return; }
    if (!compareBox.childElementCount) clear(compareBox, section("Compare", loading()));
    const got = await Promise.all(picked.map((id) => api(`/api/hub/series/${encodeURIComponent(id)}`, { ttl: 300000 })));
    if (mine !== gen) return;
    const series = got.filter((d) => !d.error).map((d) => ({ id: d.meta.id, name: d.meta.name, source: d.meta.source, points: d.points }));
    const years = RANGES.find((r) => r[0] === cmpRange)[1];
    const start = years ? new Date(Date.now() - years * 365.25 * 86400000).toISOString().slice(0, 10) : "0000";
    const { days, values } = align(series, start);
    const lines = [], skipped = [];
    series.forEach((s, i) => { const v = transform(values[i], cmpMode); if (v) lines.push({ label: s.name, values: v }); else skipped.push(s.name); });
    const buttons = (opts, cur, set) => h("span", { class: "tabs inline" }, opts.map(([k, label]) => h("button", { class: k === cur ? "on" : "", onclick: () => { set(k); drawCompare(); } }, label || k)));
    const csv = () => {
      const t = h("table", null, h("tr", null, h("td", null, "date"), series.map((s) => h("td", null, s.name))),
        days.map((d, i) => h("tr", null, h("td", null, d), values.map((v) => h("td", null, v[i] == null ? "" : String(v[i]))))));
      tableCsv(t, "datahub_compare");
    };
    clear(compareBox, section(`Compare (${series.length})`,
      h("div", { class: "toolbar" }, buttons(MODES, cmpMode, (k) => { cmpMode = k; }), buttons(RANGES.map(([k]) => [k]), cmpRange, (k) => { cmpRange = k; }),
        h("button", { class: "linkish", onclick: csv }, "CSV (raw, aligned)"), h("button", { class: "linkish", onclick: () => { picked = []; savePicked(); drawCompare(); drawList(); } }, "clear")),
      multiChart(days, lines, { height: 300, fmtY: (v) => num(v, cmpMode === "z" ? 1 : Math.abs(v) < 10 ? 2 : 1) }),
      skipped.length ? note(`Not shown ${cmpMode === "rebased" ? "rebased (needs a positive first value)" : "(no variation)"}: ${skipped.join(", ")} - switch to standardized or raw.`, "warn") : null,
      note((cmpMode === "rebased" ? "Each series = 100 on the first date of the window. " : cmpMode === "z" ? "Each series in standard deviations from its own mean over the window. " : "Raw values - only meaningful for series in the same unit. ")
        + "Weekly and monthly series keep their last value until the next print. Sources: " + [...new Set(series.map((s) => s.source))].join(", ") + ".")));
    ctx.setContext({ page: "Data hub compare", mode: cmpMode, range: cmpRange, series: series.map((s, i) => ({ name: s.name, first: values[i].find((v) => v != null), last: values[i][values[i].length - 1] })) });
  };

  const drawList = () => {
    if (!data) return;
    const q = filter.value.trim().toLowerCase();
    const rows = data.series.filter((s) => !q || s.name.toLowerCase().includes(q) || (s.category || "").toLowerCase().includes(q));
    const cats = [...new Set(rows.map((s) => s.category))];
    clear(listBox, cats.map((c) => h("details", { open: !!q || cats.length < 4 }, h("summary", null, `${c} (${rows.filter((s) => s.category === c).length})`),
      table([
        { label: "", render: (s) => h("input", { type: "checkbox", title: "compare", checked: picked.includes(s.id), disabled: !picked.includes(s.id) && picked.length >= MAX_COMPARE,
          onchange: (e) => togglePick(s.id, e.target.checked) }) },
        { label: "Series", render: (s) => h("a", { href: "#", onclick: (e) => { e.preventDefault(); open(s.id); } }, s.name) },
        { label: "Last", num: true, render: (s) => num(s.last, Math.abs(s.last || 0) < 10 ? 3 : 2) },
        { label: "Change", num: true, cls: (s) => dir(s.change), render: (s) => fmtChange(s, s.change) },
        { label: "z", num: true, cls: (s) => (s.z != null && Math.abs(s.z) >= data.z_warn ? "warn" : ""), render: (s) => (s.z == null ? "–" : num(s.z, 1)) },
        { label: "Trend", num: true, render: (s) => sparkline(s.spark) },
        { label: "Date", render: (s) => h("span", { class: "muted small" }, s.day || "") },
        { label: "Source", render: (s) => (s.url ? h("a", { class: "small", href: s.url, title: s.source, ...(s.url.startsWith("#") ? {} : { target: "_blank", rel: "noopener noreferrer" }) }, "↗") : "") },
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
  drawCompare();
  if (params[0]) open(params[0]);
  const off = on("hub_warning", load);
  return () => off();
}
