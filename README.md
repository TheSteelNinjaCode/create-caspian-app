# Caspian — The Native Python Web Framework for the Reactive Web

Caspian is a high-performance, FastAPI-powered full-stack framework that brings reactive UI to Python without forcing a JavaScript backend. It combines:

- **FastAPI Engine** for async-native performance and the broader FastAPI ecosystem
- **Hybrid Frontend Engine**: start with zero-build HTML, then upgrade to Vite + NPM + TypeScript when needed
- **Direct async RPC** ("Zero-API"): call Python functions from the browser via `pp.rpc()`
- **File-system routing** with nested layouts and dynamic routes (Next.js App Router mental model)
- **Prisma ORM integration** with an auto-generated, type-safe Python client
- **PulsePoint** — a lightweight browser-side reactive runtime for interactive UI
- **Session-based authentication** with RBAC support and built-in security defaults

---

## Quick Start

### Requirements

- **Node.js**: v24.13.1+
- **Python**: v3.14.0+

### Create an app (interactive wizard)

```bash
npx create-caspian-app@latest
```

The wizard walks through the main project options:

- Project name
- Feature toggles: backend-only mode, Tailwind CSS, Prisma, MCP, TypeScript
- Starter kit selection (basic, fullstack, api, realtime)

### Run dev server

```bash
cd my-app
npm run dev
```

> **Note:** Many Caspian projects use BrowserSync plus PostCSS watchers rather than a Vite dev server. Check `package.json` for the actual dev script.

---

## What "Reactive Python" looks like

A Caspian page is plain HTML with reactive directives plus a small `<script>` block for state. The framework handles the rest.

### Route template (`src/app/todos/index.html`)

```html
<!-- @import { Badge } from "../components/ui" -->

<section>
  <div class="flex gap-2 mb-4">
    <x-badge variant="default">Tasks: {todos.length}</x-badge>
  </div>

  <ul>
    <template pp-for="(todo, index) in todos">
      <li key="{todo.id}" class="p-2 border-b">
        {index + 1}. {todo.title}
        <button onclick="removeTodo(todo.id)">Remove</button>
      </li>
    </template>
  </ul>

  <script>
    const [todos, setTodos] = pp.state([]);
    function removeTodo(id) {
      setTodos(todos.filter((todo) => todo.id !== id));
    }
  </script>
</section>
```

### Backend RPC (`src/app/todos/index.py`)

```python
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

### Frontend call

```html
<script>
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

## Why developers choose Caspian

### FastAPI engine, async-native

Your logic runs in native async Python and can leverage FastAPI/Starlette features (dependency injection, middleware, validation, etc.) without a separate JS backend.

### Hybrid frontend engine (zero-build → Vite)

Start with simple HTML-first development for speed and clarity, then adopt Vite + NPM + TypeScript when you need richer libraries or complex bundles.

### "Zero-API" server actions (RPC)

Define `async def` actions decorated with `@rpc()` and call them directly from the browser; Caspian handles serialization, security, and async execution via `pp.rpc()`.

### File-system routing with nested layouts

Routes are determined by files in `src/app`, supporting dynamic segments (`[id]`), catch-alls (`[...slug]`), route groups (`(auth)`), and layout nesting via `layout.html`.

### Prisma ORM integration (type-safe Python client)

Define a single Prisma schema and generate a typed Python client — autocomplete-first database access without boilerplate.

### PulsePoint reactive runtime

A lightweight browser-side reactive runtime ships with Caspian. It follows a React-like mental model but is HTML-first rather than JSX-first, with `pp.state`, `pp.effect`, `pp.ref`, `pp-context`, `pp-for`, and `pp.portal`.

### Security defaults and authentication

Built-in CSRF protection, strict Origin validation, HttpOnly cookies, and a session-based auth model with OAuth provider support.

---

## Core concepts

### Routing

Caspian follows the same mental model as the Next.js App Router. Your directory structure becomes your URL structure.

| File                            | URL           |
| ------------------------------- | ------------- |
| `src/app/index.html`            | `/`           |
| `src/app/about/index.html`      | `/about`      |
| `src/app/blog/posts/index.html` | `/blog/posts` |

#### Dynamic segments

```
src/app/users/[id]/index.html   ->  /users/123
```

#### Catch-all segments

```
src/app/docs/[...slug]/index.html   ->  /docs/getting-started/setup
```

#### Route groups (organize without changing URLs)

```
src/app/(auth)/login/index.html     ->  /login
src/app/(auth)/register/index.html  ->  /register
```

#### Nested layouts

Layouts wrap pages and preserve state during navigation:

- Root: `src/app/layout.html`
- Section: e.g., `/dashboard/settings` inherits root + dashboard layout automatically

> **Rule:** For UI routes, keep markup in `index.html` and server logic in `index.py`. For section layouts, keep the visible wrapper in `layout.html` and layout-level props in `layout.py`.

---

### Components (Python-first, HTML when you want it)

Components are Python functions decorated with `@component`. Import them with `<!-- @import ... -->` comments and render them with `x-*` tags.

#### Atomic component

```python
from casp.component_decorator import component
from casp.html_attrs import get_attributes, merge_classes

@component
def Container(children: str = "", **props) -> str:
    incoming_class = props.pop("class", "")
    final_class = merge_classes("mx-auto max-w-7xl px-4", incoming_class)
    attributes = get_attributes({"class": final_class}, props)
    return f'<div {attributes}>{children}</div>'
```

#### Type-safe props

