# Caspian — The Native Python Web Framework for the Reactive Web

Caspian is a FastAPI-powered full-stack framework that brings reactive UI to Python without a JavaScript backend. You write file-system routes, plain HTML templates, and `async def` Python — Caspian wires the browser to your server.

- **FastAPI engine** — async-native, with the Starlette/FastAPI middleware ecosystem underneath
- **PulsePoint** — a shipped browser runtime with a React-style hook API and **plain HTML** templates (no JSX, no build step required)
- **"Zero-API" RPC** — call Python functions from the browser with `pp.rpc()`; no controllers, no fetch boilerplate
- **File-system routing** with nested layouts, dynamic segments, and route groups (Next.js App Router mental model)
- **Python components** — reusable `@component` functions rendered as HTML-first `x-*` tags
- **Prisma ORM** with a generated, typed Python client
- **Session auth** with RBAC and OAuth providers, plus fail-closed security defaults
- **Optional**: Tailwind CSS, TypeScript tooling, MCP server, WebSockets — each gated by one config flag

> **The full manual ships inside every project** at `node_modules/caspian-utils/dist/docs/` (start at `index.md`). This README is the tour; that folder is the reference.

---

## Quick Start

Requires **Python 3.14+** and **Node.js** with `npm`/`npx` (used for the CLI, Prisma, Tailwind, and the dev stack).

```bash
npx create-caspian-app@latest
```

The wizard asks for a project name, feature toggles (backend-only, Tailwind, Prisma, MCP, TypeScript), and a starter kit (`basic`, `fullstack`, `api`, `realtime`, or a custom Git source). Then:

```bash
npm run dev
```

`npm run dev` runs a **BrowserSync proxy plus asset watchers**, not a Vite dev server that owns the page. The proxy does not always land on its default port — check `settings/bs-config.json` for the active URL.

---

## What "Reactive Python" looks like

A route is a folder with one file: `index.py`. Markup lives inline in `html(r"""...""")`, next to the server logic.

```python
# src/app/todos/index.py
from casp.component_decorator import html
from casp.layout import Metadata
from casp.rpc import rpc
from casp.validate import Rule, Validate

from src.lib.prisma import prisma

metadata = Metadata(title="Todos", description="A tiny Caspian todo list.")


async def page():
    return html(r"""
<section>
  <form onsubmit="{addTodo(event)}">
    <input name="title" required />
    <button type="submit" disabled="{isSaving}">Add</button>
  </form>

  <ul>
    <template pp-for="(todo, index) in todos">
      <li key="{todo.id}" class="border-b p-2">
        {index + 1}. {todo.title}
        <button onclick="{removeTodo(todo.id)}">Remove</button>
      </li>
    </template>
  </ul>

  <p hidden="{todos.length > 0}">Nothing here yet.</p>

  <script>
    const [todos, setTodos] = pp.state([]);
    const [isSaving, setIsSaving] = pp.state(false);

    pp.effect(() => {
      pp.rpc("list_todos").then(setTodos);
    }, []);

    async function addTodo(event) {
      event.preventDefault();
      setIsSaving(true);
      try {
        const data = Object.fromEntries(
          new FormData(event.currentTarget).entries(),
        );
        setTodos([await pp.rpc("create_todo", data), ...todos]);
        event.currentTarget.reset();
      } finally {
        setIsSaving(false);
      }
    }

    async function removeTodo(id) {
      await pp.rpc("delete_todo", { id });
      setTodos(todos.filter((todo) => todo.id !== id));
    }
  </script>
</section>
""")


@rpc()
async def list_todos():
    todos = await prisma.todo.find_many(order_by={"id": "desc"})
    return [todo.to_dict() for todo in todos]


@rpc()
async def create_todo(title: str):
    checked = Validate.with_rules(title, [Rule.REQUIRED, Rule.min(3)])
    if checked is not True:
        raise ValueError("Title must be at least 3 characters.")
    todo = await prisma.todo.create(data={"title": title.strip(), "completed": False})
    return todo.to_dict()


@rpc(require_auth=True)
async def delete_todo(id: int):
    await prisma.todo.delete(where={"id": int(id)})
    return {"deleted": True}
```

That is the whole loop — no API routes, no client, no serializer. `pp.rpc("create_todo", data)` posts to the current route; Caspian resolves the decorated function, filters the payload against its signature, runs it, and returns JSON.

---

