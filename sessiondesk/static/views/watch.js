// Watchlist + unusual-move scanner + alert history with explanations.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, sparkline, price, pct, num, dir, stamp, clock, note, loading, errorBox, markdown } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const wl = h("div"), mv = h("div"), al = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Watchlist & movers")), h("div", { class: "cols" }, h("div", null, wl, mv), al));
  const state = { watch: null, movers: null, alerts: null };
  const pushCtx = () => ctx.setContext({
    page: "Watchlist & movers",
    watchlist: state.watch && Object.values(state.watch.quotes || {}).map((q) => ({ symbol: q.symbol, last: q.price, change_pct: q.change_pct })),
    flagged_moves: state.movers && (state.movers.flagged || []).map((f) => ({ symbol: f.symbol, name: f.name, pct: f.pct, z: f.z, explanation: f.explanation })),
    recent_alerts: state.alerts && state.alerts.slice(0, 15).map((a) => ({ title: a.title, body: a.body, ai: a.ai })),
  });

  // ---------------------------------------------------------------- watchlist
  const loadWatch = async () => {
    const d = await api("/api/watchlist", { fresh: true });
    state.watch = d;
    const q = d.quotes || {};
    const editor = h("input", { type: "text", placeholder: "add symbol, e.g. NVDA or SAP.DE", style: { width: "220px" } });
    const add = async () => {
      const sym = editor.value.trim().toUpperCase();
      if (!sym) return;
      await api("/api/watchlist", { method: "PUT", body: { symbols: [...d.symbols, sym] } });
      loadWatch();
    };
    editor.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    clear(wl, section("Watchlist", h("div", { class: "toolbar" }, editor, h("button", { onclick: add }, "Add")),
      table([
        { label: "Symbol", render: (s) => h("a", { href: "#/stock/" + encodeURIComponent(s) }, s) },
        { label: "Last", num: true, render: (s) => price(q[s] && q[s].price) },
        { label: "Δ %", num: true, cls: (s) => dir(q[s] && q[s].change_pct), render: (s) => pct(q[s] && q[s].change_pct) },
        { label: "Today", num: true, render: (s) => sparkline(q[s] && q[s].spark, { ref: q[s] && q[s].prev_close }) },
        { label: "", num: true, render: (s) => h("button", { class: "linkish", onclick: async () => {
          await api("/api/watchlist", { method: "PUT", body: { symbols: d.symbols.filter((x) => x !== s) } }); loadWatch();
        } }, "remove") },
      ], d.symbols || [], { empty: "Your watchlist is empty." }),
      d.error ? errorBox(d.error) : null));
    pushCtx();
  };

  // ---------------------------------------------------------------- movers
  const loadMovers = async (force = false) => {
    clear(mv, section("Unusual moves", loading(force ? "Scanning the index members…" : "Loading the last scan…")));
    const d = force ? await api("/api/movers/scan", { method: "POST" }) : await api("/api/movers", { fresh: true });
    state.movers = d;
    if (d.error) { clear(mv, section("Unusual moves", errorBox(d.error))); return; }
    const r = d.rules || {};
    clear(mv, section("Unusual moves",
      h("div", { class: "toolbar" }, h("span", { class: "muted small" }, `${d.scanned} stocks scanned (${(d.universes || []).join(", ")}) at ${clock(d.asof)}`),
        h("button", { onclick: () => loadMovers(true) }, "Scan now")),
      note(`Flag rule: |move| ≥ ${r.min_abs_pct}% and ≥ ${r.min_abs_z} σ of the stock's own 60-day daily volatility, or ≥ ${r.always_abs_pct}% outright; watchlist from ${r.watchlist_abs_pct}% / ${r.watchlist_abs_z} σ. Change it in Settings.`),
      (d.flagged || []).length ? h("ul", { class: "feed" }, d.flagged.map((f) => h("li", null,
        h("div", { class: "t" }, h("a", { href: "#/stock/" + encodeURIComponent(f.symbol) }, f.symbol), " ", h("span", { class: dir(f.pct) }, pct(f.pct, 1)),
          f.z != null ? h("span", { class: "muted" }, ` · ${num(f.z, 1)} σ`) : null, h("span", { class: "muted" }, " · " + (f.name || "") + " · " + (f.universe || ""))),
        h("div", { class: "small", style: { color: "var(--fg2)" } }, f.explanation),
        (f.headlines || []).length ? h("div", { class: "m" }, f.headlines.slice(0, 3).map((x) => h("div", null, "· ", x.url ? h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, x.title) : x.title))) : null)))
        : note("Nothing unusual right now."),
      h("h3", null, "Biggest moves in the scan"),
      h("div", { class: "cols", style: { gap: "0 20px" } },
        moverTable("Gainers", d.gainers || []), moverTable("Losers", d.losers || []))));
    pushCtx();
  };
  const moverTable = (title, rows) => h("div", null, h("div", { class: "muted small" }, title), table([
    { label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
    { label: "Δ %", num: true, cls: (r) => dir(r.pct), render: (r) => pct(r.pct, 1) },
    { label: "σ", num: true, render: (r) => r.z != null ? num(r.z, 1) : "–" },
  ], rows.slice(0, 10)));

  // ---------------------------------------------------------------- alerts
  const loadAlerts = async () => {
    const d = await api("/api/alerts?limit=60", { fresh: true });
    state.alerts = d.items || [];
    clear(al, section("Alert history", (state.alerts.length ? h("ul", { class: "feed" }, state.alerts.map(alertItem)) : note("No alerts yet."))));
    pushCtx();
  };
  const alertItem = (a) => {
    const aiBox = h("div");
    if (a.ai) aiBox.appendChild(h("div", { class: "small" }, h("span", { class: "muted" }, "AI: "), markdown(a.ai)));
    return h("li", { style: { opacity: a.acked ? 0.6 : 1 } },
      h("div", { class: "t" }, h("a", { href: "#/stock/" + encodeURIComponent(a.symbol) }, a.title), h("span", { class: "muted small" }, "  " + stamp(a.ts))),
      h("div", { class: "small", style: { color: "var(--fg2)" } }, a.body),
      aiBox,
      h("div", { class: "m" },
        h("button", { class: "linkish", onclick: async (e) => {
          e.target.disabled = true; clear(aiBox, h("span", { class: "muted loading small" }, "asking the AI…"));
          const r = await api(`/api/alerts/${a.id}/explain`, { method: "POST" });
          clear(aiBox, r.error ? h("span", { class: "error small" }, r.error) : h("div", { class: "small" }, h("span", { class: "muted" }, "AI: "), markdown(r.text)));
          e.target.disabled = false;
        } }, a.ai ? "re-explain with AI" : "explain with AI"), "  ",
        a.acked ? null : h("button", { class: "linkish", onclick: async () => { await api(`/api/alerts/${a.id}/ack`, { method: "POST" }); loadAlerts(); } }, "mark read")));
  };

  await Promise.all([loadWatch(), loadMovers(), loadAlerts()]);
  const off1 = on("alert", () => { loadAlerts(); loadMovers(); });
  const off2 = on("alert_ai", loadAlerts);
  const t = setInterval(loadWatch, 20000);
  return () => { clearInterval(t); off1(); off2(); };
}
