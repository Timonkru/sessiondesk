// Accounts & EAs - read-only view of connected trading accounts, positions, running Expert Advisors.
import { api } from "../lib/api.js";
import { h, clear, table, section, price, num, big, dir, ago, note, loading, errorBox } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Accounts & EAs"), h("span", { class: "meta" }, "read-only - SessionDesk never places, changes or closes orders")), body);
  const load = async () => {
    const d = await api("/api/broker", { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
    if (!d.connected) {
      clear(body, note(d.note), section("Connect MetaTrader 5", h("ol", { class: "small" },
        h("li", null, "Copy bridge/SessionDeskBridge.mq5 from this project into MT5: File → Open Data Folder → MQL5/Experts, then compile it in MetaEditor (or copy the .ex5)."),
        h("li", null, "Attach SessionDeskBridge to any one chart per terminal. It needs no special permissions and has no order code."),
        h("li", null, "Within a few seconds this page shows accounts, positions, running EAs and closed trades; the Calendar gets live actual values."))));
      return;
    }
    const fresh = (r) => r.fresh === false ? h("span", { class: "warn small" }, ` stale ${ago(Date.now() / 1000 - r.age)}`) : null;
    clear(body,
      section("Accounts", table([
        { label: "Account", render: (a) => [a.login, fresh(a)] }, { label: "Broker", render: (a) => h("span", { class: "small" }, a.company || a.server || a.connector) },
        { label: "Balance", num: true, render: (a) => num(a.balance, 2) }, { label: "Equity", num: true, render: (a) => num(a.equity, 2) },
        { label: "Open P/L", num: true, cls: (a) => dir(a.profit), render: (a) => num(a.profit, 2) },
        { label: "Risk to stops", num: true, render: (a) => a.risk_to_stops != null ? `${num(a.risk_to_stops, 0)} (${num(a.risk_pct, 2)}%)` : "–" },
        { label: "Trading", render: (a) => h("span", { class: a.trade_allowed ? "up" : "warn" }, a.trade_allowed ? "AutoTrading on" : "AutoTrading OFF") },
        { label: "", render: (a) => a.positions_without_stop ? h("span", { class: "warn small" }, "positions without stop") : "" },
      ], d.accounts)),
      extrasTable(d.accounts),
      section("Open positions", table([
        { label: "Account", render: (p) => p.account }, { label: "Symbol", render: (p) => p.symbol }, { label: "Side", render: (p) => p.side },
        { label: "Size", num: true, render: (p) => num(p.volume, 2) }, { label: "Open", num: true, render: (p) => price(p.open_price) },
        { label: "Now", num: true, render: (p) => price(p.price) }, { label: "Stop", num: true, render: (p) => p.sl ? price(p.sl) : h("span", { class: "warn" }, "none") },
        { label: "P/L", num: true, cls: (p) => dir(p.profit), render: (p) => num(p.profit, 2) },
        { label: "Risk to stop", num: true, render: (p) => p.risk_to_stop ? num(p.risk_to_stop, 0) : "–" },
        { label: "Origin", render: (p) => h("span", { class: "small muted" }, p.manual ? "manual" : (p.setup || `EA ${p.magic}`)) },
      ], d.positions, { empty: "No open positions." })),
      section("Running Expert Advisors", table([
        { label: "Account", render: (e) => e.account }, { label: "Chart", render: (e) => `${e.symbol} ${e.timeframe}` }, { label: "Expert", render: (e) => e.expert },
      ], d.eas, { empty: "No EA attached to any chart (or bridge without EA export)." })),
      bookBox, fxBox,
      section("Closed trades by EA - 7 days", perf(d.performance_7d)), section("Closed trades by EA - 30 days", perf(d.performance_30d)),
      specsBox,
      note("Trades are grouped by the magic number of the opening deal, so a manual close of an EA trade still counts for the EA. Net = profit + commission + swap."));
    ctx.setContext({ page: "Accounts & EAs", accounts: d.accounts, positions: d.positions, eas: d.eas, performance_7d: d.performance_7d, performance_30d: d.performance_30d });
  };
  // Extra status values an exporter provides (e.g. risk multiplier, day-start balance) - shown as delivered.
  const extrasTable = (accounts) => {
    const keys = [...new Set(accounts.flatMap((a) => Object.keys(a.extra || {})))];
    if (!keys.length) return null;
    const fmt = (v) => (v !== undefined && v !== "" && !isNaN(Number(v)) ? num(Number(v), Math.abs(Number(v)) < 10 ? 2 : 0) : (v ?? "–"));
    return section("Account details from the exporter", table([
      { label: "Value", render: (k) => k.replaceAll("_", " ") },
      ...accounts.map((a) => ({ label: a.login, num: true, render: (k) => fmt((a.extra || {})[k]) })),
    ], keys));
  };
  const bookBox = h("div"), fxBox = h("div"), specsBox = h("div");
  const loadExtras = async () => {
    const [bk, fx, sp] = await Promise.all([api("/api/book", { ttl: 30000 }), api("/api/fx/strength", { ttl: 30000 }), api("/api/specs", { ttl: 60000 })]);
    const m = bk.matrix || [];
    clear(bookBox, section("Open book: correlation and scenarios",
      m.length > 1 ? h("div", { class: "scroll" }, table([{ label: "", render: (r) => `${r.asset} ${r.side}` },
        ...m.map((c, i) => ({ label: `${c.asset} ${c.side[0]}`, num: true, render: (r) => { const v = r.values[i]; return v == null ? "–" : h("span", { class: v > 0.5 ? "warn" : v < -0.3 ? "up" : "" }, num(v, 2)); } }))], m))
        : note(bk.note || "Fewer than two open markets - nothing to correlate."),
      (bk.scenarios || []).length ? table([{ label: "Account", render: (r) => r.account }, { label: "If", render: (r) => `${r.driver} ${r.shock > 0 ? "+" : ""}${r.shock}%` },
        { label: "Book P/L", num: true, cls: (r) => dir(r.total), render: (r) => num(r.total, 0) }, { label: "of equity", num: true, cls: (r) => dir(r.total_pct), render: (r) => (r.total_pct == null ? "–" : pct(r.total_pct, 2)) },
        { label: "", render: (r) => (r.incomplete ? h("span", { class: "warn small" }, `${r.incomplete} position(s) without sensitivity or beta`) : "") }], bk.scenarios) : null,
      bk.positions && bk.positions.length ? note(bk.note) : null));
    clear(fxBox, section("Currency strength today", (fx.rows || []).length ? h("div", { class: "scroll" }, table(
      (fx.rows || []).map((r) => ({ label: r.currency, num: true, cls: () => dir(r.strength), render: () => pct(r.strength, 2) })), [0])) : note("No FX quotes."),
      note(`${fx.note || ""} Source: ${fx.source || "?"}.`)));
    clear(specsBox, (sp.rows || []).length ? section("Instrument sheet", h("details", null, h("summary", { class: "small" }, `${sp.rows.length} symbols: spread, money per point, swaps`),
      h("div", { class: "scroll" }, table([{ label: "Account", render: (r) => r.account }, { label: "Symbol", render: (r) => r.symbol },
        { label: "Spread (pts)", num: true, render: (r) => num(r.spread_points, 0) }, { label: "Money per 1.0", num: true, render: (r) => num(r.money_per_unit, 2) },
        { label: "Swap long", num: true, render: (r) => (r.swap_long_money != null ? num(r.swap_long_money, 2) : num(r.swap_long, 2)) },
        { label: "Swap short", num: true, render: (r) => (r.swap_short_money != null ? num(r.swap_short_money, 2) : num(r.swap_short, 2)) },
        { label: "3× swap", render: (r) => r.triple_day }, { label: "Min lot", num: true, render: (r) => num(r.min_lot, 2) },
        { label: "Contract", num: true, render: (r) => num(r.contract, 0) }], sp.rows)))) : null);
  };
  const perf = (rows) => table([
    { label: "Account", render: (r) => r.account }, { label: "Setup", render: (r) => r.label }, { label: "Trades", num: true, render: (r) => r.trades },
    { label: "Win rate", num: true, render: (r) => r.win_rate != null ? num(r.win_rate * 100, 0) + "%" : "–" },
    { label: "Net", num: true, cls: (r) => dir(r.net), render: (r) => num(r.net, 2) },
  ], rows || [], { empty: "No closed trades in this window." });
  await load();
  loadExtras();
  const t2 = setInterval(loadExtras, 60000);
  const t = setInterval(load, 5000);
  return () => { clearInterval(t); clearInterval(t2); };
}
