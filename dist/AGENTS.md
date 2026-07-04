# Caspian Agent Guide

## Purpose

This workspace is a Caspian application plus a packaged copy of the Caspian docs.

When you work here, use `caspian.config.json` and the code that actually runs as the source of truth for this project. Use workspace file instructions under `.github/instructions/**/*.instructions.md` as the task-specific instruction layer when they match the work, and use the packaged markdown docs under `node_modules/caspian-utils/dist/docs/` as the AI-facing Caspian feature and task-reference layer.

Do not treat the existence of a packaged doc as proof that the feature is enabled in this project.

## Document Ownership

- Keep repo-wide always-on rules in `.github/copilot-instructions.md`.
- Keep this file focused on decision order, task routing, workspace-specific clarifications, and packaged-doc maintenance.
- Keep packaged docs under `node_modules/caspian-utils/dist/docs/` framework-oriented and use `core-runtime-map.md` when those docs need to point AI back to `main.py` or the installed `casp` runtime.

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

Before making feature, tooling, or scaffolding decisions, read `caspian.config.json` almost immediately. Treat it as the workspace feature gate for flags such as `backendOnly`, `tailwindcss`, `mcp`, `prisma`, `typescript`, `websocket`, and `componentScanDirs`.

Treat `caspian.config.json` as the single source of truth for whether an optional Caspian feature is enabled in the current workspace. Use feature-specific docs only after the matching flag is confirmed as enabled. If a feature is disabled and the user wants it, ask whether they want to enable it first, then follow the Caspian update workflow to refresh framework-managed files.

When `.github/instructions/**/*.instructions.md` files exist, treat them as workspace-local instructions for specific third-party libraries, component kits, icon systems, integrations, and implementation rules. Read the matching instruction before deciding how to implement work on that surface, but do not let it override `caspian.config.json`, the project code, or the installed runtime.

## BrowserSync URL source of truth

When AI needs to test or confirm whether a page route, exposed function request, proxy-backed response, or local server workflow is working, check `./settings/bs-config.json` first.

Important rules:

- use `./settings/bs-config.json` as the source of truth for the active BrowserSync URLs in this app
- do **not** assume the proxy remains on the default `http://localhost:5090`; if that port is already in use, Caspian may use a different port
- confirm the current `local`, `external`, `ui`, and `uiExternal` values in `./settings/bs-config.json` before suggesting a browser URL, route test URL, or BrowserSync UI URL
- when frontend console logs, network errors, or terminal output suggest the app is being tested through the wrong URL or proxy port, re-check `./settings/bs-config.json` before changing app code

## Workspace Clarifications

Use `.github/copilot-instructions.md` for the repo-wide implementation rules. This file keeps only the workspace-specific retrieval and maintenance notes that help AI decide where to look next.

