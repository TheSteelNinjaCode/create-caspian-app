"""Static site exporter for this Caspian app (SSG, like Next.js `output: export`).

Boots the real ASGI app in-process and requests every route through httpx2's
``ASGITransport`` (the app's own HTTP client, same as the test suite), so the
exported HTML is byte-identical to what the dev server serves (layouts,
components, PulsePoint deferral, security headers -- the whole pipeline). The
app's real lifespan is run around the export so startup/shutdown state matches a
live server. Output goes to ``static/`` as ``<route>/index.html`` plus a copy of
the public assets.

Scope policy: "warn & skip". Routes that cannot be fully static are NOT written;
each is reported so nothing broken ships silently:
  - dynamic routes (``[id]`` / ``[...slug]``) need an explicit path list
  - auth-gated routes redirect instead of returning a page
  - non-GET-only routes / error responses

Run via ``npm run static`` (builds Tailwind first, then this script).

Caveats that hold for ANY static build of this app:
  - ``pp.rpc()`` server actions, auth/sessions, WebSockets, streaming and
    per-request server data do NOT work without the Python backend. Pages that
    rely on them still render, but those interactions are dead in the output.
  - Asset URLs are root-absolute (``/css/...``, ``/js/...``). Serve ``static/``
    at a domain root, or rewrite the base path for a subdirectory deploy.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any

# Run from the project root so relative paths (public/, src/app/, config) resolve
# exactly like the running server does.
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# Keep the app in non-production mode: dev generates an ephemeral session secret,
# so the build does not require production secrets to be present.
os.environ.setdefault("APP_ENV", "development")

import httpx2  # noqa: E402  (the app's HTTP client; drives the ASGI app in-process)

import main  # noqa: E402  (imports boot the app and register all routes)
from casp.caspian_config import get_files_index  # noqa: E402

OUT_DIR = ROOT / "static"
PUBLIC_DIR = ROOT / "public"

# Public asset trees to mirror into static/ (source name -> output name).
ASSET_DIRS = ("css", "js", "assets", "uploads")
ASSET_FILES = ("favicon.ico",)

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def _route_py_path(route) -> str:
    base = f"src/app/{route.fs_dir}" if route.fs_dir else "src/app"
    return f"{base}/index.py".replace("//", "/")


async def _resolve_static_paths(route) -> list | None:
    """Return concrete param sets for a dynamic route, or None if not declared.

    A dynamic route pre-renders itself by exporting ``static_paths`` in its
    ``index.py`` -- Caspian's equivalent of Next.js ``getStaticPaths``. It may be:
      - a list of dicts:   [{"id": 1}, {"id": 2}]
      - a list of scalars: [1, 2]  (mapped onto the route's single param)
      - a callable (sync or async) returning either of the above
    """
    if not route.has_py:
        return None
    module = main.load_route_module(_route_py_path(route))
    provider = getattr(module, "static_paths", None)
    if provider is None:
        return None
    result: Any = provider() if callable(provider) else provider
    if inspect.isawaitable(result):
        # The whole export already runs inside a single event loop, so an async
        # provider is awaited directly -- no nested loop.
        result = await result
    return list(result)


def _fill_rule(fastapi_rule: str, params) -> str:
    """Substitute a param set into a FastAPI rule -> a concrete URL path."""
    names = re.findall(r"{(\w+)(?::path)?}", fastapi_rule)
    if not isinstance(params, dict):
        # Scalar convenience for single-parameter routes like /todo/[id].
        params = {names[0]: params} if names else {}
    url = fastapi_rule
    for key, value in params.items():
        url = url.replace(f"{{{key}:path}}", str(value)).replace(f"{{{key}}}", str(value))
    return url


def _out_path_for(url_path: str) -> Path:
    """Map a URL path to its static file: '/' -> index.html, '/x' -> x/index.html."""
    clean = url_path.strip("/")
    if not clean:
        return OUT_DIR / "index.html"
    return OUT_DIR / clean / "index.html"


def _handle_locked_removal(func, path, exc) -> None:
    """``shutil.rmtree`` onexc hook: clear a read-only bit and retry the delete.

    Handles the common Windows case where a file is read-only (``os.remove`` /
    ``os.rmdir`` raise ``PermissionError``); anything still failing is left for
    the retry loop in ``_reset_out_dir`` to re-evaluate or report.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _reset_out_dir(out_dir: Path, attempts: int = 5, delay: float = 0.4) -> bool:
    """Empty ``static/`` in place and return True on success.

    Deliberately keeps the top-level ``static/`` directory instead of removing
    it. On Windows, ``rmtree(static/)`` fails with ``WinError 32`` ("used by
    another process") whenever anything holds a handle on the directory itself --
    a shell cwd'd into it, an open File Explorer window, an editor, an
    antivirus/indexer scan, or a still-running ``npm run static:serve``. Clearing
    the *contents* and rewriting them sidesteps that lock. Transient child locks
    get a few retries before we give up with an actionable message.
    """
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        return True

    for _ in range(attempts):
        if not any(out_dir.iterdir()):
            return True
        for entry in out_dir.iterdir():
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, onexc=_handle_locked_removal)
                else:
                    try:
                        entry.unlink()
                    except PermissionError:
                        os.chmod(entry, stat.S_IWRITE)
                        entry.unlink()
            except OSError:
                pass  # re-evaluated on the next pass
        if not any(out_dir.iterdir()):
            return True
        time.sleep(delay)

    stuck = ", ".join(p.name for p in out_dir.iterdir()) or out_dir.name
    print(
        f"{RED}Could not clear the static/ output directory.{RESET}\n"
        f"{DIM}  Still locked: {stuck}\n"
        f"  Something is holding a handle on it. Close whatever is using static/\n"
        f"  and retry -- a running `npm run static:serve`, a File Explorer window\n"
        f"  or terminal open inside static/, or an editor previewing an exported\n"
        f"  file are the usual causes.{RESET}"
    )
    return False


