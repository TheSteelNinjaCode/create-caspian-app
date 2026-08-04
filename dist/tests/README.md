# App tests & quality gate

Type check + lint + template lint + tests for the **application** code
(`main.py`, `src/**`, and authored markup) — not the Caspian framework under
`.venv/` or `node_modules/`.

## The command

```bash
npm run check
```

That is the single production gate. It runs **pyright** (types), **ruff**
(lint), **templates** (markup lint), and **pytest** (tests) in one pass, prints
every problem as `path:line:col  [tool:code] message`, and exits non-zero on
failure — so CI, a pre-commit hook, or an agent is told exactly which file and
location to fix.

While debugging you can narrow to one tool:

```bash
uv run python settings/check.py --only pyright   # or ruff / templates / pytest
```

## The `templates` check

`settings/check_templates.py` scans `src/**/*.html` and the markup inside
single-file Python components for JSX and directives PulsePoint does not have.

PulsePoint borrows React's hook API inside `<script>` and React's component
decomposition — never React's markup syntax. Before this check existed, the
whole `.html` surface was unvalidated, and two failures shipped repeatedly:

- `{users.map(user => (<tr/>))}` renders one literal row plus stray text.
- `class={...}` (unquoted) is **invalid HTML** — the parser shreds the element,
  the component root never compiles, and the route serves a blank page with *no
  console error at all*.

It skips `<script>`, `<pre>`/`<code>`, and HTML comments, so real component
JavaScript (`rows.map(...)` is correct there) and documentation samples do not
trip it. Run it alone with:

```bash
uv run python settings/check_templates.py
```

Its own coverage lives in `tests/test_check_templates.py`, which asserts both
directions — every JSX shape is caught, and correct markup stays silent — plus a
repo-wide assertion that `src/` is currently clean.

## Browser errors in the dev terminal — and in a file

`npm run dev` forwards PulsePoint's browser-side `[PP-ERROR]` / `[PP-WARN]`
output, uncaught errors, and unhandled rejections into the terminal, so a broken
route is visible without opening DevTools. See the `AGENTS.md` entry for how the
pieces fit (`settings/dev-log-bridge.ts` + `_inject_dev_console_bridge` in
`main.py`). It is development-only: the injecting branch is gated on
`CASPIAN_BROWSER_SYNC_PORT`, which only the dev stack sets.

The same events are appended to `.casp/browser-log.jsonl`, because stdout only
reaches whoever owns that terminal. Read it with:

```bash
npm run logs
```

`npm run check` prints the same digest at the end of its run, but never lets it
change the exit code — whether a route has been exercised depends on someone
opening a browser, and a gate that flaky gets ignored. Use `--fail-on-error` if
you want a non-zero exit in a script you control.

The log records **successful page loads too**, which is what makes it safe to
trust: a route's status is whatever happened during its most recent load, so a
fixed error stops being reported after one clean reload, and an empty log reads
as "nothing observed" rather than "healthy".

A reload only proves what a reload re-runs. Errors are classified by how long
after their page load they arrived: a **mount** error is cleared by a later load,
an **interaction** error (a click handler throwing seconds later) is not — it
carries forward as `NEEDS RECHECK` until you repeat the interaction. Reporting
those as clean is how a live bug gets signed off.

Every source change **compacts** the log to the session header, a `restart`
marker, and the errors still open, so a dev session running for hours cannot grow
an unbounded file. **Don't diagnose from the raw JSONL** — it is history, not
state. `npm run logs` derives the current status and costs the same tokens
regardless of session length. An error with no matching load — a tab left open
across a dev restart — is reported as `UNCONFIRMED` rather than as a fresh
failure. Coverage is in `tests/test_browser_log.py`.

## Auto-fixing lint issues

`npm run check` only **reports**. To auto-fix the ruff findings it lists, run:

```bash
npm run check:fix
```

That runs `settings/fix.py`, which **formats first** (see below), then safely
fixes lint issues (dead imports, redundant code, etc.), then re-runs the full
gate so you see what's left. Type errors (pyright) and failing tests (pytest)
are never auto-fixed — fix those at the reported `path:line:col`.

## Formatting

```bash
npm run format         # write
npm run format:check   # report only; exits 1 if work remains
```

`settings/format.py` formats two surfaces, **markup first, then Python**:

