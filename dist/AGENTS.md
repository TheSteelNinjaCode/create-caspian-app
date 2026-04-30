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

## Workspace Clarifications

Use `.github/copilot-instructions.md` for the repo-wide implementation rules. This file keeps only the workspace-specific retrieval and maintenance notes that help AI decide where to look next.

- Local Caspian docs live under `node_modules/caspian-utils/dist/docs/`.
- Workspace file instructions live under `.github/instructions/**/*.instructions.md` when the repo needs task- or library-specific AI guidance that should not be always-on.
- Use `node_modules/caspian-utils/dist/docs/core-runtime-map.md` when a behavior is controlled by `main.py` or `.venv/Lib/site-packages/casp/**` and the owning file is not obvious yet.
- Before updating docs, verify runtime-specific claims such as middleware order, route param injection, `layout()` sync behavior, and `StateManager` persistence against the current `main.py` and installed `casp` package rather than copying older notes.
- When generating or reviewing `src/app/**/index.html`, `src/app/**/layout.html`, or component HTML templates, treat the single-root rule as a hard requirement: exactly one authored top-level parent element or one imported `x-*` root, with any owned `<script>` kept inside that same root. Do not allow sibling top-level tags, sibling scripts, or stray top-level text, because Caspian injects `pp-component` on that final root and errors if it cannot.

## Task Routing

Use this map before making changes.

If the task generates or edits route, layout, or component HTML templates, check `routing.md`, `components.md`, and `pulsepoint.md` before writing markup. Enforce the single-root contract there: one authored root only, any owned `<script>` inside that root, and no sibling top-level nodes.

| Task area                                 | Read first                                                                                                   | Verify against                                                                   |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Project layout and file placement         | `node_modules/caspian-utils/dist/docs/index.md`, `node_modules/caspian-utils/dist/docs/project-structure.md` | current workspace tree                                                           |
| Feature availability and tooling switches | `caspian.config.json`                                                                                        | current workspace tree, `main.py`, `prisma/**`, `public/js/**`                   |
| Framework internals and core-file lookup  | `node_modules/caspian-utils/dist/docs/core-runtime-map.md`                                                   | `main.py`, `.venv/Lib/site-packages/casp/**`, matching feature docs              |
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

## Docs Maintenance Rules

- Treat `node_modules/caspian-utils/dist/docs/**` as packaged Caspian feature docs and AI routing docs, not as a snapshot of the current project.
- Treat `.github/instructions/**/*.instructions.md` as the workspace-local instruction layer for third-party libraries and narrowly scoped implementation guidance.
- Keep workspace instruction files specific to the surface they govern. Use filenames, `description`, and `applyTo` patterns that help the agent discover the right file before coding.
- Do not duplicate broad Caspian or repo-wide rules across many instruction files; keep shared guidance in `.github/copilot-instructions.md` and this file.
- Do not record this project's current feature flags, script inventory, or temporary file tree status inside the packaged docs.
- Gate optional docs with `caspian.config.json`. Use phrasing such as `when caspian.config.json enables MCP` instead of `this workspace has mcp: false`.
- Use the packaged docs to make AI aware of what Caspian can do, when a doc applies, and which project files should be inspected next.
- Use `core-runtime-map.md` to map packaged docs back to `main.py` and installed `casp` modules instead of restating the full runtime file list in every page.
- When `caspian.config.json` has `tailwindcss: true`, document Tailwind class handling as the current contract: Python `merge_classes(...)` emits frontend `{twMerge(...)}` expressions and browser `twMerge(...)` resolves conflicts.
- Keep repo-specific clarifications in this file or `.github/copilot-instructions.md` rather than embedding them in the packaged docs unless the behavior is truly framework-wide.
- Keep `index.md` and cross-links aligned so AI can discover the right task doc quickly.
- Continue validating `routing.md`, `components.md`, `auth.md`, `fetch-data.md`, `cache.md`, `pulsepoint.md`, `validation.md`, `database.md`, and `mcp.md` against the installed `casp` runtime before changing behavior claims.

## Maintenance Checklist

Before merging doc or runtime changes:

1. Compare the claim or behavior against `main.py`, `src/lib/**`, and `.venv/Lib/site-packages/casp/**`.
2. Update the matching packaged doc in `node_modules/caspian-utils/dist/docs/` if the running behavior changed.
3. Update `.github/copilot-instructions.md` if the repo-wide implementation rules changed.
4. Update this file if the decision order, task routing, workspace clarifications, or packaged-doc maintenance rules changed.
