"""App-level quality gate: type check + lint + tests in one command.

Runs the three app-owned checks against `main.py` and `src/**` and prints a
single, AI-friendly list of problems as `path:line:col` with the message, so
an agent (or a human) is told exactly which file and location to fix.

Usage (from the project root):

    python settings/check.py                # run everything (the gate)
    python settings/check.py --only pyrefly # run one tool while debugging

Exit code is 0 only when every selected check passes, so it works as a CI /
pre-commit gate. Prefer `npm run check` for day-to-day use.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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


def run_pyrefly() -> Result:
    cmd = [sys.executable, "-m", "pyrefly", "check", "--output-format", "json"]
    proc = _run(cmd)

    issues: list[Issue] = []
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        # pyrefly failed to run (e.g. config error); surface stderr as a note.
        return Result("pyrefly", ok=False, note=proc.stderr.strip() or proc.stdout.strip())

    for err in data.get("errors", []):
        if err.get("severity") not in (None, "error"):
            continue
        issues.append(
            Issue(
                path=err.get("path", "?"),
                line=int(err.get("line", 0)),
                column=int(err.get("column", 0)),
                tool="pyrefly",
                code=err.get("name", "type-error"),
                message=err.get("concise_description")
                or err.get("description", "type error"),
            )
        )
    return Result("pyrefly", ok=not issues, issues=issues)


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
    cmd = [sys.executable, "-m", "pytest"]
    proc = _run(cmd)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run app type check, lint, and tests.")
    parser.add_argument(
        "--only",
        action="append",
        choices=["pyrefly", "ruff", "pytest"],
        help="Run only the named tool(s). Repeatable. Default: all.",
    )
    args = parser.parse_args()

    selected = args.only or ["pyrefly", "ruff", "pytest"]
    results: list[Result] = []
    if "pyrefly" in selected:
        results.append(run_pyrefly())
    if "ruff" in selected:
        results.append(run_ruff())
    if "pytest" in selected:
        results.append(run_pytest())

    return 0 if print_report(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
