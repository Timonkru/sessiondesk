// Shell: router, command bar (stock search or AI question), AI drawer, event countdown, push notifications.
import { api, connect, on, streamChat } from "./lib/api.js";
import { h, clear, toast, notify, beep, markdown, countdown, errorBox } from "./lib/ui.js";

const VIEWS = {
  today: () => import("./views/today.js"),
  overview: () => import("./views/overview.js"),
  markets: () => import("./views/overview.js"),
  journal: () => import("./views/journal.js"),
  stock: () => import("./views/stock.js"),
  watch: () => import("./views/watch.js"),
  levels: () => import("./views/levels.js"),
  indices: () => import("./views/indices.js"),
  news: () => import("./views/news.js"),
  calendar: () => import("./views/calendar.js"),
  flows: () => import("./views/flows.js"),
  research: () => import("./views/research.js"),
  macro: () => import("./views/macro.js"),
  broker: () => import("./views/broker.js"),
  jobs: () => import("./views/jobs.js"),
  settings: () => import("./views/settings.js"),
  help: () => import("./views/help.js"),
};

const $ = (id) => document.getElementById(id);
const viewEl = $("view");
let cleanup = null;
let pageContext = { page: "Markets overview" };
let renderSeq = 0;

// Each view calls ctx.setContext({...}) with the data it shows; the AI gets exactly that.
const ctx = {
  setContext(obj) { pageContext = obj; $("aiCtx").textContent = "context: " + (obj.page || ""); },
  go(hash) { location.hash = hash; },
  ask(question, context) { openAI(); if (context) ctx.setContext(context); sendAI(question); },
};

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  let name = parts[0] && VIEWS[parts[0]] ? parts[0] : "today";
  if (name === "markets") name = "overview";
  return { name, params: parts.slice(1) };
}

async function route() {
  const { name, params } = parseRoute();
  const seq = ++renderSeq;
  document.querySelectorAll("#nav a[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  $("nav").classList.remove("open");
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  clear(viewEl);
  viewEl.scrollTop = 0;
  try {
    const mod = await VIEWS[name]();
    if (seq !== renderSeq) return;
    const root = h("div");
    viewEl.appendChild(root);
    cleanup = (await mod.render(root, params, ctx)) || null;
  } catch (err) {
    console.error(err);
    if (seq === renderSeq) viewEl.appendChild(errorBox("This page failed to load: " + err.message));   // not on a page opened since
  }
}

// ------------------------------------------------------------------ command bar
const input = $("cmdInput"), list = $("cmdList");
let results = [], sel = -1, searchTimer = null;

function looksLikeTicker(q) { return /^[\^]?[A-Za-z0-9]{1,6}([.=\-][A-Za-z0-9]{1,4})?$/.test(q.trim()); }

function renderList() {
  clear(list);
  list.hidden = !results.length;
  results.forEach((r, i) => {
    list.appendChild(h("div", { class: i === sel ? "sel" : "", onmousedown: (e) => { e.preventDefault(); pick(i); } },
      h("span", { class: "sym" }, r.symbol), h("span", null, r.name || ""), h("span", { class: "muted" }, r.exchange || "")));
  });
  if (input.value.trim() && !looksLikeTicker(input.value)) {
    list.hidden = false;
    list.appendChild(h("div", { class: sel === results.length ? "sel" : "", onmousedown: (e) => { e.preventDefault(); askFromBar(); } },
      h("span", { class: "sym" }, "Ask AI"), h("span", { class: "muted" }, `“${input.value.trim()}” about this page`)));
  }
}

function pick(i) {
  const r = results[i];
  if (!r) return;
  input.value = ""; results = []; renderList(); input.blur();
  ctx.go("#/stock/" + encodeURIComponent(r.symbol));
}

function askFromBar() {
  const q = input.value.trim().replace(/^\?\s*/, "");
  input.value = ""; results = []; renderList(); input.blur();
  if (q) ctx.ask(q);
}

input.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = input.value.trim();
  sel = -1;
  if (!q || q.startsWith("?") || q.split(/\s+/).length > 3) { results = []; renderList(); return; }
  searchTimer = setTimeout(async () => {
    const d = await api("/api/search?q=" + encodeURIComponent(q), { ttl: 60000 });
    if (input.value.trim() !== q) return;
    results = d.items || [];
    renderList();
  }, 140);
});
input.addEventListener("keydown", (e) => {
  const max = results.length + (input.value.trim() && !looksLikeTicker(input.value) ? 1 : 0);
  if (e.key === "ArrowDown") { sel = Math.min(max - 1, sel + 1); renderList(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { sel = Math.max(-1, sel - 1); renderList(); e.preventDefault(); }
  else if (e.key === "Escape") { input.value = ""; results = []; renderList(); input.blur(); }
  else if (e.key === "Enter") {
    e.preventDefault();
    const q = input.value.trim();
    if (sel >= 0 && sel < results.length) pick(sel);
    else if (sel === results.length && max > results.length) askFromBar();
    else if (q.startsWith("?")) askFromBar();
    else if (looksLikeTicker(q)) { input.value = ""; results = []; renderList(); ctx.go("#/stock/" + encodeURIComponent(q.toUpperCase())); }
    else askFromBar();
  }
});
input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
});

