// Jobs: your own scripts (.bat, .cmd, .ps1, .py, .sh, any command) - run, schedule, watch, copy their output.
import { api, on } from "../lib/api.js";
import { h, clear, table, section, ago, stamp, note, loading, errorBox, toast } from "../lib/ui.js";

const STATUS_CLS = { ok: "up", failed: "down", running: "warn", stopped: "muted", idle: "muted" };

export async function render(root, _params, ctx) {
  let data = { jobs: [] }, selected = localStorage.getItem("sd.job") || null;
  const listBox = h("div"), consoleBox = h("div", { class: "console" }), consoleHead = h("div", { class: "toolbar" });
  const flowsBox = h("div"), artBox = h("div"), formBox = h("div"), filesBox = h("div");
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Jobs"), h("span", { class: "meta" }, "your own routines - scripts run with your user rights, exactly like a double-click")),
    h("div", { class: "cols" }, h("div", null, listBox, flowsBox, artBox), h("div", null, section("Output", consoleHead, consoleBox), formBox, filesBox)));

  const load = async () => {
    data = await api("/api/jobs", { fresh: true });
    drawList(); drawFlows(); drawFiles();
    if (selected) selectJob(selected, false);
    ctx.setContext({ page: "Jobs", jobs: data.jobs.map((j) => ({ id: j.id, name: j.name, status: j.status, exit_code: j.exit_code, last_end: j.last_end, issue: j.issue, schedule: j.schedule })), errors: data.errors });
  };

  const drawList = () => {
    const groups = new Map();
    for (const j of data.jobs) { const g = j.group || "Jobs"; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(j); }
    clear(listBox, (data.errors || []).map((e) => errorBox(e)));
    if (!data.jobs.length) {
      listBox.appendChild(section("No jobs yet", note("A job is any command you would otherwise start from a .bat file or a terminal. Add one with the form, " +
        "import an existing job file (Settings below the form), or start from an example."),
        h("button", { onclick: async () => { const r = await api("/api/jobs/example", { method: "POST" }); if (r.error) toast("Example", r.error); load(); } }, "Add an example job")));
      return;
    }
    for (const [g, jobs] of groups) {
      listBox.appendChild(section(g, table([
        { label: "Job", render: (j) => h("span", { title: (Array.isArray(j.cmd) ? j.cmd.join(" ") : j.cmd) + "\n" + j.cwd }, j.name, j.service ? h("span", { class: "muted small" }, " · service") : "", !j.editable ? h("span", { class: "muted small" }, " · imported") : "") },
        { label: "Status", render: (j) => h("span", { class: STATUS_CLS[j.status] || "" }, j.status + (j.exit_code != null && j.status === "failed" ? ` (${j.exit_code})` : "")) },
        { label: "Last run", render: (j) => h("span", { class: "small muted" }, j.last_end ? ago(j.last_end) + " ago" : j.last_start ? "running" : "never") },
        { label: "Schedule", render: (j) => h("span", { class: "small muted" }, schedText(j)) },
        { label: "", num: true, render: (j) => [
          j.running || j.status === "running" ? h("button", { onclick: () => act(j.id, "stop") }, "Stop") : h("button", { onclick: () => act(j.id, "run") }, "Run"), " ",
          j.editable ? h("button", { class: "linkish", onclick: () => editJob(j) }, "edit") : null] },
      ], jobs, { onRow: (j) => selectJob(j.id), rowClass: (j) => (j.id === selected ? "hl" : "") })));
    }
  };
  const schedText = (j) => j.schedule ? (j.schedule.daily ? `daily ${j.schedule.daily}` : `every ${j.schedule.every_minutes} min`) + (j.next_run ? ` · next ${stamp(j.next_run)}` : "") : (j.autostart ? "autostart" : "manual");
  const act = async (id, what) => { const r = await api(`/api/jobs/${id}/${what}`, { method: "POST" }); if (r.error) toast(id, r.error); selectJob(id); setTimeout(load, 400); };

  const selectJob = async (id, scroll = true) => {
    selected = id; localStorage.setItem("sd.job", id);
    const j = data.jobs.find((x) => x.id === id);
    if (!j) return;
    clear(consoleHead, h("strong", null, j.name), h("span", { class: "muted small" }, j.hint || ""), j.clipboard ? h("button", { class: "linkish", onclick: () => copyArtifact(j.cwd + "/" + j.clipboard) }, "copy output file") : null);
    const d = await api(`/api/jobs/${id}/log`, { fresh: true });
    consoleBox.textContent = (d.lines || []).join("\n") || "(no output yet)";
    if (scroll) consoleBox.scrollTop = consoleBox.scrollHeight;
    drawList();
  };

  const drawFlows = () => {
    clear(flowsBox);
    if (!(data.workflows || []).length) return;
    flowsBox.appendChild(section("Workflows", table([
      { label: "Workflow", render: (w) => w.name },
      { label: "Steps", render: (w) => h("span", { class: "small" }, (w.steps || []).map((s, i) => {
        const st = data.flows && data.flows[w.name] && data.flows[w.name].steps[i];
        return h("span", { class: st ? STATUS_CLS[st.status] || "" : "muted" }, (i ? " → " : "") + s + (st ? ` (${st.status})` : ""));
      })) },
      { label: "", num: true, render: (w) => h("button", { onclick: async () => { await api("/api/workflows/run", { method: "POST", body: { name: w.name } }); setTimeout(load, 500); } }, "Run all") },
    ], data.workflows), note("Steps run one after another; a failed step stops the rest.")));
  };

  const loadArtifacts = async () => {
    const d = await api("/api/artifacts", { fresh: true });
    const items = d.items || [];
    clear(artBox, items.length ? section("Copy to clipboard", table([
      { label: "Group", render: (a) => h("span", { class: "muted small" }, a.group) }, { label: "File", render: (a) => h("span", { title: a.path }, a.label) },
      { label: "Age", render: (a) => a.exists ? h("span", { class: a.age > 86400 ? "warn small" : "small" }, ago(Date.now() / 1000 - a.age)) : h("span", { class: "down small" }, "missing") },
      { label: "", num: true, render: (a) => a.exists ? h("button", { onclick: () => copyArtifact(a.path) }, "Copy") : "" },
    ], items)) : null);
  };
  const copyArtifact = async (path) => {
    const d = await api("/api/artifacts/read", { method: "POST", body: { path, copy: true } });
    if (d.error) { toast("Copy failed", d.error); return; }
    if (!d.copied) { try { await navigator.clipboard.writeText(d.text); d.copied = true; } catch { /* no permission */ } }
    toast(d.copied ? "Copied to clipboard" : "Copy failed", path.split(/[\\/]/).pop());
  };

  // ---------------------------------------------------------------- add / edit
  const editJob = (j = null) => {
    const v = j ? { ...j, cmd: Array.isArray(j.cmd) ? JSON.stringify(j.cmd) : j.cmd } : { id: "", name: "", group: "", cwd: "", cmd: "", clipboard: "", hint: "" };
    const f = {};
    const field = (key, label, placeholder = "", type = "text") => [h("label", null, label), (f[key] = h("input", { type, value: v[key] ?? "", placeholder }))];
    const sched = h("select", null, [["manual", "manual"], ["daily", "daily at"], ["every", "every N minutes"]].map(([val, l]) => h("option", { value: val, selected: (j && j.schedule ? (j.schedule.daily ? "daily" : "every") : "manual") === val }, l)));
    const schedVal = h("input", { type: "text", value: j && j.schedule ? (j.schedule.daily || j.schedule.every_minutes) : "", placeholder: "08:40 or 30", style: { width: "110px" } });
    const weekdays = h("label", null, h("input", { type: "checkbox", checked: !!(j && j.schedule && j.schedule.weekdays && j.schedule.weekdays.length === 5) }), "Mon–Fri only");
    const service = h("label", null, h("input", { type: "checkbox", checked: !!(j && j.service) }), "service (keeps running)");
    const autostart = h("label", null, h("input", { type: "checkbox", checked: !!(j && j.autostart) }), "start with SessionDesk");
    const save = async () => {
      let cmd = f.cmd.value.trim();
      if (cmd.startsWith("[")) { try { cmd = JSON.parse(cmd); } catch { toast("Command", "invalid JSON list"); return; } }
      const spec = { id: f.id.value.trim(), name: f.name.value.trim() || f.id.value.trim(), group: f.group.value.trim(), cwd: f.cwd.value.trim() || ".",
        cmd, clipboard: f.clipboard.value.trim(), hint: f.hint.value.trim(), service: service.firstChild.checked, autostart: autostart.firstChild.checked };
      if (sched.value === "daily" && schedVal.value) spec.schedule = { daily: schedVal.value.trim(), ...(weekdays.firstChild.checked ? { weekdays: [0, 1, 2, 3, 4] } : {}) };
      if (sched.value === "every" && schedVal.value) spec.schedule = { every_minutes: parseFloat(schedVal.value) };
      const r = await api("/api/jobs", { method: "PUT", body: spec });
      if (r.error) { toast("Save failed", r.error); return; }
      toast("Saved", spec.name); clear(formBox); load();
    };
    clear(formBox, section(j ? `Edit “${j.name}”` : "Add a job", h("div", { class: "formgrid" },
      field("id", "Id", "short-id"), field("name", "Name", "Morning levels"), field("group", "Group", "Morning"),
      field("cwd", "Folder", "C:\\path\\to\\folder  (relative = data folder)"),
      field("cmd", "Command", 'my_routine.bat   or   ["python", "build.py", "--eu"]'),
      field("clipboard", "Output file to copy", "out/result.txt (optional)"), field("hint", "Hint", "when to run it"),
      h("label", null, "Schedule"), h("div", { class: "toolbar", style: { margin: 0 } }, sched, schedVal, weekdays),
      h("span"), h("div", { class: "toolbar", style: { margin: 0 } }, service, autostart)),
      h("div", { class: "toolbar" }, h("button", { onclick: save }, "Save"),
        j ? h("button", { class: "linkish", onclick: async () => { if (confirm(`Delete job “${j.name}”?`)) { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); clear(formBox); load(); } } }, "delete") : null,
        h("button", { class: "linkish", onclick: () => clear(formBox, addButton()) }, "cancel")),
      note("A .bat/.cmd file is started with cmd /c, .ps1 with PowerShell, .py with Python, .sh with bash. A command written as plain text runs in the shell. " +
           "\"python\" as first word uses the interpreter set in the job file (or SessionDesk's own).")));
    if (j) f.id.disabled = true;
  };
  const addButton = () => h("div", { class: "toolbar" }, h("button", { onclick: () => editJob() }, "Add a job"));

  const drawFiles = () => {
    const input = h("input", { type: "text", placeholder: "C:\\path\\to\\jobs.json", style: { width: "360px" } });
    const imports = (data.files || []).filter((x) => !x.editable).map((x) => x.path);
    clear(filesBox, section("Job files", table([
      { label: "File", render: (x) => h("span", { class: "small" }, x.path) },
      { label: "", render: (x) => h("span", { class: "small muted" }, x.editable ? "own (editable here)" : "import (read-only)") + (x.exists ? "" : " · missing") },
      { label: "", num: true, render: (x) => x.editable ? "" : h("button", { class: "linkish", onclick: async () => { await api("/api/settings", { method: "PATCH", body: { jobs_files: imports.filter((p) => p !== x.path) } }); load(); } }, "remove") },
    ], data.files || []),
    h("div", { class: "toolbar" }, input, h("button", { onclick: async () => {
      if (!input.value.trim()) return;
      await api("/api/settings", { method: "PATCH", body: { jobs_files: [...imports, input.value.trim()] } }); load(); loadArtifacts();
    } }, "Import job file"), h("button", { class: "linkish", onclick: async () => { await api("/api/jobs/reload", { method: "POST" }); load(); loadArtifacts(); } }, "reload files")),
    note("Imported files keep their own folder layout (\"workspace\", \"cwd\", \"python\") and also bring their workflows and copy-to-clipboard artifacts. Edit them in their own file.")));
  };

  clear(listBox, loading()); clear(formBox, addButton());
  await load(); loadArtifacts();
  const off1 = on("job_line", ({ job, line }) => {
    if (job !== selected) return;
    const atEnd = consoleBox.scrollTop + consoleBox.clientHeight >= consoleBox.scrollHeight - 30;
    consoleBox.textContent += (consoleBox.textContent ? "\n" : "") + line;
    if (atEnd) consoleBox.scrollTop = consoleBox.scrollHeight;
  });
  const off2 = on("job", ({ job }) => {
    const i = data.jobs.findIndex((x) => x.id === job.id);
    if (i >= 0) { data.jobs[i] = job; drawList(); }
    if (job.status === "ok" || job.status === "failed") { toast(`${job.name}: ${job.status}`, job.issue || "", { kind: job.status === "ok" ? "up" : "down" }); loadArtifacts(); }
  });
  const off3 = on("workflow", ({ workflow }) => { data.flows = { ...(data.flows || {}), [workflow.name]: workflow }; drawFlows(); });
  return () => { off1(); off2(); off3(); };
}
