// Markets: what the markets do now - one cross-asset board (the key indices, futures, rates, FX, commodities, crypto,
// volatility), your watchlist, the live squawk. Every index by region lives on Indices, the sectors on Sectors, so
// this page does not repeat them. Releases live in the Calendar, unusual moves on the Movers page.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, sparkline, price, pct, signed, dir, ago, clock, note, loading, errorBox } from "../lib/ui.js";
import { watchlist } from "../lib/watchlist.js";

const REGIONS = ["Americas", "Europe", "Asia-Pacific", "Middle East & Africa"];
const KEY_INDICES = ["^GSPC", "^NDX", "^DJI", "^RUT", "^GDAXI", "^STOXX50E", "^FTSE", "^N225", "^HSI", "000001.SS"];
const ELSEWHERE = { "US sectors": "#/sectors" };          // full lists with their own page: a link, not a second table

export async function render(root, _params, ctx) {
  const left = h("div"), right = h("div"), meta = h("span", { class: "meta" });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Markets"), meta),
    h("div", { class: "cols" }, left, right));
  left.appendChild(loading());
  const facts = {};
  const push = () => ctx.setContext({ page: "Markets overview", ...facts });

  // Indices with a bundled member list get a link to their breadth page next to the name.
  const withMembers = Object.fromEntries(((await api("/api/universes", { ttl: 600000 })).items || []).map((u) => [u.symbol, u.key]));
  const board = async () => {
    const d = await api("/api/overview", { fresh: true });
    if (d.error) { clear(left, errorBox(d.error)); return; }
    clear(left);
    const all = d.groups || [];
    const idx = all.filter((g) => REGIONS.includes(g.title)).flatMap((g) => g.rows);
    const key = KEY_INDICES.map((s) => idx.find((r) => r.symbol === s)).filter(Boolean);
    const groups = [{ title: "Key indices", rows: key, more: ["all " + idx.length + " indices by region", "#/indices"] },
      ...all.filter((g) => !REGIONS.includes(g.title) && !ELSEWHERE[g.title])];
    for (const g of groups) {
      const isRates = g.title === "Rates";
      left.appendChild(section(g.title, g.more ? h("p", { class: "small", style: { margin: "-4px 0 4px" } }, h("a", { href: g.more[1] }, g.more[0] + " →"), " · ",
        h("a", { href: "#/sectors" }, "sectors →"), " · ", h("a", { href: "#/stocks" }, "stocks →")) : null, table([
        { label: "", render: (r) => [h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.label),
          withMembers[r.symbol] ? h("a", { class: "small muted", style: { marginLeft: "6px" }, href: "#/indices/" + withMembers[r.symbol], title: "members, breadth, drivers, valuation" }, "members ›") : null] },
        { label: "Last", num: true, render: (r) => isRates ? (r.price != null ? r.price.toFixed(3) + "%" : "–") : price(r.price) },
        { label: isRates ? "Δ bp" : "Δ %", num: true, cls: (r) => dir(r.change_pct),
          render: (r) => isRates ? signed(r.change_bp, 1) : pct(r.change_pct) },
        { label: "Today", num: true, render: (r) => sparkline(r.spark, { ref: r.prev_close }) },
        { label: "", num: true, render: (r) => h("span", { class: "muted small" }, r.time ? ago(r.time) : "") },
      ], g.rows)));
    }
    meta.textContent =
      `Yahoo quotes, delayed per exchange rules · updated ${clock(d.asof)}` + (d.missing && d.missing.length ? ` · no data: ${d.missing.join(", ")}` : "");
    facts.groups = groups.map((g) => ({ group: g.title, rows: g.rows.map((r) => ({ name: r.label, symbol: r.symbol, last: r.price, change_pct: r.change_pct, change_bp: r.change_bp })) }));
    push();
  };

  const wl = watchlist((d) => { facts.watchlist = Object.values(d.quotes || {}).map((q) => ({ symbol: q.symbol, last: q.price, change_pct: q.change_pct })); push(); });
  const moves = h("p", { class: "small" }), squawk = h("ul", { class: "feed" });
  right.append(wl.el, moves, section("Squawk", squawk));

  // one line instead of a second list: the moves themselves are on the Movers page
  const loadMoves = async () => {
    const d = await api("/api/alerts?limit=50&kind=move", { fresh: true });
    const items = (d.items || []).filter((a) => a.ts > Date.now() / 1000 - 86400);
    clear(moves, items.length ? h("a", { href: "#/watch" }, `${items.length} unusual move${items.length > 1 ? "s" : ""} in the last 24 h: ${items.slice(0, 4).map((a) => a.title).join(" · ")} →`)
      : h("span", { class: "muted" }, "No unusual moves in the last 24 hours (", h("a", { href: "#/watch" }, "Movers"), ")."));
  };

  const loadSquawk = async () => {
    const d = await api("/api/news?group=squawk&limit=14", { fresh: true });
    clear(squawk, (d.items || []).map(item));
  };
  const item = (n, fresh) => h("li", { class: (n.impact === "high" ? "high " : "") + (fresh ? "fresh" : "") },
    h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
    h("div", { class: "m" }, `${clock(n.published)} · ${n.source}`, n.impact === "high" ? h("span", { class: "imp" }, " · " + (n.tags[0] || "high impact")) : ""));

  await Promise.all([board(), wl.load(), loadMoves(), loadSquawk()]);
  const offNews = on("news", ({ item: n }) => { if (n.group === "squawk") { squawk.prepend(item(n, true)); while (squawk.children.length > 14) squawk.lastChild.remove(); } });
  const offAlert = on("alert", loadMoves);
  const t1 = setInterval(board, 20000), t2 = setInterval(wl.load, 20000);
  return () => { clearInterval(t1); clearInterval(t2); offNews(); offAlert(); };
}
