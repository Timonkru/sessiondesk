// Tankers (AIS): tankers seen at oil chokepoints from live AIS (aisstream.io, the user's own free key).
import { api } from "../lib/api.js";
import { h, clear, table, section, num, note, loading, errorBox, ago } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Tankers (AIS)"), h("span", { class: "meta" }, "oil chokepoints, live ship positions")), body);

  const draw = async () => {
    const d = await api("/api/tankers", { fresh: true });
    if (d.error && !d.chokepoints) { clear(body, errorBox(d.error)); return; }
    const status = !d.configured
      ? note("Not connected yet. Get a free key at aisstream.io (sign in, API Keys) and enter it under Settings → Connectors → aisstream.io. Nothing else to install; the monitor starts within a minute.", "warn")
      : d.error ? note(`Connection problem: ${d.error} - retrying with backoff.`, "warn")
      : note(d.connected_recently ? `Connected · ${num(d.received, 0)} messages received since start · ${num(d.typed, 0)} of ${num(d.present, 0)} ships at the chokepoints have sent their type so far`
          + (d.present && d.typed / d.present < 0.6 ? " - ships send their static data (incl. the type) only every few minutes, so tanker counts fill in over the first 10-20 minutes. Types are remembered across restarts." : ".")
        : "Connecting… (first ships appear within a minute; tanker types after a few minutes).");
    const rows = d.chokepoints || [];
    clear(body, status,
      section("Chokepoints", h("div", { class: "scroll" }, table([
        { label: "Chokepoint", render: (r) => [h("strong", null, r.name), h("div", { class: "small muted" }, r.flow)] },
        { label: "Tankers now", num: true, render: (r) => num(r.tankers, 0) },
        { label: "moving", num: true, render: (r) => num(r.moving, 0) },
        { label: "slow / anchored", num: true, cls: (r) => (r.slow > r.moving && r.slow >= 5 ? "warn" : ""), render: (r) => num(r.slow, 0) },
        { label: "Tankers today", num: true, render: (r) => num(r.today, 0) },
        { label: "7-day avg / day", num: true, render: (r) => (r.avg7 == null ? "–" : num(r.avg7, 0)) },
        { label: "All vessels", num: true, render: (r) => num(r.vessels, 0) },
        { label: "type unknown", num: true, render: (r) => h("span", { class: "muted" }, num(r.type_unknown, 0)) },
        { label: "History", render: (r) => h("a", { href: "#/hub/" + encodeURIComponent("ais:" + r.key) }, "Data hub") },
      ], rows))),
      ...rows.filter((r) => r.ships.length).map((r) => h("details", null, h("summary", null, `${r.name}: ${r.ships.length} tankers`),
        table([{ label: "Ship", render: (s) => s.name || "–" }, { label: "MMSI", render: (s) => h("span", { class: "small muted" }, String(s.mmsi)) },
          { label: "Speed kn", num: true, render: (s) => (s.sog == null ? "–" : num(s.sog, 1)) },
          { label: "Draught m", num: true, render: (s) => (s.draught == null ? "–" : num(s.draught, 1)) },
          { label: "Destination", render: (s) => s.destination || "–" },
          { label: "", render: (s) => (s.imo ? h("a", { href: `https://www.marinetraffic.com/en/ais/details/ships/imo:${s.imo}`, target: "_blank", rel: "noopener noreferrer" }, "track ↗") : "") }], r.ships))),
      note(d.note));
    ctx.setContext({ page: "Tankers (AIS)", connected: d.connected_recently, chokepoints: rows.map((r) => ({ name: r.name, tankers_now: r.tankers, moving: r.moving,
      slow: r.slow, today: r.today, avg7: r.avg7 })) });
  };
  await draw();
  const t = setInterval(draw, 30000);
  return () => clearInterval(t);
}
