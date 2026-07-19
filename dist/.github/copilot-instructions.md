# Copilot Instructions

- Read `AGENTS.md` before working in `main.py`, `src/lib/**`, `.venv/Lib/site-packages/casp/**`, `public/js/**`, `prisma/**`, or `node_modules/caspian-utils/dist/docs/**`.
- Keep repo-wide always-on Copilot guidance in this file. Use `.github/instructions/**/*.instructions.md` for narrower task-, file-, library-, or implementation-specific guidance when that extra context should not load on every request.

## Document Ownership

- This file owns repo-wide always-on rules for the workspace.
- `AGENTS.md` should focus on task routing, runtime cross-checking, and packaged-doc maintenance rather than repeating full rule blocks from this file.
- When packaged docs need to point AI from a feature guide to the controlling runtime file, prefer `node_modules/caspian-utils/dist/docs/core-runtime-map.md` instead of duplicating the full module map in multiple pages.
- When packaged docs need to point AI from a PulsePoint feature or directive to the controlling browser behavior, prefer `node_modules/caspian-utils/dist/docs/pulsepoint-runtime-map.md` instead of duplicating the full browser feature map in multiple pages.

## Component-First Page Composition (Highest Priority)

This is the top architectural requirement for this workspace. Treat it as a hard rule that outranks convenience, and apply it before writing any route, layout, or page markup.

- Build pages from components, not from one large block of HTML. A route's `src/app/**/index.html` should read like a short composition of `x-*` component tags, not a wall of markup. When a page would otherwise carry a long stretch of HTML, that markup must move into a component instead of living in the page.
- Separate every page into meaningful chunks and give each chunk its own component. Typical chunks are a top menu / topbar, header, sidebar / nav rail, hero, toolbar, content sections, cards, lists, forms, footer, and any repeated block. Each chunk owns its own long markup inside its component file, so the page content stays small and readable.
- Default to single-file Python components authored with inline `html(...)` (import `html` from `casp.component_decorator`, return `html("""...""", **context)`) for each focused chunk. Single-file means the component's Python, markup, and small PulsePoint script live together; it does not mean the whole page, full dashboard, or every tab panel should be collapsed into one Python file.
- Split component files by responsibility the way you would split React components. If a page has tabs, create focused components such as `OverviewTab.py`, `ActivityTab.py`, and `SettingsTab.py` instead of one oversized `DashboardTabs.py` that contains every panel. If a section has its own form, table, toolbar, or card list, make that section a component and pass data, flags, callbacks, or labels as props.
- Put these page-chunk components in `src/components/` (or a route-local component folder when they are truly single-route), import them into the route with top-of-file `<!-- @import ... -->` directives above the route root, and render them as kebab-cased `x-*` tags. Keep the single-root contract in both the page and each component.
- When the user asks to build or extend a page, plan the chunk breakdown first (for example: top menu component, sidebar component, content section component), create those components, then assemble them in the route. Do not start by pasting a full HTML page into `index.html` and only later consider extraction; component-first is the starting point, not a cleanup step.
- If you find an existing page or single-file component with multiple unrelated responsibilities, prefer splitting it into focused chunk components as part of the work rather than adding more markup to it.

## Global Rules

