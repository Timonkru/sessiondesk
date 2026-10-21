// Central banks: Fed, ECB, BoE, BoJ - policy rate, next decision with countdown, last decision and the market's
// reaction that day, what the market prices, and the following meetings.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, pct, dir, note, loading, errorBox } from "../lib/ui.js";

const fmtDay = (d) => (d ? new Date(d + "T12:00").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : "–");

export async function render(root, _params, ctx) {
  const body = h("div", null, loading("Reading the central banks' calendars…"));
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Central banks"), h("span", { class: "meta" }, "policy rates, next decisions, what the market prices")), body);
  const d = await api("/api/centralbanks", { ttl: 300000 });
  if (d.error) { clear(body, errorBox(d.error)); return; }
  const rows = [...d.banks].sort((a, b) => (a.days_to_next ?? 999) - (b.days_to_next ?? 999));
  clear(body,
    table([
      { label: "Central bank", render: (b) => [h("strong", null, b.name), h("div", { class: "small muted" }, b.ccy)] },
      { label: "Policy rate", num: true, render: (b) => (b.policy == null ? h("span", { class: "muted" }, "no free source") : num(b.policy, 2) + "%") },
      { label: "Next decision", render: (b) => (b.next ? [fmtDay(b.next), h("div", { class: "small " + (b.days_to_next <= 7 ? "warn" : "muted") }, b.days_to_next === 0 ? "today" : `in ${b.days_to_next} days`)]
        : h("span", { class: "muted" }, b.schedule_error || "not published yet")) },
      { label: "Priced (2y - policy)", num: true, cls: (b) => dir(b.gauge_bp), render: (b) => (b.gauge_bp == null ? "–" : `${b.gauge_bp > 0 ? "+" : ""}${Math.round(b.gauge_bp)} bp${b.gauge_tenor && b.gauge_tenor !== "2y" ? ` (${b.gauge_tenor})` : ""}`) },
      { label: "Last decision", render: (b) => (b.last ? fmtDay(b.last) : "–") },
      { label: "Reaction that day", render: (b) => (b.last ? [
        h("div", { class: "small" }, `${b.last_reaction.fx[0]} `, h("span", { class: dir(b.last_reaction.fx[1]) }, pct(b.last_reaction.fx[1], 2))),
        h("div", { class: "small" }, `${b.last_reaction.index[0]} `, h("span", { class: dir(b.last_reaction.index[1]) }, pct(b.last_reaction.index[1], 2)))] : "–") },
      { label: "Following", render: (b) => h("span", { class: "small muted" }, b.upcoming.map((x) => x.slice(5)).join(" · ")) },
      { label: "", render: (b) => h("a", { class: "small", href: b.url, target: "_blank", rel: "noopener noreferrer" }, "calendar ↗") },
    ], rows),
    d.fed_path ? section("Fed: path priced by fed funds futures", h("p", { class: "small" }, h("a", { href: "#/macro" }, "full path on Macro → Rates →"))) : null,
    note(d.note));
  ctx.setContext({ page: "Central banks", banks: rows.map((b) => ({ name: b.name, policy: b.policy, next: b.next, days_to_next: b.days_to_next, priced_bp: b.gauge_bp,
    last: b.last, reaction: b.last_reaction })) });
}
