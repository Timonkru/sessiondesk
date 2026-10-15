// API client: token header, small in-memory cache for instant back/forward, the event stream.

const TOKEN = document.querySelector('meta[name="sd-token"]').content;
const memo = new Map();

export async function api(path, { method = "GET", body, fresh = false, ttl = 0 } = {}) {
  const key = method + " " + path;
  if (method === "GET" && !fresh && ttl > 0) {
    const hit = memo.get(key);
    if (hit && Date.now() - hit.t < ttl) return hit.v;
  }
  const res = await fetch(path, {
    method,
    headers: { "X-SD-Token": TOKEN, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data;
  try { data = await res.json(); } catch { data = { error: `HTTP ${res.status}` }; }
  if (res.status === 401) {
    // The server issues a new token on every start: reload once to pick it up.
    data = { error: "Session expired - reloading (the server was restarted)." };
    const last = Number(sessionStorage.getItem("sd.reloaded") || 0);
    if (Date.now() - last > 15000) { sessionStorage.setItem("sd.reloaded", String(Date.now())); location.reload(); }
  }
  if (method === "GET" && ttl > 0 && !data.error) memo.set(key, { t: Date.now(), v: data });
  return data;
}

export function peek(path) {
  const hit = memo.get("GET " + path);
  return hit ? hit.v : null;
}

// AI answers stream as server-sent events over a POST response.
export async function streamChat(body, onEvent, signal) {
  const res = await fetch("/api/ai/chat", {
    method: "POST", signal,
    headers: { "X-SD-Token": TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) { onEvent({ type: "error", error: `HTTP ${res.status}` }); return; }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (line) { try { onEvent(JSON.parse(line.slice(5))); } catch { /* partial */ } }
    }
  }
}

// Push channel: one EventSource for the whole app, auto-reconnect with the last seen id.
const handlers = new Map();
let lastId = 0, source = null, onState = () => {};

export function on(kind, fn) {
  if (!handlers.has(kind)) handlers.set(kind, new Set());
  handlers.get(kind).add(fn);
  return () => handlers.get(kind).delete(fn);
}

export function connect(stateCb) {
  onState = stateCb || onState;
  const open = () => {
    source = new EventSource(`/api/stream?t=${encodeURIComponent(TOKEN)}&since=${lastId}`);
    source.onopen = () => onState(true);
    source.onerror = () => { onState(false); source.close(); setTimeout(open, 3000); };
    const kinds = ["alert", "level", "position", "briefing", "alert_digest", "alert_ai", "news", "event_warning", "release", "release_headline", "job", "job_line", "workflow"];
    for (const k of kinds) {
      source.addEventListener(k, (ev) => {
        const data = JSON.parse(ev.data);
        lastId = Math.max(lastId, data.id || 0);
        for (const fn of handlers.get(k) || []) fn(data);
      });
    }
  };
  open();
}
