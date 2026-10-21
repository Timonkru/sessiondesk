// My desk: your own screens of tiles (quotes, a chart, an instrument, Data hub series, news, calendar, alerts, a basket,
// tankers, sectors, index movers). Several layouts as tabs. Tiles are dragged by their title bar and resized at the
// bottom-right corner on a free 24-column grid (lib/gridlayout.js); "Edit" adds, configures and removes them. Saved in settings.
// Linked tiles (Bloomberg's launchpad groups): tiles in group A (or B) follow the symbol you click in any tile of that
// group - the chart and the instrument tile jump to it; Ctrl/Cmd-click still opens the full page.
import { api } from "../lib/api.js";
import { lineChart, multiChart } from "../lib/chart.js";
import { h, clear, table, num, pct, price, dir, sparkline, note, loading, errorBox, clock, day, toast } from "../lib/ui.js";
import { COLS, normalize, arrange, bottom } from "../lib/gridlayout.js";

// w: default width out of 24 columns, h: default height in grid rows
const TILES = {
  quotes: { label: "Quotes", params: [["symbols", "symbols, comma separated", "^GSPC,^GDAXI,EURUSD=X,GC=F"]], every: 20, w: 8, h: 12 },
  chart: { label: "Chart", params: [["symbol", "symbol", "^GSPC"], ["range", "1d, 5d, 1mo, 6mo, 1y, 5y", "5d"]], every: 60, w: 12, h: 10 },
  instrument: { label: "Instrument", params: [["symbol", "symbol", "AAPL"]], every: 60, w: 8, h: 12 },
  hub: { label: "Data hub series", params: [["ids", "series ids, comma separated (see Data hub)", "fred:BAMLH0A0HYM2"], ["range", "1y, 3y, 5y, max", "1y"]], every: 300, w: 12, h: 10 },
  news: { label: "News", params: [["market", "market: us, europe, uk, japan, china, rates, fx, energy, metals, agri, crypto, tech - or empty", ""], ["impact", "high or empty", "high"]], every: 30, w: 8, h: 14 },
  calendar: { label: "Calendar", params: [["hours", "hours ahead", "24"]], every: 60, w: 8, h: 12 },
  alerts: { label: "Alerts", params: [], every: 30, w: 8, h: 8 },
  basket: { label: "Basket", params: [["id", "basket id (see Baskets)", ""]], every: 300, w: 8, h: 9 },
  stocks: { label: "Movers in a list", params: [["scope", "index:dax40, index:sp500, region:eu, all ...", "index:dax40"], ["n", "how many each way", "5"]], every: 120, w: 8, h: 10 },
  sectors: { label: "Sector heat", params: [["region", "us or eu", "us"], ["period", "1d, 1w, 1m, 3m, ytd, 1y", "1m"]], every: 300, w: 12, h: 10 },
  tankers: { label: "Tankers (AIS)", params: [], every: 60, w: 8, h: 9 },
};
const defH = (type) => (TILES[type] || {}).h || 10;
const ROW = 22, GAP = 8, MIN_W = 3, MIN_H = 3, MAX_H = 60;
const FITS = new Set(["chart", "hub", "basket"]);           // tiles whose chart fills the tile: redrawn after a resize
// chart height in the chart's own units (it is 1000 wide and scales with the tile) so it fills the rest of the tile body
const fitH = (body, reserve) => Math.round((1000 * Math.max(60, (body.clientHeight || 200) - reserve)) / (body.clientWidth || 600));
const LINKABLE = new Set(["chart", "instrument"]);          // tiles that follow their group's symbol
const LINK_GROUPS = [["", "no link"], ["A", "group A"], ["B", "group B"]];
const linkStore = {
  get: () => { try { return JSON.parse(localStorage.getItem("sd.deskLinks") || "{}"); } catch { return {}; } },
  set: (v) => { try { localStorage.setItem("sd.deskLinks", JSON.stringify(v)); } catch { /* storage blocked */ } },
};
const heat = (v, scale) => (v == null ? "var(--bg2)" : `rgba(${v >= 0 ? "22, 163, 74" : "220, 38, 38"}, ${Math.min(1, Math.abs(v) / scale) * 0.75 + 0.08})`);
const link = (href, text) => h("a", { href }, text);

