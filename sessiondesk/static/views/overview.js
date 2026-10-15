// Markets overview: cross-asset board + next releases + unusual moves + squawk.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, sparkline, price, pct, signed, dir, ago, clock, day, countdown, note, loading, errorBox } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const left = h("div"), right = h("div"), meta = h("span", { class: "meta" });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Markets"), meta),
    h("div", { class: "cols" }, left, right));
  left.appendChild(loading());

  const board = async () => {
    const d = await api("/api/overview", { fresh: true });
    if (d.error) { clear(left, errorBox(d.error)); return; }
    clear(left);
    const groups = d.groups || [];
    for (const g of groups) {
      const isRates = g.title === "Rates";
      left.appendChild(section(g.title, table([
        { label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.label) },
        { label: "Last", num: true, render: (r) => isRates ? (r.price != null ? r.price.toFixed(3) + "%" : "–") : price(r.price) },
        { label: isRates ? "Δ bp" : "Δ %", num: true, cls: (r) => dir(r.change_pct),
          render: (r) => isRates ? signed(r.change_bp, 1) : pct(r.change_pct) },
        { label: "Today", num: true, render: (r) => sparkline(r.spark, { ref: r.prev_close }) },
        { label: "", num: true, render: (r) => h("span", { class: "muted small" }, r.time ? ago(r.time) : "") },
      ], g.rows)));
    }
    meta.textContent =
      `Yahoo quotes, delayed per exchange rules · updated ${clock(d.asof)}` + (d.missing && d.missing.length ? ` · no data: ${d.missing.join(", ")}` : "");
    ctx.setContext({ page: "Markets overview", groups: groups.map((g) => ({ group: g.title, rows: g.rows.map((r) => ({ name: r.label, symbol: r.symbol, last: r.price, change_pct: r.change_pct, change_bp: r.change_bp })) })) });
  };

  const events = h("div"), moves = h("div"), squawk = h("ul", { class: "feed" });
  right.append(section("Next high-impact releases", events), section("Unusual moves today", moves), section("Squawk", squawk));

  const loadEvents = async () => {
    const d = await api("/api/calendar?days=4&back_hours=6", { ttl: 30000 });
    const now = Date.now() / 1000;
    const rows = (d.events || []).filter((e) => e.impact === "high" && e.ts > now - 6 * 3600).slice(0, 8);
    clear(events, table([
      { label: "When", render: (e) => e.ts > now ? (e.ts - now < 86400 ? "in " + countdown(e.ts - now) : day(e.ts) + " " + clock(e.ts)) : clock(e.ts) },
      { label: "", render: (e) => e.currency },
      { label: "Event", render: (e) => e.title },
      { label: "Fcst", num: true, render: (e) => e.forecast ?? "" },
      { label: "Actual", num: true, render: (e) => e.actual ?? "", cls: (e) => e.surprise > 0 ? "up" : e.surprise < 0 ? "down" : "" },
    ], rows, { empty: "No high-impact releases in the next days.", onRow: () => ctx.go("#/calendar") }));
  };

  const loadMoves = async () => {
    const d = await api("/api/alerts?limit=8&kind=move", { fresh: true });
    const items = (d.items || []).filter((a) => a.ts > Date.now() / 1000 - 86400);
    clear(moves, items.length ? h("ul", { class: "feed" }, items.map((a) => h("li", { class: "click", onclick: () => ctx.go("#/stock/" + encodeURIComponent(a.symbol)) },
      h("div", { class: "t " + dir(a.data && a.data.pct) }, a.title + "  ", h("span", { class: "muted small" }, a.data && a.data.name || "")),
      h("div", { class: "m" }, (a.body || "").split(". ").slice(1, 3).join(". "))))) : note("No unusual moves flagged in the last 24 hours. The scan runs every few minutes while markets are open."));
  };

  const loadSquawk = async () => {
    const d = await api("/api/news?group=squawk&limit=14", { fresh: true });
    clear(squawk, (d.items || []).map(item));
  };
  const item = (n, fresh) => h("li", { class: (n.impact === "high" ? "high " : "") + (fresh ? "fresh" : "") },
    h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
    h("div", { class: "m" }, `${clock(n.published)} · ${n.source}`, n.impact === "high" ? h("span", { class: "imp" }, " · " + (n.tags[0] || "high impact")) : ""));

  await Promise.all([board(), loadEvents(), loadMoves(), loadSquawk()]);
  const offNews = on("news", ({ item: n }) => { if (n.group === "squawk") { squawk.prepend(item(n, true)); while (squawk.children.length > 14) squawk.lastChild.remove(); } });
  const offAlert = on("alert", loadMoves);
  const t1 = setInterval(board, 20000), t2 = setInterval(loadEvents, 60000);
  return () => { clearInterval(t1); clearInterval(t2); offNews(); offAlert(); };
}
