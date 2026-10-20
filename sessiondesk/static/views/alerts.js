// Alerts: one-shot alerts on any number - a price, a Data hub series, a stock's measures, or any member of a basket.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, note, loading, errorBox, stamp, toast } from "../lib/ui.js";

const SOURCES = [["quote", "Price"], ["hub", "Data hub series"], ["stock", "Stock measure"], ["basket", "Basket (any member)"]];

export async function render(root, _params, ctx) {
  const formBox = h("div"), listBox = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Alerts"), h("span", { class: "meta" }, "on prices, data series, stock measures and baskets")),
    h("div", { class: "cols" }, section("Your alerts", listBox), section("New alert", formBox)));

  const [hub, baskets] = await Promise.all([api("/api/hub", { ttl: 300000 }), api("/api/baskets", { ttl: 60000 })]);
  let fields = {};

  const load = async () => {
    const d = await api("/api/price_alerts", { fresh: true });
    if (d.error) { clear(listBox, errorBox(d.error)); return; }
    fields = d.fields || fields;
    const act = (a, body) => api(`/api/price_alerts/${a.id}`, { method: "POST", body }).then(load);
    clear(listBox, table([
      { label: "Alert", render: (a) => [h("strong", null, a.title), a.note ? h("div", { class: "small muted" }, a.note) : null] },
      { label: "Now", num: true, render: (a) => (a.value == null ? "–" : [num(a.value, Math.abs(a.value) < 10 ? 2 : 1), a.nearest ? h("div", { class: "small muted" }, a.nearest) : null]) },
      { label: "Status", render: (a) => (a.active ? h("span", { class: "up" }, "watching")
        : h("span", { class: "warn" }, `fired ${stamp(a.triggered)} at ${num(a.price_at_trigger, 2)}${a.matches ? " · " + a.matches.join(", ") : ""}`)) },
      { label: "", render: (a) => [a.active ? null : h("button", { class: "linkish", onclick: () => act(a, { rearm: true }) }, "re-arm"), " ",
        h("button", { class: "linkish", onclick: () => { if (confirm("Delete this alert?")) act(a, { delete: true }); } }, "delete")] },
    ], d.alerts || [], { empty: "No alerts yet - create one on the right." }), note(d.note));
    ctx.setContext({ page: "Alerts", alerts: (d.alerts || []).map((a) => ({ title: a.title, now: a.value, active: a.active, triggered: a.triggered, matches: a.matches })) });
  };

  const draw = (source) => {
    const src = h("select", { onchange: (e) => draw(e.target.value) }, SOURCES.map(([k, l]) => h("option", { value: k, selected: k === source }, l)));
    let target;
    if (source === "hub") {
      const cats = [...new Set((hub.series || []).map((s) => s.category))];
      target = h("select", { style: { maxWidth: "100%" } }, cats.map((c) => h("optgroup", { label: c },
        (hub.series || []).filter((s) => s.category === c).map((s) => h("option", { value: s.id }, s.name)))));
    } else if (source === "basket") {
      target = h("select", null, (baskets.baskets || []).map((b) => h("option", { value: b.id }, b.name)));
    } else {
      target = h("input", { type: "text", placeholder: "symbol, e.g. AAPL, SAP.DE, ^GDAXI", style: { width: "200px" } });
    }
    const fieldSel = h("select", null, Object.entries((fields[source] || {})).map(([k, l]) => h("option", { value: k }, l)));
    const op = h("select", null, h("option", { value: "above" }, "at or above"), h("option", { value: "below" }, "at or below"));
    const level = h("input", { type: "text", inputmode: "decimal", placeholder: "value", style: { width: "100px" } });
    const memo = h("input", { type: "text", placeholder: "note (optional)", style: { width: "100%" } });
    const save = async () => {
      const r = await api("/api/price_alerts", { method: "POST", body: { source, symbol: target.value, field: fieldSel.value, op: op.value,
        level: level.value.replace(",", "."), note: memo.value } });
      if (r.error) { toast("Alert not saved", r.error); return; }
      toast("Alert saved", ""); level.value = ""; memo.value = ""; load();
    };
    const hint = {
      quote: "Price or today's change of any symbol (stocks, indices, FX, futures, crypto).",
      hub: "Any series in the Data hub: FRED, EIA stocks, power prices, gas, tanker counts, your baskets ... 'z' fires on an unusual move against the series' own history.",
      stock: "A stock's measures from daily closes: RSI, distance to the 52-week high or the 200-day average, recent changes, volatility.",
      basket: "Fires once when any member of the basket meets the condition, and names those members (e.g. RSI 14 at or below 30).",
    }[source];
    clear(formBox, h("div", { class: "toolbar" }, src), source === "basket" && !(baskets.baskets || []).length ? note("Create a basket first (Markets › Baskets).") : null,
      h("div", { class: "toolbar" }, target), h("div", { class: "toolbar" }, fieldSel, op, level), memo,
      h("div", { class: "toolbar" }, h("button", { onclick: save }, "Create alert")), note(hint));
  };

  await load();
  draw("quote");
  const t = setInterval(load, 30000);
  return () => clearInterval(t);
}
