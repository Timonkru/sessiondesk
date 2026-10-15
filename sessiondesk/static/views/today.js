// Today: accounts + prop-rule meter, rule flags, own schedule with release collisions, next releases,
// forced flows, AI briefing, changes since you last looked, one-line notes.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, num, pct, dir, clock, day, countdown, stamp, note, loading, errorBox, markdown, toast } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const top = h("div"), left = h("div"), right = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Today"), h("span", { class: "meta" }, new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }))),
    top, h("div", { class: "cols" }, left, right));
  top.appendChild(loading());
  const brief = h("div"), changes = h("div"), notesBox = h("div");
  let snap = null;

  const load = async () => {
    const d = await api("/api/today", { fresh: true });
    if (d.error) { clear(top, errorBox(d.error)); return; }
    snap = d;
    const now = Date.now() / 1000;
    const flags = d.flags || [];
    clear(top,
      d.connected ? section("Accounts", table([
        { label: "Account", render: (a) => [a.login, a.fresh === false ? h("span", { class: "warn small" }, ` stale ${Math.round((a.age || 0) / 3600)} h`) : ""] },
        { label: "Equity", num: true, render: (a) => `${num(a.equity, 2)} ${a.currency || ""}` },
        { label: "Today", num: true, cls: (a) => dir(a.day_pnl), render: (a) => (a.day_pnl == null ? "–" : `${num(a.day_pnl, 0)} (${pct(a.day_pct, 2)})`) },
        { label: "Room to own stop", num: true, cls: (a) => (a.own_stop_room_pct != null && a.own_stop_room_pct < 0.5 ? "warn" : ""), render: (a) => (a.own_stop_room_pct == null ? "–" : pct(a.own_stop_room_pct, 2, false)) },
        { label: "Room to daily limit", num: true, cls: (a) => (a.daily_loss_room_pct != null && a.daily_loss_room_pct < 1 ? "warn" : ""), render: (a) => (a.daily_loss_room_pct == null ? "–" : pct(a.daily_loss_room_pct, 2, false)) },
        { label: "Full-risk losers left", num: true, render: (a) => (a.losers_left == null ? "–" : num(a.losers_left, 1)) },
        { label: "Room to max loss", num: true, render: (a) => (a.max_loss_room_pct == null ? "–" : pct(a.max_loss_room_pct, 2, false)) },
        { label: "Risk at stops", num: true, render: (a) => (a.risk_pct == null ? "–" : pct(a.risk_pct, 2, false)) },
        { label: "Positions", num: true, render: (a) => a.positions },
        { label: "", render: (a) => (a.trade_allowed === false ? h("span", { class: "warn" }, "AutoTrading OFF") : a.risk_multiplier === 0 ? h("span", { class: "warn" }, "day locked") : "") },
      ], d.accounts || []), note("Limits come from Settings → Prop rules; the day start is the exporter's day-start balance or the first balance SessionDesk saw today.")) : null,
      flags.length ? section("Rule flags", h("ul", { class: "feed" }, flags.map((f) => h("li", null, h("span", { class: f.level === "high" ? "warn" : "muted" }, f.level === "high" ? "● " : "○ "), `${f.account}: ${f.text}`)))) : null);
    clear(left,
      section("Schedule", table([
        { label: "In", render: (s) => (s.in_sec < 0 ? h("span", { class: "muted" }, "passed") : s.in_sec < 3600 ? h("strong", null, countdown(s.in_sec)) : countdown(s.in_sec)) },
        { label: "At", render: (s) => `${day(s.when) !== day(now) ? day(s.when) + " " : ""}${clock(s.when)}` },
        { label: "", render: (s) => s.session },
        { label: "What", render: (s) => h("span", { style: { fontWeight: s.kind === "session" ? 600 : 400 } }, s.label) },
        { label: "Collides with", render: (s) => (s.collisions && s.collisions.length ? h("span", { class: "warn small" }, s.collisions.join(", ")) : "") },
      ], (d.schedule || []).filter((s) => s.in_sec > -1800).slice(0, 18), { rowClass: (s) => (s.in_sec >= 0 && s.in_sec < 900 ? "hl" : "") }),
        note("Add your own times in Settings → Schedule (relative to a cash open or absolute). Holidays of the session's exchange are skipped.")),
      section("Releases next 36 h", table([
        { label: "When", render: (e) => (e.ts > now ? (e.ts - now < 86400 ? "in " + countdown(e.ts - now) : day(e.ts) + " " + clock(e.ts)) : clock(e.ts)) },
        { label: "", render: (e) => e.currency }, { label: "Event", render: (e) => e.title },
        { label: "Impact", render: (e) => h("span", { class: e.impact === "high" ? "warn" : "muted" }, e.impact) },
        { label: "Fcst", num: true, render: (e) => e.forecast ?? "" }, { label: "Actual", num: true, render: (e) => e.actual ?? "" },
      ], d.events || [], { empty: "Nothing scheduled.", onRow: () => ctx.go("#/calendar") })),
      section("Forced flows next 5 days", table([{ label: "Date", render: (f) => f.date }, { label: "Event", render: (f) => f.name },
        { label: "Size", render: (f) => h("span", { class: f.size === "high" ? "warn" : "muted" }, f.size) }], d.flows || [], { empty: "None.", onRow: () => ctx.go("#/flows") })));
    ctx.setContext({ page: "Today", accounts: d.accounts, flags, schedule: (d.schedule || []).slice(0, 12), events: d.events, flows: d.flows });
  };

  const loadBrief = async () => {
    const [b, r] = await Promise.all([api("/api/briefing?kind=briefing", { fresh: true }), api("/api/briefing?kind=review", { fresh: true })]);
    const block = (item, kind, label) => h("div", null,
      h("div", { class: "toolbar" }, h("strong", null, label), item.item ? h("span", { class: "muted small" }, `${stamp(item.item.ts)} · ${item.item.model || ""}`) : h("span", { class: "muted small" }, "none yet"),
        h("button", { onclick: async (e) => { e.target.disabled = true; e.target.textContent = "writing…"; const res = await api("/api/briefing", { method: "POST", body: { kind } }); if (res.error) toast("AI", res.error, { kind: "high" }); e.target.disabled = false; e.target.textContent = "write now"; loadBrief(); } }, "write now")),
      item.item ? h("details", { open: kind === "briefing" && (Date.now() / 1000 - item.item.ts < 12 * 3600) }, h("summary", { class: "small" }, "show"), markdown(item.item.text)) : null);
    clear(brief, section("AI briefing", block(b, "briefing", "Pre-session briefing"), block(r, "review", "Weekly review"),
      note("Written from the facts SessionDesk computed (markets, releases, schedule, flows, moves, headlines, accounts). Optional daily time: Settings → AI.")));
  };

  const loadChanges = async () => {
    const a = await api("/api/activity?limit=40", { fresh: true });
    const icon = { position: "◆", level: "↕", move: "▲", release: "■", event: "◷", job: "⚙", note: "✎", briefing: "✦" };
    clear(changes, section("Changes", (a.items || []).length ? h("ul", { class: "feed" }, a.items.map((x) => h("li", null,
      h("div", { class: "t" }, h("span", { class: "muted" }, (icon[x.kind] || "·") + " "), x.title),
      h("div", { class: "m" }, `${stamp(x.ts)} · ${x.kind}`, x.body ? ` · ${x.body.slice(0, 160)}` : "")))) : note("Nothing logged yet.")));
  };

  const loadNotes = async (items) => {
    const n = items ? { items } : await api("/api/notes", { fresh: true });
    const input = h("input", { type: "text", placeholder: "one-line note (why this trade, what you saw) - Enter to save", style: { width: "100%" } });
    input.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !input.value.trim()) return;
      const res = await api("/api/notes", { method: "POST", body: { text: input.value.trim() } });
      if (!res.error) loadNotes(res.items);
    });
    clear(notesBox, section("Notes", input, h("ul", { class: "feed" }, (n.items || []).slice(0, 12).map((x) => h("li", null, h("div", { class: "t" }, x.text), h("div", { class: "m" }, stamp(x.ts)))))));
  };

  right.append(brief, changes, notesBox);
  await Promise.all([load(), loadBrief(), loadChanges(), loadNotes()]);
  const offs = ["position", "level", "alert", "release", "briefing", "job"].map((k) => on(k, () => { loadChanges(); if (k === "briefing") loadBrief(); if (k === "position") load(); }));
  const t1 = setInterval(load, 15000), t2 = setInterval(loadChanges, 30000);
  return () => { offs.forEach((f) => f()); clearInterval(t1); clearInterval(t2); };
}
