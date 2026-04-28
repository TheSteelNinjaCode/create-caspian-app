# Caspian Agent Guide

## Purpose

This workspace is a Caspian application plus a packaged copy of the Caspian docs.

When you work here, use `caspian.config.json` and the code that actually runs as the source of truth for this project. Use workspace file instructions under `.github/instructions/**/*.instructions.md` as the task-specific instruction layer when they match the work, and use the packaged markdown docs under `node_modules/caspian-utils/dist/docs/` as the AI-facing Caspian feature and task-reference layer.

Do not treat the existence of a packaged doc as proof that the feature is enabled in this project.

## Decision Order

Use this order depending on the question being answered:

1. Optional feature enablement and generated surface area
   - `caspian.config.json`
2. App runtime and app-owned code for current project behavior
   - `main.py`
   - `src/app/**`
   - `src/lib/**`
   - `public/js/**`
   - `prisma/**`
3. Matching workspace file instructions for task-specific guidance
   - `.github/instructions/**/*.instructions.md`
4. Installed Caspian framework runtime
   - `.venv/Lib/site-packages/casp/**`
5. Packaged Caspian docs for feature discovery, file-placement guidance, and task routing
   - `node_modules/caspian-utils/dist/docs/**`

If the task is about current repo behavior, prefer the app runtime.

If the task is about framework internals, prefer the installed `casp` package.

If packaged docs differ from the project or installed runtime, the project and runtime win. Keep the packaged docs reusable across Caspian projects and move project-specific clarifications into this file or `.github/copilot-instructions.md`.

Before making feature, tooling, or scaffolding decisions, read `caspian.config.json` almost immediately. Treat it as the workspace feature gate for flags such as `backendOnly`, `tailwindcss`, `mcp`, `prisma`, `typescript`, and `componentScanDirs`.

Treat `caspian.config.json` as the single source of truth for whether an optional Caspian feature is enabled in the current workspace. Use feature-specific docs only after the matching flag is confirmed as enabled. If a feature is disabled and the user wants it, ask whether they want to enable it first, then follow the Caspian update workflow to refresh framework-managed files.

When `.github/instructions/**/*.instructions.md` files exist, treat them as workspace-local instructions for specific third-party libraries, component kits, icon systems, integrations, and implementation rules. Read the matching instruction before deciding how to implement work on that surface, but do not let it override `caspian.config.json`, the project code, or the installed runtime.

## BrowserSync URL source of truth

When AI needs to test or confirm whether a page route, exposed function request, proxy-backed response, or local server workflow is working, check `./settings/bs-config.json` first.

Important rules:

- use `./settings/bs-config.json` as the source of truth for the active BrowserSync URLs in this app
- do **not** assume the proxy remains on the default `http://localhost:5090`; if that port is already in use, Caspian may use a different port
- confirm the current `local`, `external`, `ui`, and `uiExternal` values in `./settings/bs-config.json` before suggesting a browser URL, route test URL, or BrowserSync UI URL
- when frontend console logs, network errors, or terminal output suggest the app is being tested through the wrong URL or proxy port, re-check `./settings/bs-config.json` before changing app code

## Workspace Rules

