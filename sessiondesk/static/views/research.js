// Research: feed of research/blog sources, clean reader view, reading list, AI summary.
import { api } from "../lib/api.js";
import { h, clear, day, ago, note, loading, errorBox, markdown, ext } from "../lib/ui.js";

export async function render(root, params, ctx) {
  const listCol = h("div"), reader = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Research")), h("div", { class: "cols" }, listCol, reader));
  let data = { items: [], saved: [] }, source = "all", query = "";

  const search = h("input", { type: "search", placeholder: "search research items", style: { width: "240px" } });
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { query = search.value.trim(); load(); }, 250); });

  const load = async () => {
    data = await api("/api/research" + (query ? "?q=" + encodeURIComponent(query) : ""), { fresh: true });
    drawList();
  };
  const drawList = () => {
    const sources = ["all", "saved", ...new Set((data.items || []).map((i) => i.source))];
    const sel = h("select", { onchange: (e) => { source = e.target.value; drawList(); } }, sources.map((s) => h("option", { value: s, selected: s === source }, s === "all" ? "All sources" : s === "saved" ? "Reading list" : s)));
    let items = source === "saved" ? (data.saved || []).map((s) => ({ title: s.title, url: s.url, source: s.source, published: s.saved }))
                                   : (data.items || []).filter((i) => source === "all" || i.source === source);
    clear(listCol, h("div", { class: "toolbar" }, sel, search),
      items.length ? h("ul", { class: "feed" }, items.slice(0, 150).map((i) => h("li", { class: "click", onclick: () => open(i.url, i) },
        h("div", { class: "t" }, i.title), h("div", { class: "m" }, `${day(i.published)} · ${i.source}`),
        i.summary ? h("div", { class: "small muted" }, i.summary.slice(0, 220)) : null)))
        : note(source === "saved" ? "Nothing saved yet." : "No research items yet - feeds load in the background shortly after start. Edit the source list in Settings → Feeds."),
      note("Sources: " + (data.sources || []).join(", ")));
    ctx.setContext({ page: "Research list", items: items.slice(0, 40).map((i) => ({ title: i.title, source: i.source, summary: i.summary })) });
  };

  let current = null;
  const open = async (url, meta) => {
    if (!url) return;
    clear(reader, loading("Fetching the article…"));
    const a = await api("/api/research/article?url=" + encodeURIComponent(url), { ttl: 3600000 });
    if (a.error) { clear(reader, errorBox(a.error), ext(url, "open the original")); return; }
    current = a;
    const isSaved = (data.saved || []).some((s) => s.url === url);
    const aiBox = h("div");
    clear(reader,
      h("div", { class: "toolbar" },
        ext(url, "original"),
        h("button", { class: "linkish", onclick: async (e) => {
          const res = await api("/api/research/saved", { method: "POST", body: { url, title: a.title, source: a.site || (meta && meta.source) || "", remove: isSaved } });
          data.saved = res.saved; e.target.textContent = isSaved ? "saved ✓ (reload)" : "saved ✓";
        } }, isSaved ? "remove from reading list" : "save to reading list"),
        h("button", { class: "linkish", onclick: () => summarize(a, aiBox) }, "summarize with AI"),
        h("button", { class: "linkish", onclick: () => ctx.ask("What are the key claims of this article and how strong is the evidence?", articleContext(a)) }, "ask AI")),
      aiBox,
      h("article", { class: "reader" },
        h("h2", { style: { fontSize: "22px", marginTop: "6px" } }, a.title),
        h("p", { class: "muted small" }, [a.site, a.author, a.published && a.published.slice(0, 10), a.minutes ? `${a.minutes} min read` : null].filter(Boolean).join(" · ")),
        a.note ? h("p", { class: "warn small" }, a.note) : null,
        (a.blocks || []).map((b) => b.type === "h" ? h("h3", null, b.text) : b.type === "li" ? h("p", null, "• " + b.text)
          : b.type === "quote" ? h("blockquote", null, b.text) : b.type === "code" ? h("pre", null, b.text) : h("p", null, b.text))));
    ctx.setContext(articleContext(a));
  };
  const articleContext = (a) => ({ page: "Research article: " + a.title, title: a.title, site: a.site, url: a.url,
    text: (a.blocks || []).map((b) => b.text).join("\n").slice(0, 45000) });
  const summarize = (a, box) => {
    clear(box, h("p", { class: "muted loading small" }, "summarizing…"));
    let text = "";
    import("../lib/api.js").then(({ streamChat }) => streamChat({ mode: "summarize", question: "Summarize this article.", context: articleContext(a) }, (ev) => {
      if (ev.type === "text") { text += ev.text; clear(box, h("div", { class: "small", style: { borderLeft: "2px solid var(--line2)", paddingLeft: "10px", marginBottom: "12px" } }, markdown(text))); }
      else if (ev.type === "error") clear(box, h("p", { class: "error small" }, ev.error));
    }));
  };

  clear(listCol, loading());
  await load();
  if (params[0] === "read" && params[1]) open(params[1]);
  else clear(reader, note("Pick an article on the left. The reader strips scripts, ads and trackers and shows only the text."), note("Last refresh " + ago(data.asof) + " ago."));
}