## Core concepts

### 1. Routing

The directory structure under `src/app` is the URL structure.

```
src/app/index.py                   ->  /
src/app/blog/posts/index.py        ->  /blog/posts
src/app/users/[id]/index.py        ->  /users/123        (dynamic segment)
src/app/docs/[...slug]/index.py    ->  /docs/a/b/c       (catch-all)
src/app/(auth)/login/index.py      ->  /login            (route group, no URL segment)
src/app/dashboard/layout.py        ->  wraps every /dashboard/* page
```

Path params arrive as one positional dict (`async def page(params: dict)`); query params inject by name; `request` injects when declared. `page()` returns `html(r"""...""", **context)`, or a `(page_html, layout_props)` tuple whose keys become `{{ layout.* }}` in a parent layout.

**Special files.** Only `index.py` is required — the rest are optional, and each owns a behavior you should not hand-build.

| File           | Export                             | Owns                                                                          |
| -------------- | ---------------------------------- | ----------------------------------------------------------------------------- |
| `index.py`     | `page()`                           | The page, plus `metadata`, route-owned `@rpc()`, redirects, first-render data |
| `layout.py`    | `layout()`                         | A subtree shell containing `<slot />`, plus optional props and metadata       |
| `loading.py`   | `loading()`                        | Loading UI shown while navigating **between routes**                          |
| `not_found.py` | `page()`                           | Global 404 page                                                               |
| `error.py`     | `page(error_message, error_trace)` | Global 500 page                                                               |

`loading.py` is worth knowing because it is easy to reinvent: `loading()` is **synchronous and takes no parameters**, its URL scope comes from its folder (the closest ancestor wins), and its markup is injected as **raw HTML** — Jinja `{{ }}` interpolates, but `<x-*>` tags, `{ }` bindings, and `<script>` do nothing inside it. Mark the pane it replaces with `pp-loading-content="true"` in the layout. Most subtrees have none, and a route with no loader simply fades; add one only when a section wants it, and never replace it with a spinner component or a navigation-event listener.

---

### 2. Templates are plain HTML — not JSX

PulsePoint borrows React's **hook API** and its **component decomposition model**. It does **not** borrow JSX. This is the single most common source of broken pages.

```html
<!-- ❌ Silently corrupts the page -->
<div class="{cls}">…</div>
{isOpen &&
<div>Panel</div>
} {items.map(item => (
<li>{item.name}</li>
))}
<button className="btn" onClick="{save}">Save</button>

<!-- ✅ The PulsePoint equivalents -->
<div class="{cls}">…</div>
<div hidden="{!isOpen}">Panel</div>
<template pp-for="item in items"><li key="{item.id}">{item.name}</li></template>
<button class="btn" onclick="{save()}">Save</button>
```

An unquoted `class={...}` is **invalid HTML**: the parser splits it on spaces into junk attributes, the component root never compiles, and the route serves a blank page **with no console error**.

**Sanity check:** delete every `{}` from the template. What remains must still be valid HTML.

**The directive list is closed.** There is no `pp-if`, `pp-show`, `pp-else`, `pp-model`, or `pp-key`.

| Syntax                                                | Where                                      | Purpose                            |
| ----------------------------------------------------- | ------------------------------------------ | ---------------------------------- |
| `{expression}`                                        | Text nodes and **quoted** attribute values | Interpolation                      |
| `onclick`, `oninput`, `onsubmit`, any `on*`           | Any element                                | Event binding                      |
| `pp-for="item in items"` / `"(item, index) in items"` | **`<template>` only**                      | List rendering                     |
| `key="{expr}"`                                        | The repeated element                       | Diffing identity                   |
| `pp-ref="name"` / `pp-ref="{expr}"`                   | Native elements and `x-*` tags             | Imperative element access          |
| `defaultvalue` / `defaultchecked`                     | Form controls                              | Uncontrolled seed (lowercase)      |
| `pp-style="{cssText}"`                                | Any element                                | Dynamic inline style (string)      |
| `pp-spread="{...obj}"`                                | Any element                                | Spread object into attributes      |
| `<token.provider value="{v}">` (lowercase)            | Anywhere                                   | Context provider                   |
| `pp-spa="false"`                                      | An `<a>`                                   | Opt one link out of SPA navigation |
| `pp-reset-scroll`, `pp-scroll-key`                    | A scroll container                         | Scroll restoration control         |
| `pp-loading-content="true"`                           | The pane swapped during navigation         | Where `loading.py` markup lands    |