- Use this decision order: `caspian.config.json` for optional feature enablement, app runtime and app-owned code for current project behavior, matching workspace instruction files under `.github/instructions/**/*.instructions.md` for task-specific implementation guidance, installed `casp` runtime for framework internals, and packaged markdown docs for Caspian feature discovery and task routing.
- As the app grows, prefer `src/components/` for reusable application UI and reserve `src/lib/` for reusable non-UI code such as services, validators, adapters, and shared helpers.
- Read `./caspian.config.json` almost immediately before making feature, tooling, scaffolding, or file-placement decisions. Treat it as the workspace feature gate for flags such as `backendOnly`, `tailwindcss`, `mcp`, `prisma`, `typescript`, `websocket`, and `componentScanDirs`.
- Treat `caspian.config.json` as the single source of truth for whether optional Caspian features are enabled in the current workspace. Use feature-specific docs, files, and commands only after the matching flag is confirmed as enabled.
- If a feature is disabled and the user wants it, ask whether they want to enable it first, then update `caspian.config.json` and follow `npx casp update project` so framework-managed files align with the new feature set.
- When `.github/instructions/**/*.instructions.md` files exist, treat them as workspace-local file instructions for specific libraries, component systems, icon sets, integrations, and implementation rules. Read the matching instruction before deciding how to implement work in that area, but do not let it override `caspian.config.json`, app code, or installed runtime behavior.
- Treat `node_modules/caspian-utils/dist/docs/**` as packaged Caspian docs that teach AI how Caspian features work and where to look next. Their presence does not mean the feature is enabled in the current project.
- Use `node_modules/caspian-utils/dist/docs/pulsepoint-runtime-map.md` for fast PulsePoint feature lookup before editing browser-side behavior or generating advanced PulsePoint patterns.
- Use `node_modules/caspian-utils/dist/docs/websockets.md` before changing FastAPI WebSocket endpoints, socket origin checks, socket auth/session behavior, broadcast managers, or native browser `WebSocket` clients.
- For current repo behavior, trust `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, and `src/app/**` over generic Caspian docs.
- For framework internals, trust `.venv/Lib/site-packages/casp/**` over generic or older upstream guidance.
- When packaged docs conflict with project code or installed runtime, the project code, `caspian.config.json`, and installed runtime win. Keep the packaged docs feature-oriented and point AI back to the project files that decide actual enablement and behavior.
- When `prisma/schema.prisma` changes, follow this order: run `npx prisma migrate dev`; if the change affects seed flow or `prisma/seed.ts`, run `npx prisma generate` and then consider `npx prisma db seed`; then run `npx ppy generate` so the Python ORM stays aligned with the schema. Treat `npx prisma db seed` as a destructive data operation: it may clean tables and replace existing records, including production data if pointed at the wrong database. Before running it, tell the user exactly which command you intend to run, explain that it can delete or overwrite database data, confirm the current datasource when practical, and wait for the user's explicit approval.
- Reuse the existing Python database layer in `src/lib/prisma/**`; do not create a second app-owned database abstraction unless the user explicitly asks for one.
- When `caspian.config.json` has `prisma: true`, all Python-side database reads and writes must go through the generated Prisma Python ORM exposed from `src/lib/prisma/**`. Do not bypass it with ad hoc sqlite/postgres drivers, hand-written fetch helpers, JSON files as active stores, browser-side database fetches, or custom HTTP endpoints that reinvent the ORM. Use raw SQL only through Prisma as a narrow fallback when the generated ORM cannot express the query clearly.
- Treat `src/lib/prisma/__init__.py`, `src/lib/prisma/db.py`, `src/lib/prisma/models.py`, and `settings/prisma-schema.json` as generated outputs owned by `npx ppy generate`; do not create or hand-edit them manually.
- Treat `package.json` scripts as opt-in operations. Do not run `npm run dev`, `npm run build`, or other npm scripts unless the user explicitly asks, the task genuinely requires that exact script, or deployment preparation needs `npm run build`.
- Use `npm run build` for deployment prep or an explicit build request, not as the default validation step for routine route, feature, or documentation edits.
- This workspace has an app-level quality gate. After editing app-owned Python (`main.py`, `src/**`), run `npm run check` (which calls `uv run python settings/check.py`) before treating the change as done. It type checks with `pyrefly`, lints with `ruff`, and runs `pytest` in one pass, prints each problem as `path:line:col [tool:code] message`, and exits non-zero; fix the reported locations. Write app-owned Python to pass type checking (annotate parameters and returns, avoid untyped `Any` drift) and add or extend tests in `tests/` for the behavior you change. See `### tests/**/*.py and settings/check.py`.
- Let the running dev stack own generated outputs such as `public/css/styles.css`, `settings/component-map.json`, `settings/files-list.json`, `__pycache__/`, and `.pyc` files. Treat those as generated artifacts rather than authored source.
- Never treat `__pycache__/` directories or `.pyc` files as files to edit, regenerate on purpose, or keep in the final diff.
- Treat `settings/component-map.json` and `settings/files-list.json` as generated outputs owned by `settings/component-map.ts` and `settings/files-list.ts`; inspect them when needed, but do not hand-edit them.
- When `caspian.config.json` has `mcp: true`, treat `src/lib/mcp/mcp_server.py` as the app-owned FastMCP server and `src/lib/mcp/fastmcp.json` as the default MCP config. Use `npm run mcp` or `fastmcp run src/lib/mcp/fastmcp.json`; do not assume root `fastmcp.json` auto-discovery.
- Keep auth policy in `src/lib/auth/auth_config.py` and keep auth bootstrap, middleware wiring, and provider registration in `main.py`.
- Treat `casp.runtime_security` in `.venv/Lib/site-packages/casp/runtime_security.py` as package-owned runtime support for safe public-file serving, production session-secret enforcement, production-safe error messaging, and baseline non-CSP response headers. Users should not customize this file during normal app work.
- In app-owned starter config like this workspace, routes start public because `src/lib/auth/auth_config.py` sets `is_all_routes_private=False` by default.
- Decide route privacy in `src/lib/auth/auth_config.py` at app setup time: use `is_all_routes_private=True` when only a few routes should stay public, otherwise keep `is_all_routes_private=False` and list the protected routes in `private_routes`.
- In all-private mode, keep public exceptions in `public_routes`; the runtime defaults keep `/` public and keep `auth_routes=["/signin", "/signup"]` public.
- When building or editing sign-in flows, do not implement app-owned `next` parsing or redirect selection inside the sign-in page or sign-in action unless the user explicitly asks to replace Caspian auth behavior. Guest redirects to `/signin?next=...`, authenticated auth-route redirects, and the default post-login destination are already owned by the Caspian runtime plus `src/lib/auth/auth_config.py`, which defaults `default_signin_redirect` to `/dashboard`.
- Do not treat `token_auto_refresh` as the switch that makes routes private. In the current app it only affects sliding-session refresh if `auth.refresh_session()` is called.
- Use PulsePoint as the default reactive frontend layer unless the user requests another stack.
- For first-party Caspian HTML interactivity, use PulsePoint event attributes such as `onclick`, `oninput`, `onsubmit`, state, refs, effects, directives, and `pp.rpc()` before considering standard DOM scripting. Do not start by adding ids, `data-*` wiring, `querySelector`, `getElementById`, `addEventListener`, manual `innerHTML`, or custom client-side state managers for normal reactive UI.
- For normal forms, treat the HTML submit event as the first choice: bind `onsubmit="{submitForm(event)}"` on the `<form>`, call `event.preventDefault()` in the handler when staying on the page, and build the RPC payload with `Object.fromEntries(new FormData(event.currentTarget).entries())`. Let input `name` attributes define the payload keys and let Python validate, normalize, and decide what to persist. Do not add `pp-ref` to every input or attach an effect-managed submit listener just to build an RPC payload.
- Treat imperative DOM APIs and `pp-ref` element reads as narrow escape hatches for third-party widgets, browser APIs that require direct DOM access, focus/measurement/media/canvas behavior, or one-off integration code. When they are needed, keep them inside the owning PulsePoint component script, usually behind `pp.ref(...)` and `pp.effect(...)`, so PulsePoint still owns the component state and event flow.
- When `caspian.config.json` has `tailwindcss: true`, treat Python `merge_classes(...)` plus browser `twMerge(...)` as the only Tailwind class-merging contract: `merge_classes(...)` emits frontend-ready `{twMerge(...)}` expressions, and authored PulsePoint attribute expressions or scripts may call global `twMerge(...)` directly.
- Treat Caspian component usage as HTML-first in the current runtime: import Python components with `<!-- @import ... -->` and render them as kebab-cased `x-*` tags such as `<x-button />` or `<x-command-dialog />`.
- Components may be authored single-file. Return `html("""...""", **context)` (import `html` from `casp.component_decorator`) to keep markup, server interpolation, and a PulsePoint `<script>` inline instead of a same-name `.html` via `render_html(...)`. Inside `html(...)`, `{{ ... }}` is server-side Jinja and `{ ... }` is left for PulsePoint; never use a Python f-string for the markup. Autoescaping is on, so `{{ value }}` is safe for user text and trusted HTML needs `Markup(...)` or `| safe`; a `children` value is auto-safe. Prefer single-file `html(...)` for small and medium components, but keep each file focused on one responsibility. Split multiple panels, tabs, forms, tables, cards, and toolbars into separate components instead of making one giant single-file component.
- For single-file Python components that receive browser props, treat the Python render as an explicit bridge. Attributes on the parent `x-*` tag arrive as raw string kwargs, including unevaluated PulsePoint expressions such as `"{permOpen}"`; they do not reach `pp.props` merely because the Python signature accepts them. Re-emit browser-facing values on the component's single native root with `attributes = get_attributes({...}, props)`, `<root {{ attributes }}>`, and `html(..., attributes=attributes)`. Otherwise `pp.props` is silently empty or missing those keys with no error or warning. Forwarded props are real DOM attributes, so avoid accidental native behavior such as a `title` tooltip by choosing a non-native API name such as `user-name` when appropriate. Follow the full helper and prop-passing contract in `node_modules/caspian-utils/dist/docs/components.md`.
- Inside single-file components, use real Python imports instead of `<!-- @import ... -->` comments for child components: a component's own `x-*` tags resolve from the components imported into its Python module, which disambiguates same-name components across directories. Do not put an import comment inside the `html("""...""")` string. Runtime resolution precedence is inherited ancestor components, then the component's own Python imports, then a local `@import`, but the authoring pattern for single-file components is Python imports. Slot content resolves in the scope where it was authored, so the template that writes an `x-*` tag must import that component.
- For CRUD operations and any browser-initiated reads from the backend, use route or backend `@rpc()` actions on the server and `pp.rpc(...)` from PulsePoint code on the client unless the user explicitly asks for another integration pattern.
- Google and GitHub OAuth ship pre-registered in this starter: `main.py` already calls `Auth.set_providers(GithubProvider(), GoogleProvider())`, and `AuthMiddleware` already handles the `signin/{google,github}` and `callback/{google,github}` paths under `api_auth_prefix` (default `/api/auth`). To add social sign-in, point a link or button at `/api/auth/signin/google` or `/api/auth/signin/github` and set the provider credentials in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`). Do not hand-roll an OAuth flow, manual `httpx`/`authlib` token exchange, or custom callback routes; reuse the shipped providers and let `auth.auth_providers(...)` own redirect, callback, and sign-in.
- For one-way streaming output, including AI/LLM/chat token streams, use Caspian's shipped RPC streaming: write a generator `@rpc()` action that `yield`s chunks (the runtime wraps generators as SSE via `casp.streaming.SSE`) and consume it with `pp.rpc(name, args, { onStream, onStreamComplete, onStreamError })`. When bridging a Python LLM/SDK stream, `async for` over the provider's stream inside the `@rpc()` action and `yield` each token. Do not reinvent one-way streaming with raw `fetch`/`ReadableStream`, `EventSource`, or a WebSocket; reserve WebSockets for genuinely bidirectional channels per the WebSocket rules above.
- For live bidirectional channels, first confirm `caspian.config.json` has `websocket: true`, then use app-owned FastAPI WebSocket endpoints in `main.py` plus native browser `WebSocket` clients inside the owning PulsePoint route template. Do not replace normal CRUD, form submits, uploads, or one-way progress streams with WebSockets.
- When `caspian.config.json` has `websocket: true`, WebSocket endpoint paths are project-defined in `main.py`; do not assume any default socket path or route folder exists in every Caspian project. Keep shared socket helpers under `src/lib/websocket/**` when session extraction, auth payload validation, connection tracking, or broadcast behavior is reused.
- For route creation, keep page markup in `src/app/**/index.html`. If a route is UI-only, `index.html` alone is sufficient. Add `src/app/**/index.py` only as a companion when the same route needs metadata, `page()`, `@rpc()` actions, auth checks, caching, redirects, or other server-side behavior. Keep shared section wrappers in `layout.html` and use `layout.py` only for shared props or metadata. Do not place route HTML in `index.py` or layout HTML in `layout.py`; use a lone `index.py` only for non-visual routes such as redirect-only or action-only handlers.
- Keep route-specific logic in that route's `index.py`. Move code into `src/lib/**` only when it is genuinely reusable across routes, components, integrations, or features; do not extract one-route orchestration just to make it look generic.
- Treat the single-root template contract as a hard requirement, not a style preference: every authored route, layout, and component HTML file must have exactly one parent HTML element or one imported `x-*` component tag as its root. Do not leave sibling top-level markup, and do not place a `<script>` after the root element. If a script is needed, keep it inside that same root.
- When the user asks for a dashboard, admin area, account area, or any grouped child-route section, follow the same mental model as the Next.js App Router: create a parent folder with `layout.html`, add `layout.py` only when that section needs shared props or metadata, and place the child routes beneath it. Use a normal folder such as `dashboard/` when the segment should appear in the URL, and use `(group)/` only when it should not.
- In grouped section layouts with separate shell and content scrolling, put `pp-reset-scroll="true"` on the content scroll container that should reset on child-route navigation, usually the main pane. Leave persistent shell scrollers such as sidebars or rails unmarked so SPA navigation can preserve their scroll position.
- When a single route needs to affect a wrapping layout, have `page()` return `(render_page(__file__, page_context), {"dashboard_body_class": ...})` and consume that value as `{{ layout.dashboard_body_class }}` in `layout.html`. Use `layout.py` when the same prop should apply across a whole subtree.
- For file uploads and file-manager flows, keep browser interaction in route templates, keep upload and delete `@rpc()` actions in the owning `src/app/**/index.py`, keep shared storage and persistence helpers in `src/lib/**`, store metadata in Prisma, and store browser-accessible blobs under `public/uploads/**` when the files should be served directly.
- Local upload helpers should create `public/uploads` on demand when it does not exist yet; do not assume the folder is committed ahead of time.
- When runtime uploads write into `public/uploads/**`, keep the public-root-relative entry `uploads` in `settings/bs-config.ts` `PUBLIC_IGNORE_DIRS` so `npm run dev` does not reload on each upload.
- For logout flows, prefer `pp.rpc("signout")` backed by `@rpc(require_auth=True)` from page-level or component-level UI. Use a dedicated signout route only for plain form POST, no-JavaScript fallback, or other full-navigation edge cases.
- Protect customized `src/lib/auth/auth_config.py` from updater overwrite by adding `./src/lib/auth/auth_config.py` to `excludeFiles` in `caspian.config.json`.
- Treat `pp-component` on routes, layouts, and components, and `type="text/pp"` on owned PulsePoint scripts, as compiler-injected by the Python side; do not add them manually in authored templates unless the task is explicitly about runtime internals.
- `layout()` can be synchronous or async in the installed runtime. Keep async layout work focused on shared layout props or metadata; use `page()` or `@rpc()` when the work belongs to a specific route or user action.
- Dynamic route params currently reach `page()` as a single positional `dict`, with query params injected by name and `request` injected by keyword when declared.
- In `layout.py`, return a dict for standard `{{ layout.* }}` props. Use `render_layout(__file__, {...})` only when that layout should consume direct local variables such as `{{ my_class }}` instead of `{{ layout.my_class }}`.
- Do not assume `StateManager` survives across requests unless `request.state.session` is explicitly bridged from `request.session`.
- Route, layout, and component HTML templates must keep exactly one authored top-level parent node so Caspian can inject `pp-component` after component expansion. In source, that parent may be a native HTML element or a single imported `x-*` component tag, but it must resolve to one final HTML root. Keep any owned PulsePoint script inside that same parent, and keep top-of-file `<!-- @import ... -->` directives above it.

