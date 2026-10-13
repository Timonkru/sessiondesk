// News: live stream with impact triage, filters, full-text search in the local archive.
import { api, on } from "../lib/api.js";
import { h, clear, clock, day, note, loading } from "../lib/ui.js";

const FILTERS = [
  ["all", "All", {}], ["high", "High impact", { impact: "high" }], ["squawk", "Squawk", { group: "squawk" }],
  ["markets", "Markets", { group: "markets" }], ["cb", "Central banks", { group: "central_banks" }],
];

export async function render(root, _params, ctx) {
  let filter = localStorage.getItem("sd.newsFilter") || "all", query = "", items = [];
  const list = h("ul", { class: "feed" }), info = h("p", { class: "note" });
  const search = h("input", { type: "search", placeholder: "search the archive (all headlines since install)", style: { width: "320px" } });
  const bar = h("div", { class: "tabs" });
  root.append(h("div", { class: "pagehead" }, h("h1", null, "News")), bar, h("div", { class: "toolbar" }, search), info, list);

  const drawTabs = () => clear(bar, FILTERS.map(([k, label]) => h("button", { class: k === filter ? "on" : "", onclick: () => { filter = k; localStorage.setItem("sd.newsFilter", k); drawTabs(); load(); } }, label)));
  const matches = (n) => {
    const f = FILTERS.find((x) => x[0] === filter)[2];
    if (f.impact && n.impact !== f.impact) return false;
    if (f.group && n.group !== f.group) return false;
    return !query;
  };
  const item = (n, fresh) => {
    const detail = h("div", { hidden: true, class: "small", style: { color: "var(--fg2)", margin: "4px 0" } });
    const li = h("li", { class: (n.impact === "high" ? "high " : "") + (fresh ? "fresh " : "") + "click" },
      h("div", { class: "t" }, n.title),
      h("div", { class: "m" }, `${day(n.published)} ${clock(n.published)} · ${n.source}`,
        n.impact !== "normal" ? h("span", { class: n.impact === "high" ? "imp" : "" }, ` · ${n.impact}${n.tags && n.tags.length ? ": " + n.tags[0] : ""}`) : "",
        (n.symbols || []).length ? [" · ", ...n.symbols.slice(0, 5).flatMap((s, i) => [i ? ", " : "", h("a", { href: "#/stock/" + encodeURIComponent(s) }, s)])] : ""),
      detail);
    li.addEventListener("click", (e) => {
      if (e.target.closest("a,button")) return;
      detail.hidden = !detail.hidden;
      if (!detail.hidden && !detail.childElementCount) {
        detail.append(n.summary ? h("p", null, n.summary) : h("p", { class: "muted" }, "No summary in the feed."),
          h("div", null, n.url ? h("a", { href: n.url, target: "_blank", rel: "noopener noreferrer" }, "open article") : null, "   ",
            n.url ? h("a", { href: "#/research/read/" + encodeURIComponent(n.url) }, "read here") : null, "   ",
            h("button", { class: "linkish", onclick: () => ctx.ask("What does this headline mean for markets, and what would confirm or contradict it?",
              { page: "News item", item: n }) }, "ask AI")));
      }
    });
    return li;
  };
  const load = async () => {
    clear(list, loading());
    const f = FILTERS.find((x) => x[0] === filter)[2];
    const qs = new URLSearchParams({ limit: "200", ...(f.group ? { group: f.group } : {}), ...(f.impact ? { impact: f.impact } : {}), ...(query ? { q: query } : {}) });
    const d = await api("/api/news?" + qs.toString(), { fresh: true });
    items = d.items || [];
    clear(list, items.map((n) => item(n)));
    if (!items.length) list.appendChild(h("li", { class: "muted" }, query ? "No match in the archive." : "No headlines yet - the feeds are polled in the background (first fill takes a few seconds after start)."));
    const errs = Object.keys(d.feed_errors || {});
    info.textContent = `${items.length} headlines` + (query ? ` matching “${query}”` : "") + (errs.length ? ` · feeds failing: ${errs.join(", ")}` : "") +
      " · High impact = rule-based triage (central banks, top-tier data, geopolitics, tariffs, market structure); it is not a signal.";
    ctx.setContext({ page: "News" + (query ? ` search “${query}”` : ` (${filter})`), headlines: items.slice(0, 60).map((n) => ({ title: n.title, source: n.source, published: n.published, impact: n.impact, symbols: n.symbols })) });
  };
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { query = search.value.trim(); load(); }, 250); });
  drawTabs();
  await load();
  const off = on("news", ({ item: n }) => { if (matches(n)) list.prepend(item(n, true)); });
  const t = setInterval(() => { if (!query) load(); }, 120000);
  return () => { off(); clearInterval(t); };
}