// ---------------------------------------------------------------- tile renderers: (params, body, ctx) -> { title, facts }
const RENDER = {
  async quotes(p, body) {
    const syms = (p.symbols || "").split(",").map((s) => s.trim()).filter(Boolean);
    const d = await api("/api/quotes?symbols=" + encodeURIComponent(syms.join(",")), { fresh: true });
    const q = d.quotes || {};
    clear(body, table([
      { label: "", render: (s) => link("#/stock/" + encodeURIComponent(s), s) },
      { label: "Last", num: true, render: (s) => price((q[s] || {}).price) },
      { label: "Today", num: true, cls: (s) => dir((q[s] || {}).change_pct), render: (s) => pct((q[s] || {}).change_pct) },
      { label: "", num: true, render: (s) => sparkline((q[s] || {}).spark, { ref: (q[s] || {}).prev_close, width: 70 }) },
    ], syms));
    return { title: "Quotes", facts: syms.map((s) => ({ symbol: s, price: (q[s] || {}).price, change_pct: (q[s] || {}).change_pct })) };
  },
  async chart(p, body) {
    const sym = p.symbol || "^GSPC", range = p.range || "5d";
    const d = await api(`/api/stock/${encodeURIComponent(sym)}/history?range=${encodeURIComponent(range)}`, { ttl: 30000 });
    if (d.error) { clear(body, errorBox(d.error)); return { title: sym }; }
    const bars = d.bars || [];
    const intraday = ["1d", "5d"].includes(range);
    clear(body, h("p", { class: "small" }, link("#/stock/" + encodeURIComponent(sym), d.name || sym), " ", h("span", { class: dir(d.change_pct) }, pct(d.change_pct))),
      lineChart(bars.map((b) => ({ x: b.t, y: b.c })), { height: fitH(body, 34), area: true, fmtY: (v) => price(v),
        fmtX: (t) => (intraday ? `${day(t)} ${clock(t)}` : new Date(t * 1000).toISOString().slice(0, 10)) }));
    return { title: `${sym} · ${range}`, facts: { symbol: sym, range, last: d.price, change_pct: d.change_pct } };
  },
  async instrument(p, body) {
    const sym = (p.symbol || "AAPL").toUpperCase();
    const enc = encodeURIComponent(sym);
    const [s, n] = await Promise.all([api(`/api/stock/${enc}`, { ttl: 30000 }), api(`/api/stock/${enc}/news`, { ttl: 60000 })]);
    if (s.error) { clear(body, errorBox(s.error)); return { title: sym }; }
    const q = s.quote || {}, pr = s.profile || {};
    const items = [...(n.wire || []), ...(n.items || [])].sort((a, b) => (b.published || 0) - (a.published || 0)).slice(0, 5);
    const kv = [["Last", price(q.price)], ["Today", h("span", { class: dir(q.change_pct) }, pct(q.change_pct))],
      ["52w range", pr.low_52w ? `${price(pr.low_52w)} - ${price(pr.high_52w)}` : "–"], ["Market cap", pr.market_cap ? num(pr.market_cap / 1e9, 1) + " B" : "–"],
      ["Fwd P/E", pr.pe_forward ? num(pr.pe_forward, 1) : "–"], ["Next earnings", pr.earnings_ts ? day(pr.earnings_ts) : "–"]];
    clear(body, h("p", null, link("#/stock/" + enc, h("strong", null, sym)), " ", h("span", { class: "small" }, pr.name || q.name || "")),
      h("dl", { class: "kv" }, kv.map(([k, v]) => [h("dt", null, k), h("dd", null, v)])),
      items.length ? h("ul", { class: "feed compact" }, items.map((x) => h("li", null, h("div", { class: "t small" }, x.title),
        h("div", { class: "m" }, `${clock(x.published)} · ${x.source}`)))) : note("No recent headlines."));
    return { title: `Instrument · ${sym}`, facts: { symbol: sym, price: q.price, change_pct: q.change_pct, headlines: items.map((x) => x.title) } };
  },
  async hub(p, body) {
    const ids = (p.ids || "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 6);
    const got = (await Promise.all(ids.map((id) => api(`/api/hub/series/${encodeURIComponent(id)}`, { ttl: 300000 })))).filter((d) => !d.error);
    if (!got.length) { clear(body, note("No such series - copy ids from the Data hub (e.g. fred:DGS10, mkt:^VIX, eia:cushing_crude_stocks).")); return { title: "Data hub" }; }
    const years = { "1y": 1, "3y": 3, "5y": 5 }[p.range || "1y"] || 0;
    const start = years ? new Date(Date.now() - years * 365.25 * 86400000).toISOString().slice(0, 10) : "0000";
    if (got.length === 1) {
      const pts = got[0].points.filter(([dd]) => dd >= start);
      clear(body, h("p", { class: "small" }, link("#/hub/" + encodeURIComponent(got[0].meta.id), got[0].meta.name)),
        lineChart(pts.map(([x, y]) => ({ x, y })), { height: fitH(body, 34), area: false, fmtY: (v) => num(v, Math.abs(v) < 10 ? 2 : 1), fmtX: (x) => x }));
    } else {
      const days = [...new Set(got.flatMap((g) => g.points.map((q) => q[0])))].filter((dd) => dd >= start).sort();
      const lines = got.map((g) => {
        const m = new Map(g.points); let last = null; let base = null;
        const vals = days.map((dd) => { if (m.has(dd)) last = m.get(dd); if (last != null && base == null && last > 0) base = last; return last == null || !base ? null : (last / base) * 100; });
        return { label: g.meta.name, values: vals };
      });
      clear(body, multiChart(days, lines, { height: fitH(body, 60), fmtY: (v) => num(v, 0) }), h("p", { class: "small muted" }, "rebased to 100 at the start"));
    }
    return { title: got.length === 1 ? got[0].meta.name : "Data hub", facts: got.map((g) => ({ name: g.meta.name, last: g.points.at(-1) })) };
  },
  async news(p, body) {
    const qs = new URLSearchParams({ limit: "12", ...(p.market ? { market: p.market } : {}), ...(p.impact ? { impact: p.impact } : {}) });
    const d = await api("/api/news?" + qs, { fresh: true });
    const items = (d.items || []).slice(0, 12);
    clear(body, items.length ? h("ul", { class: "feed compact" }, items.map((n) => h("li", null,
      h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer", style: { color: "inherit" } }, n.title) : n.title),
      h("div", { class: "m" }, `${clock(n.published)} · ${n.source}`)))) : note("No headlines."));
    return { title: `News${p.market ? " · " + p.market : ""}${p.impact ? " · " + p.impact : ""}`, facts: items.slice(0, 8).map((n) => n.title) };
  },
  async calendar(p, body) {
    const hours = Math.max(1, Math.min(168, Number(p.hours) || 24));
    const d = await api(`/api/calendar?days=${Math.ceil(hours / 24)}&back_hours=1`, { ttl: 60000 });
    const now = Date.now() / 1000;
    const ev = (d.events || []).filter((e) => e.ts >= now - 3600 && e.ts <= now + hours * 3600 && e.impact !== "low").slice(0, 14);
    clear(body, table([
      { label: "", render: (e) => h("span", { class: "small" }, `${day(e.ts)} ${clock(e.ts)}`) },
      { label: "", render: (e) => h("span", { class: e.impact === "high" ? "warn" : "" }, `${e.currency} ${e.title}`) },
      { label: "Act / fcst", num: true, render: (e) => h("span", { class: "small" }, `${e.actual ?? "–"} / ${e.forecast ?? "–"}`) },
    ], ev, { empty: "Nothing medium or high impact." }), h("p", { class: "small" }, link("#/calendar", "full calendar →")));
    return { title: `Calendar · next ${hours} h`, facts: ev.map((e) => `${e.currency} ${e.title}`) };
  },
  async alerts(p, body) {
    const d = await api("/api/price_alerts", { fresh: true });
    const rows = (d.alerts || []).slice(0, 12);
    clear(body, table([
      { label: "", render: (a) => h("span", { class: "small" }, a.title) },
      { label: "Now", num: true, render: (a) => num(a.value, 2) },
      { label: "", render: (a) => (a.active ? h("span", { class: "small up" }, "watching") : h("span", { class: "small warn" }, "fired")) },
    ], rows, { empty: "No alerts yet." }), h("p", { class: "small" }, link("#/alerts", "manage alerts →")));
    return { title: "Alerts", facts: rows.map((a) => ({ title: a.title, active: a.active })) };
  },
  async basket(p, body) {
    if (!p.id) { clear(body, note("Pick a basket id (Baskets page, in the address after #/baskets/).")); return { title: "Basket" }; }
    const d = await api(`/api/baskets/${encodeURIComponent(p.id)}`, { ttl: 120000 });
    if (d.error) { clear(body, errorBox(d.error)); return { title: "Basket" }; }
    const r = d.returns || {}, br = d.benchmark_returns || {};
    clear(body, h("p", { class: "small" }, link("#/baskets/" + encodeURIComponent(p.id), d.basket.name), ` · 1 month ${pct(r["1m"], 1)} vs ${pct(br["1m"], 1)} · YTD ${pct(r.ytd, 1)} vs ${pct(br.ytd, 1)}`),
      lineChart(d.line.slice(-260).map(([x, y]) => ({ x, y })), { height: fitH(body, 48), area: false, ref: 100, fmtY: (v) => num(v, 0), fmtX: (x) => x }));
    return { title: `Basket · ${d.basket.name}`, facts: { returns: r, benchmark: br } };
  },
  async stocks(p, body) {
    const d = await api(`/api/stocks?scope=${encodeURIComponent(p.scope || "index:dax40")}`, { ttl: 60000 });
    if (d.error) { clear(body, errorBox(d.error)); return { title: "Movers" }; }
    const n = Math.max(1, Math.min(15, Number(p.n) || 5));
    const s = d.rows.filter((r) => r.chg1d != null).sort((a, b) => b.chg1d - a.chg1d);
    const mini = (rows) => table([{ label: "", render: (r) => link("#/stock/" + encodeURIComponent(r.symbol), r.symbol) },
      { label: "", render: (r) => h("span", { class: "small" }, (r.name || "").slice(0, 22)) },
      { label: "", num: true, cls: (r) => dir(r.chg1d), render: (r) => pct(r.chg1d, 1) }], rows);
    clear(body, h("div", { class: "cols" }, mini(s.slice(0, n)), mini(s.slice(-n).reverse())),
      h("p", { class: "small muted" }, `${s.filter((r) => r.chg1d > 0).length} of ${s.length} up today`));
    return { title: `Movers · ${d.label}`, facts: { up: s.slice(0, n).map((r) => [r.symbol, r.chg1d]), down: s.slice(-n).map((r) => [r.symbol, r.chg1d]) } };
  },
  async sectors(p, body) {
    const region = p.region === "eu" ? "eu" : "us", period = p.period || "1m";
    const d = await api("/api/sectors/" + region, { ttl: 300000 });
    if (d.error) { clear(body, errorBox(d.error)); return { title: "Sectors" }; }
    const scale = { "1d": 2, "1w": 4, "1m": 8, "3m": 15, ytd: 25, "1y": 30 }[period] || 8;
    const rows = [...d.rows].sort((a, b) => (b[period] ?? -1e9) - (a[period] ?? -1e9));
    clear(body, h("div", { class: "heat" }, rows.map((r) => h("a", { class: "heattile", href: `#/sectors/${region}/${encodeURIComponent(r.symbol)}`,
      style: { background: heat(r[period], scale) } }, h("div", { class: "hn" }, r.name), h("div", { class: "hv" }, pct(r[period], 1))))));
    return { title: `Sectors · ${region === "us" ? "US" : "Europe"} · ${period}`, facts: rows.map((r) => [r.name, r[period]]) };
  },
  async tankers(p, body) {
    const d = await api("/api/tankers", { fresh: true });
    if (!d.configured) { clear(body, note("Needs your free aisstream.io key (Settings → Connectors).")); return { title: "Tankers" }; }
    clear(body, table([{ label: "", render: (r) => h("span", { class: "small" }, r.name) },
      { label: "Tankers", num: true, render: (r) => r.tankers }, { label: "slow", num: true, render: (r) => r.slow },
      { label: "today", num: true, render: (r) => r.today }], d.chokepoints.filter((r) => r.vessels)), h("p", { class: "small" }, link("#/tankers", "details →")));
    return { title: "Tankers (AIS)", facts: d.chokepoints.map((r) => [r.name, r.tankers]) };
  },
};

// ---------------------------------------------------------------- page
export async function render(root, params, ctx) {
  const desk = await api("/api/desk", { fresh: true });
  desk.layouts.forEach((l) => { l.tiles = arrange(normalize(l.tiles || [], defH)); });
  let editing = false;
  const timers = [];
  const groupSym = linkStore.get();          // {A: "NVDA", B: "^GDAXI"}
  let runners = [];                           // {group, run} of linkable tiles on screen
  let els = [], runs = [];                    // tile elements and their refresh functions, by tile index
  const setGroup = (g, sym) => {
    groupSym[g] = sym;
    linkStore.set(groupSym);
    runners.filter((r) => r.group === g).forEach((r) => r.run());
  };
  const bar = h("div", { class: "toolbar" }), grid = h("div", { class: "desk" }), addBox = h("div");
  const ghost = h("div", { class: "tileghost", hidden: true });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "My desk"),
    h("span", { class: "meta" }, "your own screen - drag a tile by its title bar, resize it at the bottom-right corner")), bar, addBox, grid);
  const facts = {};

  const save = async () => {
    const r = await api("/api/desk", { method: "PUT", body: desk });
    if (r.error) toast("Desk not saved", r.error);
  };
  const layout = () => desk.layouts[Math.min(desk.active || 0, desk.layouts.length - 1)];

  // ---- geometry: grid cells -> pixels; below 700 px the tiles stack in one column and do not drag
  const narrow = () => grid.clientWidth < 700;
  const cellW = () => (grid.clientWidth - GAP * (COLS - 1)) / COLS;
  const rect = (t) => {
    const cw = cellW();
    return { left: t.x * (cw + GAP), top: t.y * (ROW + GAP), width: t.w * cw + (t.w - 1) * GAP, height: t.h * ROW + (t.h - 1) * GAP };
  };
  const setRect = (el, r) => Object.assign(el.style, { left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
  const place = (tiles, skip = -1, extra = 0) => {
    if (narrow()) {
      let top = 0;
      tiles.map((_, i) => i).sort((a, b) => tiles[a].y - tiles[b].y || tiles[a].x - tiles[b].x).forEach((i) => {
        const hh = tiles[i].h * ROW + (tiles[i].h - 1) * GAP;
        setRect(els[i], { left: 0, top, width: grid.clientWidth, height: hh });
        top += hh + GAP;
      });
      grid.style.height = top + "px";
      return;
    }
    tiles.forEach((t, i) => { if (i !== skip && els[i]) setRect(els[i], rect(t)); });
    grid.style.height = (bottom(tiles) + extra) * (ROW + GAP) + "px";
  };

  // ---- drag to move (title bar) or resize (corner grip); the others make room live, a dashed ghost shows the drop
  const startDrag = (e, i, mode) => {
    if (e.button !== 0 || narrow()) return;
    if (mode === "move" && e.target.closest("button, select, input, a, label")) return;
    e.preventDefault();
    const tiles = layout().tiles, t0 = { ...tiles[i] }, el = els[i], r0 = rect(t0);
    const sx = e.clientX, sy = e.clientY;
    let moved = false, cur = tiles;
    el.setPointerCapture(e.pointerId);
    const onMove = (ev) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      if (!moved) { moved = true; el.classList.add("lifted"); grid.classList.add("busy"); ghost.hidden = false; }
      const cw = cellW();
      let cand;
      if (mode === "move") {
        el.style.left = r0.left + dx + "px";
        el.style.top = Math.max(0, r0.top + dy) + "px";
        cand = { ...t0, x: Math.round((r0.left + dx) / (cw + GAP)), y: Math.max(0, Math.round((r0.top + dy) / (ROW + GAP))) };
      } else {
        el.style.width = Math.max(cw * MIN_W, r0.width + dx) + "px";
        el.style.height = Math.max(ROW * MIN_H, r0.height + dy) + "px";
        cand = { ...t0, w: Math.max(MIN_W, Math.min(COLS - t0.x, Math.round((r0.width + dx + GAP) / (cw + GAP)))),
          h: Math.max(MIN_H, Math.min(MAX_H, Math.round((r0.height + dy + GAP) / (ROW + GAP)))) };
      }
      cur = arrange(tiles.map((t, k) => (k === i ? cand : t)), i);
      place(cur, i, 6);
      setRect(ghost, rect(cur[i]));
    };
    const onUp = async () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      if (!moved) return;
      el.classList.remove("lifted");
      grid.classList.remove("busy");
      ghost.hidden = true;
      tiles.forEach((t, k) => Object.assign(t, { x: cur[k].x, y: cur[k].y, w: cur[k].w, h: cur[k].h }));
      place(tiles);
      if (t0.w !== tiles[i].w || t0.h !== tiles[i].h) setTimeout(() => runs[i] && runs[i].run(), 200);   // after the size transition
      await save();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
  };

  const drawBar = () => clear(bar,
    h("span", { class: "tabs inline" }, desk.layouts.map((l, i) => h("button", { class: i === (desk.active || 0) ? "on" : "", onclick: async () => { desk.active = i; await save(); draw(); } }, l.name))),
    editing ? [
      h("button", { class: "linkish", onclick: async () => { const n = prompt("Name of the new layout", "Desk " + (desk.layouts.length + 1)); if (!n) return; desk.layouts.push({ name: n, tiles: [] }); desk.active = desk.layouts.length - 1; await save(); draw(); } }, "+ layout"),
      h("button", { class: "linkish", onclick: async () => { const n = prompt("Rename layout", layout().name); if (!n) return; layout().name = n; await save(); draw(); } }, "rename"),
      desk.layouts.length > 1 ? h("button", { class: "linkish", onclick: async () => { if (!confirm(`Delete layout ${layout().name}?`)) return; desk.layouts.splice(desk.active, 1); desk.active = 0; await save(); draw(); } }, "delete layout") : null,
    ] : null,
    h("button", { onclick: () => { editing = !editing; draw(); } }, editing ? "Done" : "Edit"));

  const drawAdd = () => {
    if (!editing) { clear(addBox); return; }
    const type = h("select", null, Object.entries(TILES).map(([k, t]) => h("option", { value: k }, t.label)));
    const inputs = h("span");
    const fill = () => clear(inputs, TILES[type.value].params.map(([k, hint, def]) => h("input", { type: "text", dataset: { k }, value: def, title: hint, placeholder: hint, style: { width: "220px" } })));
    type.addEventListener("change", fill);
    fill();
    clear(addBox, h("div", { class: "toolbar deskadd" }, h("strong", { class: "small" }, "Add a tile"), type, inputs,
      h("button", { onclick: async () => {
        const p = {}; inputs.querySelectorAll("input").forEach((i) => { p[i.dataset.k] = i.value.trim(); });
        const spec = TILES[type.value];
        layout().tiles.push({ type: type.value, x: 0, y: bottom(layout().tiles), w: spec.w, h: spec.h, params: p });
        await save(); draw();
      } }, "Add")));
  };

  const tileEl = (t, i) => {
    const spec = TILES[t.type];
    const body = h("div", { class: "tilebody" }, spec ? loading() : errorBox("unknown tile type " + t.type));
    const title = h("span", { class: "tiletitle" }, spec ? spec.label : t.type);
    const group = (t.params || {}).link || "";
    const badge = group ? h("span", { class: "linkbadge", title: `linked: clicking a symbol in a group-${group} tile moves every group-${group} tile` }, group) : null;
    const params = () => ({ ...(t.params || {}), ...(group && LINKABLE.has(t.type) && groupSym[group] ? { symbol: groupSym[group] } : {}) });
    const tools = editing ? h("span", { class: "tiletools" },
      h("button", { class: "linkish", title: "settings", onclick: () => {
        const box = h("div", { class: "tileedit" }, (spec ? spec.params : []).map(([k, hint]) => h("label", { class: "small" }, hint,
          h("input", { type: "text", dataset: { k }, value: (t.params || {})[k] ?? "", style: { width: "100%" } }))),
          h("button", { onclick: async () => { box.querySelectorAll("input").forEach((inp) => { t.params[inp.dataset.k] = inp.value.trim(); }); await save(); draw(); } }, "Apply"));
        clear(body, box);
      } }, "⚙"),
      h("select", { title: "link group", onchange: async (e) => { t.params = { ...(t.params || {}), link: e.target.value }; await save(); draw(); } },
        LINK_GROUPS.map(([v, l]) => h("option", { value: v, selected: v === group }, l))),
      h("button", { class: "linkish", title: "remove", onclick: async () => { const l = layout(); l.tiles.splice(i, 1); l.tiles = arrange(l.tiles); await save(); draw(); } }, "✕")) : null;
    const el = h("section", { class: "tile" + (group ? " linked-" + group : "") },
      h("div", { class: "tilehead", title: "drag to move", onpointerdown: (e) => startDrag(e, i, "move") }, h("span", null, badge, " ", title), tools), body,
      h("div", { class: "tilegrip", title: "drag to resize", onpointerdown: (e) => startDrag(e, i, "resize") }));
    if (group) body.addEventListener("click", (e) => {
      const a = e.target.closest('a[href^="#/stock/"]');
      if (!a || e.ctrlKey || e.metaKey || editing) return;
      e.preventDefault();
      setGroup(group, decodeURIComponent(a.getAttribute("href").split("/")[2] || ""));
    });
    if (spec) {
      const run = async () => {
        try {
          const r = await RENDER[t.type](params(), body, ctx);
          if (r && r.title) title.textContent = r.title;
          facts[`${i + 1}. ${r ? r.title : t.type}`] = r ? r.facts : null;
          ctx.setContext({ page: `My desk - ${layout().name}`, tiles: facts });
        } catch (e) { clear(body, errorBox(String(e))); }
      };
      runs[i] = { run, every: spec.every || 60 };
      if (group && LINKABLE.has(t.type)) runners.push({ group, run });
    }
    return el;
  };

  let lastW = 0, refit = null;
  const draw = () => {
    timers.splice(0).forEach(clearInterval);
    runners = []; runs = [];
    for (const k of Object.keys(facts)) delete facts[k];
    drawBar(); drawAdd();
    const tiles = layout().tiles;
    if (!tiles.length) { els = []; grid.style.height = ""; clear(grid, note("This layout is empty - press Edit and add tiles.")); return; }
    els = tiles.map(tileEl);
    clear(grid, els, ghost);
    place(tiles);
    lastW = grid.clientWidth;
    runs.forEach((r) => { if (!r) return; r.run(); if (!editing) timers.push(setInterval(r.run, r.every * 1000)); });
  };
  // a wider or narrower window moves the tiles at once and redraws the charts once it settles
  const ro = new ResizeObserver(() => {
    const w = grid.clientWidth;
    if (!w || w === lastW || !els.length) return;
    lastW = w;
    place(layout().tiles);
    clearTimeout(refit);
    refit = setTimeout(() => layout().tiles.forEach((t, i) => { if (FITS.has(t.type) && runs[i]) runs[i].run(); }), 400);
  });
  ro.observe(grid);
  draw();
  return () => { timers.splice(0).forEach(clearInterval); ro.disconnect(); clearTimeout(refit); };
}
