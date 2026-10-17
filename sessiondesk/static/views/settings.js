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

  // ---------------------------------------------------------------- trading setup (JSON per key)
  const ADV = [
    ["prop_rules", "Prop rules per account", '{"*": {"daily_loss_pct": 5, "own_stop_pct": 1.5, "max_loss_pct": 10, "initial_balance": 100000, "risk_per_trade_pct": 0.25, "max_slots": 3}}'],
    ["schedule", "Schedule entries", '[{"label": "opening range done", "session": "EU", "offset_min": 30}, {"label": "lunch", "session": "EU", "time": "12:15", "tz": "Europe/Berlin"}]'],
    ["sessions", "Cash sessions (empty = EU + US)", '{"EU": {"open": "09:00", "close": "17:30", "tz": "Europe/Berlin", "calendar": "EU"}}'],
    ["level_files", "Level files", '[{"title": "Gamma levels", "path": "C:/path/today_levels.txt"}]'],
    ["level_markets", "Level markets without broker quotes", '["DAX", "NQ", "DOW", "SPX", "GOLD"]'],
    ["round_steps", "Round-number steps", '{"DAX": 500, "GOLD": 50}'],
    ["magic_names", "Setup names per EA magic number", '{"123456": "Opening breakout"}'],
    ["asset_patterns", "Extra broker symbol patterns", '{"DAX": ["DE40.CASH"]}'],
    ["scenario_drivers", "Scenario driver markets", '["NQ", "DAX"]'],
  ];
  const adv = section("Trading setup",
    note("Personal setup lives only in your local data folder. Each box takes JSON; the example shows the shape."),
    ...ADV.map(([key, label, example]) => {
      const ta = h("textarea", { rows: 3, style: { width: "100%", fontFamily: "var(--mono)", fontSize: "12px" }, placeholder: example },
        st[key] !== undefined && JSON.stringify(st[key]) !== "{}" && JSON.stringify(st[key]) !== "[]" ? JSON.stringify(st[key], null, 1) : "");
      const status = h("span", { class: "small muted" });
      const save = async () => {
        let value;
        try { value = ta.value.trim() ? JSON.parse(ta.value) : (Array.isArray(JSON.parse(example)) ? [] : {}); }
        catch (e) { status.textContent = "not valid JSON: " + e.message; status.className = "small down"; return; }
        const r = await api("/api/settings", { method: "PATCH", body: { [key]: value } });
        status.textContent = r.error ? r.error : "saved"; status.className = "small " + (r.error ? "down" : "up");
      };
      return h("div", { style: { margin: "10px 0" } }, h("label", { class: "small" }, h("strong", null, label), h("span", { class: "muted" }, ` (${key})`)), ta,
        h("div", { class: "toolbar", style: { margin: "4px 0" } }, h("button", { onclick: save }, "Save"), status));
    }),
    h("div", { class: "formgrid" }, h("label", null, "Daily AI briefing at"),
      h("div", null, (() => { const i = h("input", { type: "text", value: st.briefing_time || "", placeholder: "08:40 (empty = off)", style: { width: "120px" } });
        const b = h("button", { onclick: () => patch({ briefing_time: i.value.trim() }) }, "Save"); return [i, " ", b, h("span", { class: "muted small" }, "  weekdays, local time")]; })())));

  // ---------------------------------------------------------------- phone push
  const pushBox = h("div", null, loading());
  const pushSection = section("Phone push", pushBox);
  const drawPush = (d) => {
    const c = d.config, sec = d.secrets;
    const on = h("input", { type: "checkbox", checked: c.enabled });
    const service = h("select", null, [["ntfy", "ntfy (free app, iOS/Android)"], ["telegram", "Telegram (your own bot)"]].map(([v, l]) => h("option", { value: v, selected: c.service === v }, l)));
    const secretInput = (key, ph) => h("input", { type: "password", autocomplete: "off", placeholder: sec[key].set ? `set (${sec[key].hint}) - type to replace` : ph, style: { width: "100%" } });
    const server = h("input", { type: "text", value: c.ntfy_server, style: { width: "100%" } });
    const topic = secretInput("ntfy_topic", "your topic, e.g. " + d.suggested_topic);
    const ntfyToken = secretInput("ntfy_token", "optional access token (own server / reserved topic)");
    const tgToken = secretInput("telegram_token", "bot token from @BotFather");
    const chat = h("input", { type: "text", value: c.telegram_chat || "", placeholder: "chat id", style: { width: "160px" } });
    const chats = h("span", { class: "small muted" });
    const evs = d.events.map((e) => [e.key, h("input", { type: "checkbox", checked: !!c.events[e.key] }), e.label]);
    const warn = h("input", { type: "text", value: (c.warn_minutes || []).join(", "), style: { width: "90px" } });
    const qFrom = h("input", { type: "text", value: c.quiet_from || "", placeholder: "22:00", style: { width: "70px" } });
    const qTo = h("input", { type: "text", value: c.quiet_to || "", placeholder: "07:00", style: { width: "70px" } });
    const maxH = h("input", { type: "number", value: c.max_per_hour, min: 1, max: 500, style: { width: "70px" } });
    const result = h("span", { class: "small" });
    const save = async () => {
      const body = { config: { enabled: on.checked, service: service.value, ntfy_server: server.value.trim() || "https://ntfy.sh", telegram_chat: chat.value.trim(),
        events: Object.fromEntries(evs.map(([k, box]) => [k, box.checked])), quiet_from: qFrom.value.trim(), quiet_to: qTo.value.trim(),
        warn_minutes: warn.value.split(/[ ,]+/).map(Number).filter((x) => x > 0), max_per_hour: Number(maxH.value) || 30 },
        secrets: Object.fromEntries([["ntfy_topic", topic], ["ntfy_token", ntfyToken], ["telegram_token", tgToken]].filter(([, i]) => i.value.trim()).map(([k, i]) => [k, i.value.trim()])) };
      const r = await api("/api/push", { method: "POST", body });
      if (r.error) toast("Not saved", r.error); else { toast("Saved", ""); drawPush(r); }
    };
    const test = async () => { result.textContent = "sending…"; const r = await api("/api/push/test", { method: "POST" }); result.textContent = r.ok ? "sent - check your phone" : r.error; result.className = "small " + (r.ok ? "up" : "down"); };
    const findChat = async () => { const r = await api("/api/push/telegram_chats", { fresh: true }); if (r.error) { chats.textContent = r.error; return; }
      chats.textContent = r.chats.length ? r.chats.map((x) => `${x.id} (${x.name})`).join(", ") : r.note; if (r.chats.length === 1) chat.value = r.chats[0].id; };
    clear(pushBox,
      h("div", { class: "formgrid" },
        h("label", null, "Send to phone"), h("div", null, h("label", null, on, " on"), "  ", service),
        h("label", null, "ntfy server"), server, h("label", null, "ntfy topic"), h("div", null, topic, h("button", { class: "linkish", onclick: () => { topic.type = "text"; topic.value = d.suggested_topic; } }, "use a random topic")),
        h("label", null, "ntfy token"), ntfyToken,
        h("label", null, "Telegram bot token"), tgToken,
        h("label", null, "Telegram chat"), h("div", null, chat, " ", h("button", { class: "linkish", onclick: findChat }, "find my chat id"), " ", chats),
        h("label", null, "Warn minutes before"), h("div", null, warn, h("span", { class: "muted small" }, "  minutes before a high-impact release (the app itself warns at 30/5/1)")),
        h("label", null, "Quiet hours"), h("div", null, qFrom, " to ", qTo, h("span", { class: "muted small" }, "  only position changes come through")),
        h("label", null, "Max per hour"), maxH),
      h("div", { class: "checks" }, evs.map(([, box, label]) => h("label", { style: { display: "block" } }, box, " ", label))),
      h("div", { class: "toolbar" }, h("button", { onclick: save }, "Save"), h("button", { onclick: test }, "Send test"), result),
      d.log.length ? table([{ label: "Sent", render: (x) => new Date(x.ts * 1000).toLocaleString() }, { label: "Message", render: (x) => x.title },
        { label: "Result", render: (x) => h("span", { class: x.ok ? "up" : "down" }, x.ok ? "ok" : x.error) }], d.log.slice(0, 8)) : null,
      note("ntfy: install the ntfy app, subscribe to the same topic, and treat the topic like a password (on ntfy.sh anyone who knows it can read it). " +
        "Telegram: create a bot with @BotFather, paste its token, send the bot any message, then 'find my chat id'. Topic and tokens are stored in secrets.json. " +
        `Rate limit and duplicates are handled here${d.dropped ? `; ${d.dropped} messages were dropped by the hourly limit` : ""}.`));
  };
  api("/api/push", { fresh: true }).then(drawPush);

  // ---------------------------------------------------------------- local extensions
  const extBox = h("div");
  const drawExt = (d) => clear(extBox,
    table([{ label: "Page", render: (e) => h("a", { href: "#/ext/" + encodeURIComponent(e.name) }, e.title) },
      { label: "File", render: (e) => h("span", { class: "muted small" }, e.path) },
      { label: "Status", render: (e) => h("span", { class: e.error ? "down" : "up" }, e.error || "loaded") }],
      d.items || [], { empty: d.enabled === false ? "Extensions are switched off." : "No extensions in the folder." }),
    note(`Folder: ${d.folder}. A .py file there (or a folder with extension.py) becomes a page in the navigation. ` +
      "It runs inside SessionDesk with your rights - only your own code. Format and an example: docs/EXTENSIONS.md."));
  const extOn = h("input", { type: "checkbox", checked: st.extensions_enabled !== false });
  const extSection = section("Extensions", extBox,
    h("div", { class: "toolbar" }, h("label", null, extOn, "load extensions"),
      h("button", { onclick: async () => { await patch({ extensions_enabled: extOn.checked }); const d = await api("/api/extensions/reload", { method: "POST" }); drawExt(d); window.dispatchEvent(new Event("sd:extensions")); toast("Extensions reloaded", ""); } }, "Save & reload")));
  api("/api/extensions", { fresh: true }).then(drawExt);

  clear(body, aiSection, connSection, alertSection, pushSection, adv, feedsSection, extSection, privacy);
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
