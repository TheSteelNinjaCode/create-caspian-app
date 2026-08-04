"""App formatter: Python via ruff, authored markup via djLint (`npm run format`).

Two surfaces, one command:

1. **Python** -- `ruff format` over `main.py`, `src/**`, `settings/*.py`,
   `tests/**`. A Python formatter never rewrites string *contents*, so the
   markup inside `html(r\"\"\"...\"\"\")` is byte-preserved; this was verified
   across every block in `src/` before adopting it.

2. **Markup** -- the template inside every `html(r\"\"\"...\"\"\")` call, formatted
   with djLint and then *proved* unchanged in rendering before being written.

Why djLint, and why the proof
-----------------------------
This project layers four dialects in one string: HTML, Jinja `{{ }}`/`{% %}`,
PulsePoint `{ }`, and JavaScript inside `<script>` -- and they nest, e.g.
`class="... {currentUrl === '{{ item['href'] }}' ? 'a' : 'b'}"`. Prettier has no
Jinja awareness: it de-indents `{% for %}` blocks to column 0 and joins
`{% endfor %} {% endfor %}` onto one line. djLint is Jinja-aware and, critically,
does not reflow text -- so PulsePoint expressions survive intact.

djLint is still a general HTML formatter, and it will make changes that are
correct for HTML but wrong here. The one that matters: it inserts a newline
between a block tag and an adjacent inline or `<x-*>` tag, which renders as a
visible space, because a custom element's `display` is set by CSS the formatter
cannot see. So no block is trusted -- each is proved equivalent by
`_markup_equivalence` before it is written, and skipped with a reason if not.

Two regions are additionally masked away before djLint runs, so they are
preserved byte-for-byte by construction rather than by proof:

* `<script>` / `<style>` -- djLint reads `/>` inside a JS regex as a tag
  delimiter and rewrites `.replace(/>/g, …)` into `.replace( />/g, …)`.
* `<pre>` / `<textarea>` -- whitespace there renders literally.

Usage (from the project root):

    python settings/format.py            # format Python + markup
    python settings/format.py --check    # report only; exit 1 if work remains
    python settings/format.py --markup   # markup only, skip ruff format
    python settings/format.py --python   # ruff format only, skip markup

`npm run check:fix` runs this first, so formatting settles before the fixer and
the gate look at the code.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import _markup_equivalence as eq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = PROJECT_ROOT / "src"

# Generated or vendored trees that are not hand-authored.
EXCLUDED_PARTS = {"__pycache__", "node_modules", ".venv", "prisma"}

# Paths handed to `ruff format`. Mirrors the gate's Python surface.
PYTHON_TARGETS = ("main.py", "src", "settings", "tests")

# Excluded from formatting. The test is NOT "was this generated" -- it is
# "is this regenerated wholesale and never hand-edited". The Prisma client is
# rewritten in full by `prisma generate` and is never touched by hand, so
# formatting it is pure churn that the next generate undoes; it also holds no
# markup, so nothing is lost by leaving it alone.
#
# Component libraries under `src/lib/**` are deliberately NOT listed here even
# though a CLI first installed them: they are hand-maintained in this workspace,
# and they hold the majority of the repo's markup blocks. Excluding them would
# remove most of the formatter's reach.
PYTHON_FORMAT_EXCLUDE = ("src/lib/prisma",)

# djLint settings. Passed explicitly rather than read from pyproject, because
# blocks are formatted in a temp directory outside the project.
DJLINT_INDENT = "2"
DJLINT_MAX_LINE = "120"

# Register `<x-*>` component tags with djLint. Without this it does not know
# them, treats them as inline, and leaves a component tree flat:
#
#     <x-shell>
#     <x-brand />
#     </x-shell>
#
# Registered, they nest like any other container. This does not weaken the
# safety check -- `_markup_equivalence` still treats `<x-*>` as inline, so any
# block where the new indentation would actually add rendered whitespace is
# still skipped.
DJLINT_CUSTOM_HTML = r"x-[\w-]+"

OPAQUE = re.compile(r"(<(script|style|pre|textarea)\b[^>]*>)(.*?)(</\2\s*>)", re.I | re.S)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except AttributeError, ValueError:
    pass

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


# ---------------------------------------------------------------------------
# masking
# ---------------------------------------------------------------------------


def mask_opaque(markup: str) -> tuple[str, dict[str, str]]:
    """Replace `<script>`/`<style>`/`<pre>`/`<textarea>` bodies with tokens."""
    store: dict[str, str] = {}

    def sub(m: re.Match[str]) -> str:
        key = f"PPMASK{len(store):04d}Z"
        store[key] = m.group(3)
        return f"{m.group(1)}{key}{m.group(4)}"

    return OPAQUE.sub(sub, markup), store


def unmask_opaque(markup: str, store: dict[str, str]) -> str:
    """Restore masked bodies, re-indenting code to its new nesting depth.

    `<pre>`/`<textarea>` are restored verbatim -- their whitespace renders.
    `<script>`/`<style>` are re-indented as a block, which cannot change what
    the code does but keeps the output readable.
    """
    for key, body in store.items():
        pattern = re.compile(
            r"([ \t]*)(<(script|style|pre|textarea)\b[^>]*>)" + key + r"(</\3\s*>)",
            re.I,
        )

        def repl(m: re.Match[str], body: str = body) -> str:
            indent, open_tag, tag, close_tag = (
                m.group(1),
                m.group(2),
                m.group(3).lower(),
                m.group(4),
            )
            if tag in ("pre", "textarea"):
                return f"{indent}{open_tag}{body}{close_tag}"
            lines = body.splitlines()
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
            if not lines:
                return f"{indent}{open_tag}{close_tag}"
            base = min((len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0)
            inner = indent + "  "
            rendered = "\n".join((inner + ln[base:].rstrip()) if ln.strip() else "" for ln in lines)
            return f"{indent}{open_tag}\n{rendered}\n{indent}{close_tag}"

        markup = pattern.sub(repl, markup, count=1)
    return markup


# ---------------------------------------------------------------------------
# block discovery
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """One `html(r\"\"\"...\"\"\")` template argument in a Python file."""

    path: Path
    lineno: int
    start: int  # byte offset of the string literal's opening quote
    end: int  # byte offset just past its closing quote
    prefix: str  # the literal's opening delimiter, e.g. `r\"\"\"`
    quote: str  # the closing delimiter
    source: str  # the markup itself


def _rel(path: Path) -> str:
    """Project-relative path for reports, tolerating a path outside the root."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_python_files() -> list[Path]:
    if not SCAN_ROOT.exists():
        return []
    return sorted(p for p in SCAN_ROOT.rglob("*.py") if not EXCLUDED_PARTS.intersection(p.parts))


