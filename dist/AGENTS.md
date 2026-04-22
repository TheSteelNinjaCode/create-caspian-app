# Caspian Agent Guide

## Purpose

This workspace is a Caspian application plus a local copy of the packaged Caspian docs.

When you work here, use the code that actually runs as the source of truth and use the markdown docs as the routing and explanation layer.

## Source Of Truth Order

Use this precedence whenever behavior, docs, and generated code disagree:

1. App runtime and app-owned code
   - `main.py`
   - `src/app/**`
   - `src/lib/**`
   - `public/js/**`
   - `prisma/**`
   - `caspian.config.json`
2. Installed Caspian framework runtime
   - `.venv/Lib/site-packages/casp/**`
3. Packaged Caspian docs in this workspace
   - `node_modules/caspian-utils/dist/docs/**`

If the task is about current repo behavior, prefer the app runtime.

If the task is about framework internals, prefer the installed `casp` package.

If docs differ from either of those, update the docs to match the code that actually runs.

Before making feature, tooling, or scaffolding decisions, read `caspian.config.json` almost immediately. Treat it as the workspace feature gate for flags such as `backendOnly`, `tailwindcss`, `mcp`, `prisma`, `typescript`, and `componentScanDirs`.

Treat `caspian.config.json` as the single source of truth for whether an optional Caspian feature is enabled in the current workspace. Use feature-specific docs only after the matching flag is confirmed as enabled. If a feature is disabled and the user wants it, ask whether they want to enable it first, then follow the Caspian update workflow to refresh framework-managed files.

## Verified Workspace Facts

- Local Caspian docs live under `node_modules/caspian-utils/dist/docs/`.
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
- Protect customized `src/lib/auth/auth_config.py` from framework updates by adding `./src/lib/auth/auth_config.py` to `excludeFiles` in `caspian.config.json`.
- This workspace already has an app-owned Python database layer in `src/lib/prisma/`.
- This workspace currently has `mcp: false` in `caspian.config.json`, so do not assume `src/lib/mcp/**`, `settings/restart-mcp.ts`, or `npm run mcp` exist unless MCP is explicitly enabled later.
- `package.json` currently defines `projectName`, `tailwind`, `tailwind:build`, `browserSync`, `browserSync:build`, `dev`, and `build`. Treat those scripts as opt-in operational commands, not default validation steps for ordinary source edits.
- Reuse `src/lib/prisma/prisma`, `PrismaClient`, generated models, and helper types instead of creating a second Python database abstraction.
- Prisma schema source of truth is `prisma/schema.prisma`.
- The schema-change workflow in this workspace is: `npx prisma migrate dev`; if seed flow or `prisma/seed.ts` is involved, run `npx prisma generate` and then `npx prisma db seed`; then run `npx ppy generate`.
- `npx ppy generate` owns `src/lib/prisma/__init__.py`, `src/lib/prisma/db.py`, `src/lib/prisma/models.py`, and `settings/prisma-schema.json`; do not hand-edit those generated files.
- `caspian.config.json` is the first config file to check for enabled workspace features. In the current workspace it sets `backendOnly: false`, `tailwindcss: true`, `mcp: false`, `prisma: true`, `typescript: false`, and `componentScanDirs: ["src"]`.
- PulsePoint runtime code is shipped in `public/js/pp-reactive-v2.js` and loaded from `public/js/main.js`.
- `pp-component` is injected by the Python render pipeline onto page, layout, and component roots; authored route and component templates should not add it manually.
- `main.py` runs `transform_scripts(...)`, so authored body `<script>` tags are rewritten to `<script type="text/pp">` in rendered HTML; route, layout, and component templates should write plain `<script>` in source.
- Route and component HTML templates must keep exactly one top-level lowercase HTML element so Caspian can inject `pp-component`. Think React-style single parent wrapper: good `<div>...</div>` with any owned script inside that same root, bad sibling top-level tags such as `<div>...</div><script ...></script>`.
- When `npm run dev` is intentionally running, let that long-running stack own generated outputs such as `public/css/styles.css`, `settings/component-map.json`, `settings/files-list.json`, `__pycache__/`, and `.pyc` files. Treat those as generated artifacts, not authored source.
- `settings/component-map.json` and `settings/files-list.json` are generated by `settings/component-map.ts` and `settings/files-list.ts` through the dev and build pipelines. Analyze them when needed, but do not hand-edit them.
- In the current router inside `main.py`, path params are passed to `page()` as the first positional `dict` argument.
- Matching query params can still be injected by name, and `request` is injected by keyword when declared.
- The installed `casp.layout` runtime calls `layout()` synchronously. Keep async I/O in `page()` or `@rpc()`.
- `StateManager` reads and writes `request.state.session`, but the current middleware stack in `main.py` does not mirror `request.session` into `request.state.session`.
- Do not assume `StateManager` persistence survives across requests until that bridge exists.
- Route HTML caching uses `caches/` and `caches/cache_manifest.json` through `casp.cache_handler`.
- The current app tree has root templates in `src/app/` and does not currently include route-specific `index.py` files.

## Task Routing

Use this map before making changes.

