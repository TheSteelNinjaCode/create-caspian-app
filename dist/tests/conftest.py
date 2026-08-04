"""Shared pytest setup for the app-level test suite.

Ensures the project root is importable so `import main` and `from src...`
resolve the same way they do when Caspian boots the app.
"""

import asyncio
import os
import sys
from collections.abc import Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, TypeVar

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_T = TypeVar("_T")


def run_async(coro: Coroutine[object, object, _T]) -> _T:
    """Run a coroutine to completion and return its result.

    Shared helper so synchronous tests can exercise async runtime code
    (component compilation, streaming) without a full async test harness.
    """
    return asyncio.run(coro)


@pytest.fixture
def fake_request():
    """Factory for a minimal Starlette-like request stand-in.

    Casp's ``Auth`` reads ``request.session`` while ``StateManager`` reads
    ``request.state.session`` and ``request.headers``. The factory shares a
    single session dict between ``request.session`` and ``request.state.session``
    so both runtimes observe the same store, and exposes ``url``/``method``/
    ``query_params`` defaults that the auth request-flow helpers touch.
    """

    def _make(
        session: Optional[dict] = None,
        headers: Optional[dict] = None,
        method: str = "GET",
        path: str = "/",
        query_params: Optional[dict] = None,
    ) -> SimpleNamespace:
        store: dict = session if session is not None else {}
        return SimpleNamespace(
            session=store,
            state=SimpleNamespace(session=store),
            headers=headers if headers is not None else {},
            method=method,
            url=SimpleNamespace(path=path),
            query_params=query_params if query_params is not None else {},
        )

    return _make


@pytest.fixture
def component_fixture_dir():
    """A throwaway directory for writing component modules a test then imports.

    Tests write ``.py`` component files here and pass the path as ``base_dir``
    to ``transform_components`` so relative ``@import`` paths resolve against a
    clean, per-test directory. The compiler only loads components from inside a
    configured ``componentScanDirs`` root (``src`` here), so the directory must
    live under ``src`` rather than an arbitrary ``tmp_path``.
    """
    import shutil
    import uuid

    scan_root = PROJECT_ROOT / "src" / "__test_components__"
    fixture_dir = scan_root / uuid.uuid4().hex
    fixture_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield fixture_dir
    finally:
        shutil.rmtree(scan_root, ignore_errors=True)


# Keep the app in its non-production code paths during tests (dev security
# headers, readable error messages, no HTTPS-only cookies).
os.environ.setdefault("APP_ENV", "development")
# Deterministic session secret so importing main.py never raises in dev.
os.environ.setdefault("AUTH_SECRET", "test-secret-not-for-production")