A form control is controlled (`value="{state}"` + `oninput`) **or** uncontrolled (`defaultvalue="{expr}"`) for its lifetime, never both. Never hand-write runtime-managed attributes (`pp-component`, `pp-owner`, `pp-ref-forward`, `pp-loading-url`, `data-pp-*`, …) — the pipeline injects them.

**Root shape.** Default to one top-level element with the owned `<script>` **inside** it. Beyond that: a **component** with sibling top-level nodes becomes a fragment (the `<>…</>` equivalent) that adds no element to the DOM — but a fragment has no root, so it **cannot receive props**; give it a single native root when it takes any. A **page or layout** with sibling top-level nodes gets a layout-neutral `display: contents` boundary host instead, so skip the meaningless wrapper `<div>` when the sections really are siblings.

---

### 3. PulsePoint hooks

Component `<script>` blocks are plain JavaScript, evaluated in component scope. Only **top-level** declarations reach the template. Props are read from `pp.props` — there is no injected `props` variable.

- **State & derivation** — `pp.state`, `pp.reducer`, `pp.memo`, `pp.callback`, `pp.deferredValue`, `pp.optimistic`
- **Lifecycle** — `pp.effect`, `pp.layoutEffect` (cleanups must be synchronous; always pass a dependency array)
- **DOM & identity** — `pp.ref`, `pp.id` (for `id`/`for`/`aria-*` — never index-derived ids), `pp.portal`, `pp.imperativeHandle`
- **Cross-tree** — `pp.createContext` + a lowercase `<themecontext.provider value="{theme}">` tag + `pp.context(token)` in descendants
- **Resilience & external data** — `pp.errorBoundary` (`[error, reset]`), `pp.syncExternalStore` (subscribe must be `pp.callback(..., [])`-stable), `pp.transition`

Utilities: `pp.mount`, `pp.redirect`, `pp.rpc`, `pp.socket`, and `pp.enablePerf` / `disablePerf` / `getPerfStats` / `resetPerfStats`.

React APIs with **no** equivalent: `forwardRef`, `memo()` as a wrapper, `lazy`, `Suspense`, `useInsertionEffect`, `useActionState`, `useFormStatus`, free-function `startTransition`. `pp.transition()` reports an accurate `isPending` but does not time-slice — rendering is synchronous.

Inside an `on*` attribute the runtime injects `event` plus the aliases `e`, `$event`, `target`, `currentTarget`, and `el`.

**Performance ownership:** `pp.state` means "a render is required". Timers, request generations, cursors, and RPC-only query text belong in `pp.ref`, whose mutation never renders. Debouncing a setter limits frequency, not render cost.

---

### 4. Components

A component is a `@component` function whose markup is authored inline and rendered as a kebab-cased `x-*` tag.

```python
from casp.component_decorator import component, html
from casp.html_attrs import get_attributes, merge_classes


@component
def UserCard(user=None, **props):
    attributes = get_attributes({
        "class": merge_classes("card", props.pop("class", "")),
        "user-name": user["name"],
    }, props)

    return html(r"""
<div {{ attributes }}>
  <h3>{{ user.name }}</h3>
  <button onclick="{setLikes(likes + 1)}">Likes: {likes}</button>
  <script>
    const [likes, setLikes] = pp.state({{ user.likes | json }});
  </script>
</div>
""", attributes=attributes, user=user)
```

**`html(r"""...""")` is the one markup form** — always a raw triple-quoted literal. A non-raw string rewrites backslashes, so a regex or `\n` in the component script means one thing in the source and another at render. Never build markup as an **f-string**: it inverts the brace dialects (`{x}` becomes server interpolation), skips autoescaping while still marking the output trusted, and skips the `<x-*>` scope stash.

Three brace dialects coexist inside that literal: `{{ value }}` is server-side Jinja (autoescaped), `{{ value | json }}` safely serializes a server value into a `<script>`, `{# … #}` is a Jinja comment, and `{ value }` is left untouched for PulsePoint in the browser.

**Composition is Python-import-driven** — the import _is_ the registration:

```python
from src.components.Container import Container
from src.components.ui.Button import Button
from src.lib.ppicons import ArrowRight, Search   # -> <x-arrow-right />, <x-search />
```