| Task area                                 | Read first                                                                                                   | Verify against                                                                   |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Project layout and file placement         | `node_modules/caspian-utils/dist/docs/index.md`, `node_modules/caspian-utils/dist/docs/project-structure.md` | current workspace tree                                                           |
| Feature availability and tooling switches | `caspian.config.json`                                                                                        | current workspace tree, `main.py`, `prisma/**`, `public/js/**`                   |
| MCP server layout and launch flow         | `node_modules/caspian-utils/dist/docs/mcp.md`                                                                | `settings/restart-mcp.ts`, `package.json`, `src/lib/mcp/**`                      |
| Routing, layouts, metadata                | `node_modules/caspian-utils/dist/docs/routing.md`                                                            | `main.py`, `.venv/Lib/site-packages/casp/layout.py`                              |
| Auth, sessions, RBAC, providers           | `node_modules/caspian-utils/dist/docs/auth.md`                                                               | `src/lib/auth/auth_config.py`, `main.py`, `.venv/Lib/site-packages/casp/auth.py` |
| RPC, data loading, streaming, uploads     | `node_modules/caspian-utils/dist/docs/fetch-data.md`, `node_modules/caspian-utils/dist/docs/pulsepoint.md`   | `.venv/Lib/site-packages/casp/rpc.py`, `public/js/pp-reactive-v2.js`, `main.py`  |
| Server state                              | `node_modules/caspian-utils/dist/docs/state.md`                                                              | `.venv/Lib/site-packages/casp/state_manager.py`, `main.py`                       |
| Page caching                              | `node_modules/caspian-utils/dist/docs/cache.md`                                                              | `.venv/Lib/site-packages/casp/cache_handler.py`, `main.py`                       |
| Validation                                | `node_modules/caspian-utils/dist/docs/validation.md`                                                         | `.venv/Lib/site-packages/casp/validate.py`                                       |
| Database and seed flow                    | `node_modules/caspian-utils/dist/docs/database.md`                                                           | `prisma/schema.prisma`, `prisma/seed.ts`, `src/lib/prisma/**`                    |

## Editing Rules

- Keep app-owned shared code in `src/lib/**`.
- Keep route-specific logic in `src/app/**`.
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
- Use PulsePoint and `pp.rpc(...)` as the default frontend and browser-to-server contract unless the user explicitly wants another stack.
- Treat `pp-component` as a framework-owned attribute on authored templates. Document it, but do not manually add it in normal route or component HTML.
- Treat `type="text/pp"` on PulsePoint scripts as a render-time attribute too. In authored route, layout, and component HTML, write plain `<script>` and let Caspian rewrite it.
- Keep route and component HTML templates to a single top-level lowercase HTML element so the Python side can inject `pp-component` safely. Keep any owned PulsePoint script inside that same root instead of as a sibling top-level node.
- Keep Copilot guidance consolidated in `.github/copilot-instructions.md`; do not add `.github/instructions/` in this workspace.
- When writing docs about route behavior, describe the param passing and layout behavior implemented in the current runtime, not generic upstream assumptions.
- When a runtime change affects documentation, update the matching page in `node_modules/caspian-utils/dist/docs/`.
- When a repo-level rule changes, update this file too.

## Docs Alignment Notes

The packaged docs in this workspace are already mostly aligned with the installed runtime, but keep these repo-specific clarifications in mind:

- `database.md` is the source doc for the Prisma and Python ORM workflow in this repo: schema changes go through `npx prisma migrate dev`, optional `npx prisma generate` plus `npx prisma db seed`, then `npx ppy generate`, and generated ORM files under `src/lib/prisma/` plus `settings/prisma-schema.json` are not hand-edited.
- `mcp.md` is the source doc for MCP-enabled workspaces, but in this workspace `caspian.config.json` currently has `mcp: false`, so do not assume `src/lib/mcp/**` or `npm run mcp` exist until MCP is explicitly enabled.
- Feature-specific docs are conditional on `caspian.config.json`: use `database.md` only when `prisma: true`, use `mcp.md` only when `mcp: true`, and treat disabled-feature docs as reference material until the user chooses to enable that feature.
- `auth.md` is the source doc for auth routing guidance: choose all-private mode only when public routes are the minority, keep auth policy in `src/lib/auth/auth_config.py`, protect that file with `excludeFiles` if customized, prefer auth-protected RPC logout from page or component UI, and keep dedicated signout routes for form-post or no-JavaScript fallbacks.
- `state.md` is correct to warn that cross-request persistence depends on `request.state.session`, which is not bridged in the current `main.py`.
- `commands.md`, `installation.md`, and `project-structure.md` are the source docs for this repo's package-script guardrails: do not auto-run npm scripts for ordinary edits, use `npm run build` only for deployment prep or explicit build requests, and treat `settings/component-map.json`, `settings/files-list.json`, `__pycache__/`, and `.pyc` files as generated artifacts.
- `routing.md`, `components.md`, `auth.md`, `fetch-data.md`, `cache.md`, `pulsepoint.md`, and `validation.md` should continue to be validated against the installed `casp` package before any behavior claims are changed.

## Maintenance Checklist

Before merging doc or runtime changes:

1. Compare the claim or behavior against `main.py`, `src/lib/**`, and `.venv/Lib/site-packages/casp/**`.
2. Update the matching packaged doc in `node_modules/caspian-utils/dist/docs/` if the running behavior changed.
3. Update this file if the repo-level source-of-truth rules or workspace facts changed.
