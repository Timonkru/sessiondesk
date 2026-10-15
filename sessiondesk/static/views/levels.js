// Levels: live ladder (nearest levels above/below each price) + level alert history + level file freshness.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, price, pct, num, dir, stamp, note, loading, errorBox } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Levels"), h("span", { class: "meta" }, "gamma / file levels, round numbers, previous day and overnight range")), body);
  const lvl = (x) => h("span", { title: `${x.label} (${x.src})` }, h("span", { class: "small muted" }, x.label + " "), price(x.level),
    h("span", { class: "small " + (x.dist > 0 ? "up" : "down") }, ` ${x.dist > 0 ? "+" : ""}${num(x.dist, Math.abs(x.dist) < 10 ? 2 : 0)} (${pct(x.dist_pct, 2)})`));
  const load = async () => {
    const d = await api("/api/levels", { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    clear(body,
      section("Ladder", table([
        { label: "Market", render: (r) => h("span", null, h("strong", null, r.asset), h("span", { class: "muted small" }, " " + r.symbol)) },
        { label: "Price", num: true, render: (r) => price(r.price) },
        { label: "Δ %", num: true, cls: (r) => dir(r.change_pct), render: (r) => pct(r.change_pct) },
        { label: "Next below", render: (r) => r.below[0] ? lvl(r.below[0]) : "–" },
        { label: "2nd below", render: (r) => r.below[1] ? lvl(r.below[1]) : "–" },
        { label: "Next above", render: (r) => r.above[0] ? lvl(r.above[0]) : "–" },
        { label: "2nd above", render: (r) => r.above[1] ? lvl(r.above[1]) : "–" },
        { label: "Price from", render: (r) => h("span", { class: "muted small" }, r.source + (r.has_file_levels ? "" : " · no file levels")) },
      ], d.rows || [], { empty: "No prices - start the MT5 bridge or set level markets in Settings." })),
      section("Level files", table([
        { label: "File", render: (f) => f.title }, { label: "Markets", render: (f) => (f.assets || []).join(", ") },
        { label: "Age", num: true, render: (f) => (f.age_h == null ? "–" : h("span", { class: f.fresh ? "" : "warn" }, `${num(f.age_h, 1)} h`)) },
        { label: "", render: (f) => h("span", { class: "muted small" }, f.error || f.path) },
      ], d.files || [], { empty: "No level files registered. Settings → Levels: add text files with levels (e.g. the gamma-seed output)." })),
      section("Level alerts", table([
        { label: "Time", render: (a) => stamp(a.ts) }, { label: "Alert", render: (a) => h("span", { class: (a.data || {}).direction === "up" ? "up" : "down" }, a.title) },
        { label: "Detail", render: (a) => h("span", { class: "small muted" }, a.body) },
      ], d.alerts || [], { empty: "No level crossed yet." })),
      note("Alerts fire when the price crosses a level between two checks (every 5 s with fresh broker quotes, every 30 s otherwise); each level is silent for 10 minutes afterwards. Level files older than the age limit are ignored. Broker CFD prices and futures/index levels can differ by the basis."));
    ctx.setContext({ page: "Levels", ladder: d.rows, files: d.files, recent_alerts: (d.alerts || []).slice(0, 15).map((a) => a.title) });
  };
  await load();
  const off = on("level", load);
  const t = setInterval(load, 10000);
  return () => { off(); clearInterval(t); };
}
