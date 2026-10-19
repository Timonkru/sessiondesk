// Local extension page: renders the blocks an extension module returns (see sessiondesk/extensions.py).
// Everything goes into the DOM as text; the AI context is the same block data.
import { api } from "../lib/api.js";
import { h, clear, note, loading, errorBox, ago, toast } from "../lib/ui.js";
import { block } from "../lib/blocks.js";

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
