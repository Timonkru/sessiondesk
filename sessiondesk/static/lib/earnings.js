// Earnings desk pieces shared by Calendar > Earnings and Data hub > Earnings flash: times with their kind, the join-call
// button, the report panel (documents, consensus snapshot, flash). Every text from a filing goes through h() as text.
import { api } from "./api.js";
import { h, clear, table, note, loading, errorBox, ext, num, countdown, big, toast } from "./ui.js";

const ET_FMT = new Intl.DateTimeFormat([], { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const LOCAL_FMT = new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit", hour12: false });
const KIND = { actual: "actual", announced: "announced", historical: "historical estimate", session: "session only" };

// One timer updates every visible countdown, so a re-render never leaves one behind.
setInterval(() => {
  const now = Date.now() / 1000;
  for (const el of document.querySelectorAll("[data-countdown]")) {
    const left = Number(el.dataset.countdown) - now;
    el.textContent = left > 0 ? "in " + countdown(left) : "started";
  }
}, 1000);

export const clockBoth = (ts) => `${ET_FMT.format(new Date(ts * 1000))} ET · ${LOCAL_FMT.format(new Date(ts * 1000))} local`;

export function kindTag(kind, title) {
  return h("span", { class: "small " + (kind === "actual" ? "" : kind === "announced" ? "" : "muted"), title: title || "" }, KIND[kind] || kind || "");
}

export function releaseCell(r, row) {
  if (row && row.covered === "no") return h("span", { class: "muted small", title: row.cover_note || "" }, "not covered");
  if (row && row.covered === "foreign") return h("span", { class: "muted small", title: row.cover_note || "" }, "foreign filer, no flash");
  if (!r || !r.ts) return h("span", { class: "small muted", title: "No EDGAR history loaded yet: this is the calendar's session, not a time." }, (r && r.text) || "n/a");
  const span = r.earliest_et ? ` (${r.earliest_et}–${r.latest_et} ET, last ${r.n})` : "";
  return h("span", { class: "small", title: r.source || "" }, r.kind === "historical" ? "~" : "", clockBoth(r.ts), " ", kindTag(r.kind, r.source), span ? h("span", { class: "muted" }, span) : null);
}

export function callCell(c) {
  if (!c || (!c.ts && !c.url)) return h("span", { class: "muted small" }, "–");
  return h("span", { class: "small" }, c.ts ? h("span", { title: `${KIND[c.time_kind] || ""}, ${c.time_source || ""}` }, c.time_kind === "historical" ? "~" : "", ET_FMT.format(new Date(c.ts * 1000)), " ET ") : null,
    joinButton(c));
}

// The webcast opens in its own window: IR webcast hosts require registration and refuse to be framed (docs/EARNINGS.md).
export function joinButton(c) {
  if (!c || !c.url) return null;
  const now = Date.now() / 1000;
  const label = c.url_kind === "ir_fallback" ? "IR site" : "Join call";
  return h("span", { style: { whiteSpace: "nowrap" } },
    h("button", { class: "linkish", title: c.url_note || "", onclick: (e) => { e.stopPropagation(); window.open(c.url, "_blank", "noopener,noreferrer"); } }, label),
    c.ts && c.ts > now - 7200 ? h("span", { class: "muted small", style: { marginLeft: "6px" }, "data-countdown": String(c.ts) }, "") : null);
}

const verdictClass = (v) => (v === "beat" ? "up" : v === "miss" ? "down" : v === "basis unclear" || v === "sources disagree" ? "warn" : "muted");
export const verdictTag = (v) => h("strong", { class: "small " + verdictClass(v) }, v || "no frozen consensus");
const moneyText = (v) => (v == null ? "–" : Math.abs(v) >= 1e6 ? big(v) : num(v, 2));

function resultTable(rows, fmt) {
  return table([
    { label: "Consensus source", render: (r) => r.source },
    { label: "Reported", num: true, render: (r) => (r.actual == null ? "–" : fmt(r.actual)) },
    { label: "Consensus", num: true, render: (r) => (r.consensus == null ? "–" : fmt(r.consensus)) },
    { label: "Surprise", num: true, render: (r) => (r.surprise_pct == null ? "–" : `${r.surprise_pct > 0 ? "+" : ""}${num(r.surprise_pct, 1)} %`) },
    { label: "Result", render: (r) => verdictTag(r.verdict) },
    { label: "Why / line in the release", render: (r) => h("span", { class: "small muted" }, r.quote || r.why || r.reason || "") },
  ], rows, { empty: "No consensus was frozen before this report, so no comparison." });
}

function figureList(figs, fmt) {
  return table([
    { label: "Figure", render: (f) => h("span", { class: "small" }, (f.label || "").slice(0, 60)) },
    { label: "Value", num: true, render: (f) => fmt(f.value) },
    { label: "Basis as labelled", render: (f) => h("span", { class: "small muted" }, f.basis || "") },
    { label: "Line in the release", render: (f) => h("span", { class: "small muted" }, f.quote || "") },
  ], figs, { empty: "No figure found by the rules." });
}

export function latencyText(f) {
  if (f.late || !f.latency) return "read on request, so no latency";
  if (f.latency.total > 3600) return `read ${Math.round(f.latency.total / 60)} min after SEC: the app was not running or missed it`;
  const l = f.latency, s = (x) => (x == null ? "?" : `${Math.round(x)} s`);
  return `SEC acceptance to display ${s(l.total)} (SEC to seen ${s(l.sec_to_seen)}, read ${s(l.seen_to_shown)})`;
}

export function flashBody(f, baseRate) {
  const eps = f.result.eps, rev = f.result.revenue, g = f.guidance || {};
  return h("div", null,
    h("div", { class: "toolbar" }, h("span", null, "EPS: ", verdictTag(eps.verdict)), h("span", null, "Revenue: ", verdictTag(rev.verdict)),
      g.found ? h("span", { class: "small" }, "Guidance: ", g.direction || "stated") : h("span", { class: "small muted" }, "No guidance found"),
      h("span", { class: "small muted" }, latencyText(f)), f.exhibit_url ? ext(f.exhibit_url, "press release") : null, f.index_url ? ext(f.index_url, "filing") : null),
    baseRate ? note(baseRate) : null,
    h("h4", null, "EPS"), eps.rows.length ? resultTable(eps.rows, (v) => num(v, 2)) : null, figureList(eps.figures, (v) => num(v, 2)),
    h("h4", null, "Revenue"), rev.rows.length ? resultTable(rev.rows, moneyText) : null, figureList(rev.figures, moneyText),
    g.found ? h("div", null, h("h4", null, "Guidance (quoted)"), ...g.quotes.map((q) => h("p", { class: "small" }, q))) : null,
    (f.highlights || []).length ? h("div", null, h("h4", null, "The release's opening lines (quoted)"), ...f.highlights.map((q) => h("p", { class: "small muted" }, q))) : null,
    f.ai ? h("div", null, h("h4", null, `AI reading (${f.ai.model || f.ai.provider || "your key"}), quotes checked against the release; ${f.ai.dropped} dropped`),
      table([{ label: "Metric", render: (x) => x.metric }, { label: "Value", render: (x) => x.value }, { label: "Quote", render: (x) => h("span", { class: "small muted" }, x.quote) }], f.ai.items)) : null);
}

// The panel below a row: times, call, documents, snapshot, flash.
export async function termPanel(box, symbol, day) {
  clear(box, loading(`Loading ${symbol}…`));
  const q = `?day=${encodeURIComponent(day)}`, base = encodeURIComponent(symbol);
  const t = await api(`/api/earnings/term/${base}${q}`, { fresh: true });
  if (t.error) { clear(box, errorBox(t.error)); return; }
  const reload = () => termPanel(box, symbol, day);
  const save = (doc, format) => h("button", { class: "linkish", onclick: async (e) => {
    e.target.textContent = "saving…";
    const r = await api(`/api/earnings/save/${base}${q}&doc=${doc}&format=${format}`, { method: "POST" });
    if (r.error) toast("Report", r.error, { kind: "high" }); else toast("Report saved", r.path);
    reload();
  } }, `save ${format === "text" ? "as text" : "as HTML"}`);
  const docs = t.documents || {}, res = docs.results, qtr = docs.quarterly;
  const flash = t.flash;
  clear(box,
    t.sec_contact ? null : note("SEC asks every client for a contact email. Add yours in Settings → Connectors → SEC EDGAR; until then there is no EDGAR data here.", "warn"),
    t.cover_note ? note(t.cover_note, "warn") : null,
    h("div", { class: "toolbar" }, h("strong", null, symbol), h("span", { class: "muted small" }, `${t.name || ""} · ${day}`),
      h("span", null, "Report: ", releaseCell(t.release)), h("span", null, "Call: ", callCell(t.call))),
    t.call && t.call.url ? note(t.call.url_note || "") : null,
    t.typical ? note(`This company's last ${t.typical.n} results filings were accepted around ${t.typical.median_et} ET (${t.typical.earliest_et}–${t.typical.latest_et}), ${t.typical.session}.`) : null,
    h("h4", null, "Documents"),
    table([
      { label: "Document", render: (d) => d.label },
      { label: "Filed", render: (d) => d.when || "–" },
      { label: "Source", render: (d) => (d.url ? ext(d.url, "open on sec.gov") : h("span", { class: "muted small" }, "not filed yet")) },
      { label: "Keep a copy", render: (d) => (d.key && d.url ? h("span", null, save(d.key, "text"), " ", save(d.key, "html")) : "") },
    ], [
      { label: "Press release (Exhibit 99)", key: "release", url: docs.exhibit_url || (res && res.url), when: res ? clockBoth(res.accepted) : null },
      { label: qtr ? `Quarterly / annual report (${qtr.form})` : "Quarterly / annual report", key: "quarterly", url: qtr && qtr.url, when: qtr ? clockBoth(qtr.accepted) : null },
      ...(docs.foreign ? [{ label: `Foreign filer report (${docs.foreign.form})`, url: docs.foreign.url, when: docs.foreign.filed }] : []),
    ]),
    (t.files || []).length ? note(`Saved locally: ${t.files.map((f) => f.path).join(", ")}`) : null,
    h("h4", null, "Consensus frozen before the report"),
    table([
      { label: "Source", render: (c) => c.source }, { label: "EPS", num: true, render: (c) => (c.eps == null ? "–" : num(c.eps, 2)) },
      { label: "Revenue", num: true, render: (c) => moneyText(c.rev) }, { label: "Analysts", num: true, render: (c) => c.analysts ?? "–" },
      { label: "Quarter", render: (c) => c.quarter || "–" }, { label: "Frozen", render: (c) => (c.frozen ? new Date(c.frozen * 1000).toLocaleString() : "–") },
    ], t.consensus || [], { empty: "No snapshot. It is taken in the background for watchlist, big-index and large-cap names, and only before the report." }),
    h("h4", null, "Flash"),
    flash ? flashBody(flash, t.base_rate) : (res ? h("button", { class: "linkish", onclick: async (e) => {
      e.target.textContent = "reading…";
      const r = await api(`/api/earnings/flash/${base}${q}`, { method: "POST" });
      if (r.error) toast("Report", r.error, { kind: "high" });
      reload();
    } }, "read this report now") : note("No results filing yet. It appears here as soon as EDGAR has it.")),
    flash && t.ai_available && !flash.ai ? h("button", { class: "linkish", title: "Uses your own AI key and costs what your provider charges", onclick: async (e) => {
      e.target.textContent = "reading…";
      const r = await api(`/api/earnings/flash/${base}/ai${q}`, { method: "POST" });
      if (r.error) toast("AI reading", r.error, { kind: "high" });
      reload();
    } }, "add an AI reading (your key, with quotes)") : null);
}

// Data hub tab: every flash collected so far.
export async function flashPage(box, focus) {
  clear(box, loading("Loading flash summaries…"));
  const d = await api("/api/earnings/flash", { fresh: true });
  if (d.error) { clear(box, errorBox(d.error)); return; }
  const detail = h("div");
  const open = (r) => clear(detail, h("h3", null, `${r.symbol} · ${r.day} · ${r.quarter || ""}`), flashBody(r, d.base_rate));
  clear(box,
    d.sec_contact ? null : note("SEC asks every client for a contact email. Add yours in Settings → Connectors → SEC EDGAR; until then nothing is collected.", "warn"),
    note(d.note || ""), note(d.base_rate || ""),
    table([
      { label: "Day", render: (r) => r.day },
      { label: "Symbol", render: (r) => h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) + "/earnings" }, r.symbol) },
      { label: "Company", render: (r) => h("span", { class: "small" }, (r.name || "").slice(0, 28)) },
      { label: "Quarter", render: (r) => h("span", { class: "small" }, r.quarter || "") },
      { label: "Filed", render: (r) => (r.accepted ? h("span", { class: "small" }, clockBoth(r.accepted)) : "–") },
      { label: "EPS", render: (r) => verdictTag(r.result.eps.verdict) },
      { label: "Revenue", render: (r) => verdictTag(r.result.revenue.verdict) },
      { label: "Guidance", render: (r) => h("span", { class: "small muted" }, (r.guidance || {}).found ? (r.guidance.direction || "stated") : "–") },
      { label: "Latency", render: (r) => h("span", { class: "small muted" }, r.late || !r.latency ? "on request" : r.latency.total > 3600 ? "app was off" : `${Math.round(r.latency.total)} s`) },
    ], d.items, { onRow: open, empty: "No flash yet. They appear here while reports come in (upcoming reports: Calendar → Earnings)." }),
    detail);
  const first = d.items.find((r) => r.symbol === focus) || (focus ? null : d.items[0]);
  if (first) open(first);
}