1. **Markup** — the template inside every `html(r"""...""")`, via **djLint**.
2. **Python** — `main.py`, `src/**`, `settings/**`, `tests/**`, via
   `ruff format`, then the `html(` rejoin described below.

The order is load-bearing. Reformatting a template changes how many lines its
string literal spans, which changes how ruff wraps the enclosing `html(...)`
call — so ruff must run last, or a single pass never converges.

### The `html(r"""` opening

The house style keeps the call and its template on one line, with the markup
starting on the next:

```python
    return html(r"""
<div>…</div>
""", name=name)
```

`ruff format` will not produce that. Any call whose first argument is a
multiline string *and* which has other arguments gets exploded — in default and
preview style alike:

```python
    return html(
        r"""
<div>…</div>
""",
        name=name,
    )
```

So `format.py` rejoins the opening after ruff runs. The two steps feed each
other — rejoining the opening lets ruff also pull the closing `)` up on a
sole-argument call — so the pair is iterated to a fixed point. That is also why
`--check` replays the whole pipeline against a temporary mirror of the tree
instead of calling `ruff format --check`, which would flag every rejoined call
as unformatted.

**Running `ruff format` on its own (or on IDE save) will re-split these.**
`npm run format` puts them back.

### Why djLint, and why every block is proved

The markup layers four dialects in one string — HTML, Jinja `{{ }}`/`{% %}`,
PulsePoint `{ }`, and JS in `<script>` — and they nest:

```html
class="... {currentUrl === '{{ item['href'] }}' ? 'a' : 'b'}"
```

Prettier has no Jinja awareness: it de-indents `{% for %}` blocks to column 0
and joins `{% endfor %} {% endfor %}` onto one line. djLint is Jinja-aware and
does not reflow text, so PulsePoint expressions survive.

djLint is still a *general* HTML formatter, so it is never trusted. It will
insert a newline between a block tag and an adjacent inline or `<x-*>` tag,
which renders as a visible space — a custom element's `display` comes from CSS
the formatter cannot see. So each block is formatted and then checked against
`settings/_markup_equivalence.py`, a tokenizer that decides whether the result
is **guaranteed** to render identically. Only proven blocks are written; the
rest are skipped and printed with the reason:

```
skipped — djLint's output could not be proved to render identically:
  src/app/crm/index.py
    8: would trim whitespace around 'Only Active' inside <button>, whose
       display is not known to be block-level
```

**A skip is not a failure.** It means the reformat would have changed rendering,
so the block was left alone. Do not "fix" a skip by loosening the oracle.

`<x-*>` tags are registered with djLint (`--custom-html`), so a component tree
nests instead of sitting flat:

```html
<x-shell>
  <x-brand />
  <x-panel />
</x-shell>
```

That does not weaken the check. The oracle still treats `<x-*>` as *inline*,
because a custom element's display comes from CSS — so indenting tags that were
already on separate lines is accepted (whitespace was there either way), while
separating two tags that were touching is still refused, since that inserts a
rendered space.

SVG elements (`<svg>`, `<path>`, `<g>`, …) count as block-level for a related
reason: an SVG fragment lays out no text, so indenting the children of an inline
`<svg>` in a component template cannot change what is drawn. `<text>`,
`<tspan>`, `<textPath>` and `<foreignObject>` are excluded — they do render
their content.

`<script>`, `<style>`, `<pre>`, and `<textarea>` bodies are masked out before
djLint runs, so code and preformatted text are preserved byte-for-byte by
construction rather than by proof — djLint otherwise reads `/>` inside a JS
regex as a tag delimiter and rewrites `.replace(/>/g, …)`.

Coverage is in `tests/test_format.py`. An oracle that wrongly returns *True* is
the only failure mode that silently corrupts pages, so the tests pin both
directions: transforms that must be recognised as safe, and transforms that must
never be.

### How unused-import (F401) removal stays safe

Removing "unused" imports is the one fix that is dangerous in this app. Caspian
single-file components import their children and then use them only as `<x-*>`
tags inside `html(...)` template strings (e.g. `from .Dialog
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
- **djlint** — markup formatter, driven by `settings/format.py`. Invoked with explicit flags (`--profile jinja --indent 2 --max-line-length 120 --preserve-blank-lines`) rather than a `[tool.djlint]` config block, because blocks are formatted in a temp directory outside the project where that config would not be found.

Install/refresh them with `uv sync --group dev`.
