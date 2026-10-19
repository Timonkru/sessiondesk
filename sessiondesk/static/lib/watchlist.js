// Watchlist block: add / remove symbols, live quotes with today's path. Lives on the Markets page.
import { api } from "./api.js";
import { h, clear, table, section, sparkline, price, pct, dir, errorBox, loading } from "./ui.js";

export function watchlist(onData = () => {}) {
  const el = h("div", null, section("Watchlist", loading()));
  const load = async () => {
    const d = await api("/api/watchlist", { fresh: true });
    const q = d.quotes || {};
    const editor = h("input", { type: "text", placeholder: "add symbol, e.g. NVDA, SAP.DE, ^FTSE", style: { width: "220px" } });
    const save = async (symbols) => { await api("/api/watchlist", { method: "PUT", body: { symbols } }); load(); };
    const add = () => {
      const sym = editor.value.trim().toUpperCase();
      if (sym && !(d.symbols || []).includes(sym)) save([...(d.symbols || []), sym]);
    };
    editor.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    clear(el, section("Watchlist", h("div", { class: "toolbar" }, editor, h("button", { onclick: add }, "Add")),
      table([
        { label: "Symbol", render: (s) => h("a", { href: "#/stock/" + encodeURIComponent(s) }, s) },
        { label: "Last", num: true, render: (s) => price(q[s] && q[s].price) },
        { label: "Δ %", num: true, cls: (s) => dir(q[s] && q[s].change_pct), render: (s) => pct(q[s] && q[s].change_pct) },
        { label: "Today", num: true, render: (s) => sparkline(q[s] && q[s].spark, { ref: q[s] && q[s].prev_close }) },
        { label: "", num: true, render: (s) => h("button", { class: "linkish", onclick: () => save(d.symbols.filter((x) => x !== s)) }, "remove") },
      ], d.symbols || [], { empty: "Your watchlist is empty - add a symbol above." }),
      d.error ? errorBox(d.error) : null));
    onData(d);
  };
  return { el, load };
}