```python
from typing import Any, Literal
from casp.component_decorator import component
from casp.html_attrs import get_attributes, merge_classes

ButtonVariant = Literal["default", "outline", "destructive"]

@component
def Button(children: Any = "", variant: ButtonVariant = "default", **props) -> str:
    incoming_class = props.pop("class", "")
    attrs = get_attributes({
        "class": merge_classes(f"btn btn-{variant}", incoming_class),
    }, props)
    return f'<button {attrs}>{children}</button>'
```

#### Template-backed components (when UI is richer)

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
  <h3>[[ label ]]</h3>
  <button onclick="setCount(count + 1)">{count}</button>

  <script>
    const [count, setCount] = pp.state(0);
  </script>
</div>
```

---

### PulsePoint reactivity

PulsePoint is the default reactive frontend layer for Caspian. Key APIs:

| API                                | Description                                 |
| ---------------------------------- | ------------------------------------------- |
| `pp.state(initial)`                | Returns `[value, setValue]`                 |
| `pp.effect(callback, deps?)`       | Runs after render; returns cleanup function |
| `pp.layoutEffect(callback, deps?)` | Runs synchronously after DOM mutation       |
| `pp.ref(initialValue?)`            | Returns `{ current }`                       |
| `pp.createContext(defaultValue)`   | Creates a context token                     |
| `<Context.Provider value="{...}">` | Provide context to descendants              |
| `pp.context(token)`                | Read context in a descendant                |
| `pp.portal(ref, target?)`          | Portal rendering to a ref target            |
| `pp.rpc(name, data?, options?)`    | Call a backend RPC action                   |
| `pp.redirect(url)`                 | SPA-aware navigation                        |

#### `pp.rpc(functionName, data?)`

The bridge to your Python backend. Caspian handles:

- Smart serialization (JSON ↔ FormData when `File` is present)
- CSRF token injection via `X-CSRF-Token`
- Auto-redirects when server returns redirect headers
- Upload progress callbacks when `onUploadProgress` is provided

---

### Authentication (session-based, secure defaults)

Configure auth in `main.py` and customize settings in `src/lib/auth/auth_config.py`.

| Method                             | Description                   |
| ---------------------------------- | ----------------------------- |
| `auth.sign_in(data, redirect_to?)` | Sign in a user                |
| `auth.sign_out(redirect_to?)`      | Sign out (RPC-first)          |
| `auth.is_authenticated()`          | Check current session         |
| `auth.get_payload()`               | Get user payload from session |

```python
from casp.auth import Auth, GoogleProvider, GithubProvider, configure_auth
from src.lib.auth.auth_config import build_auth_settings

configure_auth(build_auth_settings())
Auth.set_providers(GithubProvider(), GoogleProvider())
```

---

## CLI reference

### Create a new project

```bash
npx create-caspian-app my-app
npx create-caspian-app my-app --starter-kit=fullstack
npx create-caspian-app my-app --tailwindcss --typescript --prisma
```

### Useful flags

| Flag                  | Description                                    |
| --------------------- | ---------------------------------------------- |
| `--backend-only`      | Skip frontend assets                           |
| `--tailwindcss`       | Enable Tailwind CSS                            |
| `--prisma`            | Enable Prisma ORM                              |
| `--mcp`               | Enable MCP server scaffolding                  |
| `--typescript`        | Enable TypeScript tooling                      |
| `--starter-kit=<kit>` | Use a preset (basic, fullstack, api, realtime) |
| `-y`                  | Non-interactive mode                           |

### Update existing project

```bash
npx casp update project
npx casp update project --tag beta
npx casp update project --version 1.2.3 -y
```

### ORM regeneration (after schema changes)

```bash
npx prisma migrate dev
npx prisma generate
npx prisma db seed
npx ppy generate
```

---

## Project structure

```
my-app/
├── main.py                     # FastAPI entry point
├── caspian.config.json         # Feature flags
├── prisma/
│   ├── schema.prisma
│   └── seed.ts
├── src/
│   ├── app/                    # File-system routes
│   │   ├── layout.html         # Root layout
│   │   ├── index.html          # Home page
│   │   └── users/
│   │       └── [id]/
│   │           └── index.html  # /users/:id
│   ├── components/             # Reusable UI components
│   │   └── ui/
│   │       └── Button.py
│   └── lib/                    # Non-UI helpers
│       ├── auth/auth_config.py
│       └── prisma/
│           └── db.py
├── public/                     # Static assets
└── settings/                   # BrowserSync config
```

### Key conventions

- **UI routes:** `index.html` for markup, optional `index.py` for backend logic
- **Section layouts:** `layout.html` for the wrapper, optional `layout.py` for props
- **Components:** `src/components/` for reusable UI; `src/lib/` for helpers and services
- **`<!-- @import ... -->`:** Must appear above the single authored root element
- **Single-root rule:** Every template must have exactly one top-level parent node with any owned `<script>` inside it

---

## Built-in icon workflow (ppicons)

Caspian integrates **ppicons** (Lucide-based), offering 1,500+ icons:

```bash
npx ppicons add Rocket
```

Then use in HTML:

```html
<!-- @import { Rocket } from "../lib/ppicons" -->
<x-rocket class="w-6 h-6 text-primary" />
```

---

## Recommended VS Code extensions

For the best development experience:

- **Caspian Official Framework Support** — component snippets and autocomplete
- **Python** — Python language support
- **Prisma** — Schema formatting and highlighting
- **Tailwind CSS IntelliSense** — Class completion and sorting

---

## Learn more

- Documentation: [caspian.tsnc.tech/docs](https://caspian.tsnc.tech/docs)
- PulsePoint docs: [pulsepoint.tsnc.tech](https://pulsepoint.tsnc.tech)
- ppicons library: [ppicons.tsnc.tech](https://ppicons.tsnc.tech)

---

## License

MIT
