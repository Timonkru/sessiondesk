"""Jobs: run your own scripts from the desk - .bat, .cmd, .ps1, .py, .sh or any command.

The base module for people who want to customize: register routines once, start them with a click,
on an interval, daily at a time, or keep them running as a service; watch the output live; copy
the file a job produces (e.g. generated Pine code) to the clipboard. People who don't care never
see more than an empty page with an example.

Job files (JSON). The app's own file lives in the data directory and is editable from the UI.
Extra files listed in settings["jobs_files"] are read-only imports - point it at an existing
routine collection and it shows up without rewriting anything. Schema (compatible with the
jobs.json format of the earlier terminal version, so existing routine files import unchanged):

{
  "workspace": "..",                  # root that job "cwd" values are relative to (relative to this file)
  "python": "C:/path/to/venv/python", # interpreter for cmd[0] == "python" (default: the app's own)
  "jobs": [{
      "id": "levels", "name": "Build levels", "group": "Morning",
      "cwd": "levels-digest", "cmd": ["python", "build_digest.py"],      # list, or a string (runs in the shell)
      "clipboard": "out/digest_latest.md",   # file copied to the clipboard after a successful run
      "outputs": ["out/digest_latest.md"],   # files that must be renewed, else the run counts as failed
      "service": false, "autostart": false,  # long-running process / start with the app
      "schedule": {"daily": "08:40", "weekdays": [0,1,2,3,4]} | {"every_minutes": 30},
      "env": {"KEY": "value"}, "hint": "...", "done_note": "..."
  }],
  "workflows": [{"name": "Prepare EU", "steps": ["vola", "levels"]}],
  "artifacts": [{"group": "Pine", "label": "Gamma", "path": "gamma/levels.pine"} | {"glob": "out/*/idea_*.txt"}]
}

Security: commands run with your user rights, exactly like double-clicking the script. The API that
edits and starts jobs requires the per-session token and only listens on localhost.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

EXAMPLE = {
    "workspace": ".",
    "jobs": [
        {"id": "hello", "name": "Example: print the date", "group": "Examples",
         "cmd": "echo SessionDesk job ran at %DATE% %TIME%" if sys.platform.startswith("win") else "echo SessionDesk job ran at $(date)",
         "hint": "Replace with your own script, e.g. [\"cmd\", \"/c\", \"my_routine.bat\"] or [\"python\", \"build.py\"]"},
    ],
    "workflows": [],
    "artifacts": [],
}


@dataclass
class Job:
    id: str
    name: str
    group: str
    cwd: Path
    cmd: list[str] | str
    source: str
    editable: bool
    python: str | None = None
    service: bool = False
    autostart: bool = False
    clipboard: str | None = None
    outputs: list[str] = field(default_factory=list)
    schedule: dict | None = None
    env: dict = field(default_factory=dict)
    hint: str = ""
    done_note: str = ""
    raw: dict = field(default_factory=dict)
    # runtime
    status: str = "idle"                      # idle | running | ok | failed | stopped
    last_start: float | None = None
    last_end: float | None = None
    exit_code: int | None = None
    issue: str = ""
    buffer: deque = field(default_factory=lambda: deque(maxlen=2000))
    proc: asyncio.subprocess.Process | None = None
    stop_requested: bool = False
    restarts: int = 0                          # unexpected exits of an autostart service in a row

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "group": self.group, "cwd": str(self.cwd), "cmd": self.cmd,
                "source": self.source, "editable": self.editable, "service": self.service, "autostart": self.autostart,
                "clipboard": self.clipboard, "outputs": self.outputs, "schedule": self.schedule, "hint": self.hint,
                "done_note": self.done_note, "status": self.status, "last_start": self.last_start,
                "last_end": self.last_end, "exit_code": self.exit_code, "issue": self.issue, "running": self.running,
                "next_run": next_run(self.schedule, time.time()) if self.schedule else None}


# ------------------------------------------------------------------ schedule (pure, tested)
def next_run(schedule: dict | None, now: float, last: float | None = None) -> float | None:
    if not schedule:
        return None
    if schedule.get("every_minutes"):
        step = float(schedule["every_minutes"]) * 60
        return (last + step) if last else now
    if schedule.get("daily"):
        hh, mm = (int(x) for x in str(schedule["daily"]).split(":")[:2])
        days = schedule.get("weekdays", list(range(7)))
        base = dt.datetime.fromtimestamp(now)
        for add in range(0, 8):
            day = base.date() + dt.timedelta(days=add)
            when = dt.datetime.combine(day, dt.time(hh, mm))
            if day.weekday() in days and when.timestamp() > now - 60:
                if last and last >= when.timestamp() - 60:
                    continue                        # already ran for this slot
                return when.timestamp()
    return None


def build_command(job: Job) -> tuple[list[str] | str, bool]:
    """(argv or shell string, use_shell). .bat/.cmd get cmd /c, .ps1 gets powershell -File."""
    if isinstance(job.cmd, str):
        return job.cmd, True
    cmd = list(job.cmd)
    if not cmd:
        raise ValueError("empty command")
    first = cmd[0]
    if first == "python":
        cmd = [job.python or sys.executable, "-u"] + cmd[1:]
    elif first.lower().endswith((".bat", ".cmd")) and sys.platform.startswith("win"):
        cmd = ["cmd", "/c"] + cmd
    elif first.lower().endswith(".ps1"):
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"] + cmd
    elif first.lower().endswith(".py"):
        cmd = [job.python or sys.executable, "-u"] + cmd
    elif first.lower().endswith(".sh"):
        cmd = ["bash"] + cmd
    return cmd, False


# ------------------------------------------------------------------ manager
class JobManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.data_dir: Path = ctx.data_dir
        self.own_file = self.data_dir / "jobs.json"
        self.state_file = self.data_dir / "jobs_state.json"
        self.log_dir = self.data_dir / "logs"
        self.jobs: dict[str, Job] = {}
        self.workflows: list[dict] = []
        self.artifacts: list[dict] = []
        self.errors: list[str] = []
        self.flow_status: dict[str, dict] = {}
        self._tasks: set[asyncio.Task] = set()
        self.reload()

    # ------------------------------------------------------------ config
    def files(self) -> list[tuple[Path, bool]]:
        extra = [Path(p).expanduser() for p in (self.ctx.settings.get("jobs_files") or []) if p]
        return [(self.own_file, True)] + [(p, False) for p in extra]

    def reload(self) -> None:
        old = self.jobs
        self.jobs, self.workflows, self.artifacts, self.errors = {}, [], [], []
        for path, editable in self.files():
            if not path.exists():
                if not editable:
                    self.errors.append(f"job file not found: {path}")
                continue
            try:
                cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                self.errors.append(f"{path.name}: {exc}")
                continue
            root = (path.parent / cfg.get("workspace", ".")).resolve()
            python = cfg.get("python") or self.ctx.settings.get("jobs_python") or None
            for j in cfg.get("jobs", []):
                try:
                    job = Job(id=j["id"], name=j.get("name", j["id"]), group=j.get("group", ""),
                              cwd=(root / j.get("cwd", ".")).resolve(), cmd=j["cmd"], source=str(path), editable=editable,
                              python=j.get("python") or python, service=bool(j.get("service")),
                              autostart=bool(j.get("autostart")), clipboard=j.get("clipboard"),
                              outputs=j.get("outputs", [j["clipboard"]] if j.get("clipboard") else []),
                              schedule=j.get("schedule"), env=j.get("env") or {}, hint=j.get("hint", ""),
                              done_note=j.get("done_note", ""), raw=j)
                except (KeyError, TypeError) as exc:
                    self.errors.append(f"{path.name}: bad job entry {j!r:.80} ({exc})")
                    continue
                if job.id in self.jobs:
                    self.errors.append(f"duplicate job id '{job.id}' in {path.name} - first one wins")
                    continue
                prev = old.get(job.id)
                if prev:                                    # keep runtime state across reloads
                    for attr in ("status", "last_start", "last_end", "exit_code", "issue", "buffer", "proc"):
                        setattr(job, attr, getattr(prev, attr))
                self.jobs[job.id] = job
            for wf in cfg.get("workflows", []):
                self.workflows.append({**wf, "source": str(path)})
            for a in cfg.get("artifacts", []):
                self.artifacts.append({**a, "_root": str(root)})
        self._load_state()

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for jid, s in state.items():
            job = self.jobs.get(jid)
            if job and job.status == "idle":
                job.status = s.get("status", "idle") if s.get("status") != "running" else "stopped"
                job.last_start, job.last_end, job.exit_code = s.get("last_start"), s.get("last_end"), s.get("exit_code")

    def _save_state(self) -> None:
        state = {j.id: {"status": j.status, "last_start": j.last_start, "last_end": j.last_end, "exit_code": j.exit_code}
                 for j in self.jobs.values()}
        try:
            self.state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _read_own(self) -> dict:
        try:
            return json.loads(self.own_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {"workspace": ".", "jobs": [], "workflows": [], "artifacts": []}

    def _write_own(self, cfg: dict) -> None:
        tmp = self.own_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.own_file)
        self.reload()

    def upsert(self, spec: dict) -> dict:
        if not spec.get("id") or not spec.get("cmd"):
            return {"error": "a job needs an id and a cmd"}
        existing = self.jobs.get(spec["id"])
        if existing and not existing.editable:
            return {"error": f"'{spec['id']}' comes from {existing.source} (read-only import) - edit that file"}
        cfg = self._read_own()
        jobs = [j for j in cfg.get("jobs", []) if j.get("id") != spec["id"]]
        clean = {k: v for k, v in spec.items() if k in ("id", "name", "group", "cwd", "cmd", "clipboard", "outputs", "service",
                                                         "autostart", "schedule", "env", "hint", "done_note", "python") and v not in (None, "", [])}
        jobs.append(clean)
        cfg["jobs"] = jobs
        self._write_own(cfg)
        return {"ok": True, "job": self.jobs[spec["id"]].public()}

    def delete(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            return {"error": "unknown job"}
        if not job.editable:
            return {"error": "read-only import - edit the source file"}
        cfg = self._read_own()
        cfg["jobs"] = [j for j in cfg.get("jobs", []) if j.get("id") != job_id]
        self._write_own(cfg)
        return {"ok": True}

    def install_example(self) -> dict:
        if self.own_file.exists() and self._read_own().get("jobs"):
            return {"error": "jobs.json already has jobs"}
        self._write_own(EXAMPLE)
        return {"ok": True}

    # ------------------------------------------------------------ running
    def _emit(self, job: Job, line: str, logfile: Path) -> None:
        job.buffer.append(line)
        self.ctx.broker.publish("job_line", {"job": job.id, "line": line})
        try:
            with open(logfile, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _changed(self, job: Job) -> None:
        self._save_state()
        self.ctx.broker.publish("job", {"job": job.public()})

    def start(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            return {"error": "unknown job"}
        if job.running or job.status == "running":
            return {"error": "already running"}
        # claimed now, not when run() gets the loop: two start() calls before that (autostart plus the restart of a
        # service whose saved status was "failed", or a double click) started the news watcher twice on 26.10.2026,
        # both runs shared job.proc and SessionDesk lost track of the process that kept running
        job.status = "running"
        task = asyncio.ensure_future(self.run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return {"ok": True}

    async def run(self, job: Job) -> str:
        if job.running:
            return job.status
        self.log_dir.mkdir(exist_ok=True)
        logfile = self.log_dir / f"{job.id}_{dt.date.today():%Y-%m-%d}.log"
        before = {p: _version(job.cwd / p) for p in job.outputs}
        job.status, job.last_start, job.last_end, job.exit_code, job.issue = "running", time.time(), None, None, ""
        job.stop_requested = False
        try:
            argv, shell = build_command(job)
        except ValueError as exc:
            job.status, job.issue = "failed", str(exc)
            self._changed(job)
            return job.status
        shown = argv if isinstance(argv, str) else " ".join(argv)
        self._emit(job, f"--- {dt.datetime.now():%H:%M:%S} start: {shown}  (in {job.cwd})", logfile)
        self._changed(job)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", **{k: str(v) for k, v in job.env.items()})
        flags = spawn_flags()
        try:
            if shell:
                job.proc = await asyncio.create_subprocess_shell(argv, cwd=job.cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                                 creationflags=flags)
            else:
                job.proc = await asyncio.create_subprocess_exec(*argv, cwd=job.cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                                creationflags=flags)
        except (OSError, ValueError) as exc:
            job.status, job.exit_code, job.last_end, job.issue = "failed", -1, time.time(), f"could not start: {exc}"
            self._emit(job, "--- " + job.issue, logfile)
            self._changed(job)
            return job.status
        assert job.proc.stdout is not None
        while True:
            raw = await job.proc.stdout.readline()
            if not raw:
                break
            self._emit(job, _decode(raw).rstrip(), logfile)
        code = await job.proc.wait()
        job.exit_code, job.last_end = code, time.time()
        if job.stop_requested:
            job.status = "stopped"
        else:
            job.status = "ok" if code == 0 else "failed"
        if job.status == "ok":
            stale = [p for p, old in before.items() if _version(job.cwd / p) in (None, old)]
            if stale:
                job.status, job.issue = "failed", "output missing or not renewed: " + ", ".join(stale)
                self._emit(job, "--- " + job.issue, logfile)
        self._emit(job, f"--- {dt.datetime.now():%H:%M:%S} {job.status} (exit {code}, {job.last_end - job.last_start:.1f} s)", logfile)
        if job.status == "ok" and job.clipboard:
            ok, msg = copy_file(job.cwd / job.clipboard)
            self._emit(job, "--- " + (f"{job.clipboard} -> clipboard" if ok else msg), logfile)
        if job.status == "ok" and job.done_note:
            self._emit(job, "--- " + job.done_note, logfile)
        self._changed(job)
        return job.status

    def stop(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job or not job.running:
            return {"error": "not running"}
        job.stop_requested = True
        kill_tree(job.proc.pid)
        return {"ok": True}

    async def run_workflow(self, name: str) -> dict:
        wf = next((w for w in self.workflows if w["name"] == name), None)
        if not wf:
            return {"error": "unknown workflow"}
        steps = [self.jobs.get(s) for s in wf.get("steps", [])]
        if not steps or any(s is None or s.service for s in steps):
            return {"error": "workflow references missing or service jobs"}
        status = {"name": name, "status": "running", "steps": [{"id": s.id, "status": "pending"} for s in steps]}
        self.flow_status[name] = status
        self.ctx.broker.publish("workflow", {"workflow": status})
        for job, step in zip(steps, status["steps"]):
            step["status"] = "running"
            self.ctx.broker.publish("workflow", {"workflow": status})
            result = await self.run(job)
            step["status"] = result
            if result != "ok":
                status["status"] = "failed"
                break
        else:
            status["status"] = "ok"
        for step in status["steps"]:
            if step["status"] == "pending":
                step["status"] = "skipped"
        self.ctx.broker.publish("workflow", {"workflow": status})
        return status

    async def scheduler(self) -> None:
        """Autostart services once, then fire scheduled jobs. Runs for the app's lifetime."""
        for job in self.jobs.values():
            if job.autostart and not job.running:
                self.start(job.id)
        while True:
            now = time.time()
            for job in list(self.jobs.values()):
                if job.service and job.autostart and not job.running and job.status == "failed" and job.last_end:
                    # an autostart service that died (not stopped by the user) comes back, with growing pauses
                    if now - job.last_end >= restart_delay(job.restarts):
                        job.restarts += 1
                        self.start(job.id)
                    continue
                if job.service and job.running and job.last_start and now - job.last_start > 1800:
                    job.restarts = 0                  # ran half an hour: count the next death as a first one
                if not job.schedule or job.running or job.service:
                    continue
                due = next_run(job.schedule, now, job.last_start)
                if due is not None and due <= now:
                    self.start(job.id)
            await asyncio.sleep(20)

    async def shutdown(self) -> None:
        for job in self.jobs.values():
            if job.running:
                kill_tree(job.proc.pid)

    # ------------------------------------------------------------ artifacts
    def list_artifacts(self) -> list[dict]:
        out = []
        for spec in self.artifacts:
            root = Path(spec["_root"])
            if "path" in spec:
                paths, label = [root / spec["path"]], spec.get("label")
            else:
                hits = sorted(root.glob(spec.get("glob", "")))
                newest = max((p.parent for p in hits), key=lambda d: d.name, default=None)
                paths, label = [p for p in hits if p.parent == newest], None
            for p in paths:
                exists = p.exists()
                out.append({"group": spec.get("group", ""), "label": label or p.stem, "path": str(p), "exists": exists,
                            "age": time.time() - p.stat().st_mtime if exists else None})
        for job in self.jobs.values():
            if job.clipboard:
                p = job.cwd / job.clipboard
                out.append({"group": "Job outputs", "label": job.name, "path": str(p), "exists": p.exists(),
                            "age": time.time() - p.stat().st_mtime if p.exists() else None})
        return out

    def artifact_allowed(self, path: str) -> bool:
        """Only files registered as artifacts or job outputs may be read through the API."""
        want = _norm(path)
        return any(_norm(a["path"]) == want for a in self.list_artifacts())


