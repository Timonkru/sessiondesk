// System: is every part doing its job? Problems first, then loops, connectors, exporters, jobs, extensions, files.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, note, loading, errorBox, big } from "../lib/ui.js";

const dur = (s) => (s === null || s === undefined ? "–" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} d`);
const STATE = { ok: "up", error: "down", stuck: "down", late: "warn", waiting: "muted", unused: "muted" };
const badge = (s) => h("span", { class: STATE[s] || "" }, s);

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "System"), h("span", { class: "meta" }, "sources, background work, exporters, jobs")), body);

  const load = async () => {
    const d = await api("/api/system", { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    const a = d.app;
    clear(body,
      section(`Problems (${d.counts.error} errors, ${d.counts.warn} warnings)`, d.issues.length
        ? h("ul", { class: "feed" }, d.issues.map((i) => h("li", null, h("div", { class: "t " + (i.level === "error" ? "down" : "warn") }, i.text),
            h("div", { class: "m" }, `${i.level} · ${i.area}`))))
        : note("Nothing to report.")),
      h("div", { class: "cols" },
        h("div", null,
          section("Background loops", table([
            { label: "Loop", render: (l) => l.name }, { label: "State", render: (l) => badge(l.state) },
            { label: "Every", num: true, render: (l) => dur(l.interval) }, { label: "Last OK", num: true, render: (l) => (l.last_ok_ago == null ? "–" : dur(l.last_ok_ago) + " ago") },
            { label: "Took", num: true, render: (l) => (l.duration == null ? "–" : `${l.duration.toFixed(1)} s`) },
            { label: "Runs / errors", num: true, render: (l) => `${l.runs} / ${l.errors}` },
          ], d.loops, { empty: "No background loops (started with --no-background?)." })),
          section("Connectors in use", table([
            { label: "Source", render: (c) => h("span", null, c.name, c.verified ? "" : h("span", { class: "muted small" }, " · unverified")) },
            { label: "State", render: (c) => badge(c.state) }, { label: "OK / errors", num: true, render: (c) => `${c.ok} / ${c.errors}` },
            { label: "Last OK", num: true, render: (c) => (c.last_ok_ago == null ? "–" : dur(c.last_ok_ago) + " ago") },
            { label: "Last error", render: (c) => (c.last_error ? h("span", { class: "small muted", title: c.last_error }, `${dur(c.last_error_ago)} ago: ${c.last_error.slice(0, 80)}`) : "") },
          ], d.connectors, { empty: "No active connector." })),
          note("Counts start with this run of the app. A connector stays 'unused' until a page or loop asked it for data.")),
        h("div", null,
          section("Broker exporters", table([
            { label: "Account", render: (x) => x.account }, { label: "Exporter", render: (x) => h("span", { class: "small muted" }, x.bridge || "–") },
            { label: "Age", num: true, render: (x) => h("span", { class: x.fresh ? "up" : "warn" }, dur(x.age)) },
          ], d.exporters, { empty: "No broker connected." })),
          section("Jobs", table([
            { label: "Job", render: (j) => j.name }, { label: "Status", render: (j) => h("span", { class: j.status === "failed" ? "down" : j.running ? "up" : "muted" }, j.running ? "running" : j.status) },
            { label: "Last end", num: true, render: (j) => (j.last_end_ago == null ? "–" : dur(j.last_end_ago) + " ago") },
          ], d.jobs, { empty: "No jobs." })),
          section("Extensions", table([{ label: "Page", render: (e) => e.title }, { label: "Status", render: (e) => h("span", { class: e.error ? "down" : "up" }, e.error || "loaded") }],
            d.extensions, { empty: "None." })),
          section("Level files", table([{ label: "File", render: (f) => f.title }, { label: "Age", num: true, render: (f) => (f.age_h == null ? "–" : h("span", { class: f.fresh ? "up" : "warn" }, `${num(f.age_h, 1)} h`)) }],
            d.level_files, { empty: "None registered." })),
          section("App", h("dl", { class: "kv" },
            [["Version", a.version], ["Python", a.python], ["Platform", a.platform], ["Uptime", dur(a.uptime)],
            ["AI", d.ai.ready ? `${d.ai.provider || "default"} configured (a key is set; credit is not checked)` : "no key / provider"], ["Live clients", a.stream_clients],
            ["News archive", num(a.news_archive, 0) + " headlines"], ["Database", big(a.db_bytes) + "B"], ["Cache", big(a.cache_bytes) + "B"],
            ["Data folder", a.data_dir]].flatMap(([k, v]) => [h("dt", null, k), h("dd", null, String(v))])),
            h("div", { class: "toolbar" }, h("button", { onclick: async (e) => {
              if (!confirm("Stop SessionDesk? Background loops, alerts and running jobs end until you start it again.")) return;
              const r = await api("/api/shutdown", { method: "POST" });
              e.target.textContent = r.error ? r.error : "stopped - you can close this window";
              e.target.disabled = true;
            } }, "Stop SessionDesk"))))));
    ctx.setContext({ page: "System status", issues: d.issues, loops: d.loops, connectors: d.connectors, exporters: d.exporters, jobs: d.jobs, app: a });
    window.dispatchEvent(new CustomEvent("sd:system", { detail: d.counts }));
  };
  await load();
  const t = setInterval(load, 30000);
  return () => clearInterval(t);
}
