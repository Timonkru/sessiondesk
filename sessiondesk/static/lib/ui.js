// DOM + formatting helpers. Every piece of outside text goes in via textContent, never innerHTML:
// headlines, article text and AI answers are untrusted.

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

export function svg(tag, attrs, ...children) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
  for (const c of children.flat(Infinity)) if (c) el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

// ---------------------------------------------------------------- numbers
const nf = (d) => new Intl.NumberFormat(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const cache = {};
export function num(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return (cache[d] ||= nf(d)).format(v);
}
export function price(v) {
  if (v === null || v === undefined) return "–";
  const a = Math.abs(v);
  return num(v, a >= 1000 ? 2 : a >= 10 ? 2 : a >= 1 ? 3 : 4);
}
export function pct(v, d = 2, sign = true) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return (sign && v > 0 ? "+" : "") + num(v, d) + "%";
}
export function ratio(v, d = 1) {            // fraction -> percent text
  return v === null || v === undefined ? "–" : pct(v * 100, d, false);
}
export function big(v) {
  if (v === null || v === undefined) return "–";
  const a = Math.abs(v);
  if (a >= 1e12) return num(v / 1e12, 2) + " T";
  if (a >= 1e9) return num(v / 1e9, 2) + " B";
  if (a >= 1e6) return num(v / 1e6, 1) + " M";
  if (a >= 1e3) return num(v / 1e3, 1) + " K";
  return num(v, 0);
}
export function signed(v, d = 2) {
  if (v === null || v === undefined) return "–";
  return (v > 0 ? "+" : "") + num(v, d);
}
export function dir(v) { return v > 0 ? "up" : v < 0 ? "down" : ""; }

// ---------------------------------------------------------------- time
export function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.round(s / 60) + "m";
  if (s < 86400) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}
export function clock(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}
export function day(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short" }) : "";
}
export function stamp(ts) {
  return ts ? new Date(ts * 1000).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
}
// "as of" stamp for a block of data. ts = epoch seconds (when it was fetched) or "YYYY-MM-DD" (the data date).
// Older than maxAgeHours turns amber with "(old)", so stale numbers stand out instead of looking current.
export function asOf(ts, { maxAgeHours = 24, label = "as of", stale = false } = {}) {
  if (!ts) return h("span", { class: "asof muted small" }, label + " –");
  const isDate = typeof ts === "string";
  const t = isDate ? new Date(ts + "T12:00:00").getTime() / 1000 : ts;
  const text = isDate ? new Date(t * 1000).toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short", year: "numeric" }) : stamp(ts);
  const old = stale || Date.now() / 1000 - t > maxAgeHours * 3600;
  return h("span", { class: "asof small " + (old ? "warn" : "muted"), title: old ? "older than expected for this source" : "" },
    `${label} ${text}${old ? " (old)" : ""}`);
}

