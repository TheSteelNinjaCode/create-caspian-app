"""Rendering-equivalence oracle for PulsePoint + Jinja markup.

Why this exists
---------------
`format.py` runs djLint over authored markup. djLint is Jinja-aware and does not
reflow text, which makes it the only formatter that survives this project's four
nested dialects (HTML, Jinja `{{ }}`/`{% %}`, PulsePoint `{ }`, and JS inside
`<script>`). It is still an HTML formatter, and it will happily make changes that
are correct for HTML but wrong here -- most notably inserting a newline between
two `<x-*>` tags, which renders as a visible space because a custom element's
`display` is unknowable from the markup.

So the formatter does not trust djLint. Every block is formatted, then *proved*
to render identically before it is written back. Anything unprovable is skipped
and reported. That is what makes a bulk reformat of 500+ templates safe to run.

What "equivalent" means here
----------------------------
Each rule below is a real rendering rule, not a heuristic:

* whitespace INSIDE a tag (between attributes, before `>`) never renders
* a whitespace RUN in text renders as a single space, but the presence vs
  absence of whitespace between two inline elements is significant
* whitespace touching a block-level boundary collapses and never renders
* a text node's leading/trailing whitespace collapses when its parent is
  block-level, but not when the parent is inline or an unknown `<x-*>` tag
* in a flex or grid container, an anonymous item holding only white space is
  not rendered at all (CSS Flexbox 4, CSS Grid 6), so whitespace between that
  container's children collapses -- including when the container is an `<x-*>`
  tag whose rendered root is known (see `component_display.py`)
* `<pre>` / `<textarea>` text renders verbatim
* `<script>` / `<style>` bodies are code: indentation is irrelevant
* attribute ORDER never affects rendering; attribute VALUES always do
* Jinja `{{x}}` and `{{ x }}` are the same expression

Anything this module cannot prove, it reports as a difference. False negatives
(claiming a real change is safe) are the only dangerous errors, so every rule
errs toward reporting a difference.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


LITERAL_TAGS = {"pre", "textarea"}
CODE_TAGS = {"script", "style"}

# fmt: off
# Block-level boxes. Whitespace touching one of these collapses: it sits either
# at the edge of the box's own content or on a line that the block already
# broke, and in both places it is removed.
BLOCK_TAGS = {
    "html", "head", "body", "div", "p", "section", "article", "header",
    "footer", "nav", "aside", "main", "form", "fieldset", "legend", "figure",
    "figcaption", "blockquote", "hr", "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup",
    "col", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "details", "summary",
    "dialog", "script", "style", "template", "address", "hgroup", "menu",
    "search", "noscript", "br", "meta", "link", "title",
}

# Inline-level elements that still lay their *content* out as a block. A
# `<button>` is `inline-block`: the whitespace at the edges of its content
# collapses exactly as it would in a div, even though whitespace next to the
# button itself is significant. Keeping these out of BLOCK_TAGS is the point --
# two adjacent inline-blocks separated by a newline really do render a space.
CONTENT_BOX_TAGS = {
    "button", "select", "textarea", "option", "optgroup",
    "video", "audio", "canvas", "iframe", "object", "progress", "meter",
}

# Containers where a child made only of whitespace cannot render at all.
# * SVG lays out no text, so indenting an svg fragment cannot change what is
#   drawn. `<text>`, `<tspan>`, `<textPath>` and `<foreignObject>` are excluded
#   because they do render their content.
# * A table or select drops stray text between its structural children.
# Flex and grid containers join this set at runtime, from their class list.
WS_DROPPING_TAGS = {
    "svg", "g", "defs", "symbol", "use", "path", "circle", "ellipse", "line",
    "polyline", "polygon", "rect", "clippath", "lineargradient",
    "radialgradient", "stop", "mask", "pattern", "filter", "marker", "desc",
    "animate", "animatetransform", "animatemotion", "switch", "image",
    "table", "thead", "tbody", "tfoot", "tr", "colgroup", "select", "optgroup",
    "html", "head",
}
# fmt: on

# Void elements cannot have children at all. A component written as
# `<x-input class="..."></x-input>` renders an `<input>`, so anything the author
# puts between those tags -- including a newline djLint adds -- is discarded.
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

# Tailwind's display utilities that create a flex or grid formatting context.
# Membership is tested against whitespace-split class tokens, so only the
# unprefixed form counts: `sm:flex` means the element is *not* flex at every
# breakpoint, so its whitespace can still render on a narrow screen.
FLEX_DISPLAY_CLASSES = {"flex", "inline-flex", "grid", "inline-grid"}
# Display utilities that make an element a block-level box, so whitespace next
# to it collapses. The `inline-*` forms are deliberately absent: two adjacent
# inline-blocks separated by a newline really do render a space.
BLOCK_LEVEL_CLASSES = {"block", "flow-root", "list-item", "table", "flex", "grid"}
# `display: none` removes the box entirely, so it is not a block-level box that
# whitespace beside it can collapse against. It says nothing about how its own
# content is laid out when some state does display it, so it only suppresses
# `block_level`.
HIDDEN_CLASS = "hidden"
# `display: inline` makes an element lay its content out inline, so edge
# whitespace inside it becomes significant. `display: contents` removes the box
# and hoists the children into the parent, exactly like `as-child`.
INLINE_CLASS = "inline"
CONTENTS_CLASS = "contents"

# Display utilities that make an element lay its content out as a block, so the
# whitespace at the edges of that content collapses. `inline-block` counts: only
# whitespace *next to* it stays significant, not whitespace inside it.
BLOCK_CONTAINER_CLASSES = {
    "block",
    "inline-block",
    "flow-root",
    "list-item",
    "table",
    "inline-table",
    "table-cell",
    "table-row",
    "table-caption",
}
# Utilities that switch whitespace collapsing off. Every rule here assumes
# collapsible text, so an element carrying one of these knows nothing.
PRE_WHITESPACE_CLASSES = {
    "whitespace-pre",
    "whitespace-pre-wrap",
    "whitespace-pre-line",
    "whitespace-break-spaces",
}

# Attributes that make a component transparent: `as-child` renders the child in
# the component's place, so the child's whitespace lands in the *parent's*
# formatting context, not in any box the component owns.
AS_CHILD_ATTRS = ("as-child", "aschild", "as_child")
_TRUTHY_AS_CHILD = {"", "true", "1", "yes"}

JINJA = re.compile(r"\{\{\s*(.*?)\s*\}\}|\{%\s*(.*?)\s*%\}", re.S)


def _canon_jinja(text: str) -> str:
    """`{{  x  }}` and `{{x}}` are the same expression to Jinja."""

    def sub(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return "{{ " + re.sub(r"\s+", " ", m.group(1)) + " }}"
        return "{% " + re.sub(r"\s+", " ", m.group(2)) + " %}"

    return JINJA.sub(sub, text)


def _canon_attr_value(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", _canon_jinja(value)).strip()


# ---------------------------------------------------------------------------
# What an `<x-*>` tag really is
#
# A component tag is an ordinary HTML tag with an `x-` prefix: `<x-search />`
# *is* an `<svg>`, `<x-dialog-close>` *is* a `<button>`. Nothing above needs a
# custom rule for them -- they only need resolving to the element they render,
# and then every rule already written for HTML applies unchanged.
#
# The mapping is not declared anywhere because it does not have to be: a
# component is a function returning markup, so rendering it with no props shows
# its root. That is done once, lazily, the first time a custom tag is seen.
# ---------------------------------------------------------------------------

_ROOT_TAG_RE = re.compile(r"\s*<([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>")
_CLASS_ATTR_RE = re.compile(r'(?:^|\s)class="([^"]*)"')
# `merge_classes` renders a live `{twMerge("base classes", ...)}` expression, so
# a component's own classes are the first quoted literal inside it.
_TWMERGE_LITERAL_RE = re.compile(r'twMerge\(\s*(?:"|&quot;)(.*?)(?:"|&quot;)')

_component_roots: dict[str, dict] | None = None


def _describe_component(component) -> dict | None:
    """Render one component with no props and name its root element."""
    import asyncio
    import html as html_module

    try:
        markup = str(asyncio.run(component.acall()))
    except Exception:
        # Needs props, or does not render standalone. Unknown is the safe answer.
        return None
    match = _ROOT_TAG_RE.match(markup)
    if match is None:
        return None
    root, attrs_text = match.group(1), match.group(2)
    if root.startswith("x-"):
        # A composition component whose root is another component: the compiler
        # inserts a `display: contents` host, so resolving the chain would mean
        # reasoning about a box that lays out as if it were not there.
        return None
    classes = ""
    class_match = _CLASS_ATTR_RE.search(attrs_text)
    if class_match is not None:
        literal = _TWMERGE_LITERAL_RE.search(class_match.group(1))
        raw = html_module.unescape(class_match.group(1))
        classes = html_module.unescape(literal.group(1)) if literal else ("" if "{" in raw else raw)
    return {"root": root, "classes": classes}


def _load_component_roots() -> dict[str, dict]:
    """Map every `x-*` tag to the element it renders. `{}` if unavailable."""
    import importlib
    import json
    import sys
    from pathlib import Path

    settings_dir = Path(__file__).resolve().parent
    project_root = settings_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        entries = json.loads((settings_dir / "component-map.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}

    roots: dict[str, dict] = {}
    for entry in entries:
        name = str(entry.get("componentName") or "")
        route = str(entry.get("importRoute") or "")
        if not name or not route:
            continue
        try:
            component = getattr(importlib.import_module(route), name, None)
        except Exception:
            continue
        if component is None or not hasattr(component, "acall"):
            continue
        info = _describe_component(component)
        if info is None:
            continue
        tag = "x-" + re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
        # Two components claiming one tag resolve by import order; unknown is safer.
        if tag in roots and roots[tag] != info:
            roots[tag] = {}
            continue
        roots[tag] = info
    return roots


def component_root(tag: str) -> dict:
    """The rendered root of an `x-*` tag: `{"root": ..., "classes": ...}`."""
    global _component_roots
    if _component_roots is None:
        try:
            _component_roots = _load_component_roots()
        except Exception:
            _component_roots = {}
    return _component_roots.get(tag) or {}


def resolve_tag(tag: str) -> str:
    """The HTML tag an element behaves as. Non-components are themselves."""
    if not tag.startswith("x-"):
        return tag
    return str(component_root(tag).get("root") or "")


# ---------------------------------------------------------------------------
# Seeing through `{{ attributes }}`
#
# Caspian's props contract forwards a root's attributes as one Jinja value:
# `<div {{ attributes }}>`. An HTML parser sees an attribute named
# `{{attributes}}` and no class at all, so the element's display is invisible --
# which is what froze the last few blocks.
#
# The value is built in the same Python file, by the two documented helpers, so
# an AST walk can recover it. Only a *fully literal* class is accepted:
# `merge_classes("a b c")`. The moment a props-derived value is merged in
# (`merge_classes(base, incoming_class)`) the answer is refused, because the
# call site's class wins at runtime through `twMerge` and the call site is in
# another file.
# ---------------------------------------------------------------------------

_MAX_RESOLVE_DEPTH = 6


def _call_name(node) -> str:
    func = node.func
    return getattr(func, "id", None) or getattr(func, "attr", None) or ""


def _literal_classes(node, assigned: dict, depth: int = 0) -> str | None:
    """The class list a node evaluates to, or None when it is not fully literal."""
    import ast

    if depth > _MAX_RESOLVE_DEPTH:
        return None
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        values = assigned.get(node.id)
        # Reassigned under a branch: which value reaches the template is a
        # runtime decision.
        if not values or len(values) != 1:
            return None
        return _literal_classes(values[0], assigned, depth + 1)
    if isinstance(node, ast.Call):
        name = _call_name(node)
        if name == "merge_classes":
            if node.keywords:
                return None
            parts = []
            for arg in node.args:
                value = _literal_classes(arg, assigned, depth + 1)
                if value is None:
                    return None
                parts.append(value)
            return " ".join(parts)
        if name == "get_attributes":
            if not node.args or not isinstance(node.args[0], ast.Dict):
                return None
            for key, value in zip(node.args[0].keys, node.args[0].values):
                if isinstance(key, ast.Constant) and key.value == "class":
                    return _literal_classes(value, assigned, depth + 1)
            return ""  # a forwarded attribute set with no class of its own
    return None


# A component script may also hold a class list behind a helper:
# `class="{getIndicatorIconClass()}"`. Only the simplest possible shape is
# accepted -- `const name = () => "literal";` -- because it takes no arguments,
# closes over nothing and has a single string body, so the attribute's value is
# that literal on every render. A helper with parameters or a block body is a
# runtime decision and stays unknown.
_SCRIPT_CLASS_FN = re.compile(
    r"""(?<![\w$])const\s+([A-Za-z_$][\w$]*)\s*=\s*\(\s*\)\s*=>\s*(['"])(.*?)\2""",
    re.S,
)
# Any other binding of that name means the arrow is not the whole story.
_SCRIPT_ANY_BINDING = r"(?<![\w$])(?:const|let|var|function)\s+{name}(?![\w$])"


def script_class_literals(source: str) -> dict[str, str]:
    """Map `{name()}` class expressions to the literal they always return."""
    found: dict[str, str] = {}
    for name, _, literal in _SCRIPT_CLASS_FN.findall(source):
        bindings = re.findall(_SCRIPT_ANY_BINDING.format(name=re.escape(name)), source)
        if len(bindings) != 1:
            found.pop(name, None)
            continue
        found[name] = literal
    return {"{" + name + "()}": literal for name, literal in found.items()}


def class_hints(python_source: str) -> dict[str, str]:
    """Every class list this file hides behind an expression.

    Keyed by the attribute text the markup actually carries: `{{attributes}}`
    for a forwarded Jinja value, `{helper()}` for a script helper.
    """
    hints = jinja_attr_classes(python_source)
    hints.update(script_class_literals(python_source))
    return hints


def jinja_attr_classes(python_source: str) -> dict[str, str]:
    """Map each `{{ name }}` attribute variable to the class list it carries."""
    import ast

    try:
        tree = ast.parse(python_source)
    except SyntaxError:
        return {}

    assigned: dict[str, list] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)

    resolved: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "html":
            continue
        for keyword in node.keywords:
            if not keyword.arg:
                continue
            classes = _literal_classes(keyword.value, assigned)
            if classes is not None:
                resolved["{{" + keyword.arg.lower() + "}}"] = classes
    return resolved