## BrowserSync URL Source Of Truth

- When AI needs to test or confirm whether a route, server response, or proxy-backed request is working, use `./settings/bs-config.json` as the source of truth for the current BrowserSync URLs.
- Do not assume the proxy stays on the default `http://localhost:5090`; if that port is busy, the active BrowserSync ports may change.
- Prefer confirming the current `local`, `external`, `ui`, and `uiExternal` values in `./settings/bs-config.json` before suggesting a test URL or opening the app in the browser.
- Use this file when frontend console errors or terminal output suggest the wrong local URL, proxy port, or BrowserSync UI port is being used during debugging.

## Path-Specific Rules

### `main.py`

- Treat `main.py` as the repo source of truth for FastAPI setup, auth bootstrap, middleware wiring, route registration, cache defaults, and error handlers.
- `main.py` finalizes every rendered page through `finalize_html(...)` = `transform_scripts(...)` then `defer_component_roots(...)`. `defer_component_roots(...)` wraps each outermost `pp-component` root in an inert `<template pp-component>` so the browser never parses raw `{...}` placeholders as live DOM; the PulsePoint `mount()` bootstrap materializes them back before scanning. Because of this deferral, `{...}` is safe in any attribute or position (SVG `d`/`viewBox`/`points`, `src`/`href`, form `value`/date/number/color, table/select text). Do not add per-tag workarounds to dodge browser first-paint validation (static-path `hidden` toggles, `data-*` URL holders, `hidden`-gated `<img src>`, or SSR-resolved initial values). Keep `pp-style` (source-file tooling) and the controlled form-field `value`/`checked`/`defaultvalue`/`<textarea>` rewrites (attribute-vs-property correctness); those exist for reasons deferral does not replace.
- Treat `main.py` as the source of truth for app-owned WebSocket endpoints, origin validation, idle timeouts, maximum socket message size, JSON message handling, close codes, and broadcast-channel wiring.
- When the app factors response-header hardening or safe static-file behavior into app-owned helpers, treat `main.py` plus those imported helpers as the runtime source of truth together.
- Preserve the effective middleware execution order unless the task explicitly changes request semantics: `SecurityHeadersMiddleware -> SessionMiddleware -> CSRFMiddleware -> AuthMiddleware -> RPCMiddleware`.
- Do not move normal file upload or file-manager behavior into `main.py`; keep those actions in the owning route `index.py` and shared helpers in `src/lib/**`.
- Document route param behavior exactly as implemented here.
- Do not use `main.py` alone to infer whether optional features are enabled; confirm that in `caspian.config.json` first.
- Before changing WebSocket behavior, verify `cfg.websocket`, the app's endpoint registration, the `authorize_websocket(...)` guard in `src/lib/websocket/websocket_security.py`, idle timeout, maximum message size, close codes, and connection cleanup. HTTP-only middleware does not automatically protect `scope["type"] == "websocket"` connections, so socket auth lives in that guard, not `AuthMiddleware`.
- Authorize sockets with the single `authorize_websocket(...)` guard, which runs the origin check then delegates to Caspian `Auth` (`Auth.set_request(websocket)` + `is_authenticated`/`get_payload`/`check_role`). Add channels by calling that guard with `require_auth=`/`roles=`; do not re-implement session/`exp`/payload parsing per endpoint. Keep authenticated and guest broadcast pools separate, and treat the socket session as read-only.