// ------------------------------------------------------------------ AI drawer
const aiLog = $("aiLog"), aiInput = $("aiInput");
let history = [], aiAbort = null;

function openAI() { $("ai").hidden = false; setTimeout(() => aiInput.focus(), 0); }
$("aiToggle").addEventListener("click", () => { $("ai").hidden ? openAI() : ($("ai").hidden = true); });
$("aiClose").addEventListener("click", () => { $("ai").hidden = true; });
$("aiClear").addEventListener("click", () => { history = []; clear(aiLog); if (aiAbort) aiAbort.abort(); });
$("aiForm").addEventListener("submit", (e) => { e.preventDefault(); const q = aiInput.value.trim(); if (q) { aiInput.value = ""; sendAI(q); } });
aiInput.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("aiForm").requestSubmit(); } });

async function sendAI(question, mode = "ask") {
  openAI();
  aiLog.appendChild(h("div", { class: "msg user" }, h("div", { class: "who" }, "You"), h("div", { class: "body" }, question)));
  const body = h("div", { class: "body" }, h("span", { class: "muted loading" }, "thinking…"));
  const who = h("div", { class: "who" }, "AI");
  aiLog.appendChild(h("div", { class: "msg" }, who, body));
  aiLog.scrollTop = aiLog.scrollHeight;
  if (aiAbort) aiAbort.abort();
  aiAbort = new AbortController();
  let text = "";
  const isSupport = mode === "support" || (pageContext.page || "").startsWith("Help");
  try {
    await streamChat({ mode: isSupport ? "support" : mode, question, context: pageContext, history }, (ev) => {
      if (ev.type === "meta") who.textContent = `AI · ${ev.provider} · ${ev.model}`;
      else if (ev.type === "text") { text += ev.text; clear(body, markdown(text)); aiLog.scrollTop = aiLog.scrollHeight; }
      else if (ev.type === "error") {
        clear(body, h("p", { class: "error" }, ev.error));
        if (/No AI provider/.test(ev.error)) body.appendChild(h("a", { href: "#/settings" }, "Open Settings → AI"));
      } else if (ev.type === "done") {
        const u = ev.usage || {};
        $("aiMeta").textContent = `${u.in ?? "?"} in / ${u.out ?? "?"} out tokens` + (ev.cost != null ? ` · ≈ $${ev.cost.toFixed(4)}` : "") + ` · ${ev.seconds}s`;
      }
    }, aiAbort.signal);
  } catch (err) {
    if (err.name !== "AbortError") clear(body, h("p", { class: "error" }, String(err)));
  }
  if (text) { history.push({ role: "user", content: question }, { role: "assistant", content: text }); history = history.slice(-8); }
}
export { sendAI };

