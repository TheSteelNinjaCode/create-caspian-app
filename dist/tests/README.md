# App tests & quality gate

Type check + lint + tests for the **application** code (`main.py`, `src/**`) —
not the Caspian framework under `.venv/` or `node_modules/`.

## The command

```bash
npm run check
```

That is the single production gate. It runs **pyright** (types), **ruff**
(lint), and **pytest** (tests) in one pass, prints every problem as
`path:line:col  [tool:code] message`, and exits non-zero on failure — so CI,
a pre-commit hook, or an agent is told exactly which file and location to fix.

While debugging you can narrow to one tool:

```bash
uv run python settings/check.py --only pyright   # or ruff / pytest
```

## Auto-fixing lint issues

`npm run check` only **reports**. To auto-fix the ruff findings it lists, run:

```bash
npm run check:fix
```

That runs `settings/fix.py` (safely fixes lint issues — dead imports, redundant
code, etc.) and then re-runs the full gate so you see what's left. Type errors
(pyright) and failing tests (pytest) are never auto-fixed — fix those at the
reported `path:line:col`.

### How unused-import (F401) removal stays safe

Removing "unused" imports is the one fix that is dangerous in this app. Caspian
single-file components import their children and then use them only as `<x-*>`
tags inside `html(...)`/`render_html(...)` template strings (e.g. `from .Dialog
import DialogContent` → `<x-dialog-content>`). Ruff can't parse the template, so
it sees the import as unused — but casp resolves the tag from the module's
globals at render time, so deleting it breaks the page.

Two layers keep this safe, so `check:fix` still cleans real dead imports:

- **A raw `ruff check --fix` never deletes any import.** `F401` is marked
  `unfixable` in `pyproject.toml`, so even if someone runs ruff directly, no
  component import is ever stripped.
- **`npm run check:fix` removes only genuinely dead imports.** `settings/fix.py`
  asks ruff which files have an `F401`, skips any file that contains an import
  used as an `<x-*>` tag (leaving those whole), and removes dead imports from the
  rest via an isolated ruff run. Component-guarded files are left for the gate to
  report, so you decide by hand there.

`settings/check.py` also suppresses the `F401` *reports* whose symbol is used as
an `<x-*>` tag, so **the gate fails only on genuinely dead imports**. The
`<x-*>`-tag detection is shared between the fixer and the gate in
`settings/_component_imports.py`.

## Tools (Python dev group in `pyproject.toml`)

- **pyright** — type checker. Config in `[tool.pyright]`: `include = ["main.py", "src", "settings/*.py"]` with `exclude = [".venv", "node_modules", "**/__pycache__"]`, so it checks `main.py`, all of `src` (including the generated `src/lib/prisma/**` ORM), and the top-level `settings/*.py` tooling scripts (mirroring ruff's `include`). Pylance reads the same config, so the IDE and `npm run check` agree.
- **ruff** — linter. Config in `[tool.ruff]`; correctness-focused rules.
- **pytest** — test runner. Tests live in `tests/`.

Install/refresh them with `uv sync --group dev`.
