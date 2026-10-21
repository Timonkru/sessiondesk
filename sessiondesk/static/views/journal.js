// Journal: equity curve and P/L per day per account (in money or in percent of the account), the trading days with a
// detail page each, stats per account and setup in R, closed positions with net, initial risk, R and a note.
// Copier copies (Settings -> copy_magics) are hidden from the lists unless switched on; curves always include them.
import { api } from "../lib/api.js";
import { lineChart, bars } from "../lib/chart.js";
import { h, clear, table, section, num, pct, dir, stamp, day, clock, note, loading, errorBox, toast } from "../lib/ui.js";
import { crumbs } from "../lib/stocktable.js";

const unitStore = { get: () => { try { return localStorage.getItem("sd.journalUnit") || "money"; } catch { return "money"; } },
  set: (v) => { try { localStorage.setItem("sd.journalUnit", v); } catch { /* storage blocked */ } } };

// money or percent of the account, by the switch
const amount = (unit, money, percent, cur = "") => (unit === "pct" ? (percent == null ? "–" : pct(percent, 2)) : (money == null ? "–" : `${num(money, 0)}${cur ? " " + cur : ""}`));

function unitSwitch(unit, onChange) {
  return h("span", { class: "tabs inline" }, [["money", "€ / $"], ["pct", "% of account"]].map(([k, l]) =>
    h("button", { class: k === unit ? "on" : "", onclick: () => { unitStore.set(k); onChange(k); } }, l)));
}