# Every token that can set an element's display. A component's base classes are
# merged with whatever the call site passes, and `twMerge` lets the call site
# win -- so `<x-button class="inline">` really is inline despite the component's
# `inline-flex` base.
_DISPLAY_TOKENS = (
    FLEX_DISPLAY_CLASSES
    | BLOCK_LEVEL_CLASSES
    | BLOCK_CONTAINER_CLASSES
    | {HIDDEN_CLASS, INLINE_CLASS, CONTENTS_CLASS}
)


# Class-like words in an attribute value, including the ones inside a
# PulsePoint expression such as `{compact ? 'flex' : 'block'}`. Quotes and
# punctuation are not part of a word, so `'flex'` yields `flex` while the
# flex-grow utility `flex-1` stays `flex-1`.
_CLASS_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_/-]*(?::[A-Za-z0-9_/-]+)*")


def _may_override_display(usage_class: str | None) -> bool:
    """Whether a call site's class attribute could change the rendered display.

    The value may be a PulsePoint expression rather than a plain class list, so
    every class-like word in it is checked, variant prefix stripped: `sm:flex`
    could override at that breakpoint, `flex-1` is flex-grow and cannot. If no
    word can set a display, the call site provably cannot override the
    component's own; if one can, the answer is unknown.
    """
    if not usage_class:
        return False
    for word in _CLASS_WORD.findall(usage_class):
        if word.rsplit(":", 1)[-1] in _DISPLAY_TOKENS:
            return True
    return False


