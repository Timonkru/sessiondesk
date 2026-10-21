// Data hub: every series SessionDesk collects, grouped by asset class (tabs) and category, with the chosen series'
// chart, facts, source and CSV beside the list, the early warnings (a series moving unusually against its own past),
// and a comparison of up to six series on one chart. The grouping comes from the server (datahub.layout).
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
  const tabsBox = h("div", { class: "tabs" }), warnBox = h("div"), compareBox = h("div"), listBox = h("div", { class: "hublist" }, loading("Loading all series…")), detail = h("div", { class: "hubdetail" });
  let picked = [];
  try { picked = JSON.parse(localStorage.getItem("sd.hubCompare") || "[]").slice(0, MAX_COMPARE); } catch { picked = []; }
  let cmpRange = "3y", cmpMode = "rebased", group = localStorage.getItem("sd.hubGroup") || "", current = null, showAllWarn = false;
  const filter = h("input", { type: "search", placeholder: "search all series", style: { width: "220px" } });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Data hub"), h("span", { class: "meta" }, "every series SessionDesk collects, by asset class - with history, CSV and what is unusual"),
    h("button", { class: "linkish", onclick: async (e) => { e.target.textContent = "collecting…"; const r = await api("/api/hub/collect", { method: "POST" });
      e.target.textContent = "collect now"; toast("Data hub", r.error || `${Object.values(r.collected || {}).reduce((a, b) => a + b, 0)} series updated, ${r.warnings} unusual`); load(); } }, "collect now")),
    h("div", { class: "toolbar" }, tabsBox, h("span", { style: { flex: "1" } }), filter), warnBox, compareBox,
    h("div", { class: "hubgrid" }, listBox, detail));

  let data = null, byId = new Map();
  const fmtChange = (s, v) => (v == null ? "–" : s.kind === "price" ? `${v > 0 ? "+" : ""}${num(v, 2)}%` : s.kind === "count" ? num(v, 0) : `${v > 0 ? "+" : ""}${num(v, Math.abs(v) < 1 ? 3 : 2)}`);
  const groupOf = (id) => (byId.get(id) || {}).group;

  // ---- one series: chart, facts, source, CSV - beside the list (above it on a narrow screen)
  const open = async (id, { switchGroup = true } = {}) => {
    current = id;
    if (switchGroup && groupOf(id) && groupOf(id) !== group && !filter.value.trim()) { group = groupOf(id); drawTabs(); drawList(); }
    listBox.querySelectorAll("tr.on").forEach((r) => r.classList.remove("on"));
    const row = listBox.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
    if (row) row.classList.add("on");
    clear(detail, loading());
    const d = await api(`/api/hub/series/${encodeURIComponent(id)}`, { fresh: true });
    if (current !== id) return;
    if (d.error) { clear(detail, errorBox(d.error)); return; }
    const s = byId.get(id) || {};
    let range = localStorage.getItem("sd.hubRange") || "3y";
    const chartBox = h("div");
    const drawChart = () => {
      const years = RANGES.find((r) => r[0] === range)[1];
      const start = years ? new Date(Date.now() - years * 365.25 * 86400000).toISOString().slice(0, 10) : "0000";
      const pts = d.points.filter(([day]) => day >= start);
      clear(chartBox, h("span", { class: "tabs inline" }, RANGES.map(([k]) => h("button", { class: k === range ? "on" : "", onclick: () => {
        range = k; try { localStorage.setItem("sd.hubRange", k); } catch { /* storage blocked */ } drawChart(); } }, k))),
      lineChart(pts.map(([day, v]) => ({ x: day, y: v })), { height: 300, area: false, fmtY: (v) => num(v, Math.abs(v) < 10 ? 3 : 1), fmtX: (x) => x }));
    };
    drawChart();
    const inCompare = picked.includes(id);
    clear(detail, h("h2", null, d.meta.name),
      h("p", { class: "small muted" }, `${s.shown_category || d.meta.category || ""}`),
      h("div", { class: "kpis" },
        h("div", null, h("div", { class: "small muted" }, "Last"), h("strong", null, num(s.last, Math.abs(s.last || 0) < 10 ? 3 : 2)), h("div", { class: "small muted" }, s.day || "")),
        h("div", null, h("div", { class: "small muted" }, "Change"), h("strong", { class: dir(s.change) }, fmtChange(s, s.change))),
        h("div", null, h("div", { class: "small muted" }, "z vs own history"), h("strong", { class: s.z != null && Math.abs(s.z) >= data.z_warn ? "warn" : "" }, s.z == null ? "–" : num(s.z, 1)))),
      chartBox,
      h("p", { class: "small" }, `${d.points.length} observations from ${d.points[0]?.[0] || "–"} · source: `,
        d.meta.url ? h("a", { href: d.meta.url, ...(d.meta.url.startsWith("#") ? {} : { target: "_blank", rel: "noopener noreferrer" }) }, d.meta.source) : d.meta.source),
      h("div", { class: "toolbar" },
        h("a", { href: `/api/hub/csv/${encodeURIComponent(id)}?t=${encodeURIComponent(document.querySelector('meta[name="sd-token"]').content)}` }, "download CSV"),
        h("button", { class: "linkish", disabled: !inCompare && picked.length >= MAX_COMPARE, onclick: () => togglePick(id, !inCompare) }, inCompare ? "remove from compare" : "+ compare"),
        h("span", { class: "small muted", title: "use this id in a My desk tile, an alert or /api/v1" }, "id ", h("code", null, id))));
    ctx.setContext({ page: `Data hub series ${d.meta.name}`, meta: d.meta, last_points: d.points.slice(-60) });
  };

  const savePicked = () => { try { localStorage.setItem("sd.hubCompare", JSON.stringify(picked)); } catch { /* storage blocked */ } };
  const togglePick = (id, on) => {
    picked = on ? [...new Set([...picked, id])].slice(0, MAX_COMPARE) : picked.filter((x) => x !== id);
    savePicked(); drawCompare(); drawList();
    if (current === id) open(id, { switchGroup: false });
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
    clear(compareBox, section(`Compare (${series.length} of ${MAX_COMPARE})`,
      h("div", { class: "toolbar" }, buttons(MODES, cmpMode, (k) => { cmpMode = k; }), buttons(RANGES.map(([k]) => [k]), cmpRange, (k) => { cmpRange = k; }),
        h("button", { class: "linkish", onclick: csv }, "CSV (raw, aligned)"), h("button", { class: "linkish", onclick: () => { picked = []; savePicked(); drawCompare(); drawList(); } }, "clear")),
      multiChart(days, lines, { height: 280, fmtY: (v) => num(v, cmpMode === "z" ? 1 : Math.abs(v) < 10 ? 2 : 1) }),
      skipped.length ? note(`Not shown ${cmpMode === "rebased" ? "rebased (needs a positive first value)" : "(no variation)"}: ${skipped.join(", ")} - switch to standardized or raw.`, "warn") : null,
      note((cmpMode === "rebased" ? "Each series = 100 on the first date of the window. " : cmpMode === "z" ? "Each series in standard deviations from its own mean over the window. " : "Raw values - only meaningful for series in the same unit. ")
        + "Weekly and monthly series keep their last value until the next print. Sources: " + [...new Set(series.map((s) => s.source))].join(", ") + ".")));
    ctx.setContext({ page: "Data hub compare", mode: cmpMode, range: cmpRange, series: series.map((s, i) => ({ name: s.name, first: values[i].find((v) => v != null), last: values[i][values[i].length - 1] })) });
  };

  // ---- asset-class tabs; a warning count marks the groups with something unusual
  const warnGroups = () => {
    const m = {};
    for (const w of data.warnings || []) { const g = groupOf(w.symbol); if (g) m[g] = (m[g] || 0) + 1; }
    return m;
  };
  const drawTabs = () => {
    const wg = warnGroups();
    clear(tabsBox, data.groups.map((g) => h("button", { class: g.key === group && !filter.value.trim() ? "on" : "", onclick: () => {
      group = g.key; filter.value = ""; try { localStorage.setItem("sd.hubGroup", group); } catch { /* storage blocked */ }
      drawTabs(); drawList(); const first = g.categories[0].ids[0]; if (first) open(first, { switchGroup: false });
    } }, g.label, " ", h("span", { class: "muted small" }, String(g.categories.reduce((a, c) => a + c.ids.length, 0))),
      wg[g.key] ? h("span", { class: "hubwarn", title: `${wg[g.key]} unusual in the last 3 days` }, String(wg[g.key])) : null)));
  };

  const drawWarnings = () => {
    const ws = data.warnings || [];
    if (!ws.length) { clear(warnBox); return; }
    const shown = showAllWarn ? ws : ws.slice(0, 4);
    clear(warnBox, h("div", { class: "hubwarnings" }, h("strong", { class: "small" }, `Unusual in the last 3 days (${ws.length})`),
      h("ul", { class: "feed compact" }, shown.map((w) => h("li", { class: "click", onclick: () => open(w.symbol) },
        h("div", { class: "t warn" }, w.title), h("div", { class: "m" }, `${stamp(w.ts)} · ${w.body}`)))),
      ws.length > 4 ? h("button", { class: "linkish small", onclick: () => { showAllWarn = !showAllWarn; drawWarnings(); } }, showAllWarn ? "fewer" : `all ${ws.length}`) : null,
      h("p", { class: "small muted" }, data.note)));
  };

  const seriesTable = (rows) => table([
    { label: "", render: (s) => h("input", { type: "checkbox", title: "compare", checked: picked.includes(s.id), disabled: !picked.includes(s.id) && picked.length >= MAX_COMPARE,
      onclick: (e) => e.stopPropagation(), onchange: (e) => togglePick(s.id, e.target.checked) }) },
    { label: "Series", render: (s) => s.name },
    { label: "Last", num: true, render: (s) => num(s.last, Math.abs(s.last || 0) < 10 ? 3 : 2) },
    { label: "Change", num: true, cls: (s) => dir(s.change), render: (s) => fmtChange(s, s.change) },
    { label: "z", num: true, cls: (s) => (s.z != null && Math.abs(s.z) >= data.z_warn ? "warn" : ""), render: (s) => (s.z == null ? "–" : num(s.z, 1)) },
    { label: "Trend", num: true, render: (s) => sparkline(s.spark) },
    { label: "Date", render: (s) => h("span", { class: "muted small" }, s.day || "") },
  ], rows);
  const clickable = (tbl, rows) => {
    tbl.querySelectorAll("tbody tr").forEach((tr, i) => {
      if (!rows[i]) return;
      tr.dataset.id = rows[i].id;
      tr.classList.add("click");
      if (rows[i].id === current) tr.classList.add("on");
      tr.addEventListener("click", () => open(rows[i].id, { switchGroup: false }));
    });
    return tbl;
  };

  const drawList = () => {
    if (!data) return;
    const q = filter.value.trim().toLowerCase();
    if (q) {
      const hits = data.series.filter((s) => s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q) || (s.shown_category || "").toLowerCase().includes(q));
      const cats = [...new Set(hits.map((s) => s.shown_category))];
      clear(listBox, hits.length ? cats.map((c) => { const rows = hits.filter((s) => s.shown_category === c); return section(c, clickable(seriesTable(rows), rows)); })
        : note("No series matches."));
      return;
    }
    const g = data.groups.find((x) => x.key === group) || data.groups[0];
    if (!g) { clear(listBox, note("Nothing collected yet - the collectors start a few minutes after launch, or press 'collect now'.")); return; }
    group = g.key;
    clear(listBox, g.categories.map((c) => { const rows = c.ids.map((id) => byId.get(id)).filter(Boolean); return section(c.name, clickable(seriesTable(rows), rows)); }));
  };

  const load = async () => {
    data = await api("/api/hub", { fresh: true });
    if (data.error) { clear(listBox, errorBox(data.error)); return; }
    byId = new Map(data.series.map((s) => [s.id, s]));
    if (!data.groups.some((g) => g.key === group)) group = (data.groups[0] || {}).key || "";
    drawTabs(); drawWarnings(); drawList();
    ctx.setContext({ page: "Data hub", warnings: (data.warnings || []).map((w) => ({ title: w.title, body: w.body, when: new Date(w.ts * 1000).toISOString() })),
      series: data.series.filter((s) => !s.duplicate_of).map((s) => ({ name: s.name, category: s.shown_category, last: s.last, change: s.change, z: s.z, day: s.day })) });
  };
  filter.addEventListener("input", () => { drawTabs(); drawList(); });
  await load();
  drawCompare();
  const start = params[0] ? decodeURIComponent(params[0]) : (((data.groups || []).find((g) => g.key === group) || {}).categories || [{ ids: [] }])[0].ids[0];
  if (start) open(start);
  const off = on("hub_warning", load);
  return () => off();
}