- Local Caspian docs live under `node_modules/caspian-utils/dist/docs/`.
- Workspace file instructions live under `.github/instructions/**/*.instructions.md` when the repo needs task- or library-specific AI guidance that should not be always-on.
- `main.py` is the application entry point and owns auth bootstrap, FastAPI setup, static asset routes, route registration, error handlers, cache defaults, and middleware wiring.
- Middleware is added in this source order: `RPCMiddleware`, `AuthMiddleware`, `CSRFMiddleware`, `SessionMiddleware`.
- Effective request order is therefore: `SessionMiddleware -> CSRFMiddleware -> AuthMiddleware -> RPCMiddleware`.
- App-level auth policy lives in `src/lib/auth/auth_config.py`.
- `main.py` applies auth settings with `configure_auth(build_auth_settings())` and registers `GithubProvider()` plus `GoogleProvider()`.
- In the app-owned starter config used in this workspace, routes start public because `src/lib/auth/auth_config.py` sets `is_all_routes_private=False` by default.
- Choose route privacy mode in `src/lib/auth/auth_config.py` at app setup time: use `is_all_routes_private=True` when most routes should require auth, otherwise keep `is_all_routes_private=False` and list only the protected routes in `private_routes`.
- In all-private mode, treat `public_routes` as the exception list. The runtime defaults keep `/` public and keep `auth_routes=["/signin", "/signup"]` public.
- `token_auto_refresh` does not make routes private in the current app; it only affects sliding-session refresh if `auth.refresh_session()` is called.
- Prefer logout via auth-protected RPC from page-level or component-level UI: `pp.rpc("signout")` backed by `@rpc(require_auth=True)`. Use a dedicated signout route only for plain form POST or no-JavaScript edge cases.
- Use PulsePoint as the default reactive frontend layer for app UI.
- When `caspian.config.json` has `tailwindcss: true`, treat Python `merge_classes(...)` plus browser `twMerge(...)` as the only Tailwind class-merging contract. `merge_classes(...)` emits frontend-ready `{twMerge(...)}` expressions, and authored PulsePoint expressions and scripts may call global `twMerge(...)` directly.
- For CRUD operations and any browser-initiated reads from the backend, use server `@rpc()` actions and client `pp.rpc(...)` calls unless the user explicitly asks for another integration pattern.
- When a single route needs to affect a wrapping layout, have `page()` return `(render_page(__file__, page_context), {"dashboard_body_class": ...})` and consume that value as `[[ layout.dashboard_body_class ]]` in `layout.html`. Use `layout.py` when the same prop should apply across an entire subtree.
- Protect customized `src/lib/auth/auth_config.py` from framework updates by adding `./src/lib/auth/auth_config.py` to `excludeFiles` in `caspian.config.json`.
- This workspace already has an app-owned Python database layer in `src/lib/prisma/`.
- Do not assume `src/lib/mcp/**`, `settings/restart-mcp.ts`, or MCP-related scripts exist unless `caspian.config.json` confirms MCP is enabled and the update workflow has run.
- Treat `package.json` scripts as opt-in operational commands, not default validation steps for ordinary source edits.
- Reuse `src/lib/prisma/prisma`, `PrismaClient`, generated models, and helper types instead of creating a second Python database abstraction.
- Prisma schema source of truth is `prisma/schema.prisma`.
- The schema-change workflow is: `npx prisma migrate dev`; if seed flow or `prisma/seed.ts` is involved, run `npx prisma generate` and then `npx prisma db seed`; then run `npx ppy generate`.
- `npx ppy generate` owns `src/lib/prisma/__init__.py`, `src/lib/prisma/db.py`, `src/lib/prisma/models.py`, and `settings/prisma-schema.json`; do not hand-edit those generated files.
- `caspian.config.json` is the first config file to check for enabled workspace features. Read the actual values instead of inferring them from the docs.
- As the app grows, prefer `src/components/` for reusable rendered UI and `src/lib/` for reusable non-UI support code.
- PulsePoint runtime code is shipped in `public/js/pp-reactive-v2.js` and loaded from `public/js/main.js`.
- Treat imported Python components as HTML-first `x-*` tags in authored templates, such as `<x-button />` or `<x-command-dialog />`.
- `pp-component` is injected by the Python render pipeline onto page, layout, and component roots; authored route and component templates should not add it manually.
- `main.py` runs `transform_scripts(...)`, so authored body `<script>` tags are rewritten to `<script type="text/pp">` in rendered HTML; route, layout, and component templates should write plain `<script>` in source.
- Route and component HTML templates must keep exactly one top-level lowercase HTML element so Caspian can inject `pp-component`. Think React-style single parent wrapper: good `<div>...</div>` with any owned script inside that same root, bad sibling top-level tags such as `<div>...</div><script ...></script>`.
- File-manager flows in this repo should keep upload and delete `@rpc()` actions in the owning `src/app/**/index.py`, keep shared filesystem and Prisma helpers in `src/lib/**`, persist metadata in Prisma, and store browser-accessible blobs under `public/storage/**`.
- When `npm run dev` is intentionally running, let that long-running stack own generated outputs such as `public/css/styles.css`, `settings/component-map.json`, `settings/files-list.json`, `__pycache__/`, and `.pyc` files. Treat those as generated artifacts, not authored source.
- `settings/component-map.json` and `settings/files-list.json` are generated by `settings/component-map.ts` and `settings/files-list.ts` through the dev and build pipelines. Analyze them when needed, but do not hand-edit them.
- `settings/bs-config.ts` should keep `public/storage` in `PUBLIC_IGNORE_DIRS` so runtime uploads do not trigger BrowserSync reloads during the local stack.
- In the current router inside `main.py`, path params are passed to `page()` as the first positional `dict` argument.
- Matching query params can still be injected by name, and `request` is injected by keyword when declared.
- The installed `casp.layout` runtime calls `layout()` synchronously. Keep async I/O in `page()` or `@rpc()`.
- In `layout.py`, return a dict for standard `[[ layout.* ]]` props. Use `render_layout(__file__, {...})` only when that layout should consume direct local variables such as `[[ my_class ]]` instead of `[[ layout.my_class ]]`.
- `StateManager` reads and writes `request.state.session`, but the current middleware stack in `main.py` does not mirror `request.session` into `request.state.session`.
- Do not assume `StateManager` persistence survives across requests until that bridge exists.
- Route HTML caching uses `caches/` and `caches/cache_manifest.json` through `casp.cache_handler`.
- The current app tree has root templates in `src/app/`, and route-specific `index.py` files belong only where routes need server-side logic, metadata, or non-visual handling such as uploads or redirects.
- For route creation, keep page markup in `src/app/**/index.html`. If a route is UI-only, stop there. Add `src/app/**/index.py` only as a companion when the same route needs metadata, `page()`, `@rpc()` actions, auth checks, caching, redirects, or other server-side behavior. Do not place route HTML in `index.py`; use a lone `index.py` only for non-visual routes such as redirect-only or action-only handlers.

