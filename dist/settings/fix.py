"""Safe auto-fixer for the app (`npm run check:fix`).

Removes genuinely dead imports and applies ruff's other safe fixes, then runs
the gate to report what remains. The catch it exists to handle: `pyproject.toml`
marks `F401` unfixable so a plain `ruff check --fix` (which anyone might run)
can never silently delete a component import that is used only as an `<x-*>` tag
(casp resolves those from module globals at render time). That safety also
blocks auto-removal of *ordinary* dead imports, so this script re-enables F401
removal — but only for files that contain no component-tag import, so component
imports are never at risk.

Flow:
  1. Format first (`format.py`): `ruff format` for Python, djLint for the markup
     inside `html(r\"\"\"...\"\"\")`. Formatting settles layout before anything
     inspects the code, so the fixer and the gate report on the final shape
     rather than on lines the formatter is about to move.
  2. List F401 findings under the project config (respects include/exclude).
  3. Split the owning files into "component-guarded" (has >=1 import used as an
     `<x-*>` tag) and the rest.
  4. Remove dead imports only in the non-guarded files, via an isolated ruff run
     (`--isolated` makes F401 fixable again; `--select F401` limits it to import
     removal; explicit file args keep the run scoped).
  5. Apply every other safe fix under the real project config.
  6. Run the gate (`check.py`) and exit with its status.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import _component_imports as ci

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "ruff", "check", *args])


def _remove_dead_imports() -> list[str]:
    """Delete genuinely unused imports; never touch component-tag imports.

    Returns the list of files that were auto-fixed.
    """
    proc = _ruff(".", "--select", "F401", "--output-format", "json")
    try:
        findings = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []

    guarded: set[str] = set()
    owning_files: set[str] = set()
    for f in findings:
        path = f.get("filename", "")
        if not path:
            continue
        owning_files.add(path)
        if ci.is_component_tag_f401(f.get("message", ""), path):
            guarded.add(path)

    # A file with even one template-driven import is skipped whole: we can't
    # remove just its dead imports without risking the load-bearing ones, and
    # the gate still reports any real deadwood there for manual removal.
    fixable_files = sorted(owning_files - guarded)
    if fixable_files:
        _ruff(*fixable_files, "--select", "F401", "--fix-only", "--isolated")
    return fixable_files


def _format() -> None:
    """Run the formatter, but never let it block the fixer or the gate.

    A formatting problem (a missing djLint, an unformattable block) must not
    stop dead imports from being removed or the gate from reporting. `format.py`
    prints its own summary, including anything it skipped.
    """
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "settings" / "format.py")],
        cwd=PROJECT_ROOT,
    )


def main() -> int:
    _format()
    _remove_dead_imports()
    # Every other safe fix under the real project config. F401 stays unfixable
    # here (dead imports were already handled above), so component imports are
    # untouched.
    _ruff(".", "--fix-only")

    gate = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "settings" / "check.py")],
        cwd=PROJECT_ROOT,
    )
    return gate.returncode


if __name__ == "__main__":
    raise SystemExit(main())
