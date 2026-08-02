"""Template lint: reject JSX and unknown directives in PulsePoint markup.

Why this exists
---------------
`npm run check` validated Python only. A route template could contain JSX --
`{users.map(user => (<tr/>))}`, `class={...}`, `className` -- and the gate stayed
green, because nothing in the toolchain reads `.html` files. The failure then
surfaced only in the browser, and the worst variant surfaced nowhere at all: an
unquoted brace attribute is invalid HTML, so the parser shreds the element, the
component root never compiles, the runtime's reveal step never clears
`<body style="opacity: 0">`, and the route serves a blank page with **no console
error**.

PulsePoint borrows React's hook API inside `<script>` and React's component
decomposition. It borrows none of React's markup syntax. This module enforces
that boundary at authoring time, where the fix is cheap.

Scope
-----
Scans authored markup under `src/`:

- `**/*.html` -- route, layout, and component templates
- `**/*.py`   -- single-file components that embed markup via `html(\"\"\"...\"\"\")`

Regions that legitimately contain JavaScript or sample code are removed before
matching, so a real `array.map(...)` in a component script and a JSX snippet in
a docs `<pre>` block are both ignored:

- `<script>...</script>` (the component script is JS, `.map()` is correct there)
- `<pre>` / `<code>` (documentation examples)
- `<!-- ... -->` (commented-out markup)

Usage:

    python settings/check_templates.py           # run standalone
    npm run check                                # runs as part of the gate
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = PROJECT_ROOT / "src"

# Generated or vendored trees that are not hand-authored markup.
EXCLUDED_PARTS = {"__pycache__", "node_modules", ".venv", "prisma"}


@dataclass
class TemplateIssue:
    path: str
    line: int
    column: int
    code: str
    message: str


@dataclass
class Rule:
    code: str
    pattern: re.Pattern[str]
    message: str


# Each rule names the JSX/unsupported construct and the PulsePoint replacement,
# so the report is directly actionable without opening the docs.
RULES: list[Rule] = [
    Rule(
        "jsx-map",
        # `{items.map(item => (` and `{items.map((item, i) => (` -- the trailing
        # `(` is what distinguishes returning markup from a normal value map.
        re.compile(r"\{[^{}\n]*?\.map\s*\(\s*\(?[\w\s,]*\)?\s*=>\s*\(", re.MULTILINE),
        "JSX .map() returning markup. Use <template pp-for=\"item in items\"> "
        'with key="{item.id}".',
    ),
    Rule(
        "jsx-logical",
        # `{cond && (<div` -- element after a logical AND.
        re.compile(r"\{[^{}]*?&&\s*\(\s*<", re.DOTALL),
        'JSX `{cond && (<element/>)}`. Use hidden="{!cond}" on the element.',
    ),
    Rule(
        "jsx-ternary-element",
        # `{cond ? <A` -- element directly after a ternary branch.
        re.compile(r"\{[^{}]*?\?\s*\(?\s*<[a-zA-Z]", re.DOTALL),
        "JSX `{cond ? <A/> : <B/>}`. Use two elements with complementary "
        'hidden="{...}" bindings.',
    ),
    Rule(
        "unquoted-brace-attr",
        # `class={...}` / `selected={...}` -- invalid HTML, silently blanks the page.
        re.compile(r"\s[\w:.\-]+=\{"),
        "Unquoted brace attribute. This is invalid HTML: the parser splits the "
        "value on spaces, the component root never compiles, and the page "
        'renders blank with no console error. Quote it: attr="{expr}".',
    ),
    Rule(
        "react-attribute",
        re.compile(r"\s(className|htmlFor|dangerouslySetInnerHTML)\s*="),
        "React DOM property. Use class=, for=, or server-rendered markup.",
    ),
    Rule(
        "camelcase-event",
        # `onClick="…"` / `onClick={…}` in attribute position. The value-start
        # class and the declaration lookbehinds keep ordinary JavaScript out:
        # `const onPointerEnter = () => {` is a valid handler name in a component
        # script or an injected snippet, not a JSX prop.
        re.compile(
            r"(?<!\bconst )(?<!\blet )(?<!\bvar )(?<!\bfunction )"
            r"\son[A-Z][a-zA-Z]*\s*=\s*[\"'{]"
        ),
        "camelCase event prop. PulsePoint binds native lowercase event "
        'attributes: onclick="{handler()}". A component prop uses kebab-case '
        '(on-click), which arrives as pp.props.onClick.',
    ),
    Rule(
        "jsx-fragment",
        re.compile(r"<>|</>"),
        "JSX fragment. A template needs exactly one real root element.",
    ),
    Rule(
        "style-object",
        re.compile(r"style\s*=\s*\{\{"),
        "JSX style object. pp-style takes a CSS *string*: "
        "pp-style=\"{'color: red'}\".",
    ),
    Rule(
        "unknown-directive",
        re.compile(r"\spp-(if|show|else|elif|key|class|text|html|model|bind|on)\s*[=>\s]"),
        "Directive does not exist in PulsePoint. Conditionals use "
        'hidden="{...}", lists use <template pp-for>, keys use plain key="{...}".',
    ),
]

# `pp-for` is valid only on <template>. Matching the opening tag it sits in is
# enough: the attribute cannot appear before its own tag name.
PP_FOR_TAG = re.compile(r"<\s*([a-zA-Z][\w:-]*)([^>]*?\spp-for\s*=)", re.DOTALL)

SCRIPT_BLOCK = re.compile(r"<script\b.*?</script\s*>", re.IGNORECASE | re.DOTALL)
PRE_BLOCK = re.compile(r"<(pre|code)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# Components are imported with Python imports; an `@import` HTML comment does
# not import anything and the compiler refuses it. Matched BEFORE comments are
# blanked out — the construct *is* a comment.
IMPORT_COMMENT = re.compile(r"<!--\s*@import\b")

# In a single-file component the markup lives in a triple-quoted string handed to
# `html(...)`. Surrounding Python must not be matched: `onValueChange=...` is an
# ordinary keyword argument, and flagging it as a camelCase event prop would make
# the gate unusable for every generated maddex component.
TRIPLE_QUOTED = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')


def _blank_out(text: str, pattern: re.Pattern[str]) -> str:
    """Replace matched regions with same-length whitespace.

    Offsets stay valid, so reported line/column numbers still point at the real
    location in the original file.
    """

    def replace(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return pattern.sub(replace, text)


def _keep_only(text: str, pattern: re.Pattern[str]) -> str:
    """Inverse of `_blank_out`: blank everything *outside* the matched regions."""
    kept = ["\n" if ch == "\n" else " " for ch in text]
    for match in pattern.finditer(text):
        for index in range(match.start(), match.end()):
            kept[index] = text[index]
    return "".join(kept)


def _markup_regions(text: str, *, is_python: bool) -> tuple[str, str]:
    """Reduce a source file to just the markup a template rule may match.

    Returns ``(markup, markup_with_comments)``: the first has HTML comments
    blanked for the JSX/directive rules; the second keeps them so the
    ``@import``-comment rule can still see its target.
    """
    if is_python:
        # Only triple-quoted regions can hold markup in a single-file component.
        text = _keep_only(text, TRIPLE_QUOTED)
    for pattern in (SCRIPT_BLOCK, PRE_BLOCK):
        text = _blank_out(text, pattern)
    return _blank_out(text, HTML_COMMENT), text


def _position(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def lint_text(text: str, rel_path: str, *, is_python: bool = False) -> list[TemplateIssue]:
    """Return every template issue found in one file's contents."""
    markup, markup_with_comments = _markup_regions(text, is_python=is_python)
    issues: list[TemplateIssue] = []

    for match in IMPORT_COMMENT.finditer(markup_with_comments):
        line, column = _position(markup_with_comments, match.start())
        issues.append(
            TemplateIssue(
                rel_path,
                line,
                column,
                "import-comment",
                "An '@import' HTML comment does not import a component. Import "
                "it in the owning Python module "
                "(from src.lib.maddex.Button import Button) and keep the "
                "<x-button> tag in the markup.",
            )
        )

    for rule in RULES:
        for match in rule.pattern.finditer(markup):
            line, column = _position(markup, match.start())
            issues.append(
                TemplateIssue(rel_path, line, column, rule.code, rule.message)
            )

    for match in PP_FOR_TAG.finditer(markup):
        tag = match.group(1).lower()
        if tag == "template":
            continue
        line, column = _position(markup, match.start())
        issues.append(
            TemplateIssue(
                rel_path,
                line,
                column,
                "pp-for-placement",
                f"pp-for on <{tag}>. It belongs only on <template>: "
                f'<template pp-for="item in items"><{tag} key="{{item.id}}">…',
            )
        )

    return issues


def _iter_files() -> list[Path]:
    if not SCAN_ROOT.exists():
        return []
    files: list[Path] = []
    for pattern in ("**/*.html", "**/*.py"):
        for path in SCAN_ROOT.glob(pattern):
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return sorted(files)


def lint_templates() -> list[TemplateIssue]:
    """Lint every authored template under `src/`."""
    issues: list[TemplateIssue] = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Cheap pre-filter: a file with no brace expression and no angle-bracket
        # markup cannot trip any rule.
        if "{" not in text and "<" not in text:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        issues.extend(lint_text(text, rel, is_python=path.suffix == ".py"))
    return issues


def main() -> int:
    issues = lint_templates()
    if not issues:
        print("templates: no JSX or unknown directives found.")
        return 0

    by_file: dict[str, list[TemplateIssue]] = {}
    for issue in issues:
        by_file.setdefault(issue.path, []).append(issue)

    for path in sorted(by_file):
        print(path)
        for issue in sorted(by_file[path], key=lambda i: (i.line, i.column)):
            print(
                f"  {issue.line}:{issue.column}  "
                f"[templates:{issue.code}] {issue.message}"
            )

    print(f"\n{len(issues)} template issue(s) found.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