- Local Caspian docs live under `node_modules/caspian-utils/dist/docs/`.
- Workspace file instructions live under `.github/instructions/**/*.instructions.md` when the repo needs task- or library-specific AI guidance that should not be always-on.
- Use `node_modules/caspian-utils/dist/docs/core-runtime-map.md` when a behavior is controlled by `main.py`, package-owned runtime helpers such as `.venv/Lib/site-packages/casp/runtime_security.py`, or other `.venv/Lib/site-packages/casp/**` files and the owning file is not obvious yet.
- Use `node_modules/caspian-utils/dist/docs/pulsepoint-runtime-map.md` when a behavior is controlled by the shipped PulsePoint browser runtime and the task names state, effects, refs, context, portals, directives, `pp.rpc`, uploads, streaming, SPA navigation, or scroll restoration.
- Use `node_modules/caspian-utils/dist/docs/websockets.md` when the task names WebSockets, live bidirectional channels, socket origin checks, socket auth/session behavior, broadcast managers, or native browser `WebSocket` clients.
- Use `node_modules/caspian-utils/dist/docs/file-conventions.md` when the task asks what belongs in `index.html`, `index.py`, `layout.html`, `layout.py`, `loading.html`, `not-found.html`, or `error.html`.
- When `caspian.config.json` has `prisma: true`, database reads and writes from Python routes, layouts, RPC actions, upload flows, auth flows, and helpers must use the generated Prisma Python ORM in `src/lib/prisma/**`. Do not create a separate database fetch layer with raw drivers, hand-written SQL helpers, JSON manifests, app-specific HTTP fetches, or browser-side data fetches to replace the ORM. Use raw SQL only as a narrow Prisma ORM fallback when the generated client cannot express a query clearly.
- Treat `npx prisma db seed` as a delicate, potentially destructive operation. In this workspace, seed scripts may clear tables before inserting fresh records. Before running that command, an AI agent must propose the exact command, warn that it can delete or overwrite database data including production data if the datasource is wrong, confirm the datasource when practical, and wait for explicit user approval.
- Component-first page composition is the highest-priority authoring rule for this workspace (see `.github/copilot-instructions.md`). Build pages as a short assembly of `x-*` chunk components (top menu, sidebar, header, content sections, cards, forms, footer) and keep each chunk's long markup inside its own focused single-file `html(...)` component, so `src/app/**/index.html` stays small instead of holding a wall of HTML. Plan the chunk breakdown before writing the route, not as a later cleanup pass.
- Split single-file Python components by responsibility, using the same mental model as React components. A page with tabs should usually have one component for the tab shell and separate components for each substantial tab panel. A section with its own form, table, toolbar, or list should usually be its own component with data and options passed by props, not an unrelated block inside a giant Python file.
- Components may be authored as a single Python file. Import `html` from `casp.component_decorator` and return `html("""...""", **context)` to keep markup, server interpolation, and a PulsePoint `<script>` inline, instead of pairing the `.py` with a same-name `.html` through `render_html(...)`. Inside `html(...)`, `{{ ... }}` is server-side Jinja and `{ ... }` stays for PulsePoint; do not use a Python f-string for the markup. Prefer single-file `html(...)` for small and medium components and keep `render_html(...)` plus a `.html` file for large markup or long scripts. Both forms render identically through `transform_components(...)` then `transform_scripts(...)`. See `node_modules/caspian-utils/dist/docs/components.md`.
- For component-to-component composition, use real Python imports inside single-file `html(...)` components instead of placing `<!-- @import ... -->` inside the returned HTML string. A component's own `x-*` tags resolve from the components imported into its Python module, which disambiguates same-name components across directories. Runtime resolution precedence inside a component's output is inherited ancestor components, then the component's own Python imports, then a local `@import` in that same template, but the authoring pattern for single-file components is Python imports. Slot content (children) resolves in the scope where it was authored, so the component that writes an `x-*` tag in markup must import that component.
- For first-party HTML interactivity in this workspace, PulsePoint is the required default. Use PulsePoint `on*` event attributes, `pp.state`, refs, effects, directives, and `pp.rpc()` instead of inventing id/data-attribute driven JavaScript with `querySelector`, `getElementById`, `addEventListener`, manual `innerHTML`, or parallel client state. For simple forms, bind `onsubmit` in the HTML, convert named fields with `Object.fromEntries(new FormData(event.currentTarget).entries())`, and validate/normalize that payload in Python; do not add `pp-ref` to each input, create a form ref, and attach an effect-managed submit listener just to collect submitted values.
- When `caspian.config.json` has `websocket: true`, WebSocket behavior is app-owned in `main.py`. Do not assume fixed route names or endpoint paths across Caspian projects; define project-specific socket paths in the app, keep shared socket helpers in `src/lib/websocket/**` when needed, and let each route that needs a socket client pass its own `websocket_path` or `websocket_url` into its template.
- WebSocket pages may be public, authenticated, role-gated, or mixed depending on the app. Keep route-specific browser UI in that route's `src/app/**/index.html`, keep first-render socket URL/path values in the matching `index.py`, and keep reusable session/auth/connection/broadcast helpers out of route files only when they are shared.
- For WebSocket clients, use PulsePoint for component state and lifecycle but native `new WebSocket(...)` for the transport. Keep the socket in `pp.ref(...)`, close it in a cleanup effect, and keep direct socket event listeners inside the owning route template script.
- Before changing socket security, verify the app's origin allow-list logic, auth check, idle timeout, message-size limits, and close codes in the running code. HTTP route privacy and `AuthMiddleware` do not by themselves protect WebSocket scopes: the HTTP middleware stack early-returns on `scope["type"] == "websocket"`, so only `SessionMiddleware` runs and each socket endpoint must authorize itself.
- Socket authorization in this workspace is a single guard, `authorize_websocket(...)` in `src/lib/websocket/websocket_security.py`, that runs the origin check then delegates auth to Caspian's `Auth` (`Auth.set_request(websocket)` plus `is_authenticated`/`get_payload`/`check_role`). Reuse that guard for new channels and gate them with `require_auth=` / `roles=`; do not re-implement session/`exp`/payload parsing per endpoint. Keep authenticated and guest traffic in separate broadcast pools, and treat the socket session as read-only (mutations are not persisted to the cookie over a WebSocket).
- Keep route-specific backend logic in that route's `src/app/**/index.py`, including first-render data loading, route-owned `@rpc()` actions, auth checks, redirects, and validation. Move logic to `src/lib/**` only when it is shared by more than one route, feature, component, or integration.
- For grouped-subtree SPA navigation UX, the current browser runtime keeps unmarked shell scrollers stable and uses `pp-reset-scroll="true"` on the content pane that should reset. Check `pulsepoint.md`, `routing.md`, and `public/js/pp-reactive-v2.js` before changing that behavior.
- Before updating docs, verify runtime-specific claims such as middleware order, route param injection, `layout()` behavior, `StateManager` persistence, safe public-file serving, response header, or session-secret behavior against the current `main.py` and installed `casp` package, especially `.venv/Lib/site-packages/casp/runtime_security.py`, rather than copying older notes.
- When generating or reviewing `src/app/**/index.html`, `src/app/**/layout.html`, or component HTML templates, treat the single-root rule as a hard requirement: exactly one authored top-level parent element or one imported `x-*` root, with any owned `<script>` kept inside that same root. Do not allow sibling top-level tags, sibling scripts, or stray top-level text, because Caspian injects `pp-component` on that final root and errors if it cannot.
- When generating or reviewing sign-in flows, do not ask the sign-in page to decide redirect targets by re-implementing `next` support or post-login routing. In this stack, redirect behavior is already owned by the Caspian auth runtime plus `src/lib/auth/auth_config.py`; protected-route guest redirects, auth-route redirects, and the default destination are centralized there, with `default_signin_redirect` defaulting to `/dashboard`.
- Component markup is server-deferred in an inert `<template>`. `main.py` finalizes every page through `finalize_html(...)` = `transform_scripts(...)` then `defer_component_roots(...)`, which wraps each outermost `pp-component` root in `<template pp-component="…">`. The browser never parses/validates/fetches `<template>` contents, so raw `{...}` placeholders never reach live DOM at first paint; the PulsePoint `mount()` bootstrap materializes `template[pp-component]` back into live DOM (via `OwnedTemplateManager.materializeTemplateComponentBoundaries(document.body)`, which also runs on every SPA navigation) before it scans for roots. Because of this, `{...}` is safe in ANY attribute or position — SVG geometry (`d`, `viewBox`, `points`, `transform`), URL attributes (`src`, `srcset`, `href`, `poster`), form `value`/date/number/color, and text placed directly inside `<table>`/`<select>`. Do NOT add per-tag workarounds to dodge browser first-paint validation: no static-path `hidden` toggles just to avoid binding `d`, no `data-*` URL holders, no gating `<img src>` behind `hidden`, and no SSR-resolving an initial value only to prevent a validation flash. Two compiler transforms still apply for different reasons and stay: `pp-style` (so `.html` source-file HTML/CSS tooling does not choke on `style="{...}"`) and the `<input>`/`<select>`/`checked`/`defaultvalue`/`<textarea>` value rewrites (attribute-vs-property correctness for controlled form fields), not first-paint validation.

