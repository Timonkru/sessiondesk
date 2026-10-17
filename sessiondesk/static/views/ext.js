// Local extension page: renders the blocks an extension module returns (see sessiondesk/extensions.py).
// Everything goes into the DOM as text; the AI context is the same block data.
import { api } from "../lib/api.js";
import { h, clear, table, section, note, loading, errorBox, markdown, ago, toast } from "../lib/ui.js";

const LEVEL = { high: "warn", warn: "warn", ok: "up", muted: "muted" };
const text = (v) => (v === null || v === undefined ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v));

function block(b, name, reload) {
  const t = b.title || null;
  switch (b.type) {
    case "kv":
      return section(t, h("dl", { class: "kv" }, (b.items || []).flatMap(([k, v]) => [h("dt", null, text(k)), h("dd", null, text(v))])));
    case "table": {
      const cols = (b.columns || []).map((c) => ({ label: c.label ?? c.key, num: !!c.num, render: (r) => text(r[c.key]),
        cls: (r) => (r._level && c === b.columns[0] ? LEVEL[r._level] || "" : "") }));
      return section(t, table(cols, b.rows || [], { empty: b.empty || "Nothing here." }), b.note ? note(b.note) : null);
    }
    case "list":
      return section(t, (b.items || []).length ? h("ul", { class: "feed" }, b.items.map((it) => {
        const o = typeof it === "object" && it ? it : { text: it };
        return h("li", null, h("div", { class: "t " + (LEVEL[o.level] || "") }, text(o.text)), o.detail ? h("div", { class: "m" }, text(o.detail)) : null);
      })) : note(b.empty || "Nothing here."));
    case "text":
      return section(t, markdown(text(b.text)));
    case "note":
      return note(text(b.text));
    case "input": {
      const inp = h("input", { type: "text", placeholder: b.placeholder || "", style: { width: "100%" } });
      const out = h("p", { class: "small muted" });
      inp.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter" || !inp.value.trim()) return;
        const res = await api(`/api/ext/${encodeURIComponent(name)}/action`, { method: "POST", body: { action: b.action || "input", text: inp.value.trim() } });
        out.textContent = res.error ? res.error : text(res.message ?? res.result ?? "done");
        if (!res.error) { inp.value = ""; reload(); }
      });
      return section(t, inp, out);
    }
    default:
      return note(`Unknown block type “${text(b.type)}”.`);
  }
}

export async function render(root, params, ctx) {
  const name = params[0] || "";
  const head = h("div", { class: "pagehead" }, h("h1", null, name), h("span", { class: "meta" }));
  const body = h("div", null, loading());
  root.append(head, body);
  let timer = null;

  const load = async () => {
    const d = await api(`/api/ext/${encodeURIComponent(name)}`, { fresh: true });
    const meta = d.extension || {};
    clear(head, h("h1", null, meta.title || name), h("span", { class: "meta" }, meta.description || "local extension"),
      h("button", { class: "linkish", onclick: async () => { await api("/api/extensions/reload", { method: "POST" }); window.dispatchEvent(new Event("sd:extensions")); toast("Extensions reloaded"); load(); } }, "reload code"));
    if (d.error) { clear(body, errorBox(d.error), d.trace ? h("pre", { class: "small" }, d.trace) : null, note(`File: ${meta.path || "?"}`)); return; }
    const left = h("div"), right = h("div");
    for (const b of d.blocks) (b.cols === 2 ? right : left).appendChild(block(b, name, load));
    clear(body, right.childElementCount ? h("div", { class: "cols" }, left, right) : left,
      note(`Local extension · ${meta.path || ""} · updated ${ago(d.asof)} ago${meta.refresh ? ` · refreshes every ${meta.refresh} s` : ""}.`));
    ctx.setContext({ page: `Extension ${meta.title || name}`, blocks: d.blocks.filter((b) => b.type !== "input") });
    if (meta.refresh && !timer) timer = setInterval(load, Math.max(5, meta.refresh) * 1000);
  };
  await load();
  return () => { if (timer) clearInterval(timer); };
}