export async function render(root, params, ctx) {
  if (params[0] === "day" && params[1]) return dayPage(root, params[1], ctx);
  let days = Number(localStorage.getItem("sd.journalDays") || 30);
  let copies = localStorage.getItem("sd.journalCopies") === "1";
  let unit = unitStore.get();
  const copyBox = h("input", { type: "checkbox", checked: copies, onchange: (e) => { copies = e.target.checked; localStorage.setItem("sd.journalCopies", copies ? "1" : "0"); load(); } });
  const body = h("div", null, loading());
  const sel = h("select", { onchange: (e) => { days = Number(e.target.value); localStorage.setItem("sd.journalDays", String(days)); load(); } },
    [7, 30, 90, 365].map((d) => h("option", { value: d, selected: d === days }, `last ${d} days`)));
  const switchBox = h("span");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Journal"), sel, h("label", { class: "small" }, copyBox, " include copier copies"), switchBox), body);
  let data = null;

  const edit = async (t, field) => {
    const cur = field === "risk" ? (t.risk_confirmed ?? t.risk_observed ?? "") : (t.note || "");
    const val = prompt(field === "risk" ? `Initial risk for ${t.symbol} ${t.side} (money, account currency):` : `Note for ${t.symbol} ${t.side}:`, cur);
    if (val === null) return;
    const res = await api("/api/journal", { method: "POST", body: { account: t.account, position_id: t.position_id, [field]: val } });
    if (res.error) toast("Journal", res.error); else load();
  };

  const draw = () => {
    const d = data;
    clear(switchBox, unitSwitch(unit, (k) => { unit = k; draw(); }));
    const isPct = unit === "pct";
    const charts = Object.entries(d.curves || {}).map(([acc, c]) => h("div", null,
      h("h3", null, `Account ${acc}: ${amount(unit, c.total, c.base ? (c.total / c.base) * 100 : null, c.currency)}`),
      lineChart(c.cum.map((p) => ({ x: p.t, y: isPct ? p.pct ?? 0 : p.v })), { height: 170, ref: 0, area: false, fmtY: (v) => (isPct ? v.toFixed(1) + "%" : num(v, 0)), fmtX: (t) => day(t) }),
      h("div", { class: "small muted" }, `Net per ${c.period}${isPct ? " in % of the account at the start of that " + c.period : ""} - click a day below for its detail page`),
      bars(c.periods.slice(-40).map((b) => ({ label: b.label.slice(5), value: isPct ? b.pct ?? 0 : b.net })), { height: 130, fmt: (v) => (isPct ? v.toFixed(2) + "%" : num(v, 0)) })));
    // trading days: one row per day and account, linking to the day page
    const dayRows = [];
    for (const [acc, c] of Object.entries(d.curves || {})) {
      if (c.period !== "day") continue;
      for (const p of c.periods) dayRows.push({ day: p.label, account: acc, net: p.net, pct: p.pct, currency: c.currency });
    }
    dayRows.sort((a, b) => (a.day < b.day ? 1 : -1));
    clear(body,
      charts.length ? section("Equity curve and P/L per account", h("div", { class: "cols" }, charts)) : null,
      dayRows.length ? section("Trading days", h("div", { class: "scroll" }, table([
        { label: "Day", render: (r) => h("a", { href: "#/journal/day/" + r.day }, `${r.day} ${new Date(r.day + "T12:00").toLocaleDateString([], { weekday: "short" })}`) },
        { label: "Account", render: (r) => r.account },
        { label: "Net", num: true, cls: (r) => dir(r.net), render: (r) => amount(unit, r.net, r.pct, r.currency) },
        { label: isPct ? "in money" : "in %", num: true, cls: (r) => dir(r.net), render: (r) => (isPct ? `${num(r.net, 0)} ${r.currency || ""}` : (r.pct == null ? "–" : pct(r.pct, 2))) },
      ], dayRows.slice(0, 120), { onRow: (r) => ctx.go("#/journal/day/" + r.day) }))) : null,
      d.copies_hidden ? note(`${d.copies_hidden} copied trades hidden from the lists (copier magic ${d.copy_magics.join(", ")}); the curves include them. Tick "include copier copies" to list them.`) : null,
      section("By account and setup", table([
        { label: "Account", render: (s) => s.account }, { label: "Setup", render: (s) => s.setup }, { label: "Trades", num: true, render: (s) => s.trades },
        { label: "Net", num: true, cls: (s) => dir(s.net), render: (s) => `${num(s.net, 0)} ${s.currency || ""}` },
        { label: "Win rate", num: true, render: (s) => num(s.win_rate * 100, 0) + "%" },
        { label: "With risk", num: true, render: (s) => s.with_risk },
        { label: "Avg R", num: true, cls: (s) => dir(s.avg_r), render: (s) => (s.avg_r == null ? "–" : num(s.avg_r, 2)) },
        { label: "± SE", num: true, render: (s) => (s.se_r == null ? "–" : num(s.se_r, 2)) },
        { label: "t", num: true, render: (s) => (s.avg_r != null && s.se_r ? num(s.avg_r / s.se_r, 1) : "–") },
      ], d.stats || [], { empty: "No closed trades in this window." })),
      section("Closed trades", h("div", { class: "scroll" }, tradeTable(d.trades || [], unit, edit, true))),
      (d.open || []).length ? section("Open positions being tracked", table([{ label: "Account", render: (t) => t.account }, { label: "Symbol", render: (t) => t.symbol },
        { label: "Side", render: (t) => t.side }, { label: "Observed risk", num: true, render: (t) => num(t.risk_observed, 0) }, { label: "Context", render: (t) => h("span", { class: "small muted" }, t.context || "") }], d.open)) : null,
      note(d.note + " Percent = of the account's balance at the start of that day (stored from 2026-10-18, earlier reconstructed from later trade results; deposits and withdrawals are not included)."));
    ctx.setContext({ page: "Journal", window_days: days, unit, copies_included: copies, stats: d.stats,
      totals: Object.fromEntries(Object.entries(d.curves || {}).map(([a, c]) => [a, { net: c.total, currency: c.currency, per_period: c.periods.slice(-20) }])),
      trades: (d.trades || []).slice(0, 80).map((t) => ({ closed: t.closed, setup: t.setup, symbol: t.symbol, side: t.side, net: t.net, pct: t.pct, r: t.r, note: t.note })) });
  };
  const load = async () => {
    const d = await api(`/api/journal?days=${days}&copies=${copies}`, { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    data = d;
    draw();
  };
  await load();
}

function tradeTable(rows, unit, edit, withDay) {
  return table([
    { label: "Closed", render: (t) => (withDay ? h("a", { href: "#/journal/day/" + new Date(t.closed * 1000).toLocaleDateString("sv") }, stamp(t.closed)) : clock(t.closed)) },
    ...(withDay ? [] : [{ label: "Opened", render: (t) => (t.opened ? clock(t.opened) : "–") }, { label: "Held", num: true, render: (t) => (t.minutes == null ? "–" : t.minutes < 120 ? `${Math.round(t.minutes)} min` : `${(t.minutes / 60).toFixed(1)} h`) }]),
    { label: "Account", render: (t) => t.account }, { label: "Setup", render: (t) => [t.setup, t.copy ? h("span", { class: "small muted" }, " (copy)") : ""] },
    { label: "Symbol", render: (t) => t.symbol }, { label: "Side", render: (t) => t.side },
    { label: "Net", num: true, cls: (t) => dir(t.net), render: (t) => (unit === "pct" ? (t.pct == null ? "–" : pct(t.pct, 2)) : num(t.net, 2)) },
    { label: "Risk", num: true, render: (t) => (edit ? h("button", { class: "linkish", title: "set confirmed initial risk", onclick: () => edit(t, "risk") },
      (t.risk_confirmed ?? t.risk_observed) == null ? "set" : num(t.risk_confirmed ?? t.risk_observed, 0) + (t.risk_source === "observed" ? " (obs.)" : "")) : num(t.risk_confirmed ?? t.risk_observed, 0)) },
    { label: "R", num: true, cls: (t) => dir(t.r), render: (t) => (t.r == null ? "–" : num(t.r, 2)) },
    { label: "Note", render: (t) => (edit ? h("button", { class: "linkish", onclick: () => edit(t, "note") }, t.note || "add") : t.note || "") },
  ], rows, { empty: "No closed trades yet - they appear as soon as the exporter delivers deal history." });
}

async function dayPage(root, dayStr, ctx) {
  let unit = unitStore.get();
  const body = h("div", null, loading());
  const head = h("div");
  root.append(head, body);
  const edit = async (t, field) => {
    const cur = field === "risk" ? (t.risk_confirmed ?? t.risk_observed ?? "") : (t.note || "");
    const val = prompt(field === "risk" ? `Initial risk for ${t.symbol} ${t.side}:` : `Note for ${t.symbol} ${t.side}:`, cur);
    if (val === null) return;
    const res = await api("/api/journal", { method: "POST", body: { account: t.account, position_id: t.position_id, [field]: val } });
    if (res.error) toast("Journal", res.error); else load();
  };
  let d = null;
  const draw = () => {
    clear(head, crumbs([["My trading", "#/journal"], ["Journal", "#/journal"], [dayStr]]),
      h("div", { class: "pagehead" }, h("h1", null, `${d.weekday}, ${d.day}`),
        d.prev ? h("a", { href: "#/journal/day/" + d.prev }, "← previous trading day") : null, " ",
        d.next ? h("a", { href: "#/journal/day/" + d.next }, "next trading day →") : null, " ", unitSwitch(unit, (k) => { unit = k; draw(); })));
    if (!d.accounts.length) { clear(body, note("No trades closed on this day."), d.events.length ? eventBox(d.events) : null); return; }
    const isPct = unit === "pct";
    clear(body,
      d.accounts.map((a) => section(`Account ${a.account}`,
        h("div", { class: "keystrip" }, [["Result", h("span", { class: dir(a.net) }, amount(unit, a.net, a.pct, a.currency))],
          [isPct ? "in money" : "in %", isPct ? `${num(a.net, 0)} ${a.currency || ""}` : (a.pct == null ? "–" : pct(a.pct, 2))],
          ["Trades", `${a.trades} (${a.wins} won)`], ["Sum of R", a.sum_r == null ? "–" : num(a.sum_r, 2)], ["Avg R", a.avg_r == null ? "–" : num(a.avg_r, 2)],
          ["Start balance", a.start_balance == null ? "–" : `${num(a.start_balance, 0)} ${a.currency || ""}`], a.copies ? ["Copied trades", a.copies] : null]
          .filter(Boolean).map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v)))),
        a.path.length > 1 ? lineChart(a.path.map((p) => ({ x: p.t, y: isPct ? p.pct ?? 0 : p.v })), { height: 150, ref: 0, area: false,
          fmtY: (v) => (isPct ? v.toFixed(2) + "%" : num(v, 0)), fmtX: (t) => clock(t) }) : null,
        h("div", { class: "cols" },
          table([{ label: "Setup", render: (g) => g.name }, { label: "Trades", num: true, render: (g) => g.trades },
            { label: "Net", num: true, cls: (g) => dir(g.net), render: (g) => amount(unit, g.net, g.pct) }], a.by_setup),
          table([{ label: "Symbol", render: (g) => g.name }, { label: "Trades", num: true, render: (g) => g.trades },
            { label: "Net", num: true, cls: (g) => dir(g.net), render: (g) => amount(unit, g.net, g.pct) }], a.by_symbol)))),
      section("Trades of the day", h("div", { class: "scroll" }, tradeTable(d.trades, unit, edit, false))),
      d.events.length ? eventBox(d.events) : null, note(d.note));
    ctx.setContext({ page: `Journal day ${d.day}`, unit, accounts: d.accounts.map((a) => ({ account: a.account, net: a.net, pct: a.pct, trades: a.trades, wins: a.wins,
      sum_r: a.sum_r, by_setup: a.by_setup, by_symbol: a.by_symbol })), trades: d.trades.map((t) => ({ opened: t.opened, closed: t.closed, minutes: t.minutes,
      setup: t.setup, symbol: t.symbol, side: t.side, net: t.net, pct: t.pct, r: t.r, note: t.note })), releases: d.events.map((e) => `${e.currency} ${e.title}`) });
  };
  const load = async () => {
    d = await api("/api/journal/day/" + encodeURIComponent(dayStr), { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    draw();
  };
  await load();
}

function eventBox(events) {
  return section("High-impact releases that day", table([{ label: "", render: (e) => clock(e.ts) }, { label: "", render: (e) => `${e.currency} ${e.title}` },
    { label: "Actual / fcst", num: true, render: (e) => `${e.actual ?? "–"} / ${e.forecast ?? "–"}` }], events));
}
