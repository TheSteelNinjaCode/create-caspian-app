"""Robust static preview server for the exported `static/` build.

Replaces the fragile ``python -m http.server ... 8000`` one-liner, which crashes
with ``OSError: [Errno 98/10048] address already in use`` the moment port 8000 is
taken (a second preview, another dev tool, XAMPP, etc.). This script instead:

  - serves ONLY the ``static/`` directory (no traversal outside it),
  - binds to loopback ``127.0.0.1`` by default so the preview is NOT exposed to
    the local network,
  - auto-selects a free port: it tries the preferred port and walks upward until
    one binds, so an occupied port never aborts the preview,
  - fails fast with a clear message if ``static/`` was never built,
  - shuts down cleanly on Ctrl+C.

Config via environment (all optional):
  HOST         bind address           (default 127.0.0.1; use 0.0.0.0 to expose)
  PORT         preferred start port   (default 8000)
  PORT_TRIES   how many ports to try  (default 50)

Run via ``npm run static:serve`` (after ``npm run static`` has produced static/).
"""

from __future__ import annotations

import errno
import os
import socket
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_PORT_TRIES = 50

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

# Errnos that mean "this port is taken, try the next one" across platforms.
# EADDRINUSE covers POSIX (98) and Windows WSAEADDRINUSE (10048);
# EACCES/WSAEACCES can appear on Windows when a port is held by another owner.
_PORT_TAKEN = {errno.EADDRINUSE, errno.EACCES}
if hasattr(errno, "WSAEADDRINUSE"):  # Windows-only alias
    _PORT_TAKEN.add(errno.WSAEADDRINUSE)  # type: ignore[attr-defined]


class SecureThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded server with reliable "is this port really free?" semantics.

    ``allow_reuse_address`` maps to ``SO_REUSEADDR``. On Windows that flag lets a
    NEW socket bind a port another socket is ACTIVELY listening on, which would
    make our probe silently "succeed" onto an occupied port and collide. So we
    disable it here: bind() then genuinely fails on a taken port and our
    port-walk loop can move on. (On POSIX SO_REUSEADDR only affects TIME_WAIT
    sockets, but keeping it off is harmless and keeps behavior identical.)
    """

    allow_reuse_address = False
    daemon_threads = True


class StaticRequestHandler(SimpleHTTPRequestHandler):
    """Serve static/ with light hardening and quieter, useful logging.

    SimpleHTTPRequestHandler already normalizes and confines paths to the served
    ``directory`` (no ``..`` traversal), so this only adds conservative response
    headers appropriate for a local static preview.
    """

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"{DIM}  {self.address_string()} - {format % args}{RESET}\n")


def _looks_built(static_dir: Path) -> bool:
    """True only if static/ exists and holds a real export (an index.html)."""
    return static_dir.is_dir() and (static_dir / "index.html").is_file()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"{YELLOW}  Ignoring invalid {name}={raw!r}; using {default}.{RESET}")
        return default
    return value


def _serve(host: str, start_port: int, tries: int) -> int:
    handler = partial(StaticRequestHandler, directory=str(STATIC_DIR))

    last_error: OSError | None = None
    for offset in range(max(1, tries)):
        port = start_port + offset
        if port > 65535:
            break
        try:
            httpd = SecureThreadingHTTPServer((host, port), handler)
        except OSError as exc:
            if exc.errno in _PORT_TAKEN:
                last_error = exc
                if offset == 0:
                    print(
                        f"{YELLOW}  Port {start_port} is busy; searching for a free "
                        f"port...{RESET}"
                    )
                continue
            # A different error (bad host, permissions, etc.) is not recoverable
            # by trying another port -- surface it.
            print(f"{RED}  Failed to bind {host}:{port} -- {exc}{RESET}")
            return 1

        with httpd:
            shown_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
            url = f"http://{shown_host}:{port}"
            if port != start_port:
                print(
                    f"{YELLOW}  Default port {start_port} was occupied; "
                    f"using {port} instead.{RESET}"
                )
            print(f"\n{GREEN}Serving{RESET} {DIM}{STATIC_DIR}{RESET}")
            print(f"{GREEN}  -> {url}{RESET}")
            if host == "0.0.0.0":
                lan = _lan_hint(port)
                if lan:
                    print(f"{DIM}  -> {lan} (exposed on your network){RESET}")
            print(f"{DIM}  Press Ctrl+C to stop.{RESET}\n")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print(f"\n{DIM}  Stopped.{RESET}")
            return 0

    ports = f"{start_port}-{start_port + max(1, tries) - 1}"
    print(
        f"{RED}  Could not find a free port in {ports} on {host}.{RESET}\n"
        f"{DIM}  Last error: {last_error}. Free a port or set PORT to another "
        f"start value.{RESET}"
    )
    return 1


def _lan_hint(port: int) -> str | None:
    """Best-effort LAN URL to show only when the user opted into 0.0.0.0."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        return f"http://{ip}:{port}"
    except OSError:
        return None


def main() -> int:
    if not _looks_built(STATIC_DIR):
        print(
            f"{RED}No static build found at {STATIC_DIR}.{RESET}\n"
            f"{DIM}  Build it first: {RESET}{GREEN}npm run static{RESET}"
        )
        return 1

    host = os.environ.get("HOST", "").strip() or DEFAULT_HOST
    start_port = _env_int("PORT", DEFAULT_PORT)
    tries = _env_int("PORT_TRIES", DEFAULT_PORT_TRIES)

    if not (1 <= start_port <= 65535):
        print(f"{RED}  PORT must be 1-65535 (got {start_port}).{RESET}")
        return 1

    return _serve(host, start_port, tries)


if __name__ == "__main__":
    raise SystemExit(main())