`Container` → `<x-container />`, `CommandDialog` → `<x-command-dialog />`. If one file exports several components, import them from that file. Slot content resolves in the scope where it was **authored**, so the module writing an `x-*` tag must import it.

**Every prop the template reads must be re-emitted on the root.** This is the most common silent failure:

1. Attributes on the `x-*` tag reach Python as **raw string kwargs**, kebab-case converted to camelCase — `open="{permOpen}"` arrives as the literal string `"{permOpen}"`.
2. The component must deliberately re-emit them onto its single rendered root via `get_attributes({...}, props)` + `{{ attributes }}`.
3. PulsePoint derives `pp.props` from **the rendered root's attributes**, evaluating brace expressions in the parent's scope.

A prop accepted in Python but not re-emitted is silently `undefined` — no server error, no console warning. Forwarding does not preserve types either: a brace expression keeps its real type, a literal (`volume="0"`) arrives as a **string**, a valueless attribute arrives as `true`, `None`/`False`/`""` are omitted entirely, and JS reserved words such as `class` are dropped from `pp.props`.

When `tailwindcss: true`, `merge_classes(...)` emits a frontend-ready `{twMerge(...)}` expression that the browser's `twMerge(...)` resolves. Pass it straight through — never wrap or re-merge it.

---

### 5. Data: `pp.rpc()` and `@rpc()`

```js
await pp.rpc(name, data?, optionsOrAbort?)
```

Posts to the **current route** and resolves the `@rpc()` function of that name in its `index.py`. Serialization switches to `FormData` automatically when a `File` is present, the CSRF token is injected as `X-CSRF-Token`, and server redirects are honored through `pp.redirect()`. Passing `true` as the third argument means `{ abortPrevious: true }`.

Options: `abortPrevious`, `url`, `csrfUrl`, `credentials`, `onStream`, `onStreamError`, `onStreamComplete`, `onUploadProgress`, `onUploadComplete`.

**Payload safety:** RPC keys are filtered against the function signature, so a parameter is client-settable only when declared. Declaring `**kwargs` opts into the whole payload — do that deliberately, and always derive identity and ownership server-side from the session.

**Uploads** — pass the `File` through and read progress:

```js
await pp.rpc(
  "upload_asset",
  { file },
  {
    onUploadProgress: ({ percent }) => setPercent(percent),
    onUploadComplete: () => setPercent(100),
  },
);
```

`onUploadProgress` receives `{ loaded, total, percent }`; `total` and `percent` are `null` when the length is not computable.

**Streaming** (the path for AI/LLM token output) — a generator `@rpc()` becomes a `text/event-stream` response:

```python
@rpc()
async def ask_question(topic: str):
    async for chunk in llm.stream(topic):
        yield chunk
```

```js
pp.rpc(
  "ask_question",
  { topic },
  {
    onStream: (chunk) => setAnswer((current) => current + chunk),
    onStreamComplete: () => setIsStreaming(false),
  },
);
```

Do not reinvent one-way streaming with raw `fetch`/`ReadableStream`, `EventSource`, or a WebSocket.

---

### 6. Validation

```python
from casp.validate import Rule, Validate

email = Validate.email("  User@Example.com ")     # -> "User@Example.com"
count = Validate.int("42")                        # -> 42
bad   = Validate.url("not-a-url")                 # -> None

checked = Validate.with_rules(password, [Rule.REQUIRED, Rule.min(8)])
if checked is not True:
    return {"error": checked}
```

`Validate` covers strings and identifiers (`string`, `email`, `url`, `ip`, `uuid`, `ulid`, `cuid`, `cuid2`, `nanoid`), numbers (`int`, `big_int`, `float`, `decimal`), dates (`date`, `date_time`), `boolean`, and structured values (`json`, `enum`, `enum_class`). `Validate.string()` trims and HTML-escapes by default.

Browser-side checks are UX only. Server-side validation at the RPC/route boundary is authoritative.

---

### 7. Authentication

Session-based, configured centrally in `src/lib/auth/auth_config.py` and wired in `main.py`:

```python
from casp.auth import Auth, GithubProvider, GoogleProvider, configure_auth
from src.lib.auth.auth_config import build_auth_settings

configure_auth(build_auth_settings())
Auth.set_providers(GithubProvider(), GoogleProvider())
```