## Task Routing

Use this map before making changes.

| Task area                                 | Read first                                                                                                   | Verify against                                                                   |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Project layout and file placement         | `node_modules/caspian-utils/dist/docs/index.md`, `node_modules/caspian-utils/dist/docs/project-structure.md` | current workspace tree                                                           |
| Feature availability and tooling switches | `caspian.config.json`                                                                                        | current workspace tree, `main.py`, `prisma/**`, `public/js/**`                   |
| Library-specific and task-specific rules  | matching `.github/instructions/**/*.instructions.md` files                                                   | `caspian.config.json`, current workspace tree, owning app and lib files          |
| MCP server layout and launch flow         | `node_modules/caspian-utils/dist/docs/mcp.md`                                                                | `settings/restart-mcp.ts`, `package.json`, `src/lib/mcp/**`                      |
| Routing, layouts, metadata                | `node_modules/caspian-utils/dist/docs/routing.md`                                                            | `main.py`, `.venv/Lib/site-packages/casp/layout.py`                              |
| Auth, sessions, RBAC, providers           | `node_modules/caspian-utils/dist/docs/auth.md`                                                               | `src/lib/auth/auth_config.py`, `main.py`, `.venv/Lib/site-packages/casp/auth.py` |
| RPC, data loading, streaming, uploads     | `node_modules/caspian-utils/dist/docs/fetch-data.md`, `node_modules/caspian-utils/dist/docs/pulsepoint.md`   | `.venv/Lib/site-packages/casp/rpc.py`, `public/js/pp-reactive-v2.js`, `main.py`  |
| File uploads and managers                 | `node_modules/caspian-utils/dist/docs/file-uploads.md`, `node_modules/caspian-utils/dist/docs/fetch-data.md` | `src/app/**`, `src/lib/**`, `prisma/**`, `settings/bs-config.ts`                 |
| Server state                              | `node_modules/caspian-utils/dist/docs/state.md`                                                              | `.venv/Lib/site-packages/casp/state_manager.py`, `main.py`                       |
| Page caching                              | `node_modules/caspian-utils/dist/docs/cache.md`                                                              | `.venv/Lib/site-packages/casp/cache_handler.py`, `main.py`                       |
| Validation                                | `node_modules/caspian-utils/dist/docs/validation.md`                                                         | `.venv/Lib/site-packages/casp/validate.py`                                       |
| Database and seed flow                    | `node_modules/caspian-utils/dist/docs/database.md`                                                           | `prisma/schema.prisma`, `prisma/seed.ts`, `src/lib/prisma/**`                    |