# ------------------------------------------------------------------ helpers
def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252" if sys.platform.startswith("win") else "latin-1", errors="replace")


def _version(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size) if path.is_file() and st.st_size else None
    except OSError:
        return None


def spawn_flags() -> int:
    """Windows: own process group (stoppable as a tree) and NO console window. SessionDesk in the background runs
    under pythonw without a console, so every console program it starts (python.exe, cmd for .bat, powershell)
    got a new, empty window - the output goes to the job log. 26.10.2026 closing those windows killed the news
    watcher four times (exit 0xC000013A = closed console) and the EA showed headlines hours old."""
    if not sys.platform.startswith("win"):
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


RESTART_DELAYS = (30, 60, 120, 300, 600)       # seconds before the n-th restart of a service that died


def restart_delay(restarts: int) -> float:
    """Wait before restarting an autostart service after its restarts-th unexpected exit (pure, tested)."""
    return RESTART_DELAYS[min(restarts, len(RESTART_DELAYS) - 1)]


def kill_tree(pid: int) -> None:
    """Stop a job and its children (cmd /c x.bat -> python ... would otherwise survive)."""
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass


def read_text(path: Path, limit: int = 2_000_000) -> str:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return fh.read(limit)


def copy_to_clipboard(text: str) -> bool:
    """Server-side clipboard (the server runs on your desktop). Windows: Win32 API - not clip.exe, which
    puts a visible BOM in front of the text. macOS: pbcopy. Linux: xclip/xsel if installed."""
    text = text.lstrip("\ufeff")
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes
        k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
        k32.GlobalAlloc.restype, k32.GlobalAlloc.argtypes = wintypes.HGLOBAL, [wintypes.UINT, ctypes.c_size_t]
        k32.GlobalLock.restype, k32.GlobalLock.argtypes = wintypes.LPVOID, [wintypes.HGLOBAL]
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        u32.SetClipboardData.restype, u32.SetClipboardData.argtypes = wintypes.HANDLE, [wintypes.UINT, wintypes.HANDLE]
        data = text.encode("utf-16-le") + b"\x00\x00"
        for _ in range(10):
            if u32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return False
        try:
            u32.EmptyClipboard()
            handle = k32.GlobalAlloc(0x0002, len(data))
            ptr = k32.GlobalLock(handle)
            if not ptr:
                return False
            ctypes.memmove(ptr, data, len(data))
            k32.GlobalUnlock(handle)
            return bool(u32.SetClipboardData(13, handle))
        finally:
            u32.CloseClipboard()
    for tool in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        try:
            subprocess.run(tool, input=text.encode("utf-8"), check=True, capture_output=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            continue
    return False


def copy_file(path: Path) -> tuple[bool, str]:
    try:
        text = read_text(path)
    except OSError as exc:
        return False, f"cannot read {path.name}: {exc}"
    return (True, "copied") if copy_to_clipboard(text) else (False, "clipboard not available on this system")