The `auth` instance exposes `sign_in(data, token_validity=None, redirect_to=False)`, `sign_out(redirect_to=None)`, `is_authenticated()`, `get_payload()`, `refresh_session()`, and `check_role(user, allowed_roles)`. Guards are `@rpc(require_auth=True)` for actions and `@require_auth()` / `@guest_only()` for pages, with public-vs-private route policy declared centrally.

**OAuth is already wired.** `Auth.set_providers(...)` registers `/api/auth/signin/{google,github}` and `/api/auth/callback/{google,github}`. Link a button and set the credentials in `.env` — do not hand-roll the flow.

**Redirect ownership is centralized.** Do not re-implement `next=` handling or post-login routing in a sign-in page; `auth_config.py` owns protected-route redirects, auth-route redirects, and `default_signin_redirect`.

---

### 8. Database (Prisma)

Enabled by `"prisma": true`. Define one `prisma/schema.prisma`; the typed Python client is generated into `src/lib/prisma/`.

```python
from src.lib.prisma import prisma

users = await prisma.user.find_many(
    where={"active": True},
    include={"userRole": True},
    order_by={"createdAt": "desc"},
)
```

**Two generators, one schema.** After any schema change, run exactly two commands in order — sync the database, then regenerate the Python ORM:

```bash
npx prisma migrate dev
```

```bash
npx ppy generate
```

`npx prisma generate` builds the **Node** client used by `prisma/seed.ts` and writes zero Python — it is never a substitute for `npx ppy generate`. Run it before `npx prisma db seed`, and note that **`db seed` may clear or overwrite tables; confirm the datasource first.**

`src/lib/prisma/**` and `settings/prisma-schema.json` are generated. Never hand-edit them, and never add a second data layer alongside the ORM.

---

### 9. Optional features

Every optional capability is gated by one flag in `caspian.config.json`. **That file is the single source of truth** — a doc or example mentioning a feature does not mean it is enabled in your project. To turn one on after scaffold, set the flag and run `npx casp update project`.

| Flag          | Enables                                                              |
| ------------- | -------------------------------------------------------------------- |
| `backendOnly` | API/service mode with no frontend assets                             |
| `tailwindcss` | Tailwind v4 + PostCSS pipeline, `merge_classes` / `twMerge` contract |
| `typescript`  | TypeScript frontend tooling and the Vite build path                  |
| `prisma`      | Prisma schema, migrations, and the generated Python ORM              |
| `mcp`         | A FastMCP server mounted into the same app (`/mcp`)                  |
| `websocket`   | Named sockets — `@socket()` in Python, `pp.socket()` in the browser  |

#### Named sockets

Use RPC for ordinary reads, writes, uploads, and one-way streams. Reach for a socket only when **both sides may speak at any time**: chat, collaboration, presence, multiplayer state. A named socket is the socket counterpart of `@rpc()`/`pp.rpc()` — one decorated Python function, one browser call.

```python
from src.lib.websocket.sockets import Socket, socket


@socket()
async def echo(label: str, socket: Socket):
    while (text := await socket.recv()) is not None:
        if not await socket.send(f"{label}: {text}"):
            break  # The browser is gone.
```

```js
const sock = pp.ref(null);

pp.effect(() => {
  sock.current = pp.socket(
    "echo",
    { label: "you" },
    {
      onMessage: (value) => append(value),
      onError: (error) => setStatus(error.message),
    },
  );
  return () => sock.current.close();
}, []);
```

Open the socket inside `pp.effect(..., [])`, keep the handle in `pp.ref(...)`, close it in the cleanup. The handle exposes `send(value)`, `close(code?, reason?)`, and `readyState`; handlers are `onOpen`, `onMessage(value)`, `onError(error)`, `onClose({ code, reason, wasClean })`.

The wire, in short:

- Every socket connects to **one endpoint**, wired once in `main.py`. The function is named in a query parameter, so socket names are **application-wide** and a duplicate is refused at registration.
- Arguments travel as the connection's **first frame** — one JSON object, exactly the payload `pp.rpc` would have posted — not in the URL, which every proxy logs. Keys are filtered against the handler signature, like RPC.
- There is no status line inside an open connection, so **failure is a frame**: `{"error": "..."}`, then a close — routed to `onError`, never `onMessage`. A handler that returns ends the conversation, and `await socket.send(...)` returning `False` means the browser is gone: a signal to stop, not an error to report.
- **Broadcast:** `socket.sender()` returns a detached `SocketSender` safe to hold in shared state; a room is a `SocketPool` of senders that prunes departed connections as it broadcasts. Keep authenticated and guest traffic in **separate pools**.
- **Auth is declared per socket:** `@socket()` is public, `@socket(require_auth=True)` needs a session, `@socket(allowed_roles=[...])` adds RBAC.

