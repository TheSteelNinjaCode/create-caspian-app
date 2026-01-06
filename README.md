# Caspian — The Native Python Web Framework for the Reactive Web

Caspian is a high‑performance, **FastAPI-powered** full‑stack framework that brings **reactive UI** to Python without forcing a JavaScript backend. It combines:

- **FastAPI Engine** for async-native performance and the broader FastAPI ecosystem
- A **Hybrid Frontend Engine**: start with zero-build HTML, then upgrade to **Vite + NPM + TypeScript** when needed
- **Direct async RPC** (“Zero‑API”): call Python functions from the browser via `pp.rpc()`
- **File‑system routing** with nested layouts and dynamic routes
- **Prisma ORM integration** with an auto-generated, type-safe Python client
- A secure, session-based **auth system** and built-in security defaults

---

## Quick Start

### 1) Requirements

- **Node.js**: v22.13.0+
- **Python**: v3.14.0+

### 2) Create an app (interactive wizard)

```bash
npx create-caspian-app@latest
```

Example prompts you’ll see in the wizard:

- Project name
- Tailwind CSS
- Prisma ORM
- Backend only (no frontend assets)
- TypeScript support

### 3) Run dev server

```bash
cd my-app
npm run dev
```

---

## What “Reactive Python” looks like

A Caspian page can be plain HTML with reactive directives, plus a small `<script>` block for state.

```html
<!-- src/app/todos/index.html -->

<!-- Import Python Components -->
<!-- @import { Badge } from ../components/ui -->

<div class="flex gap-2 mb-4">
  <Badge variant="default">Tasks: {todos.length}</Badge>
</div>

<!-- Reactive Loop -->
<ul>
  <template pp-for="todo in todos">
    <li key="{todo.id}" class="p-2 border-b">{todo.title}</li>
  </template>
</ul>

<script>
  // State initialized by Python backend automatically
  const [todos, setTodos] = pp.state([[todos]]);
</script>
```

---

## Why developers choose Caspian

### FastAPI engine, async-native

Your logic runs in native async Python and can leverage FastAPI/Starlette features (DI, middleware, validation, etc.) without a separate JS backend.

### Hybrid frontend engine (zero-build → Vite)

Start with simple HTML-first development for speed and clarity, then adopt Vite + NPM + TypeScript when you need richer libraries or complex bundles.

### “Zero‑API” server actions (RPC)

Define `async def` actions and call them directly from the browser; Caspian handles serialization, security, and async execution.

### File‑system routing with nested layouts

Routes are determined by files in `src/app`, supporting dynamic segments (`[id]`), catch-alls (`[...slug]`), route groups (`(auth)`), and layout nesting via `layout.html`.

### Prisma ORM integration (type-safe Python client)

Define a single Prisma schema and generate a typed Python client—autocomplete-first database access without boilerplate.

### Security defaults and authentication

Built-in CSRF protection, strict Origin validation, HttpOnly cookies, and a session-based auth model with RBAC support.

---

## Installation & DX setup (VS Code)

For the best developer experience, Caspian’s docs recommend:

- **Caspian Official Framework Support** (component autocompletion + snippets)
- **Prisma** schema formatting/highlighting
- **Tailwind CSS** IntelliSense & class sorting

---

## Core concepts

### Routing

Caspian uses **file-system routing** under `src/app`:

| File Path                       | URL Path      |
| ------------------------------- | ------------- |
| `src/app/index.html`            | `/`           |
| `src/app/about/index.py`        | `/about`      |
| `src/app/blog/posts/index.html` | `/blog/posts` |

#### Dynamic segments

```txt
src/app/users/[id]/index.py   ->  /users/123
```

#### Catch-all segments

```txt
src/app/docs/[...slug]/index.py   ->  /docs/getting-started/setup
```

#### Route groups (organize without changing URLs)

```txt
src/app/(auth)/login/index.py     ->  /login
src/app/(auth)/register/index.py  ->  /register
```

#### Nested layouts

Layouts wrap pages and preserve state during navigation:

- Root: `src/app/layout.html`
- Nested: e.g., `/dashboard/settings` inherits root + dashboard layout automatically

---

### Components (Python-first, HTML when you want it)

Components are Python functions decorated with `@component`.

#### Atomic component (best for buttons, badges, icons, etc.)

```py
from casp.html_attrs import get_attributes, merge_classes
from casp.component_decorator import component

@component
def Container(**props):
    incoming_class = props.pop("class", "")
    final_class = merge_classes("mx-auto max-w-7xl px-4", incoming_class)

    children = props.pop("children", "")

    attributes = get_attributes({"class": final_class}, props)
    return f'<div {attributes}>{children}</div>'
```

**DX speed tip:** the VS Code extension can generate boilerplate via a snippet like `caspcom`.

#### Type-safe props (TypeScript-like autocomplete)

```py
from typing import Literal, Any
from casp.component_decorator import component

ButtonVariant = Literal["default", "destructive", "outline"]
ButtonSize = Literal["default", "sm", "lg"]

@component
def Button(
    children: Any = "",
    variant: ButtonVariant = "default",
    size: ButtonSize = "default",
    **props,
) -> str:
    # merge classes + attrs here
    return f"<button>...</button>"
```