def _copy_assets() -> None:
    for name in ASSET_DIRS:
        src = PUBLIC_DIR / name
        if src.is_dir():
            dst = OUT_DIR / name
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"{DIM}  copied public/{name}/ -> static/{name}/{RESET}")
    for name in ASSET_FILES:
        src = PUBLIC_DIR / name
        if src.is_file():
            shutil.copy2(src, OUT_DIR / name)
            print(f"{DIM}  copied public/{name} -> static/{name}{RESET}")


def build() -> int:
    idx = get_files_index()

    if not _reset_out_dir(OUT_DIR):
        return 1

    exported: list[str] = []
    skipped: list[tuple[str, str]] = []
    rpc_warnings: list[str] = []

    print(f"\n{GREEN}Caspian static export{RESET} -> {OUT_DIR}\n")

    async def export_one(client, url: str) -> None:
        resp = await client.get(url, follow_redirects=False)

        if resp.status_code in (301, 302, 303, 307, 308):
            target = resp.headers.get("location", "?")
            skipped.append(
                (url, f"redirects to {target} -- likely auth-gated, needs the server")
            )
            return

        if resp.status_code != 200:
            skipped.append((url, f"returned HTTP {resp.status_code}"))
            return

        if "text/html" not in resp.headers.get("content-type", ""):
            skipped.append((url, "non-HTML response"))
            return

        html = resp.text
        out_file = _out_path_for(url)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html, encoding="utf-8")
        exported.append(url)

        # Heuristic: flag pages whose interactivity depends on the backend.
        if "pp.rpc" in html or "X-PP-RPC" in html or "pp-rpc" in html:
            rpc_warnings.append(url)

    async def render_all() -> None:
        # Drive the ASGI app in-process with httpx2 (same as the test suite).
        # ASGITransport does not run lifespan on its own, so enter the app's real
        # lifespan context to mirror a live server's startup/shutdown state.
        transport = httpx2.ASGITransport(app=main.app)
        async with main.app.router.lifespan_context(main.app):
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                for route in idx.routes:
                    url = route.url_path

                    # Dynamic segments: pre-render only what the route declares via
                    # static_paths() (the getStaticPaths equivalent). Otherwise skip.
                    if "{" in route.fastapi_rule:
                        param_sets = await _resolve_static_paths(route)
                        if not param_sets:
                            skipped.append(
                                (url, "dynamic route -- add static_paths() to its index.py to pre-render (like getStaticPaths)")
                            )
                            continue
                        for params in param_sets:
                            await export_one(client, _fill_rule(route.fastapi_rule, params))
                        continue

                    await export_one(client, url)

    asyncio.run(render_all())

    _copy_assets()

    # ---- Report ----
    print(f"\n{GREEN}Exported {len(exported)} page(s):{RESET}")
    for url in exported:
        rel = _out_path_for(url).relative_to(ROOT)
        print(f"  {GREEN}OK{RESET}  {url}  ->  {rel}")

    if rpc_warnings:
        print(f"\n{YELLOW}Note: these pages appear to use pp.rpc()/server actions{RESET}")
        print(f"{DIM}  (they render, but those interactions are dead without the backend):{RESET}")
        for url in rpc_warnings:
            print(f"  {YELLOW}!{RESET}  {url}")

    if skipped:
        print(f"\n{YELLOW}Skipped {len(skipped)} route(s):{RESET}")
        for url, reason in skipped:
            print(f"  {YELLOW}SKIP{RESET} {url}  ({reason})")

    print(
        f"\n{GREEN}Done.{RESET} Preview it over HTTP: {GREEN}npm run static:serve{RESET} "
        f"-> http://localhost:8000\n"
        f"{DIM}  Do NOT double-click static/index.html (file://): root-absolute asset\n"
        f"  paths break and browsers block ES module scripts from file:// origins.\n"
        f"  Deploy the static/ folder to any HTTP host (Netlify, Vercel, GitHub Pages, nginx).{RESET}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