## Task Routing

Use this map before making changes.

If the task generates or edits route, layout, or component HTML templates, check `routing.md`, `components.md`, and `pulsepoint.md` before writing markup. Enforce the single-root contract there: one authored root only, any owned `<script>` inside that root, and no sibling top-level nodes. For reactive behavior, button clicks, form events, uploads, filters, toggles, and list updates, use PulsePoint in the template first instead of standard DOM-event wiring. For normal form submits, prefer `onsubmit="{submitForm(event)}"` plus `Object.fromEntries(new FormData(event.currentTarget).entries())` over `pp-ref`/`pp.effect` listener boilerplate.

- Project layout and file placement: read `node_modules/caspian-utils/dist/docs/index.md` and `node_modules/caspian-utils/dist/docs/project-structure.md`. Verify against the current workspace tree.
- File conventions and special route files: read `node_modules/caspian-utils/dist/docs/file-conventions.md` and `node_modules/caspian-utils/dist/docs/routing.md`. Verify against `main.py`, `.venv/Lib/site-packages/casp/layout.py`, `.venv/Lib/site-packages/casp/loading.py`, and `.venv/Lib/site-packages/casp/caspian_config.py`.
- Feature availability and tooling switches: read `caspian.config.json`. Verify against the current workspace tree, `main.py`, `prisma/**`, and `public/js/**`.
- Framework internals and core-file lookup: read `node_modules/caspian-utils/dist/docs/core-runtime-map.md`. Verify against `main.py`, `.venv/Lib/site-packages/casp/**`, and the matching feature docs.
- PulsePoint browser runtime lookup: read `node_modules/caspian-utils/dist/docs/pulsepoint-runtime-map.md` and `node_modules/caspian-utils/dist/docs/pulsepoint.md`. Verify against `public/js/pp-reactive-v2.js`, `main.py`, `.venv/Lib/site-packages/casp/scripts_type.py`, and `.venv/Lib/site-packages/casp/components_compiler.py`.
- Library-specific and task-specific rules: read the matching `.github/instructions/**/*.instructions.md` file. Verify against `caspian.config.json`, the current workspace tree, and the owning app and lib files.
- MCP server layout and launch flow: read `node_modules/caspian-utils/dist/docs/mcp.md`. Verify against `settings/restart-mcp.ts`, `package.json`, and `src/lib/mcp/**`.
- Routing, layouts, metadata: read `node_modules/caspian-utils/dist/docs/routing.md`. Verify against `main.py` and `.venv/Lib/site-packages/casp/layout.py`.
- SPA navigation and scroll restoration: read `pulsepoint.md`, `routing.md`, and `core-runtime-map.md`. Verify against `public/js/pp-reactive-v2.js`, `src/app/**/layout.html`, and `main.py`.
- Auth, sessions, RBAC, providers: read `node_modules/caspian-utils/dist/docs/auth.md`. Verify against `src/lib/auth/auth_config.py`, `main.py`, `.venv/Lib/site-packages/casp/runtime_security.py`, and `.venv/Lib/site-packages/casp/auth.py`.
- Social login (Google or GitHub sign-in): treat it as shipped. `main.py` already registers both providers via `Auth.set_providers(...)`, and `AuthMiddleware` already serves `/api/auth/signin/{google,github}` and `/api/auth/callback/{google,github}`. Link a button at the signin path and set `.env` credentials instead of hand-rolling OAuth. Read `node_modules/caspian-utils/dist/docs/auth.md` "OAuth Providers" and verify against `main.py` plus `src/lib/auth/auth_config.py`.
- RPC, data loading, streaming, uploads: read `node_modules/caspian-utils/dist/docs/fetch-data.md` and `node_modules/caspian-utils/dist/docs/pulsepoint.md`. Verify against `.venv/Lib/site-packages/casp/rpc.py`, `public/js/pp-reactive-v2.js`, and `main.py`.
- AI/LLM/chat or any one-way streaming output: use the shipped RPC streaming path (generator `@rpc()` that `yield`s chunks, consumed by `pp.rpc(..., { onStream })`); for an LLM SDK, `async for ... yield`. Read `node_modules/caspian-utils/dist/docs/fetch-data.md` "Streaming Responses" and `node_modules/caspian-utils/dist/docs/pulsepoint.md`. Verify against `.venv/Lib/site-packages/casp/streaming.py`, `.venv/Lib/site-packages/casp/rpc.py`, `public/js/pp-reactive-v2.js`, and `main.py`. Do not reinvent with raw `fetch`/`ReadableStream`, `EventSource`, or WebSockets.
- WebSockets and live channels: first confirm `caspian.config.json` has `websocket: true`, then read `node_modules/caspian-utils/dist/docs/websockets.md`. Verify against `main.py`, `src/lib/websocket/**` when present, the owning `src/app/**` route files, and `settings/bs-config.json`.
- File uploads and managers: read `node_modules/caspian-utils/dist/docs/file-uploads.md` and `node_modules/caspian-utils/dist/docs/fetch-data.md`. Verify against `src/app/**`, `src/lib/**`, `prisma/**`, and `settings/bs-config.ts`.
- Server state: read `node_modules/caspian-utils/dist/docs/state.md`. Verify against `.venv/Lib/site-packages/casp/state_manager.py` and `main.py`.
- Page caching: read `node_modules/caspian-utils/dist/docs/cache.md`. Verify against `.venv/Lib/site-packages/casp/cache_handler.py` and `main.py`.
- Validation: read `node_modules/caspian-utils/dist/docs/validation.md`. Verify against `.venv/Lib/site-packages/casp/validate.py`.
- Database and seed flow: read `node_modules/caspian-utils/dist/docs/database.md`. Verify against `prisma/schema.prisma`, `prisma/seed.ts`, and `src/lib/prisma/**`.

