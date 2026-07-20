"""App-level quality gate: type check + lint + tests in one command.

Runs the three app-owned checks against `main.py` and `src/**` and prints a
single, AI-friendly list of problems as `path:line:col` with the message, so
an agent (or a human) is told exactly which file and location to fix.

Usage (from the project root):

    python settings/check.py                # run everything (the gate)
    python settings/check.py --only pyright # run one tool while debugging

Exit code is 0 only when every selected check passes, so it works as a CI /
pre-commit gate. Prefer `npm run check` for day-to-day use.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import _component_imports as ci

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _is_component_import_false_positive(issue: Issue) -> bool:
    # Keep the gate honest for `<x-*>` tags: a component imports its children and
    # uses them only as tags in a template string ruff can't parse, so ruff
    # reports the import as F401. Those are load-bearing (see _component_imports),
    # so drop the report; genuinely dead imports still fail.
    if issue.tool != "ruff" or issue.code != "F401":
        return False
    return ci.is_component_tag_f401(issue.message, issue.path)

# Terminal colors (disabled automatically when output is not a TTY).
_TTY = sys.stdout.isatty()

# On Windows a redirected stdout defaults to cp1252, which can't encode some
# characters; ask for UTF-8 with a safe fallback so output never crashes.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    pass


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def red(t: str) -> str:
    return _c("31", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def bold(t: str) -> str:
    return _c("1", t)


def cyan(t: str) -> str:
    return _c("36", t)


class _Heartbeat:
    """Live "still working" indicator for a captured (non-streaming) tool.

    Tools like pyright/ruff emit one JSON blob only when they finish, so without
    this the terminal looks frozen while they run. On a TTY a background thread
    ticks a spinner + elapsed seconds on one line; off a TTY (CI/pipe) it prints
    a single start line instead of spamming carriage returns.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_Heartbeat":
        if _TTY:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            print(f"  {cyan('>')} {self.label} ... (running)", flush=True)
        return self

    def _spin(self) -> None:
        start = time.perf_counter()
        for frame in itertools.cycle("|/-\\"):
            if self._stop.wait(0.4):
                return
            elapsed = time.perf_counter() - start
            sys.stdout.write(f"\r  {cyan(frame)} {self.label} ... {elapsed:0.0f}s ")
            sys.stdout.flush()

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if _TTY:
            # Wipe the spinner line so the result line prints cleanly over it.
            sys.stdout.write("\r" + " " * 48 + "\r")
            sys.stdout.flush()


def _run_streamed(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a tool and echo its output live while also capturing it.

    Used for pytest so each test's progress line appears as it happens instead
    of after a multi-minute silence. The captured text is still returned so the
    caller can parse `FAILED` lines from it.
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    captured: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        captured.append(line)
        sys.stdout.write("    " + line)
        sys.stdout.flush()
    proc.wait()
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(captured), "")


