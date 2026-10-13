// Settings: AI (bring your own key), connectors (free / free key / paid), alerts, feeds, privacy, notifications.
import { api } from "../lib/api.js";
import { h, clear, section, table, note, loading, toast, num } from "../lib/ui.js";

const TIER = { free: "free", "free-key": "free with your key", paid: "paid plan, your key" };
const KIND_ORDER = [["ai", "AI providers"], ["data", "Market data"], ["news", "News"], ["calendar", "Economic calendar"], ["broker", "Brokers & EAs (read-only)"]];

export async function render(root, _params, ctx) {
  const body = h("div", null, loading());
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Settings")), body);
  ctx.setContext({ page: "Help: settings" });
  const [s, c, u] = await Promise.all([api("/api/settings", { fresh: true }), api("/api/connectors", { fresh: true }), api("/api/ai/usage", { fresh: true })]);
  const st = s.settings;
  const patch = async (p) => { const r = await api("/api/settings", { method: "PATCH", body: p }); if (r.error) toast("Not saved", r.error); else toast("Saved", ""); return r; };

  // ---------------------------------------------------------------- AI
  const aiProviders = c.items.filter((x) => x.kind === "ai" && !x.planned);
  const provSel = h("select", null, aiProviders.map((p) => h("option", { value: p.id, selected: p.id === st.ai.provider }, p.name + (p.active ? "" : " (not set up)"))));
  const modelIn = h("input", { type: "text", list: "modelList", value: st.ai.models[st.ai.provider] || "", style: { width: "260px" } });
  const modelList = h("datalist", { id: "modelList" });
  const fillModels = () => { clear(modelList, (s.suggested_models[provSel.value] || []).map((m) => h("option", { value: m }))); modelIn.value = st.ai.models[provSel.value] || (s.suggested_models[provSel.value] || [""])[0]; };
  provSel.addEventListener("change", fillModels);
  const effort = h("select", null, ["low", "medium", "high"].map((e) => h("option", { value: e, selected: e === st.ai.effort }, e)));
  const lang = h("input", { type: "text", value: st.language, style: { width: "160px" } });
  const cap = h("input", { type: "number", value: st.ai.max_calls_per_day, min: 1, style: { width: "90px" } });
  const customUrl = h("input", { type: "text", value: st.ai.custom_base_url, placeholder: "http://127.0.0.1:1234/v1", style: { width: "260px" } });
  const ollamaUrl = h("input", { type: "text", value: st.ai.ollama_url, style: { width: "260px" } });
  const autoExplain = h("input", { type: "checkbox", checked: st.alerts.ai_explain });
  fillModels();
  const today = u.today || {};
  const aiSection = section("AI assistant",
    note("Every user brings their own key. Keys stay on this computer (or in environment variables) and are never shown again in the browser. Without a key, everything except the AI answers works."),
    h("div", { class: "formgrid" },
      h("label", null, "Provider"), provSel, h("label", null, "Model"), h("div", null, modelIn, modelList),
      h("label", null, "Answer language"), lang, h("label", null, "Thinking effort"), h("div", null, effort, h("span", { class: "muted small" }, "  Claude only: low = fastest/cheapest")),
      h("label", null, "Max AI calls per day"), cap,
      h("label", null, "Auto-explain move alerts"), h("label", null, autoExplain, "explain each new move alert with the AI (costs tokens)"),
      h("label", null, "OpenAI-compatible server URL"), customUrl, h("label", null, "Ollama URL"), ollamaUrl),
    h("div", { class: "toolbar" }, h("button", { onclick: () => patch({
      language: lang.value.trim() || "English",
      ai: { provider: provSel.value, models: { [provSel.value]: modelIn.value.trim() }, effort: effort.value, max_calls_per_day: parseInt(cap.value, 10) || 100,
            custom_base_url: customUrl.value.trim(), ollama_url: ollamaUrl.value.trim() },
      alerts: { ai_explain: autoExplain.checked } }) }, "Save AI settings")),
    h("p", { class: "small muted" }, `Today: ${today.calls || 0} calls · ${today.tok_in || 0} input / ${today.tok_out || 0} output tokens` + (today.cost ? ` · ≈ $${num(today.cost, 3)} (Anthropic prices)` : "")),
    note("The key itself goes in the provider's row under Connectors below (AI providers)."));

  // ---------------------------------------------------------------- connectors
  const connSection = section("Connectors",
    note("Free sources work out of the box. Keyed and paid sources are optional: add your own key, press Test, and SessionDesk prefers them automatically " +
         "(paid first, then free). “Not verified” means the adapter follows the vendor's documentation but has not yet been run with a live key - the Test button tells you immediately."));
  for (const [kind, title] of KIND_ORDER) {
    const items = c.items.filter((x) => (x.kind === kind) || (kind === "data" && !KIND_ORDER.some(([k]) => k === x.kind)));
    if (!items.length) continue;
    connSection.appendChild(h("h3", null, title));
    for (const it of items) connSection.appendChild(connectorRow(it));
  }

  // ---------------------------------------------------------------- alerts & universes & events
  const al = st.alerts, ev = st.events;
  const n = (v, w = 70) => h("input", { type: "number", value: v, step: "0.1", style: { width: w + "px" } });
  const f = { min_abs_pct: n(al.min_abs_pct), min_abs_z: n(al.min_abs_z), always_abs_pct: n(al.always_abs_pct), watchlist_abs_pct: n(al.watchlist_abs_pct),
              watchlist_abs_z: n(al.watchlist_abs_z), scan_minutes: n(al.scan_minutes) };
  const unis = Object.entries(s.universes).map(([k, label]) => h("label", null, h("input", { type: "checkbox", value: k, checked: st.universes.includes(k) }), label));
  const warn = h("input", { type: "text", value: ev.warn_minutes.join(", "), style: { width: "120px" } });
  const ccy = h("input", { type: "text", value: ev.currencies.join(", "), style: { width: "320px" } });
  const medium = h("input", { type: "checkbox", checked: ev.impact.includes("medium") });
  const alertSection = section("Alerts",
    h("div", { class: "formgrid" },
      h("label", null, "Index members"), h("div", null, "flag when move ≥ ", f.min_abs_pct, " % and ≥ ", f.min_abs_z, " σ, or ≥ ", f.always_abs_pct, " % outright"),
      h("label", null, "Watchlist"), h("div", null, "flag when move ≥ ", f.watchlist_abs_pct, " % and ≥ ", f.watchlist_abs_z, " σ"),
      h("label", null, "Scan every"), h("div", null, f.scan_minutes, " minutes while markets are open"),
      h("label", null, "Scan these indices"), h("div", { class: "toolbar", style: { margin: 0 } }, unis),
      h("label", null, "Release warnings"), h("div", null, warn, " minutes before · ", h("label", null, medium, "also medium impact")),
      h("label", null, "Currencies"), ccy),
    h("div", { class: "toolbar" }, h("button", { onclick: () => patch({
      alerts: Object.fromEntries(Object.entries(f).map(([k, el]) => [k, parseFloat(el.value)])),
      universes: unis.map((l) => l.firstChild).filter((x) => x.checked).map((x) => x.value),
      events: { warn_minutes: warn.value.split(/[ ,;]+/).map(Number).filter((x) => x > 0), currencies: ccy.value.split(/[ ,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean),
                impact: medium.checked ? ["high", "medium"] : ["high"] } }) }, "Save alert settings")),
    h("div", { class: "toolbar" },
      h("button", { onclick: async () => { const p = await Notification.requestPermission(); toast("Browser notifications", p); } }, "Allow desktop notifications"),
      h("label", null, h("input", { type: "checkbox", checked: localStorage.getItem("sd.sound") !== "off", onchange: (e) => localStorage.setItem("sd.sound", e.target.checked ? "on" : "off") }), "sound on alerts")),
    note("Desktop notifications appear when the SessionDesk tab is in the background. Keep the tab open (pinned) to receive them."));

  // ---------------------------------------------------------------- feeds
  const feedsSection = section("Feeds");
  const conn = c.items.find((x) => x.id === "rss");
  const feedsApi = await api("/api/settings", { fresh: true });
  const groups = ["squawk", "markets", "central_banks", "research"];
  for (const g of groups) {
    const current = (feedsApi.settings.feeds || {})[g];
    const ta = h("textarea", { rows: 4, style: { width: "100%", fontFamily: "var(--mono)", fontSize: "12px" },
      placeholder: "Name | https://feed.url  (one per line; empty = built-in list)" },
      Array.isArray(current) ? current.map((x) => `${x.name} | ${x.url}`).join("\n") : "");
    feedsSection.append(h("h3", null, g.replace("_", " ")), ta, h("div", { class: "toolbar" },
      h("button", { onclick: async () => {
        const lines = ta.value.split("\n").map((l) => l.trim()).filter(Boolean);
        const list = lines.map((l) => { const [name, url] = l.includes("|") ? l.split("|").map((x) => x.trim()) : [l, l]; return { name, url }; });
        await patch({ feeds: { ...(feedsApi.settings.feeds || {}), [g]: lines.length ? list : null } });
      } }, "Save " + g.replace("_", " "))));
  }
  feedsSection.appendChild(note("Leave a box empty to use the built-in list (see docs/CONNECTORS.md). " + (conn ? "" : "")));

  // ---------------------------------------------------------------- privacy
  const mask = h("input", { type: "checkbox", checked: st.privacy.mask_accounts });
  const privacy = section("Privacy",
    h("label", null, mask, "mask account numbers (show only the last 3 digits)"),
    h("div", { class: "toolbar" }, h("button", { onclick: () => patch({ privacy: { mask_accounts: mask.checked } }) }, "Save")),
    note(`Data folder: ${s.data_dir} - settings, keys (secrets.json), cache, news archive and job logs. Nothing is sent anywhere except the requests to the sources you enable.`));

  clear(body, aiSection, connSection, alertSection, feedsSection, privacy);
}

function connectorRow(it) {
  const inputs = {};
  const stateTxt = it.planned ? "planned" : it.active ? "active" : it.configured ? "disabled" : "not set up";
  const row = h("div", { class: "conn-row" });
  const bodyEl = h("div", { class: "body", hidden: true });
  const head = h("div", { class: "head" },
    h("span", { class: "name" }, it.homepage ? h("a", { href: it.homepage, target: "_blank", rel: "noopener noreferrer" }, it.name) : it.name),
    h("span", { class: "tier" }, TIER[it.tier] || it.tier),
    h("span", { class: "state " + (it.active ? "ok" : "no") }, stateTxt),
    !it.verified && !it.planned ? h("span", { class: "tag warn" }, "not verified with a live key") : null,
    it.planned ? null : h("button", { class: "linkish", onclick: () => { bodyEl.hidden = !bodyEl.hidden; } }, "configure"));
  row.append(head, h("div", { class: "small muted" }, it.description), bodyEl);
  if (it.planned) return row;
  const result = h("span", { class: "small" });
  const enabled = h("input", { type: "checkbox", checked: it.enabled });
  const fields = it.fields.map((f) => {
    const input = h("input", { type: f.secret ? "password" : "text", autocomplete: "off", style: { width: "340px" },
      placeholder: f.secret ? (f.state && f.state.set ? `set (${f.state.source}, ${f.state.hint})` : "paste your key") : (f.placeholder || "") });
    if (!f.secret) input.value = f.value || "";
    inputs[f.key] = input;
    return [h("label", null, f.label + (f.required ? "" : " (optional)")), h("div", null, input, f.help ? h("div", { class: "small muted" }, f.help) : null)];
  });
  const save = async () => {
    const payload = { enabled: enabled.checked, fields: {} };
    for (const f of it.fields) {
      const v = inputs[f.key].value.trim();
      if (!f.secret || v) payload.fields[f.key] = v;
    }
    const r = await api(`/api/connectors/${it.id}`, { method: "POST", body: payload });
    if (r.error) { toast("Not saved", r.error); return; }
    for (const f of it.fields) if (f.secret) inputs[f.key].value = "";
    toast(it.name, r.active ? "active" : r.configured ? "saved (disabled)" : "saved - required fields missing");
  };
  const clearKey = async () => {
    const payload = { fields: Object.fromEntries(it.fields.filter((f) => f.secret).map((f) => [f.key, ""])) };
    await api(`/api/connectors/${it.id}`, { method: "POST", body: payload });
    toast(it.name, "stored key removed (environment variables still apply)");
  };
  const test = async () => {
    result.textContent = "testing…"; result.className = "small muted loading";
    const r = await api(`/api/connectors/${it.id}/test`, { method: "POST" });
    result.className = "small " + (r.ok ? "up" : "down");
    result.textContent = (r.ok ? "OK · " : "Failed · ") + (r.detail || r.error || "");
  };
  bodyEl.append(h("div", { class: "formgrid" }, h("label", null, "Enabled"), h("label", null, enabled, "use this connector"), fields),
    h("div", { class: "toolbar" }, h("button", { onclick: save }, "Save"), h("button", { onclick: test }, "Test connection"),
      it.fields.some((f) => f.secret) ? h("button", { class: "linkish", onclick: clearKey }, "remove stored key") : null, result));
  return row;
}