def _preserves_whitespace(class_value: str | None) -> bool:
    """Whether a class list turns off whitespace collapsing.

    Every rule here assumes collapsible text. Under `white-space: pre` a run of
    spaces renders literally, and even a whitespace-only flex item is drawn, so
    an element carrying one of these utilities has to fall back to knowing
    nothing about its children.
    """
    if not class_value:
        return False
    return any(token in PRE_WHITESPACE_CLASSES for token in class_value.split())


def _as_child_state(attr_map: dict[str, str | None]) -> str:
    """`"yes"` / `"no"` / `"unknown"` for a tag's as-child attribute."""
    for name in AS_CHILD_ATTRS:
        if name not in attr_map:
            continue
        value = (attr_map[name] or "").strip().lower()
        if "{" in value:
            # A runtime expression: the component may or may not be transparent,
            # and guessing either way could drop whitespace that renders.
            return "unknown"
        return "yes" if value in _TRUTHY_AS_CHILD else "no"
    return "no"


class _Frame:
    """One open element, reduced to how it treats its children's whitespace.

    ``collapses`` -- a text child's edge whitespace cannot render.
    ``drops_ws``  -- a child made only of whitespace cannot render at all.
    ``transparent`` -- the element owns no box (`as-child`); defer to the
    nearest ancestor that does.
    ``opaque``    -- nothing is known; every rule must stay conservative.
    """

    __slots__ = (
        "tag",
        "collapses",
        "drops_ws",
        "block_level",
        "flex_container",
        "transparent",
        "opaque",
    )

    def __init__(
        self,
        tag: str,
        attrs: tuple,
        in_flex_parent: bool = False,
        jinja_classes: dict | None = None,
    ) -> None:
        self.tag = tag
        attr_map = dict(attrs)
        state = _as_child_state(attr_map)
        self.transparent = state == "yes"
        self.opaque = state == "unknown"
        self.block_level = False
        self.flex_container = False
        if self.transparent or self.opaque:
            self.collapses = self.drops_ws = False
            return

        # A component behaves as the element it renders, plus that element's
        # own classes; an ordinary tag is simply itself.
        html_tag = tag
        classes = attr_map.get("class") or ""
        if classes and jinja_classes:
            # `class="{helper()}"` -- a helper with a single literal body.
            classes = jinja_classes.get(classes, classes)
        if not classes and jinja_classes:
            # `<div {{ attributes }}>` -- the class is behind a forwarded value.
            for name in attr_map:
                if name in jinja_classes:
                    classes = jinja_classes[name]
                    break
        if tag.startswith("x-"):
            html_tag = resolve_tag(tag)
            if _may_override_display(classes):
                # The call site could win the display over the component's base
                # classes, and which one wins is a runtime `twMerge` decision.
                self.collapses = self.drops_ws = False
                return
            classes = str(component_root(tag).get("classes") or "")

        class_tokens = set(classes.split())
        if CONTENTS_CLASS in class_tokens:
            # No box of its own: the children belong to the parent's context.
            self.transparent = True
            self.collapses = self.drops_ws = False
            return
        if not html_tag or _preserves_whitespace(classes) or INLINE_CLASS in class_tokens:
            self.collapses = self.drops_ws = False
            return

        flex = bool(class_tokens & FLEX_DISPLAY_CLASSES)
        self.flex_container = flex
        self.drops_ws = flex or html_tag in WS_DROPPING_TAGS or html_tag in VOID_TAGS
        self.collapses = (
            flex
            or self.drops_ws
            or html_tag in BLOCK_TAGS
            or html_tag in CONTENT_BOX_TAGS
            or bool(class_tokens & BLOCK_CONTAINER_CLASSES)
        )
        # An element's own display utility outranks its tag's default: a
        # `<label class="block">` is a block-level box, a `<div class="inline">`
        # is not one any more.
        if HIDDEN_CLASS in class_tokens:
            self.block_level = False
            return
        if in_flex_parent:
            # A flex or grid item is blockified: its computed display becomes
            # the block-level equivalent whatever the element's default was
            # (CSS Display 2.7). So an inline `<label>` inside a grid really is
            # a block box, and the whitespace at its edges collapses.
            self.block_level = True
            self.collapses = True
            return
        self.block_level = bool(class_tokens & BLOCK_LEVEL_CLASSES) or (
            html_tag in BLOCK_TAGS
            and not (class_tokens & BLOCK_CONTAINER_CLASSES - BLOCK_LEVEL_CLASSES)
        )