## Editing Rules

- Keep app-owned shared code in `src/lib/**`.
- Keep reusable application UI components in `src/components/**`.
- Keep route-specific logic in `src/app/**`.
- For route creation, keep page markup in `src/app/**/index.html`. If a route is UI-only, `index.html` alone is sufficient. Add `src/app/**/index.py` only as a companion when the same route needs metadata, `page()`, `@rpc()` actions, auth checks, caching, redirects, or other server-side behavior. Do not place route HTML in `index.py`; use a lone `index.py` only for non-visual routes such as redirect-only or action-only handlers.
- If a single route only needs to tweak a parent layout, return `(render_page(__file__, ...), {"dashboard_body_class": ...})` from `page()` instead of introducing one-off global state or moving route HTML into `index.py`.
- For file-manager work, keep route-owned upload and delete `@rpc()` actions in `src/app/**/index.py`, keep shared storage and Prisma helper logic in `src/lib/**`, and keep uploaded public blobs under `public/storage/**`.
- When deciding between `src/components/**` and `src/lib/**`, put reusable rendered UI in `src/components/**` and put services, validators, adapters, database helpers, and other non-UI support code in `src/lib/**`.
- Read `caspian.config.json` before deciding whether a Caspian feature should be used, documented, scaffolded, or avoided in the current workspace.
- Treat `caspian.config.json` as the single source of truth for optional features. Do not use feature-specific files, commands, or docs until the corresponding flag is enabled.
- If a feature flag is false and the user wants that feature, ask for confirmation first, then update `caspian.config.json` and run `npx casp update project` so framework-managed files align with the new feature set.
- Do not run `package.json` scripts unless the user explicitly asks for them, the task genuinely requires that exact script, or deployment preparation needs `npm run build`.
- Use `npm run build` for deployment prep or an explicit build request, not as the default validation step for routine route, feature, or documentation edits.
- Never treat `__pycache__/` directories or `.pyc` files as authored source. Do not edit them manually and do not leave them in the final diff if a tool run creates them.
- Never hand-edit `settings/component-map.json` or `settings/files-list.json`. Inspect them if needed, but let the framework regeneration flow update them.
- Treat `.venv/Lib/site-packages/casp/**` as framework internals unless the task is explicitly about Caspian core behavior or installed-runtime documentation.
- When a task involves Python-side database access, reuse `src/lib/prisma/**` instead of introducing a parallel helper, but do not hand-edit generated files in that directory.
- When `prisma/schema.prisma` changes, run `npx prisma migrate dev` first. If seed flow or `prisma/seed.ts` is involved, run `npx prisma generate` and then `npx prisma db seed`. After that, run `npx ppy generate` so the Python ORM layer and `settings/prisma-schema.json` stay aligned.
- Keep auth policy in `src/lib/auth/auth_config.py`.
- Keep auth bootstrap, middleware ordering, provider wiring, and router behavior in `main.py`.
- Treat the app-owned `src/lib/auth/auth_config.py` as the effective default when generating routes for this repo: it starts public-first with `is_all_routes_private=False` unless the app explicitly switches to all-private mode.
- Decide all-private versus mixed public/private routing in `src/lib/auth/auth_config.py` before creating many routes; use all-private mode only when public routes are the minority.
- Keep public exceptions in `public_routes`, keep explicit protected routes in `private_routes` when not using all-private mode, and leave default `auth_routes` alone unless the app explicitly needs custom auth endpoints.
- Do not treat `token_auto_refresh` as the switch for private routes.
- For logout flows, prefer `pp.rpc("signout")` plus `@rpc(require_auth=True)` in page or component UI. Only scaffold a signout route for no-JavaScript, form-post, or full-navigation edge cases.
- When MCP is enabled, keep the app-owned FastMCP server in `src/lib/mcp/mcp_server.py` and the default config in `src/lib/mcp/fastmcp.json`. If those paths move, update `settings/restart-mcp.ts` and the MCP docs together.
- Use PulsePoint as the default reactive frontend and browser-side UI layer unless the user explicitly wants another stack.
- When HTML templates import reusable Python components, render them as kebab-cased `x-*` tags after a top-level `<!-- @import ... -->` directive.
- For CRUD operations and any browser-initiated reads from the backend, use `@rpc()` plus `pp.rpc(...)` as the default contract instead of ad hoc fetch or parallel REST endpoints unless the user explicitly asks for them.
- Treat `pp-component` as a framework-owned attribute on authored templates. Document it, but do not manually add it in normal route or component HTML.
- Treat `type="text/pp"` on PulsePoint scripts as a render-time attribute too. In authored route, layout, and component HTML, write plain `<script>` and let Caspian rewrite it.
- Keep route and component HTML templates to a single top-level lowercase HTML element so the Python side can inject `pp-component` safely. Keep any owned PulsePoint script inside that same root instead of as a sibling top-level node.
- Keep repo-wide always-on Copilot guidance consolidated in `.github/copilot-instructions.md`.
- Use `.github/instructions/**/*.instructions.md` for narrower file-, task-, library-, or implementation-specific instructions, and keep those files tightly scoped instead of duplicating general repo rules.
- When writing docs about route behavior, describe the param passing and layout behavior implemented in the current runtime, not generic upstream assumptions.
- When a runtime change affects documentation, update the matching page in `node_modules/caspian-utils/dist/docs/`.
- When a repo-level rule changes, update this file too.