def find_blocks(path: Path) -> list[Block]:
    """Every raw triple-quoted `html(...)` template argument in one file.

    Only the `html(r\"\"\"...\"\"\")` form is touched. That is the single markup
    entrypoint the `templates` gate already enforces (`html-form`), so any other
    shape is a gate failure to fix rather than something to reformat.
    """
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except OSError, UnicodeDecodeError, SyntaxError:
        return []

    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    blocks: list[Block] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "html" or not node.args:
            continue
        arg = node.args[0]
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue
        if arg.end_lineno is None or arg.end_col_offset is None:
            continue
        start = offsets[arg.lineno - 1] + arg.col_offset
        end = offsets[arg.end_lineno - 1] + arg.end_col_offset
        literal = text[start:end]
        match = re.match(r'^([rR]?)("""|\'\'\')', literal)
        if not match or not match.group(1):
            continue  # not the raw triple-quoted form; `templates` reports it
        prefix, quote = match.group(0), match.group(2)
        if not literal.endswith(quote):
            continue
        blocks.append(
            Block(
                path=path,
                lineno=arg.lineno,
                start=start,
                end=end,
                prefix=prefix,
                quote=quote,
                source=literal[len(prefix) : -len(quote)],
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# djLint
# ---------------------------------------------------------------------------


def _djlint_available() -> bool:
    return shutil.which("djlint") is not None or _djlint_module()


def _djlint_module() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "djlint", "--version"],
            capture_output=True,
            timeout=60,
        )
        return True
    except OSError, subprocess.SubprocessError:
        return False


