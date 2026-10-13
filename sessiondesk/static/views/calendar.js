// Economic calendar (merged sources, live actuals) + earnings calendar.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, clock, day, countdown, note, loading, errorBox } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  let tab = "eco", level = localStorage.getItem("sd.calLevel") || "high", events = [];
  const bar = h("div", { class: "tabs" }), body = h("div"), info = h("p", { class: "note" });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Calendar")), bar, body);
  const drawTabs = () => clear(bar, [["eco", "Economic"], ["earn", "Earnings"]].map(([k, l]) =>
    h("button", { class: k === tab ? "on" : "", onclick: () => { tab = k; drawTabs(); draw(); } }, l)));

  const levelSel = h("select", { onchange: (e) => { level = e.target.value; localStorage.setItem("sd.calLevel", level); drawEco(); } },
    [["high", "High impact"], ["medium", "High + medium"], ["all", "All"]].map(([v, l]) => h("option", { value: v, selected: v === level }, l)));

  const loadEco = async () => {
    const d = await api("/api/calendar?days=10&back_hours=36", { fresh: true });
    if (d.error) { clear(body, errorBox(d.error)); return; }
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
    ctx.setContext({ page: "Economic calendar", events: keep.map((e) => ({ when_utc: new Date(e.ts * 1000).toISOString(), currency: e.currency, title: e.title, impact: e.impact, actual: e.actual, forecast: e.forecast, previous: e.previous, surprise: e.surprise })) });
  };

  const loadEarn = async () => {
    clear(body, loading());
    const d = await api("/api/earnings?days=7", { ttl: 300000 });
    const items = (d.items || []).slice().sort((a, b) => (a.date + a.symbol).localeCompare(b.date + b.symbol));
    const capNum = (s) => parseFloat(String(s || "").replace(/[$,]/g, "")) || 0;
    const big = items.filter((r) => capNum(r.market_cap) >= 10e9 || r.eps_forecast);
    clear(body, note(`Source: ${d.source || "none"}. Showing companies with ≥ $10 B market cap or a consensus estimate (${big.length} of ${items.length}).`),
      table([
        { label: "Date", render: (r) => r.date }, { label: "Timing", render: (r) => r.timing },
        { label: "Symbol", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, r.symbol) },
        { label: "Company", render: (r) => r.name || "" }, { label: "EPS est.", num: true, render: (r) => r.eps_forecast ?? "" },
        { label: "Est.", num: true, render: (r) => r.estimates ?? "" }, { label: "Market cap", num: true, render: (r) => r.market_cap ?? "" },
      ], big, { empty: d.error_detail || "No earnings data." }));
    ctx.setContext({ page: "Earnings calendar", earnings: big.slice(0, 120) });
  };
  const draw = () => (tab === "eco" ? (events.length ? drawEco() : loadEco()) : loadEarn());

  drawTabs();
  clear(body, loading());
  await loadEco();
  const off = on("release", loadEco);
  const t1 = setInterval(() => tab === "eco" && drawEco(), 1000 * 15), t2 = setInterval(() => tab === "eco" && loadEco(), 60000);
  return () => { off(); clearInterval(t1); clearInterval(t2); };
}
