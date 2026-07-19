"""Recognize Caspian component imports that are used only as `<x-*>` tags.

A single-file component imports its children (`from .Dialog import
DialogContent`) and then uses them **only** as `<x-dialog-content>` tags inside
an `html(...)` / `render_html(...)` template string. Ruff parses Python, not the
template, so it reports every such import as unused (F401). Those imports are
load-bearing: casp resolves the tag from the module's globals at render time
(`component_decorator._attach_caller_scope`).

Both the quality gate (`check.py`) and the auto-fixer (`fix.py`) use these
helpers so they agree on which F401s are template-driven — the gate must not
fail on them and the fixer must not delete them. The tag name is derived exactly
as the compiler does it: `x-{camel_to_kebab(import_name)}`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# Mirror of casp.string_helpers.camel_to_kebab. Kept in lockstep so the tag we
# look for matches the tag the compiler actually resolves.
def camel_to_kebab(name: str) -> str:
    name = re.sub(r"[\._:]+", "-", str(name))
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()


# Pull the bound local name out of a ruff F401 message such as
# "`.Dialog.DialogContent` imported but unused" -> "DialogContent".
_F401_SYMBOL = re.compile(r"`([^`]+)`")


def f401_bound_name(message: str) -> str | None:
    m = _F401_SYMBOL.search(message)
    if not m:
        return None
    qualified = m.group(1).strip()
    if " as " in qualified:  # aliased import binds the alias
        qualified = qualified.split(" as ")[-1].strip()
    return qualified.split(".")[-1].strip() or None


@lru_cache(maxsize=512)
def _file_source(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def import_used_as_component_tag(path: str, symbol: str) -> bool:
    """True when `symbol` is used as an `<x-...>` component tag in the file."""
    source = _file_source(path)
    if not source:
        return False
    tag = f"x-{camel_to_kebab(symbol)}"
    # Match `<x-dialog-content` on a tag boundary so `x-dialog-content` does not
    # spuriously match `x-dialog-content-extra`.
    pattern = re.compile(r"<" + re.escape(tag) + r"(?=[\s/>])", re.IGNORECASE)
    return bool(pattern.search(source))


def is_component_tag_f401(message: str, path: str) -> bool:
    """True when an F401 finding is an import used as an `<x-*>` tag in the file."""
    symbol = f401_bound_name(message)
    if not symbol:
        return False
    return import_used_as_component_tag(path, symbol)