### `src/lib/**/*.py`

- Keep `src/lib/` for app-owned shared non-UI code, service wrappers, validators, adapters, and reusable helpers.
- Prefer `src/components/` for reusable rendered UI instead of placing component modules in `src/lib/`.
- Reuse the generated `src/lib/prisma/` package for Python database access, but do not hand-edit files under `src/lib/prisma/`; regenerate them with `npx ppy generate` after schema changes.
- For file managers, keep shared storage, normalization, and Prisma-backed persistence helpers here while route-owned upload and delete `@rpc()` actions stay in `src/app/**/index.py`.
- When `caspian.config.json` has `mcp: true`, keep app-owned MCP tools in `src/lib/mcp/mcp_server.py` and keep the default FastMCP config in `src/lib/mcp/fastmcp.json`. If those locations change, update `settings/restart-mcp.ts` and the MCP docs together.
- Keep auth policy in `src/lib/auth/auth_config.py`. Keep auth bootstrap and middleware order changes in `main.py`.
- Do not recreate or customize `src/lib/security/runtime_security.py` for normal application work. Runtime security helpers are package-owned in `casp.runtime_security`; app-specific policy should live in app-owned config or route/helper code instead.
- Keep reusable WebSocket helpers under `src/lib/websocket/**` when they are shared across socket endpoints or route clients. Common shared helpers include the `authorize_websocket(...)` guard (origin + `Auth`-delegated auth), origin utilities, connection managers, payload normalization, and broadcast fan-out.