export function countdown(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh > 0 ? `${hh}h ${String(mm).padStart(2, "0")}m` : `${mm}:${String(ss).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- small widgets
export function sparkline(values, { width = 90, height = 22, ref = null } = {}) {
  if (!values || values.length < 2) return h("span", { class: "muted" }, "");
  const min = Math.min(...values, ref ?? Infinity), max = Math.max(...values, ref ?? -Infinity);
  const span = max - min || 1;
  const x = (i) => (i / (values.length - 1)) * width;
  const y = (v) => height - 1 - ((v - min) / span) * (height - 2);
  const d = values.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  const up = values[values.length - 1] >= (ref ?? values[0]);
  const s = svg("svg", { width, height, class: "spark " + (up ? "up" : "down"), viewBox: `0 0 ${width} ${height}` });
  if (ref !== null && ref !== undefined) s.appendChild(svg("line", { x1: 0, x2: width, y1: y(ref), y2: y(ref), class: "ref" }));
  s.appendChild(svg("path", { d }));
  return s;
}

export function table(columns, rows, { onRow, empty = "Nothing here yet.", rowClass } = {}) {
  const thead = h("thead", null, h("tr", null, columns.map((c) => h("th", { class: c.num ? "num" : "" }, c.label))));
  const tbody = h("tbody");
  if (!rows.length) tbody.appendChild(h("tr", null, h("td", { colspan: columns.length, class: "muted" }, empty)));
  for (const r of rows) {
    const tr = h("tr", { class: (onRow ? "click " : "") + (rowClass ? rowClass(r) || "" : "") });
    if (onRow) tr.addEventListener("click", (e) => { if (!e.target.closest("a,button,input")) onRow(r, e); });
    for (const c of columns) {
      const v = c.render ? c.render(r) : r[c.key];
      tr.appendChild(h("td", { class: (c.num ? "num " : "") + (c.cls ? c.cls(r) || "" : "") }, v));
    }
    tbody.appendChild(tr);
  }
  const t = h("table", { class: "grid" }, thead, tbody);
  if (rows.length) t.prepend(h("caption", null, h("button", { class: "csvbtn", type: "button", title: "Download this table as CSV", onclick: () => tableCsv(t) }, "CSV")));
  return t;
}

// CSV of exactly what a table shows (text of every cell), for any table built with table().
export function tableCsv(t, name) {
  const esc = (s) => (/[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const lines = [...t.querySelectorAll("tr")].map((tr) => [...tr.children].map((c) => esc(c.textContent.trim())).join(","));
  const title = name || (document.querySelector("#view h1")?.textContent || "table").replace(/[^\w-]+/g, "_").toLowerCase();
  const url = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" }));
  const a = h("a", { href: url, download: `${title}_${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function section(title, ...children) {
  return h("section", { class: "block" }, title ? h("h2", null, title) : null, ...children);
}

export function note(text, cls = "") {
  return h("p", { class: "note " + cls }, text);
}

export function loading(text = "Loading…") {
  return h("p", { class: "muted loading" }, text);
}

export function errorBox(err) {
  return h("p", { class: "error" }, String(err || "Something went wrong."));
}

export function ext(url, text) {
  return h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, text || url);
}

// ---------------------------------------------------------------- toast + notifications + sound
let toastBox;
export function toast(title, body = "", { kind = "", onClick, ttl = 9000 } = {}) {
  toastBox ||= document.getElementById("toasts");
  const t = h("div", { class: "toast " + kind }, h("strong", null, title), body ? h("div", null, body) : null);
  if (onClick) { t.classList.add("click"); t.addEventListener("click", () => { onClick(); t.remove(); }); }
  toastBox.prepend(t);
  while (toastBox.children.length > 3) toastBox.lastChild.remove();
  setTimeout(() => t.remove(), ttl);
}

export function notify(title, body) {
  try {
    if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
      new Notification(title, { body, tag: title });
    }
  } catch { /* notifications unavailable */ }
}

let audio;
export function beep(kind = "info") {
  try {
    if (localStorage.getItem("sd.sound") === "off") return;
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = kind === "high" ? 880 : 660;
    g.gain.setValueAtTime(0.0001, audio.currentTime);
    g.gain.exponentialRampToValueAtTime(0.15, audio.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.35);
    o.connect(g).connect(audio.destination);
    o.start(); o.stop(audio.currentTime + 0.4);
  } catch { /* audio blocked until first user gesture */ }
}

// ---------------------------------------------------------------- tiny markdown (escaped)
export function markdown(text) {
  const root = h("div", { class: "md" });
  let list = null;
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)/) || line.match(/^\s*\d+[.)]\s+(.*)/);
    if (bullet) {
      if (!list) { list = h("ul"); root.appendChild(list); }
      list.appendChild(h("li", null, inline(bullet[1])));
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const head = line.match(/^#{1,4}\s+(.*)/);
    root.appendChild(head ? h("h4", null, inline(head[1])) : h("p", null, inline(line)));
  }
  return root;
}

function inline(text) {
  const out = [];
  const rx = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = rx.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    out.push(t.startsWith("**") ? h("strong", null, t.slice(2, -2)) : h("code", null, t.slice(1, -1)));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
