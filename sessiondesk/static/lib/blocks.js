// Renders the blocks extensions return (see sessiondesk/extensions.py). Everything goes into the DOM as text.
import { api } from "./api.js";
import { h, table, section, note, markdown } from "./ui.js";

const LEVEL = { high: "warn", warn: "warn", ok: "up", muted: "muted" };
const text = (v) => (v === null || v === undefined ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function block(b, name, reload = () => {}) {
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
