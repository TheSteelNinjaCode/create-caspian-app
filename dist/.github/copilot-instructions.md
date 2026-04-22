# Copilot Instructions

- Read `AGENTS.md` before working in `main.py`, `src/lib/**`, `.venv/Lib/site-packages/casp/**`, `public/js/**`, `prisma/**`, or `node_modules/caspian-utils/dist/docs/**`.
- Keep all repo-level Copilot guidance in this file. Do not add `.github/instructions/` for this workspace.

## Global Rules

- Use this decision order: `caspian.config.json` for optional feature enablement, app runtime and app-owned code for current project behavior, installed `casp` runtime for framework internals, and packaged markdown docs for Caspian feature discovery and task routing.
- As the app grows, prefer `src/components/` for reusable application UI and reserve `src/lib/` for reusable non-UI code such as services, validators, adapters, and shared helpers.
- Read `./caspian.config.json` almost immediately before making feature, tooling, scaffolding, or file-placement decisions. Treat it as the workspace feature gate for flags such as `backendOnly`, `tailwindcss`, `mcp`, `prisma`, `typescript`, and `componentScanDirs`.
- Treat `caspian.config.json` as the single source of truth for whether optional Caspian features are enabled in the current workspace. Use feature-specific docs, files, and commands only after the matching flag is confirmed as enabled.
- If a feature is disabled and the user wants it, ask whether they want to enable it first, then update `caspian.config.json` and follow `npx casp update project` so framework-managed files align with the new feature set.
- Treat `node_modules/caspian-utils/dist/docs/**` as packaged Caspian docs that teach AI how Caspian features work and where to look next. Their presence does not mean the feature is enabled in the current project.
- For current repo behavior, trust `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, and `src/app/**` over generic Caspian docs.
- For framework internals, trust `.venv/Lib/site-packages/casp/**` over generic or older upstream guidance.
- When packaged docs conflict with project code or installed runtime, the project code, `caspian.config.json`, and installed runtime win. Keep the packaged docs feature-oriented and point AI back to the project files that decide actual enablement and behavior.
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

- These files are the packaged Caspian documentation layer, not the runtime and not the source of current workspace state.
- Use them to help AI answer three questions: which Caspian feature applies, which project files should be inspected next, and which workflow is appropriate once the feature is confirmed as enabled.
- Verify behavior claims in this order:
  1.  `caspian.config.json`, then `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, `src/app/**`
  2.  `.venv/Lib/site-packages/casp/**`
  3.  the markdown file being edited
- Do not encode the current project's feature flags, file inventory, script list, or temporary status inside the packaged docs. Keep those facts in `.github/copilot-instructions.md`, `AGENTS.md`, or the project code.
- When an optional feature doc is edited, phrase it as feature guidance, for example `when caspian.config.json has mcp: true`, instead of as a project snapshot such as `this workspace has mcp: false`.
- Keep `index.md` discoverable as the manifest, keep cross-links aligned, and make each feature page explicit about when it applies and what file AI should inspect next.
