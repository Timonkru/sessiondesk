// Portfolio (PORT): exposure of the open book per account - leverage, asset class, region, currency, sector,
// largest positions, risk to stops - plus correlation and scenarios. Read-only, accounts never added together.
import { api } from "../lib/api.js";
import { bars } from "../lib/chart.js";
import { h, clear, table, section, num, pct, big, dir, note, loading, errorBox } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const body = h("div", null, loading("Reading your accounts…"));
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Portfolio"), h("span", { class: "meta" }, "what your open book is exposed to")), body);
  const draw = async () => {
    const d = await api("/api/portfolio", { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    if (!d.connected) { clear(body, note(d.note || "No broker connected.")); return; }
    if (!d.accounts.length) {
      clear(body, note(`No open positions in ${d.all_accounts.length} connected account${d.all_accounts.length === 1 ? "" : "s"} - exposure appears as soon as something is open.`), note(d.note));
      ctx.setContext({ page: "Portfolio", open_positions: 0 });
      return;
    }
    const chart = (rows) => (rows.length ? bars(rows.map((r) => ({ label: r.name, value: r.pct ?? 0 })), { height: 130, fmt: (v) => v.toFixed(0) + "%" }) : note("–"));
    const cards = d.accounts.map((a) => section(`Account …${String(a.account).slice(-3)} · ${a.currency || ""}`,
      h("div", { class: "keystrip" }, [["Equity", big(a.equity)], ["Positions", a.positions], ["Gross (leverage)", pct(a.gross_pct, 0, false)],
        ["Net", h("span", { class: dir(a.net_pct) }, pct(a.net_pct, 0))], ["Risk to stops", a.risk_pct == null ? "–" : pct(a.risk_pct, 2, false)],
        ["Without stop", h("span", { class: a.without_stop ? "warn" : "" }, a.without_stop)]].map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v)))),
      h("div", { class: "cols" },
        h("div", null, h("h3", null, "Net exposure by asset class, % of equity"), chart(a.by_class), h("h3", null, "by region"), chart(a.by_region)),
        h("div", null, h("h3", null, "by currency (FX on both legs)"), chart(a.by_currency), a.by_sector.length ? [h("h3", null, "by sector (single stocks)"), chart(a.by_sector)] : null)),
      h("h3", null, "Largest positions"),
      table([{ label: "Symbol", render: (r) => r.symbol }, { label: "Side", render: (r) => r.side }, { label: "Class", render: (r) => r.class },
        { label: "Exposure", num: true, cls: (r) => dir(r.notional), render: (r) => big(r.notional) },
        { label: "% of equity", num: true, render: (r) => pct(r.pct, 1) },
        { label: "Risk to stop", num: true, render: (r) => (r.risk_to_stop == null ? h("span", { class: "warn" }, "no stop") : big(r.risk_to_stop)) }], a.largest),
      a.missing_notional ? note(`${a.missing_notional} position(s) without a money-per-move figure from the broker export are not counted.`, "warn") : null));
    const matrix = d.matrix.length ? section("Do your positions move together? (sign-adjusted correlation)", h("div", { class: "scroll" }, table([
      { label: "", render: (r) => `${r.asset} ${r.side}` },
      ...d.matrix.map((c, i) => ({ label: `${c.asset} ${c.side[0]}`, num: true, cls: (r) => (r.values[i] != null && r.values[i] > 0.5 && r.asset !== c.asset ? "warn" : ""),
        render: (r) => (r.values[i] == null ? "–" : num(r.values[i], 2)) }))], d.matrix)),
      note("Above +0.5: the two positions win and lose together - effectively one bigger bet.")) : null;
    const scen = d.scenarios.length ? section("If a driver market moves", table([
      { label: "Account", render: (s) => "…" + String(s.account).slice(-3) }, { label: "Driver", render: (s) => s.driver }, { label: "Move", num: true, render: (s) => pct(s.shock, 1) },
      { label: "P/L", num: true, cls: (s) => dir(s.total), render: (s) => big(s.total) }, { label: "% of equity", num: true, cls: (s) => dir(s.total_pct), render: (s) => pct(s.total_pct, 2) },
      { label: "", render: (s) => (s.incomplete ? h("span", { class: "small muted" }, `${s.incomplete} not modelled`) : "") }], d.scenarios)) : null;
    clear(body, cards, matrix, scen, note(d.note));
    ctx.setContext({ page: "Portfolio", accounts: d.accounts.map((a) => ({ account: "…" + String(a.account).slice(-3), currency: a.currency, gross_pct: a.gross_pct,
      net_pct: a.net_pct, risk_pct: a.risk_pct, by_class: a.by_class, by_currency: a.by_currency, largest: a.largest.slice(0, 5) })), scenarios: d.scenarios });
  };
  await draw();
  const t = setInterval(draw, 30000);
  return () => clearInterval(t);
}
