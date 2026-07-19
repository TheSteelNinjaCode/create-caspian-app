# App tests & quality gate

Type check + lint + tests for the **application** code (`main.py`, `src/**`) —
not the Caspian framework under `.venv/` or `node_modules/`.

## The command

```bash
npm run check
```

That is the single production gate. It runs **pyrefly** (types), **ruff**
(lint), and **pytest** (tests) in one pass, prints every problem as
`path:line:col  [tool:code] message`, and exits non-zero on failure — so CI,
a pre-commit hook, or an agent is told exactly which file and location to fix.

While debugging you can narrow to one tool:

```bash
uv run python settings/check.py --only pyrefly   # or ruff / pytest
```

## Auto-fixing lint issues

`npm run check` only **reports**. To auto-fix the ruff findings it lists, run:

```bash
npm run check:fix
```

That runs `ruff check . --fix` (safely fixes most lint issues — unused
variables, redundant code, etc.) and then re-runs the full gate so you see
what's left. Type errors (pyrefly) and failing tests (pytest) are never
auto-fixed — fix those at the reported `path:line:col`.

### One deliberate exception: unused imports (F401) are never auto-deleted

`--fix` will **not** remove "unused" imports, because in this app that check is
unreliable. Caspian single-file components import their children and then use
them only as `<x-*>` tags inside `html(...)`/`render_html(...)` template strings
(e.g. `from .Dialog import DialogContent` → `<x-dialog-content>`). Ruff can't
parse the template, so it sees the import as unused — but casp resolves the tag
from the module's globals at render time, so deleting it breaks the page.

`F401` is marked `unfixable` in `pyproject.toml`, so `--fix` reports these
imports but never strips them. `settings/check.py` then suppresses the F401s
whose symbol is actually used as an `<x-*>` tag, so **the gate fails only on
genuinely dead imports**. When `npm run check` reports an F401, remove that
import **by hand** — first confirm it is not used as an `<x-*>` tag in the same
file.

## Tools (Python dev group in `pyproject.toml`)

- **pyrefly** — type checker. Config in `[tool.pyrefly]`; checks `main.py` and `src/**`.
- **ruff** — linter. Config in `[tool.ruff]`; correctness-focused rules.
- **pytest** — test runner. Tests live in `tests/`.

Install/refresh them with `uv sync --group dev`.