**HTML templates for complex UI**
For larger layouts or reactive UIs, bridge to an HTML file:

```py
from casp.component_decorator import component, render_html

@component
def Counter(**props):
    return render_html("Counter.html", **props)
```

---

### Reactivity (PulsePoint)

Caspian is built on **PulsePoint**, a lightweight reactive DOM engine, plus Caspian-specific helpers for full-stack workflows.

Core directives/primitives include:

- `pp-component`, `pp-spread`, `pp-ref`, `pp-for`, `pp.state`, `pp.effect`, `pp.ref`, `pp-ignore`

#### `pp.rpc(functionName, data?)`

The bridge to your Python backend. Caspian handles:

- smart serialization (JSON ↔ FormData when `File` is present)
- auto-redirects when server returns redirect headers
- `X-CSRF-Token` injection for security

#### `searchParams`

A reactive wrapper around `URLSearchParams` that updates the URL without full reloads.

#### Navigation

Caspian intercepts internal `<a>` links for client-side navigation; for programmatic navigation use:

```js
pp.redirect("/dashboard");
```

---

## Backend: Async Server Actions (RPC)

Decorate `async def` functions with `@rpc`, then call them from the client using `pp.rpc()`.

**Backend (`src/app/todos/index.py`)**

```py
from casp.rpc import rpc
from casp.validate import Validate
from src.lib.prisma.db import prisma

@rpc()
async def create_todo(title):
    if Validate.with_rules(title, "required|min:3") is not True:
        raise ValueError("Title must be at least 3 chars")

    new_todo = await prisma.todo.create(data={
        "title": title,
        "completed": False
    })
    return new_todo.to_dict()

@rpc(require_auth=True)
async def delete_todo(id, _current_user_id=None):
    await prisma.todo.delete(where={"id": id})
    return {"success": True}
```

**Frontend (`src/app/todos/index.html`)**

```html
<form onsubmit="add(event)">
  <input name="title" required />
  <button>Add</button>
</form>

<script>
  const [todos, setTodos] = pp.state([]);

  async function add(e) {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));

    const newTodo = await pp.rpc("create_todo", data);
    setTodos([newTodo, ...todos]);
    e.target.reset();
  }
</script>
```

---

## Database: Prisma ORM

Caspian uses a Prisma schema as the single source of truth and generates a typed Python client. It is designed to translate Prisma syntax into optimized SQL without requiring the heavy Prisma Engine binary.

**Schema (`prisma/schema.prisma`)**

```prisma
model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String?
  posts     Post[]
  createdAt DateTime @default(now())
}

model Post {
  id        String   @id @default(cuid())
  title     String
  published Boolean  @default(false)
  author    User     @relation(fields: [authorId], references: [id])
  authorId  String
}
```

### Client usage

```py
from src.lib.prisma.db import prisma

users = prisma.user.find_many()
```

The docs also describe connection pooling and common CRUD patterns (create, find, update, delete), plus aggregations and transactions.

---

## Authentication (session-based, secure defaults)

Caspian includes session-based authentication with HttpOnly cookies and RBAC-friendly conventions.

**Configure auth in `main.py`**

- global protection toggle (`is_all_routes_private`)
- public routes whitelist
- auth routes (signin/signup)
- default redirects

The global `auth` object provides:

- `auth.sign_in(data, redirect_to?)`
- `auth.sign_out(redirect_to?)`
- `auth.is_authenticated()`
- `auth.get_payload()`

---

## CLI reference

### Create projects

```bash
npx create-caspian-app
```

### Useful flags

- `--tailwindcss` Tailwind CSS v4 + PostCSS + `globals.css`
- `--typescript` TypeScript support with Vite + `tsconfig.json`
- `--websocket` WebSocket server scaffolding
- `--mcp` Model Context Protocol server scaffolding (AI Agents)
- `--backend-only` skip frontend assets

### Code generation

Generate strict Python data classes (Pydantic) from your Prisma schema:

```bash
npx ppy generate
```

### Updating the project

```bash
npx casp update project
```

Tip: use `excludeFiles` in `caspian.config.json` to prevent overwrites during updates.

---

## Built-in icon workflow (ppicons)

Caspian integrates **ppicons** (Lucide-based), offering 1,500+ icons and an instant add command:

```bash
npx ppicons add Rocket
```

Then use in HTML:

```html
<!-- @import { Rocket } from ../lib/ppicons -->
<Rocket class="w-6 h-6 text-primary" />
```

---

## Project structure (generated by the CLI)

High-level layout:

- `main.py` — FastAPI app & ASGI entry
- `caspian.config.json` — project config
- `prisma/` — schema + seed scripts
- `src/` — app routes, pages, styles, shared libs
- `public/` — static assets served directly

---

## License

MIT

---

## Learn more

- Documentation: [Caspian docs](https://caspian.tsnc.tech/docs)
- Site: [caspian.tsnc.tech](https://caspian.tsnc.tech)
- PulsePoint docs: [pulsepoint.tsnc.tech](https://pulsepoint.tsnc.tech)
- ppicons library: [ppicons.tsnc.tech](https://ppicons.tsnc.tech)