// ------------------------------------------------------------------ event countdown + release bar
let nextEvent = null;
async function loadNextEvent() {
  const d = await api("/api/calendar?days=7&back_hours=0", { fresh: true });
  const now = Date.now() / 1000;
  nextEvent = (d.events || []).filter((e) => e.impact === "high" && e.ts > now).sort((a, b) => a.ts - b.ts)[0] || null;
}
function tickStrip() {
  const el = $("eventStrip");
  if (!nextEvent) { el.textContent = ""; return; }
  const left = nextEvent.ts - Date.now() / 1000;
  if (left < -60) { nextEvent = null; loadNextEvent(); return; }
  el.textContent = `${nextEvent.currency} ${nextEvent.title} · ${left > 0 ? "in " + countdown(left) : "now"}` + (nextEvent.forecast ? ` · fcst ${nextEvent.forecast}` : "");
  el.classList.toggle("soon", left < 1800);
}
$("eventStrip").addEventListener("click", () => ctx.go("#/calendar"));

function showRelease(text) {
  const bar = $("releaseBar");
  bar.hidden = false;
  bar.textContent = text;
  clearTimeout(showRelease.t);
  showRelease.t = setTimeout(() => { bar.hidden = true; }, 5 * 60 * 1000);
}

// ------------------------------------------------------------------ push handlers
function wirePush() {
  on("event_warning", ({ event, minutes }) => {
    const t = `${event.currency} ${event.title} in ${minutes} min`;
    toast(t, event.forecast ? `forecast ${event.forecast} · previous ${event.previous ?? "–"}` : "", { kind: "high", onClick: () => ctx.go("#/calendar") });
    notify("High-impact release soon", t);
    beep("high");
  });
  on("release", ({ event, source }) => {
    const s = event.surprise != null ? ` · surprise ${event.surprise > 0 ? "+" : ""}${Number(event.surprise.toFixed(3))}` : "";
    const t = `${event.currency} ${event.title}: ${event.actual}  (forecast ${event.forecast ?? "–"}, previous ${event.previous ?? "–"})${s}`;
    showRelease("RELEASED  " + t + `  · via ${source}`);
    toast("Released", t, { kind: "high" });
    notify("Released: " + event.title, t);
    beep("high");
  });
  on("release_headline", ({ event, headline }) => {
    const t = `${headline.source}: ${headline.title}`;
    showRelease(`${event.currency} ${event.title}  ·  ${t}`);
    toast(event.title, t, { kind: "high" });
    notify(event.title, t);
    beep("high");
  });
  on("alert", ({ alert }) => {
    const kind = alert.data && alert.data.pct > 0 ? "up" : "down";
    toast(alert.title, (alert.body || "").split(". ").slice(0, 2).join(". ").slice(0, 160), { kind, onClick: () => ctx.go("#/stock/" + encodeURIComponent(alert.symbol)) });
    notify("Unusual move: " + alert.title, (alert.body || "").slice(0, 180));
  });
  on("level", ({ alert }) => {
    toast(alert.title, alert.body, { kind: (alert.data || {}).direction === "up" ? "up" : "down", onClick: () => ctx.go("#/levels") });
    notify("Level: " + alert.title, alert.body);
    beep("info");
  });
  on("position", ({ title, position }) => {
    toast(title, "", { kind: position && position.sl ? "" : "high", onClick: () => ctx.go("#/broker") });
    notify("Position", title);
  });
  on("alert_digest", ({ count, top }) => {
    toast(`${count} unusual moves today`, (top || []).join(" · "), { onClick: () => ctx.go("#/watch") });
  });
  on("news", ({ item }) => {
    if (item.impact === "high") {
      toast(item.source + (item.tags && item.tags.length ? " · " + item.tags[0] : ""), item.title, { kind: "high", onClick: () => ctx.go("#/news") });
      notify(item.source, item.title);
      beep("high");
    }
  });
}

// ------------------------------------------------------------------ theme, menu, boot
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
applyTheme(localStorage.getItem("sd.theme"));
$("theme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const next = cur === "dark" ? "light" : "dark";
  localStorage.setItem("sd.theme", next); applyTheme(next);
});
$("menu").addEventListener("click", () => $("nav").classList.toggle("open"));

window.addEventListener("hashchange", route);
connect((live) => { const c = $("conn"); c.textContent = live ? "live" : "offline"; c.className = live ? "live" : "off"; });
wirePush();
route();
loadNextEvent();
setInterval(tickStrip, 1000);
setInterval(loadNextEvent, 5 * 60 * 1000);