A socket in a route's `index.py` registers when that route first renders; one shared by several routes belongs in `src/lib/**`. A hand-written `@app.websocket(...)` route stays the escape hatch for wires the JSON-frame contract cannot carry (binary frames, non-JSON protocols) — and then the app owns every security check itself.

#### MCP

When `mcp: true`, a FastMCP server is mounted into the same app so one deploy serves both web and MCP. The endpoint sits **outside** the routing tree, so `AuthMiddleware` does not cover it — `MCP_AUTH_TOKEN` is its credential. With no token it stays open in development and returns **503 in production**.

---

## Security defaults

Caspian ships fail-closed. Worth knowing before changing any of it:

- **`APP_ENV` resolves fail-closed.** Only an explicit development value (`dev`, `development`, `local`, `staging`, `test`, `testing`) enables relaxations. Unset or misspelled counts as **production**.
- **Server-interpolated values never carry live PulsePoint syntax.** Jinja encodes `{` / `}` as entities on every non-`Markup` value, so stored user data cannot execute as a template expression. `Markup` is the trust boundary — `| safe`, `get_attributes(...)`, `merge_classes(...)`, and the `json` filter legitimately keep their braces.
- **Authenticated renders are never cached.** The page cache keys on the URI alone, so an eligibility check gates both read and write; a route's `Cache(...)` cannot override it.
- **RPC payload keys are filtered against the function signature.**
- **`/uploads` serves user content in attachment mode**; only real image types render inline. First-party `/css`, `/js`, and `/assets` stay inline.
- **Sockets authorize themselves.** The HTTP middleware stack early-returns on `scope["type"] == "websocket"`, so `AuthMiddleware` never sees a handshake — HTTP route privacy does not extend to a socket.
- **CSRF protection, strict Origin validation, HttpOnly cookies, security headers, and page rate limiting** are on by default.

Security-relevant environment variables: `MCP_AUTH_TOKEN`, `RATE_LIMIT_PAGES` (default `200/minute`), `CONTENT_SECURITY_POLICY` (replaces the default policy wholesale), `MAX_WEBSOCKET_CONNECTIONS`, `MAX_WEBSOCKET_MESSAGE_BYTES`, `MAX_WEBSOCKET_MESSAGES_PER_WINDOW`, `WEBSOCKET_RATE_WINDOW_SECONDS`, `WEBSOCKET_IDLE_TIMEOUT_SECONDS`, and `WEBSOCKET_ALLOWED_ORIGINS` (**required in production** — the same-origin fallback is derived from the client-supplied `Host` header and is development-only).

---

## Project structure

```
my-app/
├── main.py                      # FastAPI entry point, middleware stack, socket + MCP mounts
├── caspian.config.json          # Feature flags — the single source of truth
├── prisma/schema.prisma
├── src/
│   ├── app/                     # File-system routes
│   │   ├── layout.py            # Root layout
│   │   ├── index.py             # Home page (markup + logic in one file)
│   │   ├── globals.css
│   │   ├── not_found.py         # Global 404
│   │   ├── error.py             # Global 500
│   │   ├── dashboard/loading.py # Optional: /dashboard navigation loading UI
│   │   └── users/[id]/index.py  # /users/:id
│   ├── components/              # Reusable UI (@component)
│   └── lib/                     # Non-UI code
│       ├── auth/auth_config.py
│       ├── prisma/              # Generated Python ORM — do not edit
│       ├── websocket/           # Named sockets: @socket(), Socket, SocketPool
│       └── mcp/                 # FastMCP server (when mcp: true)
├── public/                      # Static assets, incl. the PulsePoint runtime and uploads
└── settings/                    # Dev stack config and generated indexes
```

**Placement rules**

- **Route-owned** logic (first-render query, route `@rpc()` actions, redirects, validation) stays in that route's `index.py`. Move it to `src/lib/**` only when genuinely shared.
- **Reusable UI** goes in `src/components/`; **helpers, services, adapters** go in `src/lib/`.
- **Compose pages from components.** A route's template should read as a short assembly of `x-*` chunks (topbar, sidebar, sections, forms, footer), not a wall of markup. Plan the breakdown before writing the route.
- **Generated, never hand-edited:** `src/lib/prisma/**`, `settings/prisma-schema.json`, `settings/files-list.json`, `settings/component-map.json`, `public/css/styles.css`.