## Docs Maintenance Rules

- Treat `node_modules/caspian-utils/dist/docs/**` as packaged Caspian feature docs and AI routing docs, not as a snapshot of the current project.
- Treat `.github/instructions/**/*.instructions.md` as the workspace-local instruction layer for third-party libraries and narrowly scoped implementation guidance.
- Keep workspace instruction files specific to the surface they govern. Use filenames, `description`, and `applyTo` patterns that help the agent discover the right file before coding.
- Do not duplicate broad Caspian or repo-wide rules across many instruction files; keep shared guidance in `.github/copilot-instructions.md` and this file.
- Do not record this project's current feature flags, script inventory, or temporary file tree status inside the packaged docs.
- Gate optional docs with `caspian.config.json`. Use phrasing such as `when caspian.config.json enables MCP` instead of `this workspace has mcp: false`.
- Use the packaged docs to make AI aware of what Caspian can do, when a doc applies, and which project files should be inspected next.
- Use `core-runtime-map.md` to map packaged docs back to `main.py` and installed `casp` modules instead of restating the full runtime file list in every page.
- Use `pulsepoint-runtime-map.md` to map PulsePoint feature names and directives back to the shipped browser runtime instead of restating browser behavior in every page.
- When `caspian.config.json` has `tailwindcss: true`, document Tailwind class handling as the current contract: Python `merge_classes(...)` emits frontend `{twMerge(...)}` expressions and browser `twMerge(...)` resolves conflicts.
- Keep repo-specific clarifications in this file or `.github/copilot-instructions.md` rather than embedding them in the packaged docs unless the behavior is truly framework-wide.
- Keep `index.md` and cross-links aligned so AI can discover the right task doc quickly.
- Continue validating `file-conventions.md`, `routing.md`, `components.md`, `auth.md`, `fetch-data.md`, `websockets.md`, `cache.md`, `pulsepoint.md`, `validation.md`, `database.md`, and `mcp.md` against the installed `casp` runtime before changing behavior claims.

## Maintenance Checklist

Before merging doc or runtime changes:

1. Compare the claim or behavior against `main.py`, `src/lib/**`, and `.venv/Lib/site-packages/casp/**`.
2. Update the matching packaged doc in `node_modules/caspian-utils/dist/docs/` if the running behavior changed.
3. Update `.github/copilot-instructions.md` if the repo-wide implementation rules changed.
4. Update this file if the decision order, task routing, workspace clarifications, or packaged-doc maintenance rules changed.
