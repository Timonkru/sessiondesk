"""Start SessionDesk:  python -m sessiondesk  [--port 8765] [--host 127.0.0.1] [--no-browser]"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(prog="sessiondesk", description="Local-first market desk in your browser.")
    parser.add_argument("--host", default=os.environ.get("SESSIONDESK_HOST", "127.0.0.1"),
                        help="interface to listen on (default 127.0.0.1 = this computer only)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SESSIONDESK_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()

    if sys.platform.startswith("win"):
        # Jobs start subprocesses; on Windows that needs the Proactor loop (the default, made explicit).
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    import uvicorn

    from .app import create_app
    app = create_app()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}/"
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening beyond this computer. Anyone who can reach this port and load the page can use the desk "
              "and run your jobs. Use only on a trusted network or behind an authenticated tunnel.")
    print(f"SessionDesk running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", loop="asyncio")


if __name__ == "__main__":
    main()