## Docs Maintenance Rules

- Treat `node_modules/caspian-utils/dist/docs/**` as packaged Caspian feature docs and AI routing docs, not as a snapshot of the current project.
- Treat `.github/instructions/**/*.instructions.md` as the workspace-local instruction layer for third-party libraries and narrowly scoped implementation guidance.
- Keep workspace instruction files specific to the surface they govern. Use filenames, `description`, and `applyTo` patterns that help the agent discover the right file before coding.
- Do not duplicate broad Caspian or repo-wide rules across many instruction files; keep shared guidance in `.github/copilot-instructions.md` and this file.
- Do not record this project's current feature flags, script inventory, or temporary file tree status inside the packaged docs.
- Gate optional docs with `caspian.config.json`. Use phrasing such as `when caspian.config.json enables MCP` instead of `this workspace has mcp: false`.
- Use the packaged docs to make AI aware of what Caspian can do, when a doc applies, and which project files should be inspected next.
- When `caspian.config.json` has `tailwindcss: true`, document Tailwind class handling as the current contract: Python `merge_classes(...)` emits frontend `{twMerge(...)}` expressions and browser `twMerge(...)` resolves conflicts.
- Keep repo-specific clarifications in this file or `.github/copilot-instructions.md` rather than embedding them in the packaged docs unless the behavior is truly framework-wide.
- Keep `index.md` and cross-links aligned so AI can discover the right task doc quickly.
- Continue validating `routing.md`, `components.md`, `auth.md`, `fetch-data.md`, `cache.md`, `pulsepoint.md`, `validation.md`, `database.md`, and `mcp.md` against the installed `casp` runtime before changing behavior claims.

## Maintenance Checklist

Before merging doc or runtime changes:

1. Compare the claim or behavior against `main.py`, `src/lib/**`, and `.venv/Lib/site-packages/casp/**`.
2. Update the matching packaged doc in `node_modules/caspian-utils/dist/docs/` if the running behavior changed.
3. Update this file if the repo-level decision rules, workspace rules, or packaged-doc maintenance rules changed.