@dataclass
class Issue:
    path: str
    line: int
    column: int
    tool: str
    code: str
    message: str

    def location(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"


@dataclass
class Result:
    tool: str
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    note: str = ""


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_pyright() -> Result:
    # `--outputjson` emits a single JSON object the gate can parse; pyright
    # picks up its config (scope, mode) from `[tool.pyright]` in pyproject.toml.
    cmd = [sys.executable, "-m", "pyright", "--outputjson"]
    proc = _run(cmd)

    issues: list[Issue] = []
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        # pyright failed to run (e.g. config error); surface stderr as a note.
        return Result("pyright", ok=False, note=proc.stderr.strip() or proc.stdout.strip())

    for diag in data.get("generalDiagnostics", []):
        if diag.get("severity") != "error":
            # warnings/information don't fail the gate, only `error` does.
            continue
        start = (diag.get("range") or {}).get("start") or {}
        issues.append(
            Issue(
                path=diag.get("file", "?"),
                # pyright ranges are 0-based; the gate reports 1-based.
                line=int(start.get("line", 0)) + 1,
                column=int(start.get("character", 0)) + 1,
                tool="pyright",
                code=diag.get("rule") or "type-error",
                message=diag.get("message", "type error"),
            )
        )
    return Result("pyright", ok=not issues, issues=issues)


def run_ruff() -> Result:
    cmd = [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"]
    proc = _run(cmd)

    issues: list[Issue] = []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return Result("ruff", ok=False, note=proc.stderr.strip() or proc.stdout.strip())

    for err in data:
        loc = err.get("location") or {}
        issue = Issue(
            path=err.get("filename", "?"),
            line=int(loc.get("row", 0)),
            column=int(loc.get("column", 0)),
            tool="ruff",
            code=err.get("code") or "lint",
            message=err.get("message", "lint error"),
        )
        # Drop F401 for imports that are actually used as `<x-*>` component tags
        # in the same file; keep genuinely dead imports so they still fail.
        if _is_component_import_false_positive(issue):
            continue
        issues.append(issue)
    return Result("ruff", ok=not issues, issues=issues)


def run_pytest() -> Result:
    # `-o addopts=` drops the ini `-q` so `-v` can print one live line per test
    # (the "which test is running" progress); `-rfE` keeps the `FAILED nodeid -
    # reason` summary lines this function parses below.
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-v",
        "--no-header",
        "-rfE",
    ]
    proc = _run_streamed(cmd)
    ok = proc.returncode == 0

    issues: list[Issue] = []
    if not ok:
        # Pull the `FAILED path::test - reason` lines from pytest's summary.
        for line in (proc.stdout + proc.stderr).splitlines():
            stripped = line.strip()
            if stripped.startswith("FAILED "):
                body = stripped[len("FAILED "):]
                nodeid, _, reason = body.partition(" - ")
                path, _, _ = nodeid.partition("::")
                issues.append(
                    Issue(
                        path=path.strip(),
                        line=0,
                        column=0,
                        tool="pytest",
                        code=nodeid.strip(),
                        message=reason.strip() or "test failed",
                    )
                )
    note = ""
    if not ok and not issues:
        # No parseable FAILED lines (e.g. a collection/import error) — keep the
        # last summary line so the failure is still visible.
        summary_lines = proc.stdout.strip().splitlines()
        note = summary_lines[-1] if summary_lines else "pytest failed"
    return Result("pytest", ok=ok, issues=issues, note=note)


def print_report(results: list[Result]) -> bool:
    all_issues = [i for r in results for i in r.issues]
    print()
    print(bold("Caspian app checks"))
    print("=" * 60)

    for r in results:
        if r.ok:
            print(f"  {green('PASS')}  {r.tool}")
        else:
            count = len(r.issues)
            detail = f"{count} issue(s)" if count else (r.note or "failed")
            print(f"  {red('FAIL')}  {r.tool}  ({detail})")

    if all_issues:
        print()
        print(bold(red("Issues to fix (file:line:col):")))
        print("-" * 60)
        # Group by file so the fix targets are obvious.
        by_file: dict[str, list[Issue]] = {}
        for issue in all_issues:
            by_file.setdefault(issue.path, []).append(issue)
        for path in sorted(by_file):
            print(yellow(path))
            for issue in sorted(by_file[path], key=lambda i: (i.line, i.column)):
                loc = f"{issue.line}:{issue.column}" if issue.line else "-"
                print(f"  {loc:>8}  [{issue.tool}:{issue.code}] {issue.message}")

    print()
    ok = all(r.ok for r in results)
    if ok:
        print(green(bold("All checks passed.")))
    else:
        print(red(bold(f"{len(all_issues)} issue(s) found. Fix the locations above.")))
    print()
    return ok


def _execute(label: str, runner, *, streamed: bool) -> Result:
    """Run one tool with live progress, then print a one-line result."""
    start = time.perf_counter()
    if streamed:
        # The tool echoes its own progress live (e.g. pytest's per-test lines).
        print(f"  {cyan('>')} {label} ... (live output below)", flush=True)
        result = runner()
    else:
        # Captured tool — show a ticking heartbeat so it never looks frozen.
        with _Heartbeat(label):
            result = runner()
    elapsed = time.perf_counter() - start
    mark = green("OK  ") if result.ok else red("FAIL")
    count = len(result.issues)
    detail = "" if result.ok else f"  ({count} issue(s))" if count else f"  ({result.note or 'failed'})"
    print(f"  {mark} {label}  {elapsed:0.1f}s{detail}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run app type check, lint, and tests.")
    parser.add_argument(
        "--only",
        action="append",
        choices=["pyright", "ruff", "pytest"],
        help="Run only the named tool(s). Repeatable. Default: all.",
    )
    args = parser.parse_args()

    selected = args.only or ["pyright", "ruff", "pytest"]

    print()
    print(bold("Caspian app checks") + "  (live progress)")
    print("=" * 60)

    results: list[Result] = []
    if "pyright" in selected:
        results.append(_execute("pyright", run_pyright, streamed=False))
    if "ruff" in selected:
        results.append(_execute("ruff", run_ruff, streamed=False))
    if "pytest" in selected:
        results.append(_execute("pytest", run_pytest, streamed=True))

    return 0 if print_report(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