### `src/components/**/*.py`

- Keep `src/components/` as the default home for reusable application UI components and for the page chunks produced by component-first composition (top menus, sidebars, headers, content sections, cards, lists, forms, footers).
- Move shared cards, forms, shells, navigation, and other reusable rendered building blocks here once they are used across routes or features.
- Keep route-owned markup in `src/app/**`, and keep non-UI helpers or services in `src/lib/**`.
- Author components as a single Python file with inline `html(...)` by default for small and medium UI, or as a `.py` plus same-name `.html` via `render_html(...)` for large markup or long scripts. Keep the single-root rule in both forms. Resolve child `x-*` tags from real Python imports in single-file components rather than `<!-- @import ... -->`. Prefer one focused component per file unless a file intentionally exports tiny, tightly coupled subcomponents. See `node_modules/caspian-utils/dist/docs/components.md`.

### `tests/**/*.py` and `settings/check.py`

- This is the app's own testing and static-analysis layer, added on top of Caspian; the framework ships no test runner, so treat it as a workspace convention documented here and in `AGENTS.md`, not as a packaged Caspian feature.
- Run the whole gate with the single command `npm run check` (or `uv run python settings/check.py`). It runs `pyrefly` (type check), `ruff` (lint), and `pytest` (tests) against `main.py` and `src/**`, prints each problem as `path:line:col [tool:code] message`, and exits non-zero when any check fails. For debugging one tool, use `uv run python settings/check.py --only pyrefly` (or `ruff` / `pytest`).
- `npm run check` only reports. Auto-fix with `npm run check:fix`, which runs `settings/fix.py` (safe ruff fixes, then the gate). pyrefly and pytest failures are never auto-fixed.
- Unused-import (`F401`) removal is handled carefully because component imports look unused to ruff. Single-file components import children used only as `<x-*>` tags in `html(...)`/`render_html(...)` templates (`from .Dialog import DialogContent` → `<x-dialog-content>`); ruff cannot see that, and Caspian resolves the tag from module globals at render time, so deleting the import breaks rendering. Two layers keep it safe: `F401` is `unfixable` in `[tool.ruff.lint]` so a raw `ruff check --fix` never deletes any import; and `settings/fix.py` removes dead imports only from files that contain no `<x-*>`-tag import (component-guarded files are skipped whole and left for the gate). `settings/check.py` likewise suppresses the `F401` reports whose symbol is used as an `x-{camel_to_kebab(name)}` tag, so the gate fails only on genuinely dead imports. The tag detection is shared in `settings/_component_imports.py`. Do not blanket-ignore `F401` or re-enable its autofix globally. See `node_modules/caspian-utils/dist/docs/testing.md`.
- Keep tests in `tests/` app-focused: `main.py` helpers and route behavior (via `starlette.testclient.TestClient` against `main.app`), and `src/lib/**` policy such as `auth_config.py`. Do not test framework internals under `.venv/Lib/site-packages/casp/**`.
- `tests/conftest.py` puts the project root on `sys.path` and sets safe dev env defaults (`APP_ENV`, `AUTH_SECRET`) so importing `main` never fails during tests; extend it rather than duplicating that setup per test file.
- When adding or changing app-owned Python, add or extend the matching test and keep `npm run check` green before finishing. New tests follow `tests/test_*.py`.
- Tooling and config live in `pyproject.toml`: dev tools in `[dependency-groups] dev` (install/refresh with `uv sync --group dev`), type checking in `[tool.pyrefly]` (includes `main.py` and `src/**`), linting in `[tool.ruff]` (correctness-focused; `E501` line length and `I` import ordering are intentionally not enforced on generated starter code), and tests in `[tool.pytest.ini_options]`.
- `[tool.pyrefly.errors]` suppresses `bad-return` and `bad-assignment`, so those specific type-error kinds are not reported by the gate; do not assume every annotation mismatch is caught.
- Treat `settings/check.py` as the app-owned orchestrator for the gate. Keep it as the single entry point (parses each tool's output into the shared `path:line:col` report). The only sanctioned `package.json` scripts are `check` (report) and `check:fix` (auto-fix then report); do not add parallel one-off `test`, `lint`, or `typecheck` scripts when the `--only` flag already covers per-tool debugging.

### `public/js/main.js`

- Treat `public/js/main.js` as the thin browser bootstrap entry point.
- Keep it minimal and point it at the runtime shipped in `public/js/pp-reactive-v2.js`.
- Do not duplicate PulsePoint runtime logic here.

### `public/js/pp-reactive-v2.js`

- Treat `public/js/pp-reactive-v2.js` as the browser-side PulsePoint runtime source of truth for component execution, refs, directives, SPA navigation, and `pp.rpc(...)` behavior.
- Preserve the current public runtime contract unless the task explicitly changes Caspian frontend behavior.
- At runtime, component logic is discovered from `script[type="text/pp"]` inside `pp-component` roots. In authored route, layout, and component templates, write plain `<script>` and let `main.py` plus `casp.scripts_type.transform_scripts(...)` add the type.
- The current SPA scroll contract is: save scroll positions per history entry, reset window scroll on push navigation, and use `pp-reset-scroll="true"` to opt specific containers into reset behavior. Use `body[pp-reset-scroll="true"]` only when a target route should reset every scrollable surface.

### `src/app/**/*.html`

- Compose pages from components first (see "Component-First Page Composition"). Keep `index.html` a short assembly of `x-*` chunk components (top menu, sidebar, content sections, cards, forms, footer, and other repeated blocks) instead of a long inline HTML body. When a route would carry a long stretch of markup, move that markup into a single-file `html(...)` component and render it as an `x-*` tag here.
- Keep route templates and layouts server-rendered first, with PulsePoint enhancement as the default interactive layer.
- Keep visible page and layout markup in `index.html` and `layout.html`. Treat `index.py` and `layout.py` as backend companions for metadata, `page()` or `layout()`, `@rpc()` actions, auth checks, caching, redirects, and other server-side preparation, not as places to author visible HTML.
- When a route renders UI, author that markup in the route's `index.html` even if the route also has an `index.py` companion.
- When route templates import reusable Python components, render them as kebab-cased `x-*` tags such as `<x-button />` after top-of-file `<!-- @import Button from "..." -->` directives. The import comments belong above the single route root, not inside it.
- For route-level reactivity, prefer PulsePoint state, effects, refs, and template directives together with `pp.rpc(...)` instead of manual DOM mutation or ad hoc browser fetch code.
- For route-level buttons, forms, inputs, toggles, menus, filters, uploads, and list updates, bind events directly in the authored HTML with native PulsePoint-handled `on*` attributes such as `onclick`, `oninput`, `onchange`, and `onsubmit`. Avoid id-driven `querySelector`/`addEventListener` setup for first-party UI because it duplicates the PulsePoint event and rerender model.
- For simple route-level form submissions, collect the submitted fields with `Object.fromEntries(new FormData(event.currentTarget).entries())` inside the `onsubmit` handler and pass that object directly to `pp.rpc(...)`. Use `pp.state(...)` for pending/error/success UI and controlled non-native widgets; use `pp-ref` only when the handler needs imperative element access such as focus, measurement, file input reset, or third-party integration.
- Preserve standard Jinja template syntax such as `{{ ... }}` in layouts and `pp-*` runtime attributes in rendered HTML.
- Do not author `pp-component="..."` manually in route or layout templates; the Python render pipeline injects it onto the single root element.
- Do not author `type="text/pp"` manually in route or layout templates either. Use plain `<script>` in source and let the render path rewrite it.
- Keep authored route and layout templates to exactly one top-level parent node, the same constraint used for component templates. In source, that parent may be a native HTML element or a single imported `x-*` component tag. If a script is needed, keep it inside that parent instead of as a sibling top-level node. AI must follow this the same way React components return one parent node, otherwise Caspian raises `must have exactly one top-level HTML element so Caspian can inject pp-component`.
- For dashboard, admin, or grouped sections with multiple child routes, prefer folder-level `layout.html` wrappers in `src/app/**` instead of repeating the same shell in each child route.
- For grouped shells with independent sidebar and content scrolling, mark the content pane with `pp-reset-scroll="true"` when that pane should start at the top on each child-route navigation. Do not put the attribute on the whole shell when the sidebar or rail should retain its own scroll.
- For upload managers and similar interactive lists, prefer `pp.state(...)` plus `pp-for` over manual DOM painting so rerenders keep the list stable.
- For route-owned WebSocket clients, use PulsePoint state, refs, and cleanup effects around the native `WebSocket`. Keep the socket object in `pp.ref(...)`, close it on component disposal, and keep socket event listeners inside the owning route template script.
- Do not assume WebSocket clients live in a dashboard or any fixed route. Put the browser client in whichever route owns that live experience, pass first-render socket values from the matching `index.py`, and use route auth policy plus WebSocket endpoint auth checks intentionally for public, private, or mixed channels.
- Do not assume React, Vue, JSX-first component syntax, HTMX, or another frontend runtime unless the user explicitly requests one.

### `prisma/**`

- Treat `prisma/schema.prisma` as the data-model source of truth.
- Treat `prisma.config.ts` as the datasource and migration or seed configuration source of truth.
- After changing `prisma/schema.prisma`, run `npx prisma migrate dev` first so migrations and the development database stay aligned.
- If the schema change affects seed data or `prisma/seed.ts`, run `npx prisma generate`, then ask for explicit user approval before running `npx prisma db seed` because the seed script may delete or replace table data.
- Run `npx ppy generate` after every schema change so the Python ORM files and `settings/prisma-schema.json` stay aligned with Prisma.
- Keep Node-side generation and seeding aligned with `npx prisma generate` and `prisma/seed.ts`.
- Keep Python-side database access aligned with `src/lib/prisma/**`, and treat that directory as generated output rather than a manual editing surface.

### `.venv/Lib/site-packages/casp/**/*.py`

- Treat these files as framework internals.
- Only change them when the task is explicitly about Caspian core behavior, installed-runtime debugging, or documentation that must match the installed implementation.
- If behavior changes here, update the matching docs under `node_modules/caspian-utils/dist/docs/`.
- `casp/runtime_security.py` owns framework-managed safe public-file serving, baseline non-CSP response headers, production-safe error messages, and production session-secret enforcement used by `main.py`.

### `.github/instructions/**/*.instructions.md`

- Treat these files as workspace-local, task-scoped AI instructions for third-party libraries, design systems, icon packs, integrations, and narrowly scoped implementation rules.
- Check for a matching instruction file almost immediately before coding when the task mentions or touches a library or workflow that may have dedicated guidance, for example maddex, ppicons, or another named integration.
- Keep these files specific and discoverable: the filename, `description`, and `applyTo` pattern should make it obvious when the instruction applies.
- Use these files to guide implementation choices and coding style for that surface, but keep actual runtime behavior grounded in `caspian.config.json`, app code, and installed framework code.

### `node_modules/caspian-utils/dist/docs/**/*.md`

- These files are the packaged Caspian documentation layer, not the runtime and not the source of current workspace state.
- Use them to help AI answer three questions: which Caspian feature applies, which project files should be inspected next, and which workflow is appropriate once the feature is confirmed as enabled.
- Use `node_modules/caspian-utils/dist/docs/file-conventions.md` when deciding what belongs in `index.html`, `index.py`, `layout.html`, `layout.py`, `loading.html`, `not-found.html`, or `error.html`.
- Use `node_modules/caspian-utils/dist/docs/websockets.md` when deciding how to document or implement app-owned FastAPI WebSockets, browser `WebSocket` clients, origin checks, auth/session checks, message contracts, and the choice between WebSockets, RPC, and SSE.
- Verify behavior claims in this order:
  1.  `caspian.config.json`, then `main.py`, `src/lib/**`, `public/js/**`, `prisma/**`, `src/app/**`
  2.  `.venv/Lib/site-packages/casp/**`
  3.  the markdown file being edited
- Do not encode the current project's feature flags, file inventory, script list, or temporary status inside the packaged docs. Keep those facts in `.github/copilot-instructions.md`, `AGENTS.md`, or the project code.
- When an optional feature doc is edited, phrase it as feature guidance, for example `when caspian.config.json has mcp: true`, instead of as a project snapshot such as `this workspace has mcp: false`.
- When `caspian.config.json` has `tailwindcss: true`, document the current Tailwind flow as a full replacement: Python `merge_classes(...)` builds frontend `{twMerge(...)}` expressions and browser-side `twMerge(...)` resolves conflicts.
- Keep `index.md` discoverable as the manifest, keep cross-links aligned, and make each feature page explicit about when it applies and what file AI should inspect next.
