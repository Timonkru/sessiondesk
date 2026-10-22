// Calendar: one timeline of everything scheduled (releases, earnings that matter, forced flows, your schedule),
// plus the detailed economic calendar (live actuals, reaction history) and the full earnings list.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, clock, day, countdown, note, loading, errorBox, num, pct, dir, big } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  let tab = localStorage.getItem("sd.calTab") || "time", level = localStorage.getItem("sd.calLevel") || "high", events = [];
  const KINDS = [["release", "Releases"], ["earnings", "Earnings"], ["flow", "Forced flows"], ["setup", "My schedule"]];
  const shown = new Set(JSON.parse(localStorage.getItem("sd.calKinds") || '["release","earnings","flow","setup"]'));
  const bar = h("div", { class: "tabs" }), body = h("div"), info = h("p", { class: "note" });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Calendar")), bar, body);
  const drawTabs = () => clear(bar, [["time", "Timeline"], ["eco", "Economic"], ["earn", "Earnings"]].map(([k, l]) =>
    h("button", { class: k === tab ? "on" : "", onclick: () => { tab = k; localStorage.setItem("sd.calTab", k); drawTabs(); draw(); } }, l)));

  // ---------------------------------------------------------------- timeline
  let tl = null;
  const loadTimeline = async () => {
    if (!tl) clear(body, loading());
    tl = await api("/api/timeline?days=7", { fresh: true });
    drawTimeline();
  };
  const drawTimeline = () => {
    if (tab !== "time" || !tl) return;
    if (tl.error) { clear(body, errorBox(tl.error)); return; }
    const now = Date.now() / 1000;
    const want = (x) => shown.has(x.kind === "session" ? "setup" : x.kind);
    const items = (tl.items || []).filter(want);
    const missing = items.filter((x) => x.result && x.result.missing).length;
    const boxes = KINDS.map(([k, label]) => h("label", null, h("input", { type: "checkbox", checked: shown.has(k), onchange: (e) => {
      if (e.target.checked) shown.add(k); else shown.delete(k);
      localStorage.setItem("sd.calKinds", JSON.stringify([...shown])); drawTimeline(); } }), " " + label));
    const byDay = new Map();
    for (const x of items) { if (!byDay.has(x.day)) byDay.set(x.day, []); byDay.get(x.day).push(x); }
    const KIND = { release: "● release", earnings: "◆ earnings", flow: "⇄ flow", setup: "· setup", session: "▸ session" };
    // what came out: the actual against the forecast (releases), EPS against the estimate and the reaction (earnings)
    const result = (x) => {
      const r = x.result;
      if (!r) return "";
      if (r.missing) return h("span", { class: "muted small", title: "No source delivered the actual yet - see the note below the timeline." }, "no actual yet");
      const cls = r.verdict === "above" || r.verdict === "beat" ? "up" : r.verdict === "below" || r.verdict === "miss" ? "down" : "";
      if (x.kind === "earnings") {
        return h("span", { class: "small" }, h("strong", { class: cls }, `EPS ${r.actual ?? "–"}`), ` vs ${r.forecast ?? "–"}`,
          r.surprise_pct != null ? ` (${r.surprise_pct > 0 ? "+" : ""}${num(r.surprise_pct, 1)} %)` : "",
          r.move != null ? h("span", { class: dir(r.move) }, ` · stock ${pct(r.move, 1)}`) : "");
      }
      return h("span", { class: "small" }, h("strong", { class: cls }, r.actual), ` vs ${r.forecast ?? "–"} fcst`,
        r.verdict ? h("span", { class: "muted" }, ` · ${r.verdict}`) : "");
    };
    clear(body, h("div", { class: "screenfilters" }, boxes),
      ...[...byDay].map(([d, rows]) => section(new Date(d + "T12:00:00").toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }), table([
        { label: "Time", render: (x) => (x.ts ? clock(x.ts) : h("span", { class: "muted small" }, "all day")) },
        { label: "In", render: (x) => (!x.ts ? "" : x.ts > now ? (x.ts - now < 86400 ? countdown(x.ts - now) : "") : h("span", { class: "muted" }, "done")) },
        { label: "", render: (x) => h("span", { class: "small " + (x.kind === "release" ? (x.level === "high" ? "warn" : "") : x.kind === "setup" ? "muted" : "") }, KIND[x.kind] || x.kind) },
        { label: "", render: (x) => h("span", { class: "small" }, x.tag || "") },
        { label: "What", render: (x) => (x.link ? h("a", { href: x.link }, x.title) : h("span", { style: { fontWeight: x.kind === "release" && x.level === "high" ? 600 : 400 } }, x.title)) },
        { label: "Result", render: result },
        { label: "", render: (x) => h("span", { class: "muted small" }, x.detail || "") },
      ], rows, { rowClass: (x) => (x.ts && x.ts > now && x.ts - now < 1800 ? "hl" : "") }))),
      items.length ? null : note("Nothing in the selected kinds from yesterday to the next 7 days."),
      missing ? note(`${missing} released ${missing === 1 ? "number has" : "numbers have"} no actual yet. Actual values come from the free MetaTrader 5 bridge (bridge/SessionDeskBridge.mq5 on any chart: every currency within seconds)`
        + " or a calendar key (TradingEconomics, Finnhub, FMP) in Settings → Connectors; Forex Factory's free feed carries forecasts only."
        + (tl.has_actuals ? " A source with actuals is connected but did not cover these - an exporter limited to a few currencies or events does that." : ""), "warn") : null,
      note(tl.note + (Object.keys(tl.errors || {}).length ? " · Errors: " + Object.entries(tl.errors).map(([k, v]) => `${k}: ${v}`).join("; ") : "")));
    ctx.setContext({ page: "Calendar timeline", items: items.slice(0, 150).map((x) => ({ day: x.day, time: x.ts ? new Date(x.ts * 1000).toISOString() : "all day", kind: x.kind, tag: x.tag, title: x.title, detail: x.detail, result: x.result || null })) });
  };

  const levelSel = h("select", { onchange: (e) => { level = e.target.value; localStorage.setItem("sd.calLevel", level); drawEco(); } },
    [["high", "High impact"], ["medium", "High + medium"], ["all", "All"]].map(([v, l]) => h("option", { value: v, selected: v === level }, l)));

  const loadEco = async () => {
    const d = await api("/api/calendar?days=10&back_hours=36", { fresh: true });
    if (d.error) { if (tab === "eco") clear(body, errorBox(d.error)); return; }
    events = d.events || [];
    const actualSources = (d.sources || []).filter((s) => s !== "ffcal");
    info.textContent = `Sources: ${(d.sources || []).join(", ") || "none"}.` +
      (actualSources.length ? " Actual values arrive live from " + actualSources.join(", ") + "." :
        " Actual values need MetaTrader 5 (bridge EA) or a calendar key (TradingEconomics, Finnhub, FMP); until then the squawk feeds deliver the print as a headline.") +
      (Object.keys(d.errors || {}).length ? " Errors: " + Object.entries(d.errors).map(([k, v]) => `${k}: ${v}`).join("; ") : "");
    drawEco();
  };
  const drawEco = () => {
    if (tab !== "eco") return;
    const now = Date.now() / 1000;
    const keep = events.filter((e) => level === "all" || e.impact === "high" || (level === "medium" && e.impact === "medium"));
    const byDay = new Map();
    for (const e of keep) { const k = day(e.ts); if (!byDay.has(k)) byDay.set(k, []); byDay.get(k).push(e); }
    clear(body, h("div", { class: "toolbar" }, h("label", null, "Show", levelSel)), info);
    for (const [d, rows] of byDay) {
      body.appendChild(section(d, table([
        { label: "Time", render: (e) => clock(e.ts) },
        { label: "In", render: (e) => e.ts > now ? (e.ts - now < 86400 ? countdown(e.ts - now) : "") : h("span", { class: "muted" }, "done") },
        { label: "", render: (e) => e.currency },
        { label: "Event", render: (e) => e.title },
        { label: "Impact", render: (e) => h("span", { class: e.impact === "high" ? "warn" : "muted" }, e.impact) },
        { label: "Actual", num: true, render: (e) => e.actual ?? "", cls: (e) => e.surprise > 0 ? "up" : e.surprise < 0 ? "down" : "" },
        { label: "Forecast", num: true, render: (e) => e.forecast ?? "" },
        { label: "Previous", num: true, render: (e) => e.previous ?? "" },
        { label: "Surprise", num: true, render: (e) => e.surprise != null ? (e.surprise > 0 ? "+" : "") + Number(e.surprise.toFixed(3)) : "" },
        { label: "Source", render: (e) => h("span", { class: "muted small" }, (e.sources || []).join(", ")) },
      ], rows, { rowClass: (e) => (e.ts > now && e.ts - now < 1800 ? "hl" : "") })));
    }
    if (!keep.length) body.appendChild(note("No events at this level."));
    body.appendChild(histBox);
    ctx.setContext({ page: "Economic calendar", events: keep.map((e) => ({ when_utc: new Date(e.ts * 1000).toISOString(), currency: e.currency, title: e.title, impact: e.impact, actual: e.actual, forecast: e.forecast, previous: e.previous, surprise: e.surprise })) });
  };

  // Reaction history: last releases of upcoming events (exported by the MT5 bridge) and how markets moved.
  const histBox = h("div");
  const loadHistory = async () => {
    const d = await api("/api/calendar/history", { ttl: 600000 });
    const evs = Object.values(d.events || {}).sort((a, b) => (a.currency + a.name).localeCompare(b.currency + b.name));
    if (!evs.length) { clear(histBox, section("Reaction history", note(d.note || d.error || "No history available."))); return; }
    clear(histBox, section("Reaction history of upcoming events", note(d.note),
      ...evs.map((ev) => h("details", null,
        h("summary", null, `${ev.currency} ${ev.name}  `, h("span", { class: "muted small" },
          Object.entries(ev.avg_abs_move || {}).map(([a, v]) => `${a} ±${num(v, 2)}%`).join(" · ") || "no price reaction data")),
        table([{ label: "Released", render: (r) => new Date(r.ts * 1000).toLocaleString([], { day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" }) },
          { label: "Actual", num: true, render: (r) => num(r.actual, 2) + (ev.unit || "") }, { label: "Forecast", num: true, render: (r) => (r.forecast == null ? "–" : num(r.forecast, 2) + (ev.unit || "")) },
          { label: "Surprise", num: true, cls: (r) => (r.surprise > 0 ? "up" : r.surprise < 0 ? "down" : ""), render: (r) => (r.surprise == null ? "–" : (r.surprise > 0 ? "+" : "") + num(r.surprise, 2)) },
          ...ev.markets.map((m) => ({ label: m + " 3h", num: true, cls: (r) => dir(r.moves[m]), render: (r) => (r.moves[m] == null ? "–" : pct(r.moves[m], 2)) }))], ev.releases)))));
  };

  // Earnings: filter by market cap and importance (ranked by the server: watchlist / mega cap = high,
  // big-index member / large cap = medium, rest = low), sort by date or size.
  const CAPS = [["0", "Any size"], ["2e9", "≥ 2 B"], ["10e9", "≥ 10 B"], ["50e9", "≥ 50 B"], ["200e9", "≥ 200 B"]];
  const IMPORTANCE = [["low", "All"], ["medium", "Medium + high"], ["high", "High only"]];
  const RANK = { low: 0, medium: 1, high: 2 };
  let earnMode = localStorage.getItem("sd.earnMode") || "upcoming", reported = null;
  let earn = null, minCap = localStorage.getItem("sd.earnCap") || "10e9", minImp = localStorage.getItem("sd.earnImp") || "low",
    earnSort = localStorage.getItem("sd.earnSort") || "date";
  const pick = (key, opts, cur, set) => h("select", { onchange: (e) => { set(e.target.value); localStorage.setItem(key, e.target.value); drawEarn(); } },
    opts.map(([v, l]) => h("option", { value: v, selected: v === cur }, l)));
  const loadEarn = async () => {
    clear(body, loading());
    [earn, reported] = await Promise.all([api("/api/earnings?days=7", { ttl: 300000 }), api("/api/earnings/reported", { ttl: 300000 })]);
    drawEarn();
  };
  const modeBar = () => h("span", { class: "tabs inline" }, [["upcoming", "Upcoming"], ["reported", "Reported"]].map(([k, l]) =>
    h("button", { class: k === earnMode ? "on" : "", onclick: () => { earnMode = k; localStorage.setItem("sd.earnMode", k); drawEarn(); } }, l)));
  const drawReported = () => {
    const items = (reported && reported.items) || [], s = (reported && reported.summary) || {};
    const keep = items.filter((r) => RANK[r.importance || "low"] >= RANK[minImp]);
    clear(body, h("div", { class: "toolbar" }, modeBar(), h("label", null, "Importance", pick("sd.earnImp", IMPORTANCE.slice(1), minImp === "low" ? "medium" : minImp, (v) => { minImp = v; }))),
      note(`${s.reported || 0} relevant reports in the last trading days; ${s.beat || 0} of ${s.with_estimate || 0} beat the EPS consensus.`),
      h("div", { class: "scroll" }, table([
        { label: "Date", render: (r) => `${r.date.slice(5)} ${r.timing === "after close" ? "AMC" : r.timing === "pre-market" ? "BMO" : ""}` },
        { label: "Symbol", render: (r) => h("a", { href: `#/stock/${encodeURIComponent(r.symbol)}/earnings` }, r.symbol) },
        { label: "Company", render: (r) => h("span", { class: "small" }, (r.name || "").slice(0, 28)) },
        { label: "EPS", num: true, render: (r) => (r.actual == null ? "–" : num(r.actual, 2)) },
        { label: "Est.", num: true, render: (r) => (r.estimate == null ? "–" : num(r.estimate, 2)) },
        { label: "Surprise", num: true, cls: (r) => dir(r.surprise_pct), render: (r) => (r.surprise_pct == null ? "–" : pct(r.surprise_pct, 1)) },
        { label: "Stock", num: true, cls: (r) => dir(r.move), render: (r) => (r.move == null ? "pending" : pct(r.move, 1)) },
        { label: "S&P 500", num: true, cls: (r) => dir(r.market), render: (r) => (r.market == null ? "–" : pct(r.market, 1)) },
        { label: "vs market", num: true, cls: (r) => dir(r.excess), render: (r) => (r.excess == null ? "–" : pct(r.excess, 1)) },
        { label: "Why", render: (r) => h("span", { class: "small muted" }, r.why || "") },
        { label: "Source", render: (r) => h("span", { class: "small muted" }, r.source || "") },
      ], keep, { empty: "No relevant report in the last trading days." })),
      note(reported && reported.note ? reported.note + " AMC = after the close, BMO = before the open; 'pending' = the reaction session has not closed yet." : ""));
    ctx.setContext({ page: "Earnings reported", summary: s, reports: keep.slice(0, 80).map((r) => ({ date: r.date, timing: r.timing, symbol: r.symbol,
      actual: r.actual, estimate: r.estimate, surprise_pct: r.surprise_pct, move: r.move, vs_market: r.excess })) });
  };
  const drawEarn = () => {
    if (tab !== "earn" || !earn) return;
    if (earnMode === "reported") { drawReported(); return; }
    const items = earn.items || [], cap = Number(minCap);
    // your watchlist names always pass the size filter; unknown market caps only show with "Any size"
    const keep = items.filter((r) => RANK[r.importance || "low"] >= RANK[minImp] && (r.why === "watchlist" || cap === 0 || (r.cap || 0) >= cap))
      .sort(earnSort === "cap" ? (a, b) => (b.cap || 0) - (a.cap || 0) : (a, b) => (a.date + a.symbol).localeCompare(b.date + b.symbol));
    const IMP = { high: "warn", medium: "", low: "muted" };
    clear(body, h("div", { class: "toolbar" }, modeBar(),
      h("label", null, "Market cap", pick("sd.earnCap", CAPS, minCap, (v) => { minCap = v; })),
      h("label", null, "Importance", pick("sd.earnImp", IMPORTANCE, minImp, (v) => { minImp = v; })),
      h("label", null, "Sort", pick("sd.earnSort", [["date", "By date"], ["cap", "By market cap"]], earnSort, (v) => { earnSort = v; }))),
      note(`Source: ${earn.source || "none"} (US listings). Showing ${keep.length} of ${items.length} reports in the next 7 days. ` +
        "Importance: high = your watchlist or a mega cap (≥ 200 B USD); medium = member of Dow 30, Nasdaq-100, DAX 40 or Euro Stoxx 50, or ≥ 50 B; low = the rest."),
      table([
        { label: "Date", render: (r) => r.date }, { label: "Timing", render: (r) => r.timing },
        { label: "Symbol", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
        { label: "Company", render: (r) => r.name || "" },
        { label: "Importance", render: (r) => h("span", { class: "small " + (IMP[r.importance] ?? "") }, r.importance + (r.why ? " · " + r.why : "")) },
        { label: "EPS est.", num: true, render: (r) => r.eps_forecast ?? "" },
        { label: "Est.", num: true, render: (r) => r.estimates ?? "" }, { label: "Market cap", num: true, render: (r) => (r.cap ? big(r.cap) : "–") },
      ], keep, { empty: earn.error_detail || (items.length ? "No reports match the filter." : "No earnings data.") }));
    ctx.setContext({ page: "Earnings calendar", filter: { min_market_cap_usd: cap, min_importance: minImp, sort: earnSort },
      earnings: keep.slice(0, 120).map((r) => ({ date: r.date, timing: r.timing, symbol: r.symbol, name: r.name, importance: r.importance, why: r.why, market_cap_usd: r.cap, eps_forecast: r.eps_forecast })) });
  };
  const draw = () => (tab === "time" ? (tl ? drawTimeline() : loadTimeline()) : tab === "eco" ? (events.length ? drawEco() : loadEco()) : earn ? drawEarn() : loadEarn());

  drawTabs();
  clear(body, loading());
  if (tab === "time") await loadTimeline(); else if (tab === "eco") await loadEco(); else await loadEarn();
  if (tab !== "eco") loadEco();
  loadHistory();
  const off = on("release", () => { loadEco(); if (tab === "time") loadTimeline(); });
  const t1 = setInterval(() => (tab === "eco" ? drawEco() : tab === "time" ? drawTimeline() : null), 1000 * 15),
    t2 = setInterval(() => (tab === "eco" ? loadEco() : tab === "time" ? loadTimeline() : null), 60000);
  return () => { off(); clearInterval(t1); clearInterval(t2); };
}