---

## CLI reference

```bash
npx create-caspian-app my-app
```

| Flag                         | Description                                       |
| ---------------------------- | ------------------------------------------------- |
| `-y`                         | Non-interactive; skip all prompts                 |
| `--backend-only`             | API/service project, no frontend assets           |
| `--tailwindcss`              | Enable Tailwind CSS                               |
| `--typescript`               | Enable TypeScript frontend tooling                |
| `--prisma`                   | Enable Prisma ORM                                 |
| `--mcp`                      | Enable MCP server scaffolding                     |
| `--starter-kit=<kit>`        | `basic`, `fullstack`, `api`, `realtime`, `custom` |
| `--starter-kit-source=<url>` | Git repository for `--starter-kit=custom`         |
| `--list-starter-kits`        | Print the built-in starter catalog                |

In `-y` mode every feature defaults to `false`, and starter-kit presets can still be overridden by explicit flags. `websocket` has no create flag — enable it in `caspian.config.json` after scaffold, then run `npx casp update project` (which also accepts `--tag beta` / `--version 1.2.3` and `-y`). Use `excludeFiles` in `caspian.config.json` to protect files you have customized (commonly `./src/lib/auth/auth_config.py`) from being overwritten on update.

**Project scripts**

| Command                | What it does                                                       |
| ---------------------- | ------------------------------------------------------------------ |
| `npm run dev`          | Full local stack: BrowserSync proxy, Tailwind watch, asset watch   |
| `npm run build`        | Build Tailwind and regenerate the route/component index            |
| `npm run static`       | Export every static route to `static/` (SSG)                       |
| `npm run static:serve` | Preview the exported folder on an auto-selected free loopback port |

These are opt-in workflows — don't run them as a validation step just because source files changed.

---

## Static export (SSG)

`npm run static` boots the app and writes `static/<route>/index.html` plus copied public assets — the equivalent of Next.js `output: export`, running `npm run build` first so the export walks a fresh route index. Policy is **warn & skip**: dynamic routes are pre-rendered only when their `index.py` exports `static_paths` (the `getStaticPaths` equivalent); auth-gated, non-200, and non-HTML routes are reported and skipped.

`npm run static:serve` serves only `static/`, binds loopback `127.0.0.1` (network exposure is opt-in via `HOST=0.0.0.0`), and walks upward from port 8000 until it finds a free one — **read the port it prints**. `pp.rpc()`, auth, WebSockets, streaming, and per-request server data are all inert in a static export.

---

## Ecosystem

Two CLIs install ready-made Python components into `src/lib/`, where they behave like any other `x-*` tag:

```bash
npx ppicons add Rocket          # 1,500+ Lucide-based icons
npx maddex add button card dialog   # shadcn-style UI kit
```

```python
from src.lib.ppicons import Rocket        # -> <x-rocket class="size-6" />
from src.lib.maddex.Button import Button  # -> <x-button variant="outline">Continue</x-button>
```

---

## Recommended VS Code setup

- **[Caspian Official Framework Support](https://marketplace.visualstudio.com/items?itemName=JeffersonAbrahamOmier.caspian)** — component snippets and autocomplete (the key piece)
- **[Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)** — ships Pylance, which is Pyright under the hood
- **[Prisma](https://marketplace.visualstudio.com/items?itemName=Prisma.prisma)** — schema formatting and highlighting
- **[Tailwind CSS IntelliSense](https://marketplace.visualstudio.com/items?itemName=bradlc.vscode-tailwindcss)** — class completion and sorting

---

## Learn more

The full documentation ships inside every Caspian project at `node_modules/caspian-utils/dist/docs/` — start with `index.md`, which routes you to the right feature guide.

- Documentation: [caspian.tsnc.tech/docs](https://caspian.tsnc.tech/docs)
- PulsePoint: [pulsepoint.tsnc.tech](https://pulsepoint.tsnc.tech)
- Components: [maddex.tsnc.tech/docs](https://maddex.tsnc.tech)
- Icons: [ppicons.tsnc.tech](https://ppicons.tsnc.tech)

---

## License

MIT
