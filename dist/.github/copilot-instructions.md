# Copilot Instructions

- Read `AGENTS.md` before working in `main.py`, `src/lib/**`, `.venv/Lib/site-packages/casp/**`, `public/js/**`, `prisma/**`, or `node_modules/caspian-utils/dist/docs/**`.
- Keep all repo-level Copilot guidance in this file. Do not add `.github/instructions/` for this workspace.

## Global Rules

- Use this source-of-truth order: app runtime and app-owned code first, installed `casp` runtime second, packaged markdown docs third.
- As the app grows, prefer `src/components/` for reusable application UI and reserve `src/lib/` for reusable non-UI code such as services, validators, adapters, and shared helpers.
- Read `./caspian.config.json` almost immediately before making feature, tooling, scaffolding, or file-placement decisions. Treat it as the workspace feature gate for flags such as `backendOnly`, `tailwindcss`, `mcp`, `prisma`, `typescript`, and `componentScanDirs`.
- Treat `caspian.config.json` as the single source of truth for whether optional Caspian features are enabled in the current workspace. Use feature-specific docs, files, and commands only after the matching flag is confirmed as enabled.
- If a feature is disabled and the user wants it, ask whether they want to enable it first, then update `caspian.config.json` and follow `npx casp update project` so framework-managed files align with the new feature set.
- For current repo behavior, trust `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, and `src/app/**` over generic Caspian docs.
- For framework internals, trust `.venv/Lib/site-packages/casp/**` over generic or older upstream guidance.
- When docs and runtime disagree, align the docs to the code that actually runs in this workspace.
- When `prisma/schema.prisma` changes, follow this order: run `npx prisma migrate dev`; if the change affects seed flow or `prisma/seed.ts`, run `npx prisma generate` and then `npx prisma db seed`; then run `npx ppy generate` so the Python ORM stays aligned with the schema.
- Reuse the existing Python database layer in `src/lib/prisma/**`; do not create a second app-owned database abstraction unless the user explicitly asks for one.
- Treat `src/lib/prisma/__init__.py`, `src/lib/prisma/db.py`, `src/lib/prisma/models.py`, and `settings/prisma-schema.json` as generated outputs owned by `npx ppy generate`; do not create or hand-edit them manually.
- Treat `package.json` scripts as opt-in operations. Do not run `npm run dev`, `npm run build`, or other npm scripts unless the user explicitly asks, the task genuinely requires that exact script, or deployment preparation needs `npm run build`.
- Use `npm run build` for deployment prep or an explicit build request, not as the default validation step for routine route, feature, or documentation edits.
- Let the running dev stack own generated outputs such as `public/css/styles.css`, `settings/component-map.json`, `settings/files-list.json`, `__pycache__/`, and `.pyc` files. Treat those as generated artifacts rather than authored source.
- Never treat `__pycache__/` directories or `.pyc` files as files to edit, regenerate on purpose, or keep in the final diff.
- Treat `settings/component-map.json` and `settings/files-list.json` as generated outputs owned by `settings/component-map.ts` and `settings/files-list.ts`; inspect them when needed, but do not hand-edit them.
- When `caspian.config.json` has `mcp: true`, treat `src/lib/mcp/mcp_server.py` as the app-owned FastMCP server and `src/lib/mcp/fastmcp.json` as the default MCP config. Use `npm run mcp` or `fastmcp run src/lib/mcp/fastmcp.json`; do not assume root `fastmcp.json` auto-discovery.
- Keep auth policy in `src/lib/auth/auth_config.py` and keep auth bootstrap, middleware wiring, and provider registration in `main.py`.
- In app-owned starter config like this workspace, routes start public because `src/lib/auth/auth_config.py` sets `is_all_routes_private=False` by default.
- Decide route privacy in `src/lib/auth/auth_config.py` at app setup time: use `is_all_routes_private=True` when only a few routes should stay public, otherwise keep `is_all_routes_private=False` and list the protected routes in `private_routes`.
- In all-private mode, keep public exceptions in `public_routes`; the runtime defaults keep `/` public and keep `auth_routes=["/signin", "/signup"]` public.
- Do not treat `token_auto_refresh` as the switch that makes routes private. In the current app it only affects sliding-session refresh if `auth.refresh_session()` is called.
- Use PulsePoint and `pp.rpc(...)` as the default frontend and client-to-server contract unless the user requests another stack.
- For file uploads and file-manager flows, keep browser interaction in route templates, keep upload and delete `@rpc()` actions in the owning `src/app/**/index.py`, keep shared storage and persistence helpers in `src/lib/**`, store metadata in Prisma, and store browser-accessible blobs under `public/storage/**`.
- When runtime uploads write into `public/storage/**`, keep `public/storage` in `settings/bs-config.ts` `PUBLIC_IGNORE_DIRS` so `npm run dev` does not reload on each upload.
- For logout flows, prefer `pp.rpc("signout")` backed by `@rpc(require_auth=True)` from page-level or component-level UI. Use a dedicated signout route only for plain form POST, no-JavaScript fallback, or other full-navigation edge cases.
- Protect customized `src/lib/auth/auth_config.py` from updater overwrite by adding `./src/lib/auth/auth_config.py` to `excludeFiles` in `caspian.config.json`.
- Treat `pp-component` on routes, layouts, and components, and `type="text/pp"` on owned PulsePoint scripts, as compiler-injected by the Python side; do not add them manually in authored templates unless the task is explicitly about runtime internals.
- `layout()` is synchronous in the installed runtime. Put async I/O in `page()` or `@rpc()`.
- Dynamic route params currently reach `page()` as a single positional `dict`, with query params injected by name and `request` injected by keyword when declared.
- Do not assume `StateManager` survives across requests unless `request.state.session` is explicitly bridged from `request.session`.
- Route, layout, and component HTML templates must keep a single top-level lowercase HTML element so Caspian can inject `pp-component`. Think React-style single parent wrapper: good one root containing the markup and any owned PulsePoint script, bad sibling top-level tags.

## Path-Specific Rules

### `main.py`

- Treat `main.py` as the repo source of truth for FastAPI setup, static asset routes, auth bootstrap, middleware order, route registration, cache defaults, and error handlers.
- Preserve the effective middleware execution order unless the task explicitly changes request semantics: `SessionMiddleware -> CSRFMiddleware -> AuthMiddleware -> RPCMiddleware`.
- Do not move normal file upload or file-manager behavior into `main.py`; keep those actions in the owning route `index.py` and shared helpers in `src/lib/**`.
- Document route param behavior exactly as implemented here.
- Do not use `main.py` alone to infer whether optional features are enabled; confirm that in `caspian.config.json` first.

### `src/lib/**/*.py`

- Keep `src/lib/` for app-owned shared non-UI code, service wrappers, validators, adapters, and reusable helpers.
- Prefer `src/components/` for reusable rendered UI instead of placing component modules in `src/lib/`.
- Reuse the generated `src/lib/prisma/` package for Python database access, but do not hand-edit files under `src/lib/prisma/`; regenerate them with `npx ppy generate` after schema changes.
- For file managers, keep shared storage, normalization, and Prisma-backed persistence helpers here while route-owned upload and delete `@rpc()` actions stay in `src/app/**/index.py`.
- When `caspian.config.json` has `mcp: true`, keep app-owned MCP tools in `src/lib/mcp/mcp_server.py` and keep the default FastMCP config in `src/lib/mcp/fastmcp.json`. If those locations change, update `settings/restart-mcp.ts` and the MCP docs together.
- Keep auth policy in `src/lib/auth/auth_config.py`. Keep auth bootstrap and middleware order changes in `main.py`.

### `src/components/**/*.py`

- Keep `src/components/` as the default home for reusable application UI components.
- Move shared cards, forms, shells, navigation, and other reusable rendered building blocks here once they are used across routes or features.
- Keep route-owned markup in `src/app/**`, and keep non-UI helpers or services in `src/lib/**`.

### `public/js/main.js`

- Treat `public/js/main.js` as the thin browser bootstrap entry point.
- Keep it minimal and point it at the runtime shipped in `public/js/pp-reactive-v2.js`.
- Do not duplicate PulsePoint runtime logic here.

### `public/js/pp-reactive-v2.js`

- Treat `public/js/pp-reactive-v2.js` as the browser-side PulsePoint runtime source of truth for component execution, refs, directives, SPA navigation, and `pp.rpc(...)` behavior.
- Preserve the current public runtime contract unless the task explicitly changes Caspian frontend behavior.
- At runtime, component logic is discovered from `script[type="text/pp"]` inside `pp-component` roots. In authored route, layout, and component templates, write plain `<script>` and let `main.py` plus `casp.scripts_type.transform_scripts(...)` add the type.

### `src/app/**/*.html`

- Keep route templates and layouts server-rendered first, with PulsePoint enhancement as the default interactive layer.
- Preserve Caspian template syntax such as `[[...]]` in layouts and `pp-*` runtime attributes in rendered HTML.
- Do not author `pp-component="..."` manually in route or layout templates; the Python render pipeline injects it onto the single root element.
- Do not author `type="text/pp"` manually in route or layout templates either. Use plain `<script>` in source and let the render path rewrite it.
- Keep authored route and layout templates to one top-level lowercase HTML root element, the same constraint used for component templates. If a script is needed, keep it inside that root instead of as a sibling top-level node.
- For upload managers and similar interactive lists, prefer `pp.state(...)` plus `pp-for` over manual DOM painting so rerenders keep the list stable.
- Do not assume React, Vue, JSX, HTMX, or another frontend runtime unless the user explicitly requests one.

### `prisma/**`

- Treat `prisma/schema.prisma` as the data-model source of truth.
- Treat `prisma.config.ts` as the datasource and migration or seed configuration source of truth.
- After changing `prisma/schema.prisma`, run `npx prisma migrate dev` first so migrations and the development database stay aligned.
- If the schema change affects seed data or `prisma/seed.ts`, run `npx prisma generate` and then `npx prisma db seed`.
- Run `npx ppy generate` after every schema change so the Python ORM files and `settings/prisma-schema.json` stay aligned with Prisma.
- Keep Node-side generation and seeding aligned with `npx prisma generate` and `prisma/seed.ts`.
- Keep Python-side database access aligned with `src/lib/prisma/**`, and treat that directory as generated output rather than a manual editing surface.

### `.venv/Lib/site-packages/casp/**/*.py`

- Treat these files as framework internals.
- Only change them when the task is explicitly about Caspian core behavior, installed-runtime debugging, or documentation that must match the installed implementation.
- If behavior changes here, update the matching docs under `node_modules/caspian-utils/dist/docs/`.

### `node_modules/caspian-utils/dist/docs/**/*.md`

- These files are the local documentation layer, not the runtime. Verify every behavior claim against the actual code that runs.
- Use this verification order:
  1.  `caspian.config.json`, then `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, `src/app/**`
  2.  `.venv/Lib/site-packages/casp/**`
  3.  the markdown file being edited
