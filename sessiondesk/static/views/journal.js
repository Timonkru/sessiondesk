// Journal: closed positions with net, initial risk, R and a note; stats per setup in R.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, dir, stamp, note, loading, errorBox, toast } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  let days = Number(localStorage.getItem("sd.journalDays") || 30);
  const body = h("div", null, loading());
  const sel = h("select", { onchange: (e) => { days = Number(e.target.value); localStorage.setItem("sd.journalDays", String(days)); load(); } },
    [7, 30, 90, 365].map((d) => h("option", { value: d, selected: d === days }, `last ${d} days`)));
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Journal"), sel), body);

  const edit = async (t, field) => {
    const cur = field === "risk" ? (t.risk_confirmed ?? t.risk_observed ?? "") : (t.note || "");
    const val = prompt(field === "risk" ? `Initial risk for ${t.symbol} ${t.side} (money, account currency):` : `Note for ${t.symbol} ${t.side}:`, cur);
    if (val === null) return;
    const res = await api("/api/journal", { method: "POST", body: { account: t.account, position_id: t.position_id, [field]: val } });
    if (res.error) toast("Journal", res.error); else load();
  };

  const load = async () => {
    const d = await api(`/api/journal?days=${days}`, { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    clear(body,
      section("By setup", table([
        { label: "Setup", render: (s) => s.setup }, { label: "Trades", num: true, render: (s) => s.trades },
        { label: "Net", num: true, cls: (s) => dir(s.net), render: (s) => num(s.net, 0) },
        { label: "Win rate", num: true, render: (s) => num(s.win_rate * 100, 0) + "%" },
        { label: "With risk", num: true, render: (s) => s.with_risk },
        { label: "Avg R", num: true, cls: (s) => dir(s.avg_r), render: (s) => (s.avg_r == null ? "–" : num(s.avg_r, 2)) },
        { label: "± SE", num: true, render: (s) => (s.se_r == null ? "–" : num(s.se_r, 2)) },
        { label: "t", num: true, render: (s) => (s.avg_r != null && s.se_r ? num(s.avg_r / s.se_r, 1) : "–") },
      ], d.stats || [], { empty: "No closed trades in this window." })),
      section("Closed trades", h("div", { class: "scroll" }, table([
        { label: "Closed", render: (t) => stamp(t.closed) }, { label: "Account", render: (t) => t.account }, { label: "Setup", render: (t) => t.setup },
        { label: "Symbol", render: (t) => t.symbol }, { label: "Side", render: (t) => t.side },
        { label: "Net", num: true, cls: (t) => dir(t.net), render: (t) => num(t.net, 2) },
        { label: "Risk", num: true, render: (t) => h("button", { class: "linkish", title: "set confirmed initial risk", onclick: () => edit(t, "risk") },
          (t.risk_confirmed ?? t.risk_observed) == null ? "set" : num(t.risk_confirmed ?? t.risk_observed, 0) + (t.risk_source === "observed" ? " (obs.)" : "")) },
        { label: "R", num: true, cls: (t) => dir(t.r), render: (t) => (t.r == null ? "–" : num(t.r, 2)) },
        { label: "Note", render: (t) => h("button", { class: "linkish", onclick: () => edit(t, "note") }, t.note || "add") },
      ], d.trades || [], { empty: "No closed trades yet - they appear as soon as the exporter delivers deal history." }))),
      (d.open || []).length ? section("Open positions being tracked", table([{ label: "Account", render: (t) => t.account }, { label: "Symbol", render: (t) => t.symbol },
        { label: "Side", render: (t) => t.side }, { label: "Observed risk", num: true, render: (t) => num(t.risk_observed, 0) }, { label: "Context", render: (t) => h("span", { class: "small muted" }, t.context || "") }], d.open)) : null,
      note(d.note));
    ctx.setContext({ page: "Journal", window_days: days, stats: d.stats, trades: (d.trades || []).slice(0, 80).map((t) => ({ closed: t.closed, setup: t.setup, symbol: t.symbol, side: t.side, net: t.net, r: t.r, note: t.note })) });
  };
  await load();
}
