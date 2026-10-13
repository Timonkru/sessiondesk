// Forced-flow calendar: index rebalances, expiries, month end, Tokyo fix.
import { api } from "../lib/api.js";
import { h, clear, table, section, note, loading, ext } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  let showLow = localStorage.getItem("sd.flowsLow") === "1";
  const body = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Forced flows"), h("span", { class: "meta" }, "who must trade, when - regardless of price")), body);
  clear(body, loading());
  const d = await api("/api/flows?days=150", { ttl: 3600000 });
  const draw = () => {
    const rows = (d.events || []).filter((e) => showLow || e.size !== "low");
    const months = new Map();
    for (const e of rows) { const m = e.date.slice(0, 7); if (!months.has(m)) months.set(m, []); months.get(m).push(e); }
    const toggle = h("label", null, h("input", { type: "checkbox", checked: showLow, onchange: (e) => { showLow = e.target.checked; localStorage.setItem("sd.flowsLow", showLow ? "1" : "0"); draw(); } }),
      "show small flows (Tokyo fix, monthly VIX, futures roll)");
    clear(body, note(d.note), h("div", { class: "toolbar" }, toggle));
    for (const [m, evs] of months) {
      const label = new Date(m + "-01T12:00:00").toLocaleDateString([], { month: "long", year: "numeric" });
      body.appendChild(section(label, table([
        { label: "Date", render: (e) => new Date(e.date + "T12:00:00").toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short" }) },
        { label: "When", render: (e) => h("span", { class: "muted small" }, e.time) },
        { label: "Event", render: (e) => h("span", { style: { fontWeight: e.size === "high" ? 600 : 400 } }, e.name) },
        { label: "Size", render: (e) => h("span", { class: e.size === "high" ? "warn" : "muted" }, e.size) },
        { label: "Markets", render: (e) => h("span", { class: "small" }, e.markets.join(", ")) },
        { label: "Mechanism", render: (e) => h("span", { class: "small", style: { color: "var(--fg2)" } }, e.mechanism, e.certainty !== "rule" ? h("span", { class: "warn" }, " (approximate)") : "") },
        { label: "", render: (e) => ext(e.verify, "verify") },
      ], evs)));
    }
    body.appendChild(section("Every day", table([
      { label: "Flow", render: (r) => r.name }, { label: "When", render: (r) => r.when }, { label: "Mechanism", render: (r) => h("span", { class: "small" }, r.mechanism) },
    ], d.always || [])));
    body.appendChild(note("Most calendar flows do not survive costs as a stand-alone trade once tested; a known date mainly tells you when closing auctions, spreads and volatility behave differently. Research on these effects: ", ));
    body.lastChild.appendChild(ext("https://kruegeralgorithms.com/en/research", "kruegeralgorithms.com/research"));
    ctx.setContext({ page: "Forced-flow calendar", events: rows.slice(0, 60), note: d.note });
  };
  draw();
}