class _Tokens(HTMLParser):
    """Reduce markup to a token stream where equality implies equal rendering."""

    def __init__(self, jinja_classes: dict | None = None) -> None:
        super().__init__(convert_charrefs=False)
        self.jinja_classes = jinja_classes or {}
        self.out: list[tuple] = []
        self._open: list[_Frame] = []
        self._raw_stack: list[str] = []
        self._raw_buf: list[str] = []

    def _in_raw(self) -> str | None:
        return self._raw_stack[-1] if self._raw_stack else None

    def _parent_is_flex(self) -> bool:
        """Whether the element about to open becomes a flex or grid item."""
        frame = self._context()
        return frame is not None and frame.flex_container

    def _context(self) -> "_Frame | None":
        """The nearest open element that actually owns a box.

        A transparent element (`as-child`) renders its child in its own place,
        so whitespace written inside it belongs to whichever ancestor lays the
        child out. An opaque one stops the walk with nothing known.
        """
        for frame in reversed(self._open):
            if frame.transparent:
                continue
            return frame
        return None

    def _attrs(self, attrs) -> tuple:
        return tuple(sorted((k, _canon_attr_value(v)) for k, v in attrs))

    def handle_starttag(self, tag, attrs):
        if self._in_raw():
            self._raw_buf.append(self.get_starttag_text() or "")
            return
        if tag in LITERAL_TAGS | CODE_TAGS:
            self._raw_stack.append(tag)
            self._raw_buf = []
        attrs_tuple = self._attrs(attrs)
        frame = _Frame(tag, attrs_tuple, self._parent_is_flex(), self.jinja_classes)
        self.out.append(("start", tag, attrs_tuple, frame.block_level))
        self._open.append(frame)

    def handle_startendtag(self, tag, attrs):
        if self._in_raw():
            self._raw_buf.append(self.get_starttag_text() or "")
            return
        attrs_tuple = self._attrs(attrs)
        frame = _Frame(tag, attrs_tuple, self._parent_is_flex(), self.jinja_classes)
        self.out.append(("start", tag, attrs_tuple, frame.block_level))
        self.out.append(("end", tag, frame.block_level))

    def handle_endtag(self, tag):
        raw = self._in_raw()
        if raw:
            if tag != raw:
                self._raw_buf.append(f"</{tag}>")
                return
            body = "".join(self._raw_buf)
            if raw in CODE_TAGS:
                # Code: indentation and blank lines carry no meaning.
                body = "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())
            self.out.append(("raw", raw, body))
            self._raw_stack.pop()
            self._raw_buf = []
        closing = next((f for f in reversed(self._open) if f.tag == tag), None)
        self.out.append(("end", tag, closing.block_level if closing else False))
        if any(frame.tag == tag for frame in self._open):
            while self._open and self._open.pop().tag != tag:
                pass

    def handle_data(self, data):
        if self._in_raw():
            self._raw_buf.append(data)
            return
        collapsed = re.sub(r"\s+", " ", _canon_jinja(data))
        if collapsed == "":
            return
        frame = self._context()
        parent = frame.tag if frame is not None else ""
        if collapsed.strip() == "":
            # A pure-whitespace node. Inside a flex or grid container it becomes
            # an anonymous item holding only white space, which is never
            # rendered; anywhere else its presence can separate two inline
            # elements, so it is kept as a token whose length is irrelevant.
            if frame is not None and frame.drops_ws:
                return
            self.out.append(("ws", frame is not None and frame.collapses))
            return
        collapses = frame is not None and frame.collapses
        self.out.append(
            (
                "text",
                collapsed.strip(),
                collapsed[0].isspace() and not collapses,
                collapsed[-1].isspace() and not collapses,
                parent,
            )
        )

    def handle_comment(self, data):
        if self._in_raw():
            self._raw_buf.append(f"<!--{data}-->")
            return
        self.out.append(("comment", re.sub(r"\s+", " ", data).strip()))

    def handle_entityref(self, name):
        if self._in_raw():
            self._raw_buf.append(f"&{name};")
        else:
            self.out.append(("entity", name))

    def handle_charref(self, name):
        if self._in_raw():
            self._raw_buf.append(f"&#{name};")
        else:
            self.out.append(("charref", name))

    def handle_decl(self, decl):
        self.out.append(("decl", decl))


