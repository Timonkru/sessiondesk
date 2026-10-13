# Jobs: your own scripts on the desk

A job is any command you would otherwise start from a `.bat` file, a shortcut or a terminal.

## Ways to add jobs

1. **Jobs → Add a job.** Stored in `~/.sessiondesk/jobs.json` and editable in the UI.
2. **Import an existing job file** (Jobs → Job files). Imports are read-only, keep their own folder
   layout and bring their workflows and clipboard artifacts along. Useful when routines already
   live in a project folder.

## Job file format

```json
{
  "workspace": "..",
  "python": "C:/path/to/venv/Scripts/python.exe",
  "jobs": [
    {"id": "levels", "name": "Build levels", "group": "Morning",
     "cwd": "levels-digest", "cmd": ["python", "build_digest.py"],
     "clipboard": "out/digest_latest.md",
     "schedule": {"daily": "08:40", "weekdays": [0, 1, 2, 3, 4]}},
    {"id": "watcher", "name": "News watcher", "cwd": "watcher", "cmd": "run_watcher.bat",
     "service": true, "autostart": true}
  ],
  "workflows": [{"name": "Prepare EU", "steps": ["levels"]}],
  "artifacts": [{"group": "Pine", "label": "Levels", "path": "levels-digest/out/levels.pine"},
                {"group": "Ideas", "glob": "levels-digest/out/*/idea_*.txt"}]
}
```

| Field | Meaning |
|---|---|
| `workspace` | root that `cwd` is relative to (relative to the job file) |
| `python` | interpreter used when a command starts with `python` or a `.py` file |
| `cmd` | list of arguments, or a string that runs in the shell |
| `clipboard` | file copied to the clipboard after a successful run |
| `outputs` | files the run must renew, otherwise it counts as failed |
| `service`, `autostart` | long-running process; start together with SessionDesk |
| `schedule` | `{"daily": "HH:MM", "weekdays": [0..6]}` or `{"every_minutes": N}` |
| `env` | extra environment variables |

`.bat` and `.cmd` start via `cmd /c`, `.ps1` via PowerShell, `.py` via the configured Python, `.sh`
via bash. Output streams live into the page and into `~/.sessiondesk/logs/<job>_<date>.log`.

Jobs run without console input (stdin is closed): a script waiting for `input()` hangs until you
stop it. Stopping a job also stops its child processes.
