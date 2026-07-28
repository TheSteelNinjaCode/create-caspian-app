# Caspian — The Native Python Web Framework for the Reactive Web

Caspian is a FastAPI-powered full-stack framework that brings reactive UI to Python without forcing a JavaScript backend. You write file-system routes, plain HTML templates, and `async def` Python — Caspian wires the browser to your server.

- **FastAPI engine** — async-native, with the Starlette/FastAPI middleware and ecosystem underneath
- **PulsePoint** — a shipped browser-side reactive runtime with a React-style hook API and **plain HTML** templates (no JSX, no build step required)
- **"Zero-API" RPC** — call Python functions from the browser with `pp.rpc()`; no controllers, no route handlers, no fetch boilerplate
- **File-system routing** with nested layouts, dynamic segments, and route groups (Next.js App Router mental model)
- **Python components** — reusable `@component` functions rendered as HTML-first `x-*` tags
- **Prisma ORM** with a generated, type-safe Python client
- **Session auth** with RBAC and OAuth providers, plus fail-closed security defaults
- **Optional**: Tailwind CSS, TypeScript tooling, MCP server, WebSockets — each gated by one config flag

---

## Quick Start

### Requirements

- **Python** `3.14` or newer
- **Node.js** with `npm` and `npx` available (used for the CLI, Prisma, Tailwind, and the dev stack)

```bash
node -v
python -V
```

### Create an app

```bash
npx create-caspian-app@latest
```

The interactive wizard walks through:

- Project name
- Feature toggles: backend-only, Tailwind CSS, Prisma, MCP, TypeScript
- Starter kit selection (`basic`, `fullstack`, `api`, `realtime`, or a custom Git source)

### Run the dev server

```bash
cd my-app
npm run dev
```

> The generated `package.json` is the source of truth for what `npm run dev` does. Caspian projects typically run a **BrowserSync proxy plus PostCSS/Vite watchers**, not a Vite dev server that owns the page. When the dev stack is running, check `settings/bs-config.json` for the active local URL and port — the proxy does not always land on the default port.

---

## What "Reactive Python" looks like

A route is a folder. The markup lives in `index.html`, the server logic in `index.py`. Templates are **plain HTML** with `{expression}` interpolation and a small `<script>` for state.

### Route template — `src/app/todos/index.html`

```html
<!-- @import { Badge } from "../../components/ui/Badge.py" -->

<section>
  <x-badge variant="default">Tasks: {todos.length}</x-badge>

  <form onsubmit="{addTodo(event)}">
    <input name="title" required />
    <button type="submit" disabled="{isSaving}">Add</button>
  </form>

  <ul>
    <template pp-for="(todo, index) in todos">
      <li key="{todo.id}" class="p-2 border-b">
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
        const created = await pp.rpc("create_todo", data);
        setTodos([created, ...todos]);
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
```

### Backend — `src/app/todos/index.py`