def _is_block_boundary(token: tuple | None) -> bool:
    """Whether whitespace touching this token collapses.

    Only a genuinely block-level box qualifies. An inline-block (`<button>`) or
    an inline replaced element (`<svg>`) does not: two of them separated by a
    newline really do render a space between them.
    """
    if token is None:
        return True  # the fragment's own edge
    if token[0] in ("start", "end"):
        return bool(token[-1])
    return False


def _drop_insignificant_ws(tokens: list[tuple]) -> list[tuple]:
    """Remove whitespace nodes that provably cannot render."""
    out: list[tuple] = []
    for i, tok in enumerate(tokens):
        if tok[0] != "ws":
            out.append(tok)
            continue
        prev = out[-1] if out else None
        nxt = next((t for t in tokens[i + 1 :] if t[0] != "ws"), None)
        if _is_block_boundary(prev) and _is_block_boundary(nxt):
            continue
        # Whitespace at the first or last position inside a container that lays
        # its content out as a block: a leading space is removed at the start of
        # the first line box, a trailing one at the end of the last.
        at_open = prev is not None and prev[0] == "start"
        at_close = nxt is not None and nxt[0] == "end"
        if tok[1] and (at_open or at_close):
            continue
        out.append(("ws",))
    return out


def _canon_text_edges(tokens: list[tuple]) -> list[tuple]:
    """Drop edge-whitespace flags that provably cannot render.

    Three separate reasons a text node's edge whitespace collapses:

    * its parent lays its content out as a block -- `<h1>\n  Title\n</h1>`
      is `<h1>Title</h1>`, because whitespace at the edge of a block container
      always collapses;
    * the neighbour on that side is a block-level box -- whitespace next to one
      is removed, even inside an inline parent;
    * both, which is the common case.

    Inside a `<span>` between two inline siblings none of that applies, and the
    flags survive to be reported as a difference.
    """
    out: list[tuple] = []
    for i, tok in enumerate(tokens):
        if tok[0] != "text":
            out.append(tok)
            continue
        _, body, lead, trail, parent = tok
        if parent in BLOCK_TAGS:
            lead = trail = False
        if lead and _is_block_boundary(out[-1] if out else None):
            lead = False
        if trail and _is_block_boundary(tokens[i + 1] if i + 1 < len(tokens) else None):
            trail = False
        out.append(("text", body, lead, trail, parent))
    return out


