// Today: what concerns you now - accounts + prop-rule meter, rule flags, one "next up" timeline (your setups and
// sessions plus high-impact releases, collisions marked), forced flows, extension blocks, AI briefing, headlines on
// your positions, changes since you last looked, one-line notes. The full timeline is the Calendar.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, num, pct, dir, clock, day, countdown, stamp, note, loading, errorBox, markdown, toast } from "../lib/ui.js";
import { block } from "../lib/blocks.js";

export async function render(root, _params, ctx) {
  const top = h("div"), left = h("div"), right = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Today"), h("span", { class: "meta" }, new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }))),
    top, h("div", { class: "cols" }, left, right));
  top.appendChild(loading());
  const brief = h("div"), posNews = h("div"), changes = h("div"), notesBox = h("div");
  let snap = null, showAll = false;
  const extBox = h("div");

  const load = async () => {
    const d = await api("/api/today", { fresh: true });
    if (d.error) { clear(top, errorBox(d.error)); return; }
    snap = d;
    const now = Date.now() / 1000;
    const flags = d.flags || [];
    clear(top,
      d.connected ? section("Accounts", h("div", { class: "scroll" }, table([
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
      ], d.accounts || [])), note("Limits come from Settings → Prop rules; the day start is the exporter's day-start balance or the first balance SessionDesk saw today.")) : null,
      flags.length ? section("Rule flags", h("ul", { class: "feed" }, flags.map((f) => h("li", null, h("span", { class: f.level === "high" ? "warn" : "muted" }, f.level === "high" ? "● " : "○ "), `${f.account}: ${f.text}`)))) : null);
    // One compact timeline: your setups and sessions plus high-impact releases, by time. The full picture
    // (all releases, earnings, forced flows) lives in the Calendar.
    const items = [
      ...(d.schedule || []).filter((s) => s.in_sec > -1800).map((s) => ({ ts: s.when, kind: s.kind === "session" ? "session" : "setup", tag: s.session, what: s.label, collisions: s.collisions })),
      ...(d.events || []).filter((e) => e.impact === "high" && e.ts >= now - 1800).map((e) => ({ ts: e.ts, kind: "release", tag: e.currency, what: e.title,
        extra: [e.forecast ? "fcst " + e.forecast : "", e.actual ? "actual " + e.actual : ""].filter(Boolean).join(" · ") })),
    ].sort((a, b) => a.ts - b.ts);
    const shown = showAll ? items : items.slice(0, 10);
    const KIND = { release: "warn", session: "", setup: "muted" };
    clear(left,
      section("Next up", table([
        { label: "In", render: (x) => (x.ts < now ? h("span", { class: "muted" }, "passed") : x.ts - now < 3600 ? h("strong", null, countdown(x.ts - now)) : countdown(x.ts - now)) },
        { label: "At", render: (x) => `${day(x.ts) !== day(now) ? day(x.ts) + " " : ""}${clock(x.ts)}` },
        { label: "", render: (x) => h("span", { class: "small " + (KIND[x.kind] || "") }, x.kind === "release" ? "● " + x.tag : x.tag) },
        { label: "What", render: (x) => h("span", { style: { fontWeight: x.kind === "setup" ? 400 : 600 } }, x.what) },
        { label: "", render: (x) => (x.collisions && x.collisions.length ? h("span", { class: "warn small" }, "collides: " + x.collisions.join(", ")) : h("span", { class: "muted small" }, x.extra || "")) },
      ], shown, { empty: "Nothing scheduled.", rowClass: (x) => (x.ts >= now && x.ts - now < 900 ? "hl" : "") }),
        h("p", { class: "small" }, items.length > 10 ? h("button", { class: "linkish", onclick: () => { showAll = !showAll; load(); } }, showAll ? "show fewer" : `show all ${items.length}`) : null,
          items.length > 10 ? " · " : "", h("a", { href: "#/calendar" }, "full timeline in the Calendar"), " · your own times: Settings → Schedule")),
      (d.flows || []).length ? section("Forced flows next 5 days", h("ul", { class: "feed" }, d.flows.map((f) =>
        h("li", { class: "click", onclick: () => ctx.go("#/flows") }, h("div", { class: "t" }, `${f.date} · ${f.name}`), h("div", { class: "m" }, f.size + " size"))))) : null);
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

  const loadPosNews = async () => {
    const d = await api("/api/news/positions?hours=12&strict=true", { fresh: true });
    if (d.error || !(d.held || []).length) { clear(posNews); return; }
    clear(posNews, section("Headlines on your open positions", (d.items || []).length
      ? h("ul", { class: "feed" }, d.items.slice(0, 10).map((n) => h("li", { class: n.impact === "high" ? "high" : "" },
        h("div", { class: "t" }, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer" }, n.title) : n.title),
        h("div", { class: "m" }, `${clock(n.published)} · ${n.source} · `, h("strong", null, n.held.join(", ")), n.impact !== "normal" ? ` · ${n.impact}` : ""))))
      : note(`Nothing in the last ${d.hours} h touching ${d.held.join(", ")}.`),
      h("p", { class: "small" }, "Central banks, data, yields, commodities and named companies; broader matches (geopolitics, tariffs) on the ",
        h("a", { href: "#/news" }, "News page, filter My positions"), ".")));
  };

  const loadChanges = async () => {
    const a = await api("/api/activity?limit=40", { fresh: true });
    const icon = { position: "◆", level: "↕", price: "◎", hub: "◬", move: "▲", release: "■", event: "◷", job: "⚙", note: "✎", briefing: "✦" };
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

  // blocks from your extensions (e.g. a private vola traffic light) sit at the top of the right column
  const loadExt = async () => {
    const d = await api("/api/extensions/today", { fresh: true });
    clear(extBox, (d.blocks || []).map((b) => block(b, b.extension)));
    const retry = Math.min(...(d.blocks || []).map((b) => b.retry_in || Infinity));   // a block still loading asks for a re-check
    if (Number.isFinite(retry)) setTimeout(loadExt, Math.max(5, retry) * 1000);
  };
  // earnings that came out since yesterday and matter (watchlist, mega caps) - the full list is Calendar > Earnings > Reported
  const earnBox = h("div");
  api("/api/earnings/reported?days=3", { ttl: 300000 }).then((d) => {
    const items = (d.items || []).filter((r) => r.importance === "high").slice(0, 8);
    if (!items.length) return;
    clear(earnBox, section("Earnings reported", table([
      { label: "", render: (r) => h("a", { href: `#/stock/${encodeURIComponent(r.symbol)}/earnings` }, r.symbol) },
      { label: "Surprise", num: true, cls: (r) => dir(r.surprise_pct), render: (r) => (r.surprise_pct == null ? "–" : pct(r.surprise_pct, 1)) },
      { label: "Stock", num: true, cls: (r) => dir(r.move), render: (r) => (r.move == null ? "pending" : pct(r.move, 1)) },
      { label: "", render: (r) => h("span", { class: "small muted" }, `${r.date.slice(5)} ${r.why || ""}`) }], items),
      h("p", { class: "small" }, h("a", { href: "#/calendar" }, "all relevant reports (Calendar → Earnings → Reported) →"))));
  });
  right.append(extBox, earnBox, brief, posNews, changes, notesBox);
  await Promise.all([load(), loadExt(), loadBrief(), loadPosNews(), loadChanges(), loadNotes()]);
  const offs = ["position", "level", "price_alert", "alert", "release", "briefing", "job"].map((k) => on(k, () => { loadChanges(); if (k === "briefing") loadBrief(); if (k === "position") { load(); loadPosNews(); } }));
  offs.push(on("news", ({ item }) => { if ((item.held || []).length) loadPosNews(); }));
  const t1 = setInterval(load, 15000), t2 = setInterval(loadChanges, 30000), t3 = setInterval(loadExt, 60000);
  return () => { offs.forEach((f) => f()); clearInterval(t1); clearInterval(t2); clearInterval(t3); };
}
