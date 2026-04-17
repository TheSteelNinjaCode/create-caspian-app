# Copilot Instructions

- Read `AGENTS.md` before working in `main.py`, `src/lib/**`, `.venv/Lib/site-packages/casp/**`, `public/js/**`, `prisma/**`, or `node_modules/caspian-utils/dist/docs/**`.
- Keep all repo-level Copilot guidance in this file. Do not add `.github/instructions/` for this workspace.

## Global Rules

- Use this source-of-truth order: app runtime and app-owned code first, installed `casp` runtime second, packaged markdown docs third.
- For current repo behavior, trust `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, and `src/app/**` over generic Caspian docs.
- For framework internals, trust `.venv/Lib/site-packages/casp/**` over generic or older upstream guidance.
- When docs and runtime disagree, align the docs to the code that actually runs in this workspace.
- Reuse the existing Python database layer in `src/lib/prisma/**`; do not create a second app-owned database abstraction unless the user explicitly asks for one.
- Keep auth policy in `src/lib/auth/auth_config.py` and keep auth bootstrap, middleware wiring, and provider registration in `main.py`.
- Use PulsePoint and `pp.rpc(...)` as the default frontend and client-to-server contract unless the user requests another stack.
- `layout()` is synchronous in the installed runtime. Put async I/O in `page()` or `@rpc()`.
- Dynamic route params currently reach `page()` as a single positional `dict`, with query params injected by name and `request` injected by keyword when declared.
- Do not assume `StateManager` survives across requests unless `request.state.session` is explicitly bridged from `request.session`.

## Path-Specific Rules

### `main.py`

- Treat `main.py` as the repo source of truth for FastAPI setup, static asset routes, auth bootstrap, middleware order, route registration, cache defaults, and error handlers.
- Preserve the effective middleware execution order unless the task explicitly changes request semantics: `SessionMiddleware -> CSRFMiddleware -> AuthMiddleware -> RPCMiddleware`.
- Document route param behavior exactly as implemented here.

### `src/lib/**/*.py`

- Keep `src/lib/` for app-owned shared code, service wrappers, and reusable helpers.
- Reuse and extend the existing `src/lib/prisma/` package for Python database access.
- Keep auth policy in `src/lib/auth/auth_config.py`. Keep auth bootstrap and middleware order changes in `main.py`.

### `public/js/main.js`

- Treat `public/js/main.js` as the thin browser bootstrap entry point.
- Keep it minimal and point it at the runtime shipped in `public/js/pp-reactive-v2.js`.
- Do not duplicate PulsePoint runtime logic here.

### `public/js/pp-reactive-v2.js`

- Treat `public/js/pp-reactive-v2.js` as the browser-side PulsePoint runtime source of truth for component execution, refs, directives, SPA navigation, and `pp.rpc(...)` behavior.
- Preserve the current public runtime contract unless the task explicitly changes Caspian frontend behavior.
- In `pp-component` roots, component logic must live in `script[type="text/pp"]`.

### `src/app/**/*.html`

- Keep route templates and layouts server-rendered first, with PulsePoint enhancement as the default interactive layer.
- Preserve Caspian template syntax such as `[[...]]` in layouts and `pp-*` runtime attributes in rendered HTML.
- Do not assume React, Vue, JSX, HTMX, or another frontend runtime unless the user explicitly requests one.

### `prisma/**`

- Treat `prisma/schema.prisma` as the data-model source of truth.
- Treat `prisma.config.ts` as the datasource and migration or seed configuration source of truth.
- Keep Node-side generation and seeding aligned with `npx prisma generate` and `prisma/seed.ts`.
- Keep Python-side database access aligned with `src/lib/prisma/**`.

### `.venv/Lib/site-packages/casp/**/*.py`

- Treat these files as framework internals.
- Only change them when the task is explicitly about Caspian core behavior, installed-runtime debugging, or documentation that must match the installed implementation.
- If behavior changes here, update the matching docs under `node_modules/caspian-utils/dist/docs/`.

### `node_modules/caspian-utils/dist/docs/**/*.md`

- These files are the local documentation layer, not the runtime. Verify every behavior claim against the actual code that runs.
- Use this verification order:
	1. `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, `src/app/**`
	2. `.venv/Lib/site-packages/casp/**`
	3. the markdown file being edited
- Keep repo-specific facts accurate when they matter:
	- this workspace already has `src/lib/prisma/**`
	- auth policy lives in `src/lib/auth/auth_config.py`
	- PulsePoint runtime lives in `public/js/pp-reactive-v2.js`
	- dynamic route params are passed to `page()` as a single positional `dict`
	- `layout()` is sync-only in the installed runtime
	- `StateManager` persistence depends on `request.state.session`, which is not bridged from `request.session` in the current `main.py`
- Keep `index.md` and cross-links aligned when adding or changing pages.