```python
from casp.layout import Metadata, render_page
from casp.rpc import rpc
from casp.validate import Rule, Validate
from src.lib.prisma import prisma

metadata = Metadata(
    title="Todos",
    description="A tiny Caspian todo list.",
)


async def page():
    return render_page(__file__)


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

That is the whole loop: no API routes, no client, no serializer. `pp.rpc("create_todo", data)` posts to the current route, Caspian resolves the decorated function, filters the payload against its signature, runs it, and returns JSON.

---

## Core concepts

### 1. Routing

Your directory structure under `src/app` is your URL structure.

| File                            | URL           |
| ------------------------------- | ------------- |
| `src/app/index.html`            | `/`           |
| `src/app/about/index.html`      | `/about`      |
| `src/app/blog/posts/index.html` | `/blog/posts` |

```
src/app/users/[id]/index.html        ->  /users/123          (dynamic segment)
src/app/docs/[...slug]/index.html    ->  /docs/a/b/c         (catch-all)
src/app/(auth)/login/index.html      ->  /login              (route group, no URL segment)
src/app/dashboard/layout.html        ->  wraps every /dashboard/* page
```

#### Route file conventions

| File             | Owns                                                                             |
| ---------------- | -------------------------------------------------------------------------------- |
| `index.html`     | The page's authored markup (single root element)                                 |
| `index.py`       | `metadata`, `page()`, route-owned `@rpc()` actions, redirects, first-render data |
| `layout.html`    | A section wrapper containing `<slot />`                                          |
| `layout.py`      | Layout-level props and server logic                                              |
| `loading.html`   | Navigation loading state for the route                                           |
| `not-found.html` | 404 UI                                                                           |
| `error.html`     | Error UI                                                                         |

`page()` renders the sibling template with `render_page(__file__, context)`. It can also return a
`(page_html, layout_props)` tuple, whose dict keys become `{{ layout.* }}` in a parent layout.

> **Rule:** `index.py` never inlines page HTML. Markup belongs in `index.html`.

---

### 2. Templates are plain HTML — not JSX

PulsePoint borrows React's **hook API** and its **component decomposition model**. It does **not** borrow JSX. This is the single most common source of broken pages.

```html
<!-- ❌ These silently corrupt the page -->
<div class="{cls}">…</div>
<!-- unquoted brace attr -->
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

**Sanity check:** delete every `{}` from your template. What remains must still be valid HTML.

There is no `pp-if`, `pp-show`, `pp-else`, or `pp-key`. Conditionals are `hidden="{...}"` or a ternary inside `{...}`. Keyed lists use plain `key`.

#### The complete author-facing template surface

| Syntax                                                          | Where                                      | Purpose                       |
| --------------------------------------------------------------- | ------------------------------------------ | ----------------------------- |
| `{expression}`                                                  | Text nodes and **quoted** attribute values | Interpolation                 |
| `onclick`, `oninput`, `onchange`, `onsubmit`, any `on*`         | Any element                                | Event binding                 |
| `pp-for="item in items"` / `"(item, index) in items"`           | **`<template>` only**                      | Keyed list rendering          |
| `key="{expr}"`                                                  | The repeated element                       | Diffing identity              |
| `pp-ref="name"` / `pp-ref="{expr}"`                             | Native elements and `x-*` tags             | Imperative element access     |
| `pp-style="{cssText}"`                                          | Any element                                | Dynamic inline style (string) |
| `pp-spread="{...obj}"`                                          | Any element                                | Spread object into attributes |
| `<token.provider value="{v}">` (lowercase)                      | Anywhere                                   | Context provider              |
| `pp-spa="false"`                                                | An `<a>`                                   | Opt one link out of SPA navigation, which starts automatically on mount |
| `pp-reset-scroll="true"`, `pp-scroll-key="name"`                | A scroll container                         | Scroll restoration control    |
| `pp-loading-content`, `pp-loading-url`, `pp-loading-transition` | Navigation regions                         | Loading UI                    |

Never handwrite runtime-managed attributes (`pp-component`, `pp-owner`, `pp-ref-owner`, `pp-ref-forward`, `data-pp-*`, …). Component logic belongs in a plain, untyped `<script>`; the render pipeline and browser runtime capture it safely.

#### The single-root rule

Every route, layout, and component template must have **exactly one** top-level element (or one imported `x-*` root), with any owned `<script>` **inside** that root. Caspian injects `pp-component` on the final root and errors if it cannot find one. `<!-- @import ... -->` comments sit above the root and do not count as content.

---

### 3. PulsePoint hooks

Component `<script>` blocks are plain JavaScript. The `pp` object mirrors React hooks:

| Hook                                          | Returns / purpose                                                      |
| --------------------------------------------- | ---------------------------------------------------------------------- |
| `pp.state(initial)`                           | `[value, setValue]` — setter accepts a value or an updater             |
| `pp.effect(fn, deps?)`                        | After render; may return a cleanup function                            |
| `pp.layoutEffect(fn, deps?)`                  | Synchronously after DOM mutation                                       |
| `pp.ref(initial?)`                            | `{ current }`                                                          |
| `pp.memo(fn, deps)` / `pp.callback(fn, deps)` | Memoized value / stable function                                       |
| `pp.reducer(reducer, initial)`                | `[state, dispatch]`                                                    |
| `pp.context(token)`                           | Read a context value from an ancestor provider                         |
| `pp.portal(ref, target?)`                     | Render into another DOM target, preserving logical ancestry            |
| `pp.id()`                                     | Stable unique id for `id`/`for`/`aria-*` pairing                       |
| `pp.errorBoundary()`                          | `[error, reset]` — catches render and effect throws in descendants     |
| `pp.syncExternalStore(subscribe, snapshot)`   | Subscribe to a source the component doesn't own (`matchMedia`, stores) |
| `pp.imperativeHandle(ref, create, deps?)`     | Publish an imperative API to a parent's ref                            |
| `pp.transition()`                             | `[isPending, startTransition]`                                         |
| `pp.deferredValue(value, initial?)`           | Lags one commit behind the source                                      |
| `pp.optimistic(passthrough, reducer?)`        | Optimistic UI that reconciles against a confirmed value                |
| `pp.props`                                    | Props bag derived from the rendered root's attributes                  |

Runtime utilities: `pp.createContext`, `pp.mount`, `pp.redirect`, `pp.rpc`, `pp.enablePerf`, `pp.disablePerf`, `pp.getPerfStats`, `pp.resetPerfStats`.

React APIs with **no** PulsePoint equivalent: `forwardRef`, `memo()` as a wrapper, `lazy`, `Suspense`, `useInsertionEffect`, `useActionState`, `useFormStatus`, free-function `startTransition`.

Inside an `on*` attribute the runtime injects `event` plus the aliases `e`, `$event`, `target`, `currentTarget`, and `el`.

#### Context

Providers are authored as **lowercase** tags derived from the token variable name:

```html
<section>
  <script>
    const ThemeContext = pp.createContext("light");
    const [theme, setTheme] = pp.state("dark");
  </script>

  <themecontext.provider value="{theme}">
    <button onclick="setTheme(theme === 'dark' ? 'light' : 'dark')">
      Theme: {theme}
    </button>
    <x-child-panel />
  </themecontext.provider>
</section>
```

A descendant reads it with `const theme = pp.context(ThemeContext);`.

---

### 4. Components

Components are Python functions decorated with `@component`, imported at the top of a template and rendered as kebab-cased `x-*` tags.

#### Return a string (small, presentational)

```python
from casp.component_decorator import component
from casp.html_attrs import get_attributes, merge_classes

@component
def Container(children: str = "", **props) -> str:
    final_class = merge_classes("mx-auto max-w-7xl px-4", props.pop("class", ""))
    attributes = get_attributes({"class": final_class}, props)
    return f"<div {attributes}>{children}</div>"
```

#### Single-file with `html(...)` (small/medium, the common case)

Keep markup, server interpolation, and the PulsePoint script inline. Three brace dialects coexist:
`{{ value }}` is server-side Jinja, `{{ value | json }}` safely serializes into a `<script>`,
`{# … #}` is a Jinja comment, and `{ value }` is left untouched for PulsePoint.

```python
from casp.component_decorator import component, html
from casp.html_attrs import get_attributes, merge_classes

@component
def UserCard(user=None, **props):
    attributes = get_attributes({
        "class": merge_classes("card", props.pop("class", "")),
        "user-name": user["name"],
    }, props)

    # html
    return html("""
      <div {{ attributes }}>
        <h3>{{ user.name }}</h3>
        <button onclick="setLikes(likes + 1)">Likes: {likes}</button>
        <script>
          const [likes, setLikes] = pp.state({{ user.likes | json }});
        </script>
      </div>
    """, attributes=attributes, user=user)
```

> Use a raw string (`r"""…"""`) when the inline `<script>` contains backslashes (regex, `\n`).

#### Template-backed (`render_html`) — for large markup

`Counter.py`:

```python
from casp.component_decorator import component, render_html

@component
def Counter(label: str = "Clicks") -> str:
    return render_html(__file__, {"label": label})
```

`Counter.html`:

```html
<div>
  <h3>{{ label }}</h3>
  <button onclick="setCount(count + 1)">{count}</button>

  <script>
    const [count, setCount] = pp.state(0);
  </script>
</div>
```

#### Importing and rendering

```html
<!-- @import Container from "../components" -->
<!-- @import { Button, Card as UserCard } from "../components/ui" -->
<!-- @import { Breadcrumb, BreadcrumbItem, BreadcrumbLink } from "../components/Breadcrumb.py" -->

<x-container class="py-10">
  <x-button variant="outline">Continue</x-button>
</x-container>
```

- `Container` → `<x-container />`, `CommandDialog` → `<x-command-dialog />`.
- If one Python file exports several components, import them **from that file path**, not from the folder.
- `@import` is a file-level directive: it must sit **above** the authored root, never inside it.
- For component-to-component composition, prefer real Python imports inside the component module; a component's own `x-*` tags resolve from its module imports.

#### Props: every prop the template reads must be re-emitted on the root

This is the most common silent failure in Python components:

1. Attributes on the `x-*` tag arrive in Python as **raw string kwargs** (`open="{permOpen}"` arrives as the literal `"{permOpen}"`), kebab-case converted to camelCase.
2. The Python component must deliberately re-emit them onto its single rendered root via `get_attributes({...}, props)` + `{{ attributes }}`.
3. PulsePoint derives `pp.props` from **the rendered root's attributes** and evaluates pure `{expr}` values in the parent's scope.

A prop accepted by Python but not re-emitted is silently `undefined` in the browser — no server error, no console warning. Forwarding also does not preserve types: a brace expression keeps its real type, a literal (`volume="0"`) arrives as a **string**, a valueless attribute arrives as `true`, `None`/`False`/`""` are omitted entirely, and JS reserved words such as `class` are dropped from `pp.props`.

#### Tailwind class merging

When `tailwindcss: true`, Python `merge_classes(...)` emits a frontend-ready `{twMerge(...)}` expression, and the browser's global `twMerge(...)` resolves conflicts. That pair is the only supported merge path.

---

### 5. Data: `pp.rpc()` and `@rpc()`

```js
await pp.rpc(name, data?, optionsOrAbort?)
```

- Posts to the **current route**; resolves the `@rpc()` function of that name in the route's `index.py`.
- Smart serialization — switches to `FormData` automatically when a `File` is present.
- CSRF token injected as `X-CSRF-Token`.
- Server redirect headers are honored through `pp.redirect()`.
- Passing `true` as the third argument means `{ abortPrevious: true }`.

Options: `abortPrevious`, `url`, `csrfUrl`, `credentials`, `onStream`, `onStreamError`, `onStreamComplete`, `onUploadProgress`, `onUploadComplete`.

**Payload safety:** RPC keys are filtered against the function signature, so a parameter is client-settable only when it is declared. Declaring `**kwargs` opts into the whole payload — do that deliberately.

#### Upload progress

```html
<input type="file" onchange="{upload(event.target.files?.[0])}" />
<progress max="100" value="{percent ?? 0}"></progress>

<script>
  const [percent, setPercent] = pp.state(null);

  async function upload(file) {
    if (!file) return;
    await pp.rpc(
      "upload_asset",
      { file },
      {
        onUploadProgress: ({ percent }) => setPercent(percent),
        onUploadComplete: () => setPercent(100),
      },
    );
  }
</script>
```

`onUploadProgress` receives `{ loaded, total, percent }`; `total` and `percent` are `null` when the length is not computable.

#### Streaming (the path for AI/LLM token output)

A generator `@rpc()` becomes a `text/event-stream` response:

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

Session-based, configured centrally in `src/lib/auth/auth_config.py` and wired in `main.py`.

```python
from casp.auth import Auth, GithubProvider, GoogleProvider, configure_auth
from src.lib.auth.auth_config import build_auth_settings

configure_auth(build_auth_settings())
Auth.set_providers(GithubProvider(), GoogleProvider())
```

| Method                                                       | Purpose                                                           |
| ------------------------------------------------------------ | ----------------------------------------------------------------- |
| `auth.sign_in(data, token_validity=None, redirect_to=False)` | Store the payload, set a CSRF token; returns `"ok"` or a redirect |
| `auth.sign_out(redirect_to=None)`                            | Clear the session and redirect                                    |
| `auth.is_authenticated()`                                    | `False` when the payload is missing, malformed, or expired        |
| `auth.get_payload()`                                         | Read the signed-in payload                                        |
| `auth.refresh_session()`                                     | Extend expiry when `token_auto_refresh=True`                      |
| `auth.check_role(user, allowed_roles)`                       | RBAC check against the configured role field                      |

Guards: `@rpc(require_auth=True)` for actions, `@guest_only()` / route-level guards for pages, and central public-vs-private route policy in `auth_config.py`.

**OAuth is already wired.** `Auth.set_providers(...)` registers `/api/auth/signin/{google,github}` and `/api/auth/callback/{google,github}`. Link a button and set the credentials in `.env` — do not hand-roll the flow.

**Redirect ownership is centralized.** Do not re-implement `next=` handling or post-login routing in a sign-in page; `auth_config.py` owns protected-route redirects, auth-route redirects, and `default_signin_redirect` (defaults to `/dashboard`).

---

### 8. Database (Prisma)

Enabled by `"prisma": true`. Define one `prisma/schema.prisma` and generate a typed Python client into `src/lib/prisma/`.

```python
from src.lib.prisma import prisma

users = await prisma.user.find_many(
    where={"active": True},
    include={"userRole": True},
    order_by={"createdAt": "desc"},
)
```

After schema changes, in this order:

```bash
npx prisma migrate dev
```

```bash
npx ppy generate
```

If the seed flow depends on the new schema, run `npx prisma generate` first, then `npx prisma db seed` — **`db seed` may clear or overwrite tables; confirm the datasource before running it.**

`src/lib/prisma/__init__.py`, `db.py`, `models.py`, and `settings/prisma-schema.json` are generated by `npx ppy generate`. Never hand-edit them, and never add a second data layer (raw drivers, hand-written SQL helpers, JSON stores, browser-side fetches) alongside the ORM.

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
| `websocket`   | App-owned FastAPI `@app.websocket(...)` endpoints and socket helpers |

#### WebSockets

Use RPC for ordinary reads, writes, uploads, and SSE streams. Reach for WebSockets only for **long-lived bidirectional** channels: chat, collaboration, presence, multiplayer state.

Endpoints are app-owned in `main.py`; reusable session/auth/broadcast helpers live in `src/lib/websocket/`. In the browser, use PulsePoint for state and lifecycle but the **native** `WebSocket` for the transport — keep the socket in `pp.ref(...)` and close it in a cleanup effect.

**Sockets authorize themselves.** The HTTP middleware stack early-returns on `scope["type"] == "websocket"`, so `AuthMiddleware` does not protect them. Every endpoint must run its own origin + auth guard, and authenticated and guest traffic belong in separate broadcast pools.

#### MCP

When `mcp: true`, a FastMCP server is mounted into the same app so one deploy serves both web and MCP. The endpoint is mounted **outside** the routing tree, so `AuthMiddleware` does not cover it — `MCP_AUTH_TOKEN` is its credential. With no token it stays open in development and returns **503 in production**.

---

## Security defaults

Caspian ships fail-closed defaults. Things worth knowing before you change them:

- **`APP_ENV` resolves fail-closed.** Only an explicit development value (`dev`, `development`, `local`, `staging`, `test`, `testing`) enables relaxations. Unset or misspelled counts as **production**.
- **Server-interpolated values never carry live PulsePoint syntax.** The Jinja environment encodes `{` / `}` as entities on every non-`Markup` value, so stored user data can never execute as a template expression. `Markup` is the trust boundary — `| safe`, `get_attributes(...)`, `merge_classes(...)`, and the `json` filter legitimately keep their braces.
- **Authenticated renders are never cached.** The page cache keys on the URI alone, so a request-eligibility check gates both the read and the write; a route's `Cache(...)` cannot override it.
- **RPC payload keys are filtered against the function signature.**
- **`/uploads` serves user content in attachment mode**; only real image types render inline. First-party `/css`, `/js`, and `/assets` stay inline.
- **CSRF protection, strict Origin validation, HttpOnly cookies, security headers, and page rate limiting** are on by default.

Security-relevant environment variables: `MCP_AUTH_TOKEN`, `RATE_LIMIT_PAGES` (default `200/minute`), `CONTENT_SECURITY_POLICY` (replaces the default policy wholesale), `MAX_WEBSOCKET_CONNECTIONS`, `MAX_WEBSOCKET_MESSAGES_PER_WINDOW`, `WEBSOCKET_RATE_WINDOW_SECONDS`, and `WEBSOCKET_ALLOWED_ORIGINS` (**required in production** — the same-origin fallback is derived from the client-supplied `Host` header and is development-only).

---

## Project structure

```
my-app/
├── main.py                      # FastAPI entry point, middleware stack, WebSocket + MCP mounts
├── caspian.config.json          # Feature flags — the single source of truth
├── pyproject.toml               # Python deps and tooling config
├── package.json                 # CLI/tooling scripts
├── prisma/
│   ├── schema.prisma
│   └── seed.ts
├── src/
│   ├── app/                     # File-system routes
│   │   ├── layout.html          # Root layout
│   │   ├── layout.py
│   │   ├── index.html           # Home page
│   │   ├── index.py
│   │   ├── globals.css
│   │   ├── error.html
│   │   ├── not-found.html
│   │   └── users/[id]/
│   │       ├── index.html       # /users/:id
│   │       └── index.py
│   ├── components/              # Reusable UI (@component)
│   └── lib/                     # Non-UI code
│       ├── auth/auth_config.py
│       ├── prisma/              # Generated Python ORM — do not edit
│       ├── websocket/           # Socket helpers (when websocket: true)
│       └── mcp/                 # FastMCP server (when mcp: true)
├── public/                      # Static assets, incl. the PulsePoint runtime and uploads
└── settings/                    # Dev stack config and generated indexes
```

### Placement rules

- **Route-owned** logic (first-render query, route `@rpc()` actions, redirects, route validation) stays in that route's `index.py`. Move it to `src/lib/**` only when it is genuinely shared.
- **Reusable UI** goes in `src/components/`; **helpers, services, adapters** go in `src/lib/`.
- **Compose pages from components.** A route's `index.html` should read as a short assembly of `x-*` chunks (topbar, sidebar, header, sections, forms, footer), not a wall of markup. Plan the breakdown before writing the route.
- **Generated, never hand-edited:** `src/lib/prisma/**`, `settings/prisma-schema.json`, `settings/files-list.json`, `settings/component-map.json`, `public/css/styles.css`, `__pycache__/`.

---

## CLI reference

### Create

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

In `-y` mode every feature defaults to `false`. Starter kit presets can still be overridden by explicit flags: `npx create-caspian-app my-app --starter-kit=fullstack --typescript`.

`websocket` has no create flag — enable it in `caspian.config.json` after scaffold, then run the update command.

### Update an existing project

```bash
npx casp update project
```

Also accepts a positional tag or version, or the named forms `--tag beta`, `--tag=beta`, `--version 1.2.3`, `--version=1.2.3`, plus `-y`. Supplying more than one version source is an error. On Windows the updater resolves `npx.cmd`, and the creator reuses an existing `.venv` rather than recreating it.

Use `excludeFiles` in `caspian.config.json` to protect files you have customized (a common entry is `./src/lib/auth/auth_config.py`) from being overwritten on update. Excluded files are yours to merge going forward.

### Project scripts

| Command                | What it does                                                       |
| ---------------------- | ------------------------------------------------------------------ |
| `npm run dev`          | Full local stack: BrowserSync proxy, Tailwind watch, asset watch   |
| `npm run build`        | Build Tailwind and regenerate the route/component index            |
| `npm run static`       | Export every static route to `static/` (SSG)                       |
| `npm run static:serve` | Preview the exported folder on an auto-selected free loopback port |

These are opt-in workflows. Don't run them as a validation step just because source files changed.

---

## Static export (SSG)

`npm run static` boots the app and writes `static/<route>/index.html` plus copied public assets — the equivalent of Next.js `output: export`. It always runs `npm run build` first so the export walks a fresh route index.

Policy is **warn & skip**: dynamic routes are pre-rendered only when their `index.py` exports `static_paths` (the `getStaticPaths` equivalent); auth-gated, non-200, and non-HTML routes are reported and skipped.

`npm run static:serve` serves only `static/`, binds loopback `127.0.0.1` (network exposure is opt-in via `HOST=0.0.0.0`), and walks upward from port 8000 until it finds a free one — **read the port it prints**.

`pp.rpc()`, auth, WebSockets, streaming, and per-request server data are all inert in a static export.

---

## Ecosystem

### ppicons — 1,500+ Lucide-based icons as Python components

```bash
npx ppicons add Rocket
```

```html
<!-- @import { Rocket, ChevronDown } from "../lib/ppicons" -->
<x-rocket class="w-6 h-6 text-primary" />
```

### maddex — shadcn-style UI component kit for Caspian

```bash
npx maddex add button card dialog
```

```html
<!-- @import { Button } from "../lib/maddex/Button.py" -->
<x-button variant="outline">Continue</x-button>
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
