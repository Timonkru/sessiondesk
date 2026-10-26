// Movers: unusual-move scan over the indices you pick, biggest moves, alert history with explanations.
// The watchlist itself lives on the Markets page; its stocks are always part of the scan.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, pct, num, dir, stamp, clock, day, asOf, note, loading, errorBox, markdown } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const scope = h("div"), mv = h("div"), al = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Movers"), h("span", { class: "meta" }, "unusual moves across the indices you scan and your watchlist")),
    h("div", { class: "cols" }, h("div", null, mv, scope), al));
  const state = { watch: null, movers: null, alerts: null };
  const pushCtx = () => ctx.setContext({
    page: "Movers",
    flagged_moves: state.movers && (state.movers.flagged || []).map((f) => ({ symbol: f.symbol, name: f.name, pct: f.pct, z: f.z, explanation: f.explanation })),
    recent_alerts: state.alerts && state.alerts.slice(0, 15).map((a) => ({ title: a.title, body: a.body, ai: a.ai })),
  });

  // ---------------------------------------------------------------- which indices the scan covers (same list as Screener / Indices)
  const loadUniverses = async () => {
    const u = await api("/api/universes", { fresh: true });
    const boxes = (u.items || []).map((x) => [x.key, h("input", { type: "checkbox", checked: (u.scan || []).includes(x.key) }), `${x.name} (${x.members})`]);
    const status = h("span", { class: "small muted" });
    clear(scope, section("Indices to scan", h("div", { class: "screenfilters" }, boxes.map(([, box, label]) => h("label", null, box, " ", label))),
      h("div", { class: "toolbar" }, h("button", { onclick: async () => {
        const r = await api("/api/universes/scan", { method: "PUT", body: { keys: boxes.filter(([, b]) => b.checked).map(([k]) => k) } });
        status.textContent = r.error || "saved - scanning…";
        if (!r.error) await loadMovers(true);
        status.textContent = r.error || "";
      } }, "Save & scan"), status),
      note("The Screener and the Indices page offer the same indices for filtering and breadth.")));
  };

  // ---------------------------------------------------------------- movers
  const loadMovers = async (force = false) => {
    clear(mv, section("Unusual moves", loading(force ? "Scanning the index members…" : "Loading the last scan…")));
    const d = force ? await api("/api/movers/scan", { method: "POST" }) : await api("/api/movers", { fresh: true });
    state.movers = d;
    if (d.error) { clear(mv, section("Unusual moves", errorBox(d.error))); return; }
    const r = d.rules || {};
    clear(mv, section("Unusual moves",
      h("div", { class: "toolbar" }, h("span", { class: "muted small" }, `${d.scanned} stocks traded today (${(d.universes || []).join(", ")})`
        + (d.not_traded_today ? ` · ${d.not_traded_today} not yet today (shown below as the last session)` : "") + " · "),
        asOf(d.asof, { label: "scanned", maxAgeHours: 0.25 }), h("button", { onclick: () => loadMovers(true) }, "Scan now")),
      note(`Flag rule: |move| ≥ ${r.min_abs_pct}% and ≥ ${r.min_abs_z} σ of the stock's own 60-day daily volatility, or ≥ ${r.always_abs_pct}% outright; watchlist from ${r.watchlist_abs_pct}% / ${r.watchlist_abs_z} σ. Change it in Settings.`),
      (d.flagged || []).length ? h("ul", { class: "feed" }, d.flagged.map((f) => h("li", null,
        h("div", { class: "t" }, h("a", { href: "#/stock/" + encodeURIComponent(f.symbol) }, f.symbol), " ", h("span", { class: dir(f.pct) }, pct(f.pct, 1)),
          f.z != null ? h("span", { class: "muted" }, ` · ${num(f.z, 1)} σ`) : null, h("span", { class: "muted" }, " · " + (f.name || "") + " · " + (f.universe || ""))),
        h("div", { class: "small", style: { color: "var(--fg2)" } }, f.explanation),
        (f.headlines || []).length ? h("div", { class: "m" }, f.headlines.slice(0, 3).map((x) => h("div", null, "· ", x.url ? h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, x.title) : x.title))) : null)))
        : note("Nothing unusual right now."),
      h("h3", null, "Biggest moves today"),
      h("div", { class: "cols", style: { gap: "0 20px" } },
        moverTable("Gainers", d.gainers || []), moverTable("Losers", d.losers || [])),
      (d.previous_session || []).length ? h("div", null, h("h3", null, "Last session (not traded yet today)"),
        note("Unusual moves of stocks whose market has not opened today - e.g. US stocks before 15:30 CET. They are the previous session's moves, not news of today."),
        table([{ label: "", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
          { label: "Δ %", num: true, cls: (r) => dir(r.pct), render: (r) => pct(r.pct, 1) },
          { label: "σ", num: true, render: (r) => r.z != null ? num(r.z, 1) : "–" },
          { label: "Session", render: (r) => h("span", { class: "muted small" }, day(r.time)) },
          { label: "", render: (r) => h("span", { class: "muted small" }, r.universe || "") }], d.previous_session)) : null));
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

  await Promise.all([loadUniverses(), loadMovers(), loadAlerts()]);
  const off1 = on("alert", () => { loadAlerts(); loadMovers(); });
  const off2 = on("alert_ai", loadAlerts);
  return () => { off1(); off2(); };
}
