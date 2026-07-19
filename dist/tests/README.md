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

## Tools (Python dev group in `pyproject.toml`)

- **pyrefly** — type checker. Config in `[tool.pyrefly]`; checks `main.py` and `src/**`.
- **ruff** — linter. Config in `[tool.ruff]`; correctness-focused rules.
- **pytest** — test runner. Tests live in `tests/`.

Install/refresh them with `uv sync --group dev`.
