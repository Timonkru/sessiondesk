"""Local extensions: your own Python modules that add pages to SessionDesk without entering the repository.

Put a file `<name>.py` (or a folder `<name>/` with `extension.py`) into `<data dir>/extensions/`
(default `~/.sessiondesk/extensions/`). It runs inside SessionDesk with your user rights - only put
your own code there. Set `extensions_enabled` to false in Settings to skip loading.

Module contract:
    TITLE = "My desk"              # navigation label (default: the file name)
    DESCRIPTION = "..."            # optional, shown under the page title
    REFRESH = 30                   # optional: seconds between automatic page refreshes (0 = manual only)
    async def page(ctx) -> dict    # {"blocks": [...]} - a plain `def` also works (runs in a worker thread)
    async def action(ctx, payload) -> dict   # optional: receives {"action": ..., "text": ...} from an input block

Blocks (every value is shown as text, never as HTML; the page's AI context is the same data):
    {"type": "kv", "title": t, "items": [[label, value], ...]}
    {"type": "table", "title": t, "columns": [{"key": k, "label": l, "num": bool}], "rows": [{...}], "empty": text}
    {"type": "list", "title": t, "items": [text | {"text": .., "level": "high"|"warn"|"ok"|"muted", "detail": ..}]}
    {"type": "text", "title": t, "text": "simple markdown: **bold**, bullet lines"}
    {"type": "note", "text": t}
    {"type": "input", "title": t, "action": name, "placeholder": text}   -> POSTs to action()
Optional per block: "cols": 2 puts it in the right column on wide screens.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import re
import sys
import time
import traceback
from pathlib import Path

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
TIMEOUT = 90


class Extension:
    def __init__(self, name: str, path: Path):
        self.name, self.path = name, path
        self.module = None
        self.error: str | None = None

    @property
    def title(self) -> str:
        return str(getattr(self.module, "TITLE", "") or self.name)

    def describe(self) -> dict:
        m = self.module
        return {"name": self.name, "title": self.title, "description": str(getattr(m, "DESCRIPTION", "") or ""),
                "refresh": int(getattr(m, "REFRESH", 0) or 0), "actions": bool(m and hasattr(m, "action")),
                "error": self.error, "path": str(self.path)}


def discover(folder: Path) -> list[Extension]:
    if not folder.is_dir():
        return []
    found = []
    for p in sorted(folder.iterdir()):
        if p.name.startswith(("_", ".")):
            continue
        if p.is_file() and p.suffix == ".py":
            name, src = p.stem.lower(), p
        elif p.is_dir() and (p / "extension.py").is_file():
            name, src = p.name.lower(), p / "extension.py"
        else:
            continue
        if NAME_RX.match(name):
            found.append(Extension(name, src))
    return found


def load(ext: Extension) -> Extension:
    try:
        spec = importlib.util.spec_from_file_location(f"sessiondesk_ext_{ext.name.replace('-', '_')}", ext.path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if not callable(getattr(module, "page", None)):
            raise TypeError("the module has no page(ctx) function")
        ext.module, ext.error = module, None
    except Exception as exc:                        # one broken extension must not stop the app
        ext.module, ext.error = None, f"{type(exc).__name__}: {exc}"
    return ext


def load_all(ctx) -> dict[str, Extension]:
    if ctx.settings.get("extensions_enabled") is False:
        return {}
    return {e.name: load(e) for e in discover(ctx.data_dir / "extensions")}


async def _call(fn, *args):
    if inspect.iscoroutinefunction(fn):
        return await asyncio.wait_for(fn(*args), TIMEOUT)
    return await asyncio.wait_for(asyncio.to_thread(fn, *args), TIMEOUT)


def _clean(result) -> dict:
    if not isinstance(result, dict):
        return {"error": "page() must return a dict with 'blocks'"}
    blocks = [b for b in (result.get("blocks") or []) if isinstance(b, dict) and b.get("type")]
    return {**result, "blocks": blocks}


async def page(ctx, exts: dict[str, Extension], name: str) -> dict:
    ext = exts.get(name)
    if not ext:
        return {"error": f"no extension '{name}'"}
    if ext.error:
        return {"error": ext.error, "extension": ext.describe()}
    try:
        out = _clean(await _call(ext.module.page, ctx))
    except asyncio.TimeoutError:
        out = {"error": f"page() took longer than {TIMEOUT} s"}
    except Exception as exc:
        out = {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=4)}
    return {**out, "extension": ext.describe(), "asof": time.time()}


async def action(ctx, exts: dict[str, Extension], name: str, payload: dict) -> dict:
    ext = exts.get(name)
    if not ext or ext.error or not hasattr(ext.module, "action"):
        return {"error": "this extension has no actions"}
    try:
        res = await _call(ext.module.action, ctx, payload)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return res if isinstance(res, dict) else {"result": str(res)}
