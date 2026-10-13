"""Start SessionDesk:  sessiondesk  [--port 8765] [--host 127.0.0.1] [--no-browser] [--app]

--app opens the desk in its own window (Edge or Chrome app mode, no tabs or address bar) and is what
the desktop shortcut uses. Starting again while SessionDesk already runs on the port just opens the
window again instead of failing with "address in use".
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def already_running(url: str) -> bool | None:
    """True = SessionDesk answers on the URL, False = something else holds the port, None = free."""
    try:
        with urllib.request.urlopen(url, timeout=0.8) as resp:
            return b"<title>SessionDesk</title>" in resp.read(4096)
    except OSError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower() or "timed out" in str(reason).lower():
            return None
        return False


def app_browser() -> str | None:
    """Path of a Chromium browser that supports --app (Edge ships with Windows)."""
    candidates = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                       Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    for c in candidates:
        if c.exists():
            return str(c)
    for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_ui(url: str, app_window: bool) -> None:
    exe = app_browser() if app_window else None
    if exe:
        subprocess.Popen([exe, f"--app={url}", "--window-size=1440,900"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def open_when_ready(url: str, app_window: bool, timeout: float = 30.0) -> None:
    def wait():
        end = time.time() + timeout
        while time.time() < end:
            if already_running(url):
                open_ui(url, app_window)
                return
            time.sleep(0.3)
        print(f"SessionDesk did not answer within {timeout:.0f} s - open {url} manually.")
    threading.Thread(target=wait, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(prog="sessiondesk", description="Local-first market desk in your browser.")
    parser.add_argument("--host", default=os.environ.get("SESSIONDESK_HOST", "127.0.0.1"),
                        help="interface to listen on (default 127.0.0.1 = this computer only)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SESSIONDESK_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--app", action="store_true", help="open in its own app window (Edge/Chrome app mode)")
    args = parser.parse_args()

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}/"
    state = already_running(url)
    if state:
        print(f"SessionDesk already runs at {url} - opening it.")
        if not args.no_browser:
            open_ui(url, args.app)
        return
    if state is False:
        sys.exit(f"Port {args.port} is used by another program. Start with --port 8766 (or another free port).")

    if sys.platform.startswith("win"):
        # Jobs start subprocesses; on Windows that needs the Proactor loop (the default, made explicit).
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    import uvicorn

    from .app import create_app
    app = create_app()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening beyond this computer. Anyone who can reach this port and load the page can use the desk "
              "and run your jobs. Use only on a trusted network or behind an authenticated tunnel.")
    print(f"SessionDesk running at {url}  - close this window (or Ctrl+C) to stop it.")
    if not args.no_browser:
        open_when_ready(url, args.app)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", loop="asyncio")


if __name__ == "__main__":
    main()
