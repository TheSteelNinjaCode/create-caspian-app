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

# Whitespace touching one of these collapses away. A custom `<x-*>` tag is
# deliberately absent: its display is set by CSS the formatter cannot see, so it
# is treated as inline and its surrounding whitespace is significant.
# fmt: off
BLOCK_TAGS = {
    "html", "head", "body", "div", "p", "section", "article", "header",
    "footer", "nav", "aside", "main", "form", "fieldset", "legend", "figure",
    "figcaption", "blockquote", "hr", "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup",
    "col", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "details", "summary",
    "dialog", "script", "style", "template", "option", "optgroup", "select",
    "textarea", "video", "audio", "source", "track", "canvas", "iframe",
    "meta", "link", "title", "address", "hgroup", "menu", "search", "noscript",
    "br",
    # SVG. Inside an SVG fragment, whitespace between elements is never laid out
    # as text, so indenting the children of an inline <svg> cannot change what is
    # drawn. `<text>`, `<tspan>` and `<textPath>` are deliberately excluded --
    # they do render their content -- as is `<foreignObject>`, whose children are
    # HTML again and follow HTML rules.
    "svg", "g", "defs", "symbol", "use", "path", "circle", "ellipse", "line",
    "polyline", "polygon", "rect", "clippath", "lineargradient",
    "radialgradient", "stop", "mask", "pattern", "filter", "marker", "desc",
    "animate", "animatetransform", "animatemotion", "switch", "image",
}
# fmt: on

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


class _Tokens(HTMLParser):
    """Reduce markup to a token stream where equality implies equal rendering."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: list[tuple] = []
        self._open: list[str] = []
        self._raw_stack: list[str] = []
        self._raw_buf: list[str] = []

    def _in_raw(self) -> str | None:
        return self._raw_stack[-1] if self._raw_stack else None

    def _attrs(self, attrs) -> tuple:
        return tuple(sorted((k, _canon_attr_value(v)) for k, v in attrs))

    def handle_starttag(self, tag, attrs):
        if self._in_raw():
            self._raw_buf.append(self.get_starttag_text() or "")
            return
        if tag in LITERAL_TAGS | CODE_TAGS:
            self._raw_stack.append(tag)
            self._raw_buf = []
        self.out.append(("start", tag, self._attrs(attrs)))
        self._open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if self._in_raw():
            self._raw_buf.append(self.get_starttag_text() or "")
            return
        self.out.append(("start", tag, self._attrs(attrs)))
        self.out.append(("end", tag))

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
        self.out.append(("end", tag))
        if tag in self._open:
            while self._open and self._open.pop() != tag:
                pass

    def handle_data(self, data):
        if self._in_raw():
            self._raw_buf.append(data)
            return
        collapsed = re.sub(r"\s+", " ", _canon_jinja(data))
        if collapsed == "":
            return
        parent = self._open[-1] if self._open else ""
        if collapsed.strip() == "":
            # A pure-whitespace node: its existence can separate two inline
            # elements, so it is kept as a token, but its length is irrelevant.
            self.out.append(("ws",))
            return
        self.out.append(
            (
                "text",
                collapsed.strip(),
                collapsed[0].isspace(),
                collapsed[-1].isspace(),
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
    if token is None:
        return True  # the fragment's own edge
    if token[0] in ("start", "end"):
        return token[1] in BLOCK_TAGS
    return False


def _drop_insignificant_ws(tokens: list[tuple]) -> list[tuple]:
    """Remove whitespace nodes that provably cannot render."""
    out: list[tuple] = []
    for i, tok in enumerate(tokens):
        if tok != ("ws",):
            out.append(tok)
            continue
        prev = out[-1] if out else None
        nxt = next((t for t in tokens[i + 1 :] if t != ("ws",)), None)
        if _is_block_boundary(prev) and _is_block_boundary(nxt):
            continue
        out.append(tok)
    return out


def _canon_text_edges(tokens: list[tuple]) -> list[tuple]:
    """Drop edge-whitespace flags for text inside a block-level parent.

    `<h1>\\n  Title\\n</h1>` -> `<h1>Title</h1>` cannot change rendering, because
    whitespace at the edges of a block container always collapses. The same trim
    inside a `<span>` or an `<x-*>` tag CAN change rendering (it closes a gap
    against an adjacent inline sibling), so those keep their flags and will be
    reported as a difference.
    """
    out: list[tuple] = []
    for tok in tokens:
        if tok[0] == "text" and tok[4] in BLOCK_TAGS:
            out.append(("text", tok[1], False, False, tok[4]))
        else:
            out.append(tok)
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


def tokenize(markup: str) -> list[tuple] | None:
    parser = _Tokens()
    try:
        parser.feed(_squeeze_jinja(markup))
        parser.close()
    except Exception:
        return None
    return _canon_text_edges(_drop_insignificant_ws(parser.out))


def equivalent(before: str, after: str) -> tuple[bool, str]:
    """True when `after` is guaranteed to render exactly like `before`.

    The second element is a short explanation of the first difference, for the
    skip report.
    """
    ta, tb = tokenize(before), tokenize(after)
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
