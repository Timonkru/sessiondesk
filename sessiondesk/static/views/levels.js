// Levels: live ladder (nearest levels above/below each price), your own price alerts, level alert history,
// level file freshness.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, price, pct, num, dir, stamp, note, loading, errorBox, toast } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const facts = {};                                   // one AI context for both halves of the page
  const alertsBox = h("div", null, loading());
  const loadAlerts = async () => {
    const d = await api("/api/price_alerts", { fresh: true });
    if (d.error) { clear(alertsBox, errorBox(d.error)); return; }
    const sym = h("input", { type: "text", placeholder: "symbol (AAPL, ^GDAXI, EURUSD=X)", style: { width: "220px" } });
    const op = h("select", null, h("option", { value: "above" }, "at or above"), h("option", { value: "below" }, "at or below"));
    const lvl = h("input", { type: "text", placeholder: "price", style: { width: "110px" } });
    const memo = h("input", { type: "text", placeholder: "note (optional)", style: { width: "220px" } });
    const add = async () => {
      const r = await api("/api/price_alerts", { method: "POST", body: { symbol: sym.value, op: op.value, level: lvl.value.replace(",", "."), note: memo.value } });
      if (r.error) toast("Alert not set", r.error); else loadAlerts();
    };
    const act = (a, body) => api(`/api/price_alerts/${a.id}`, { method: "POST", body }).then(loadAlerts);
    clear(alertsBox,
      h("div", { class: "toolbar" }, sym, op, lvl, memo, h("button", { onclick: add }, "Set alert")),
      table([
        { label: "Symbol", render: (a) => h("a", { href: "#/stock/" + encodeURIComponent(a.symbol) }, a.symbol) },
        { label: "When", render: (a) => `${a.op === "above" ? "≥" : "≤"} ${price(a.level)}` },
        { label: "Now", num: true, render: (a) => price(a.price) },
        { label: "Distance", num: true, render: (a) => (a.active ? pct(a.distance_pct, 2) : "") },
        { label: "State", render: (a) => (a.active ? h("span", { class: "up" }, "active") : h("span", { class: "warn" }, `hit ${stamp(a.triggered)} at ${price(a.price_at_trigger)}`)) },
        { label: "Note", render: (a) => h("span", { class: "muted small" }, a.note || "") },
        { label: "", render: (a) => h("span", null, a.active ? null : h("button", { class: "linkish", onclick: () => act(a, { rearm: true }) }, "re-arm"), " ",
          h("button", { class: "linkish", onclick: () => act(a, { delete: true }) }, "delete")) },
      ], d.alerts || [], { empty: "No price alerts. Set one above or with the alert button on an instrument page." }),
      note(d.note));
    facts.price_alerts = d.alerts;
    ctx.setContext({ page: "Levels and price alerts", ...facts });
  };
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Levels"), h("span", { class: "meta" }, "gamma / file levels, round numbers, previous day and overnight range")), section("Your price alerts", h("p", { class: "small" }, h("a", { href: "#/alerts" }, "all alerts - prices, data series, stock measures, baskets →")), alertsBox), body);
  loadAlerts();
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
    Object.assign(facts, { ladder: d.rows, files: d.files, recent_alerts: (d.alerts || []).slice(0, 15).map((a) => a.title) });
    ctx.setContext({ page: "Levels and price alerts", ...facts });
  };
  await load();
  const off = on("level", load), offP = on("price_alert", loadAlerts);
  const t = setInterval(load, 10000);
  return () => { off(); offP(); clearInterval(t); };
}
