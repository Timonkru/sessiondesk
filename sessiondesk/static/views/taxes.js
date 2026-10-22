// Taxes: per account and month what the broker withheld or refunded next to the trading result before tax, plus
// deposits, withdrawals and fees - from the MetaTrader 5 export. Accounts without bookings in their export get an
// estimate from SessionDesk's own day-start records.
import { api } from "../lib/api.js";
import { h, clear, table, section, note, loading, errorBox, num, pct, dir, stamp } from "../lib/ui.js";

export async function render(root, params, ctx) {
  const year = Number(params[0]) || new Date().getFullYear();
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Taxes"), h("span", { class: "meta" }, "withheld, refunded and the result before tax - per account"),
    h("span", { class: "tabs inline" }, [year - 1, year].map((y) => h("button", { class: y === year ? "on" : "", onclick: () => ctx.go(`#/taxes/${y}`) }, String(y))))), body);
  const d = await api(`/api/taxes?year=${year}`, { fresh: true });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  const money = (v) => (v == null ? "–" : num(v, 2));
  const blocks = (d.accounts || []).map((a) => {
    const title = `${a.account} · ${a.currency || ""}${a.server ? " · " + a.server : ""}`;
    if (!a.covered) {
      return section(title, note("This account's export carries no tax or other balance bookings (KasseNews exporter or SessionDeskBridge before 1.2). "
        + "Below: an estimate - every balance change that is not a trade, between the day-start balances SessionDesk recorded. Exact figures need SessionDeskBridge 1.2 on any chart of this terminal.", "warn"),
        table([{ label: "From day start", render: (e) => e.from }, { label: "to", render: (e) => e.to },
          { label: "Not trades", num: true, cls: (e) => dir(e.non_trade), render: (e) => money(e.non_trade) }], a.estimate || [], { empty: "No day starts recorded yet." }),
        a.estimate && a.estimate.length ? h("p", { class: "small" }, "Sum: ", h("strong", { class: dir(a.estimate_total) }, `${money(a.estimate_total)} ${a.currency || ""}`), " - tax, but also fees, dividend adjustments or a payout look like this.") : null);
    }
    const y = a.year || {};
    return section(title,
      h("div", { class: "keystrip" }, [["Result before tax", money(y.result), dir(y.result)], ["Withheld", money(y.withheld), "down"], ["Refunded", money(y.refunded), "up"],
        ["Net tax", money(y.net_tax), dir(y.net_tax)], ["Effective rate", y.rate == null ? "–" : pct(y.rate, 1, false), ""], ["After tax", money(y.after_tax), dir(y.after_tax)]]
        .map(([k, v, c]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v " + c }, v)))),
      table([
        { label: "Month", render: (m) => m.month },
        { label: "Result before tax", num: true, cls: (m) => dir(m.result), render: (m) => money(m.result) },
        { label: "Withheld", num: true, cls: () => "down", render: (m) => money(m.withheld) },
        { label: "Refunded", num: true, cls: () => "up", render: (m) => money(m.refunded) },
        { label: "Net tax", num: true, cls: (m) => dir(m.net_tax), render: (m) => money(m.net_tax) },
        { label: "Rate", num: true, render: (m) => (m.rate == null ? "–" : pct(m.rate, 1, false)) },
        { label: "After tax", num: true, cls: (m) => dir(m.after_tax), render: (m) => money(m.after_tax) },
        { label: "Deposits", num: true, render: (m) => (m.deposits ? money(m.deposits) : "") },
        { label: "Withdrawals", num: true, render: (m) => (m.withdrawals ? money(m.withdrawals) : "") },
      ], a.months || [], { empty: "No trades or bookings this year in the export." }),
      a.export_from ? note(`The deal export reaches back to ${a.export_from} (bridge setting InpDealDays); earlier months are missing or incomplete.`) : null,
      (a.bookings || []).length ? h("details", null, h("summary", { class: "small" }, `${a.bookings.length} bookings`),
        table([{ label: "Time", render: (b) => stamp(b.time) }, { label: "Type", render: (b) => b.type },
          { label: "Comment", render: (b) => h("span", { class: "small muted" }, b.comment || "") },
          { label: "Amount", num: true, cls: (b) => dir(b.amount), render: (b) => money(b.amount) }], a.bookings)) : null);
  });
  clear(body, blocks.length ? blocks : note("No MetaTrader 5 account connected (Accounts & EAs)."), note(d.note));
  ctx.setContext({ page: "Taxes", year, accounts: (d.accounts || []).map((a) => ({ account: a.account, covered: a.covered, year: a.year, estimate_total: a.estimate_total })) });
}