- Keep repo-specific facts accurate when they matter:
  - `caspian.config.json` is the first config file to read for enabled workspace features and scan directories
  - `caspian.config.json` is the single source of truth for whether an optional feature is enabled in the current workspace
  - this workspace already has `src/lib/prisma/**`
  - this workspace currently has `mcp: false` in `caspian.config.json`, so do not assume `src/lib/mcp/**`, `settings/restart-mcp.ts`, or `npm run mcp` exist until MCP is explicitly enabled
  - `package.json` currently defines `projectName`, `tailwind`, `tailwind:build`, `browserSync`, `browserSync:build`, `dev`, and `build`
  - if a feature flag is false and the user wants that feature, ask before enabling it, then update `caspian.config.json` and use `npx casp update project` to refresh framework-managed files
  - do not run `package.json` scripts by default for ordinary source edits; only use them when the user explicitly asks, the task requires them, or deployment prep needs `npm run build`
  - `npm run dev` is a long-running local stack command that can regenerate `public/css/styles.css`, `settings/component-map.json`, `settings/files-list.json`, `__pycache__/`, and `.pyc` artifacts; those are generated outputs, not authored source files
  - `node_modules/caspian-utils/dist/docs/file-uploads.md` is the source doc for route-local upload and file-manager guidance in this workspace
  - uploaded public blobs live under `public/storage/**`, and `settings/bs-config.ts` should keep `public/storage` in `PUBLIC_IGNORE_DIRS`
  - `settings/component-map.ts` and `settings/files-list.ts` own `settings/component-map.json` and `settings/files-list.json`; inspect the JSON when needed, but let the framework regenerate it instead of editing it by hand
  - auth policy lives in `src/lib/auth/auth_config.py`
  - the app-owned starter config in this workspace begins public-first with `is_all_routes_private=False`, so treat routes as public by default unless the app explicitly switches to all-private mode
  - choose all-private mode in `src/lib/auth/auth_config.py` only when public routes are the minority; otherwise keep mixed mode and maintain `private_routes`
  - `public_routes` is the exception list for all-private apps, while `auth_routes=["/signin", "/signup"]` stays public by default unless the app explicitly needs different auth endpoints
  - `token_auto_refresh` is not the route-privacy switch in the current app; it only matters when `auth.refresh_session()` is called
  - protect customized `src/lib/auth/auth_config.py` by adding `./src/lib/auth/auth_config.py` to `excludeFiles` in `caspian.config.json`
  - prefer logout via `pp.rpc("signout")` plus `@rpc(require_auth=True)` from page or component UI; use a dedicated signout route only for form-post or no-JavaScript fallbacks
  - PulsePoint runtime lives in `public/js/pp-reactive-v2.js`
  - `pp-component` is injected by the Python render pipeline, and `main.py` rewrites authored body scripts to `type="text/pp"`; authored route, layout, and component templates should not add those attributes manually
  - route, layout, and component templates must keep a single top-level lowercase HTML root for `pp-component` injection, with any owned plain `<script>` kept inside that same root
  - dynamic route params are passed to `page()` as a single positional `dict`
  - `layout()` is sync-only in the installed runtime
  - `StateManager` persistence depends on `request.state.session`, which is not bridged from `request.session` in the current `main.py`
- Keep `index.md` and cross-links aligned when adding or changing pages.