def _squeeze_jinja(markup: str) -> str:
    """Collapse padding inside Jinja delimiters before the HTML parser runs.

    A Jinja tag can sit in attribute position -- `<div {{attributes}}>` is how a
    component forwards props onto its root. djLint renders that as
    `<div {{ attributes }}>`, which is the same template but which an HTML parser
    reads as three attributes instead of one. Squeezing both sides first means
    the comparison sees the Jinja tag, not the parser's guess at it.
    """

    def sub(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return "{{" + re.sub(r"\s+", " ", m.group(1)) + "}}"
        return "{%" + re.sub(r"\s+", " ", m.group(2)) + "%}"

    return JINJA.sub(sub, markup)


def tokenize(markup: str, jinja_classes: dict | None = None) -> list[tuple] | None:
    parser = _Tokens(jinja_classes)
    try:
        parser.feed(_squeeze_jinja(markup))
        parser.close()
    except Exception:
        return None
    return _canon_text_edges(_drop_insignificant_ws(parser.out))


def equivalent(before: str, after: str, jinja_classes: dict | None = None) -> tuple[bool, str]:
    """True when `after` is guaranteed to render exactly like `before`.

    `jinja_classes` maps `{{name}}` attribute variables to the class list they
    forward, from `jinja_attr_classes` on the owning Python file. Without it a
    `<div {{ attributes }}>` simply has an unknown display, as before.

    The second element is a short explanation of the first difference, for the
    skip report.
    """
    ta, tb = tokenize(before, jinja_classes), tokenize(after, jinja_classes)
    if ta is None or tb is None:
        return False, "markup could not be parsed"
    if ta == tb:
        return True, ""
    for x, y in zip(ta, tb):
        if x != y:
            return False, _diff_reason(x, y)
    extra = ta[len(tb) :] or tb[len(ta) :]
    side = "would remove" if len(ta) > len(tb) else "would add"
    return False, f"{side} {_describe(extra[0]) if extra else 'content'}"


def _diff_reason(x: tuple, y: tuple) -> str:
    """Explain one token difference in terms an author can act on."""
    if x[0] == "text" and y[0] == "text" and x[1] == y[1]:
        return (
            f"would trim whitespace around {_clip(x[1])} inside <{x[4] or '?'}>, "
            f"whose display is not known to be block-level"
        )
    if x[0] == "start" and y[0] == "start" and x[1] == y[1]:
        before, after = dict(x[2]), dict(y[2])
        names = sorted(set(before) | set(after))
        for name in names:
            if before.get(name) != after.get(name):
                if name not in after:
                    return f"would drop attribute {name!r} on <{x[1]}>"
                if name not in before:
                    return f"would add attribute {name!r} on <{x[1]}>"
                return f"would change attribute {name!r} on <{x[1]}>"
        return f"attributes on <{x[1]}> would change"
    if x == ("ws",):
        return f"would remove whitespace before {_describe(y)}"
    if y == ("ws",):
        return f"would add whitespace before {_describe(x)}"
    if x[0] == "raw" and y[0] == "raw":
        return f"<{x[1]}> body would change"
    return f"{_describe(x)} would become {_describe(y)}"


def _clip(text: str, limit: int = 40) -> str:
    return repr(text if len(text) <= limit else text[:limit] + "…")


def _describe(token: tuple) -> str:
    kind = token[0]
    if kind == "start":
        return f"<{token[1]}>"
    if kind == "end":
        return f"</{token[1]}>"
    if kind == "text":
        return f"text {_clip(token[1])}"
    if kind == "ws":
        return "whitespace"
    if kind == "raw":
        return f"<{token[1]}> body"
    if kind == "comment":
        return "comment"
    return kind