def djlint_batch(sources: list[str]) -> list[str | None]:
    """Format many markup fragments in a single djLint run.

    djLint costs roughly a second of interpreter start-up per invocation, and
    this repo has well over 500 blocks. Writing them all into one temp directory
    and reformatting it once turns minutes into seconds.
    """
    if not sources:
        return []
    results: list[str | None] = [None] * len(sources)
    with tempfile.TemporaryDirectory(prefix="pp-format-") as tmp:
        root = Path(tmp)
        for index, text in enumerate(sources):
            (root / f"{index:05d}.html").write_text(text, encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "djlint",
                str(root),
                "--reformat",
                "--profile",
                "jinja",
                "--indent",
                DJLINT_INDENT,
                "--max-line-length",
                DJLINT_MAX_LINE,
                "--preserve-blank-lines",
                "--custom-html",
                DJLINT_CUSTOM_HTML,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # djLint exits 1 when it reformatted something; only >1 is a real error.
        if proc.returncode > 1:
            return results
        for index in range(len(sources)):
            try:
                results[index] = (root / f"{index:05d}.html").read_text(encoding="utf-8")
            except OSError:
                results[index] = None
    return results


def format_markup(source: str, formatted_skeleton: str | None, store: dict[str, str]) -> str | None:
    if formatted_skeleton is None:
        return None
    return unmask_opaque(formatted_skeleton, store)


# ---------------------------------------------------------------------------
# splicing
# ---------------------------------------------------------------------------


def render_literal(block: Block, markup: str) -> str | None:
    """Rebuild the Python string literal around freshly formatted markup.

    Returns None when the result could not be spliced back safely.
    """
    body = markup.strip("\n")
    if block.quote in body:
        return None  # would terminate the literal early
    if body.endswith("\\"):
        return None  # a trailing backslash escapes the closing quote
    original_multiline = "\n" in block.source.strip("\n") or block.source.startswith("\n")
    if "\n" in body or original_multiline:
        body = f"\n{body}\n"
    return f"{block.prefix}{body}{block.quote}"


@dataclass
class Skip:
    path: str
    lineno: int
    reason: str


@dataclass
class MarkupReport:
    scanned: int = 0
    formatted: int = 0
    already: int = 0
    files_changed: int = 0
    skips: list[Skip] = field(default_factory=list)
    error: str = ""


def format_markup_blocks(*, write: bool) -> MarkupReport:
    report = MarkupReport()

    files = _iter_python_files()
    per_file: dict[Path, list[Block]] = {}
    flat: list[tuple[Path, Block]] = []
    for path in files:
        blocks = find_blocks(path)
        if blocks:
            per_file[path] = blocks
            flat.extend((path, b) for b in blocks)

    report.scanned = len(flat)
    if not flat:
        return report

    masked: list[str] = []
    stores: list[dict[str, str]] = []
    for _, block in flat:
        skeleton, store = mask_opaque(block.source)
        masked.append(skeleton)
        stores.append(store)

    outputs = djlint_batch(masked)
    if all(o is None for o in outputs):
        report.error = "djLint did not run. Install it with `uv sync --group dev`."
        return report

    # Decide each block, then apply per file from the bottom up so earlier
    # offsets stay valid.
    decisions: dict[Path, list[tuple[Block, str]]] = {}
    for (path, block), skeleton, store in zip(flat, outputs, stores):
        rel = _rel(path)
        formatted = format_markup(block.source, skeleton, store)
        if formatted is None:
            report.skips.append(Skip(rel, block.lineno, "djLint could not format this block"))
            continue
        if formatted.strip("\n") == block.source.strip("\n"):
            report.already += 1
            continue
        same, why = eq.equivalent(block.source, formatted)
        if not same:
            report.skips.append(Skip(rel, block.lineno, why))
            continue
        literal = render_literal(block, formatted)
        if literal is None:
            report.skips.append(Skip(rel, block.lineno, "could not be spliced back safely"))
            continue
        decisions.setdefault(path, []).append((block, literal))
        report.formatted += 1

    report.files_changed = len(decisions)
    if not write:
        return report

    for path, items in decisions.items():
        text = path.read_text(encoding="utf-8")
        for block, literal in sorted(items, key=lambda i: i[0].start, reverse=True):
            text = text[: block.start] + literal + text[block.end :]
        # Never leave a file that no longer parses, or whose markup did not land
        # exactly as intended.
        try:
            ast.parse(text)
        except SyntaxError:
            report.skips.append(Skip(_rel(path), 0, "rewrite would not parse; file left unchanged"))
            report.formatted -= len(items)
            report.files_changed -= 1
            continue
        path.write_text(text, encoding="utf-8")

    return report


# ---------------------------------------------------------------------------
# ruff format
# ---------------------------------------------------------------------------


def _ruff_format_cmd(targets: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "ruff", "format", *targets]
    for excluded in PYTHON_FORMAT_EXCLUDE:
        cmd += ["--exclude", excluded]
    return cmd


def hug_html_call_openings(paths: list[Path], *, write: bool) -> list[Path]:
    """Put `html(r\"\"\"` back on one line, so the markup starts at line 1.

        `ruff format` always explodes a call whose first argument is a multiline
        string when the call has other arguments, producing:

            return html(
                r\"\"\"
            <div>…

    That buries the template one level deeper and separates `html(` from the
        markup it opens. The house style is `html(r\"\"\"` with the markup starting
        on the next line, so this runs *after* ruff and closes the gap.

        Ruff will re-split these on its next run, in default and preview style
        alike, so the two steps must always run as a pair -- which is why
        `--check` re-runs the whole pipeline rather than calling
        `ruff format --check` directly.

        Returns the paths that needed the fix.
    """
    touched: list[Path] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if "html(" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        cuts: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "html" or not node.args:
                continue
            arg = node.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            func_line, func_col = node.func.end_lineno, node.func.end_col_offset
            if func_line is None or func_col is None:
                continue
            paren = text.find("(", offsets[func_line - 1] + func_col)
            if paren == -1:
                continue
            literal_start = offsets[arg.lineno - 1] + arg.col_offset
            gap = text[paren + 1 : literal_start]
            # Only close a gap that is pure whitespace spanning a line break;
            # anything else means this is not the shape ruff produced.
            if gap and gap.strip() == "" and "\n" in gap:
                cuts.append((paren + 1, literal_start))

        if not cuts:
            continue
        touched.append(path)
        if not write:
            continue
        for start, end in sorted(cuts, reverse=True):
            text = text[:start] + text[end:]
        try:
            ast.parse(text)
        except SyntaxError:
            continue  # leave the file as ruff wrote it rather than risk it
        path.write_text(text, encoding="utf-8")
    return touched


def _python_files_for_hug() -> list[Path]:
    """Every formatted Python file that could contain an `html(...)` call."""
    found: list[Path] = []
    for target in PYTHON_TARGETS:
        base = PROJECT_ROOT / target
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in candidates:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            if any(rel.startswith(x) for x in PYTHON_FORMAT_EXCLUDE):
                continue
            found.append(path)
    return found


_PYTHON_PIPELINE_ROUNDS = 4


def _snapshot(files: list[Path]) -> dict[Path, bytes]:
    out: dict[Path, bytes] = {}
    for path in files:
        try:
            out[path] = path.read_bytes()
        except OSError:
            continue
    return out


def _python_pipeline(root: Path, targets: list[str], files: list[Path]) -> int:
    """Run `ruff format` + the `html(` hug until the tree stops changing.

    One pass is not enough, because the two steps feed each other. Ruff splits
    `html(` off its template; the hug rejoins it; and for a call whose template
    is the *only* argument, that rejoin then lets ruff pull the closing `)` up
    on its next run. Iterating to a fixed point is what makes the result stable
    -- and it is what lets `--check` replay this exact function against a mirror
    of the tree, instead of trusting `ruff format --check`, which would flag
    every hugged call as unformatted because ruff is what splits them.

    It settles in a couple of rounds: a multi-argument call lands on
    ruff-splits-then-hug-rejoins, which is a fixed point of the *pair* even
    though neither step is idempotent alone.

    Returns the number of files whose bytes changed.
    """
    initial = _snapshot(files)
    for _ in range(_PYTHON_PIPELINE_ROUNDS):
        before = _snapshot(files)
        subprocess.run(
            _ruff_format_cmd(targets),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        hug_html_call_openings(files, write=True)
        if _snapshot(files) == before:
            break
    final = _snapshot(files)
    return sum(1 for path, data in initial.items() if final.get(path) != data)


def run_ruff_format(*, write: bool) -> tuple[bool, str]:
    targets = [t for t in PYTHON_TARGETS if (PROJECT_ROOT / t).exists()]
    files = _python_files_for_hug()

    if write:
        changed = _python_pipeline(PROJECT_ROOT, targets, files)
        total = len(files)
        if changed:
            return True, f"{changed} file(s) reformatted, {total - changed} left unchanged"
        return True, f"{total} files already formatted"

    with tempfile.TemporaryDirectory(prefix="pp-pyfmt-") as tmp:
        root = Path(tmp)
        # Ruff resolves `include`/`exclude` relative to the config's directory,
        # so the mirror needs the same relative layout and its own copy of the
        # config, or every file is filtered out as "not part of the project".
        (root / "pyproject.toml").write_bytes((PROJECT_ROOT / "pyproject.toml").read_bytes())
        mirrored: list[tuple[Path, Path]] = []
        for path in files:
            dest = root / path.relative_to(PROJECT_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(path.read_bytes())
            except OSError:
                continue
            mirrored.append((path, dest))

        _python_pipeline(root, targets, [d for _, d in mirrored])
        differing = sum(
            1 for original, dest in mirrored if original.read_bytes() != dest.read_bytes()
        )

    total = len(mirrored)
    if differing:
        return (
            False,
            f"{differing} file(s) would be reformatted, {total - differing} already formatted",
        )
    return True, f"{total} files already formatted"


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def print_report(report: MarkupReport, ruff_line: str, *, write: bool) -> None:
    verb = "formatted" if write else "would format"
    if ruff_line:
        print(f"{bold('python')}   {ruff_line}")
    if report.error:
        print(f"{bold('markup')}   {red(report.error)}")
        return
    print(
        f"{bold('markup')}   {verb} {report.formatted} of {report.scanned} block(s); "
        f"{report.already} already formatted; {len(report.skips)} skipped"
    )
    if not report.skips:
        return
    print(
        f"\n{yellow('skipped')} — djLint's output could not be proved to render "
        f"identically, so these were left alone:"
    )
    by_file: dict[str, list[Skip]] = {}
    for skip in report.skips:
        by_file.setdefault(skip.path, []).append(skip)
    for path in sorted(by_file):
        print(f"  {path}")
        for skip in sorted(by_file[path], key=lambda s: s.lineno):
            print(f"    {skip.lineno}: {skip.reason}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Format app Python (ruff) and authored markup (djLint)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change without writing; exit 1 if work remains",
    )
    parser.add_argument("--python", action="store_true", help="format Python only")
    parser.add_argument("--markup", action="store_true", help="format markup only")
    args = parser.parse_args()

    do_python = args.python or not args.markup
    do_markup = args.markup or not args.python
    write = not args.check

    # Markup first, Python second. Reformatting a template changes how many
    # lines its string literal spans, which can change how ruff wraps the
    # enclosing `html(...)` call. Running ruff last means one pass converges;
    # the other order leaves files that `--check` would still flag.
    report = MarkupReport()
    if do_markup:
        report = format_markup_blocks(write=write)

    ruff_ok, ruff_line = (True, "")
    if do_python:
        ruff_ok, ruff_line = run_ruff_format(write=write)

    print_report(report, ruff_line, write=write)

    if report.error:
        return 1
    if args.check:
        return 0 if (ruff_ok and report.formatted == 0) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
