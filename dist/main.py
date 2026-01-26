from casp.components_compiler import transform_components
from casp.scripts_type import transform_scripts
import inspect
import os
import importlib.util
import mimetypes
import secrets
import traceback
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
import uvicorn
from casp.state_manager import StateManager
from casp.cache_handler import CacheHandler
from casp.caspian_config import get_files_index, get_config
from casp.auth import (
    Auth,
    AuthSettings,
    GoogleProvider,
    GithubProvider,
    configure_auth,
)
from casp.rpc import register_rpc_routes
from casp.layout import (
    render_with_nested_layouts,
    string_env,
    load_template_file,
    render_page,
    _runtime_injections,
    _runtime_metadata,
)
import hashlib
from casp.streaming import SSE
from typing import Any, Optional, get_args, get_origin, Union

load_dotenv()
cfg = get_config()

# ====
# AUTH CONFIGURATION (App behavior - customize here)
# ====


def setup_auth():
    """
    Configure authentication behavior.
    Secrets (AUTH_SECRET, OAUTH credentials) come from .env
    """
    configure_auth(AuthSettings(
        # Token settings
        default_token_validity="7d",
        token_auto_refresh=False,

        # Route protection mode
        # True = all routes private except public_routes and auth_routes
        # False = only private_routes require auth
        is_all_routes_private=False,

        # Route lists
        private_routes=[],  # Used when is_all_routes_private=False
        public_routes=["/"],
        auth_routes=["/signin", "/signup"],

        # Role-based access (optional)
        is_role_based=False,
        role_identifier="role",
        role_based_routes={
            # "/admin": [AuthRole.ADMIN],
            # "/reports": [AuthRole.ADMIN, AuthRole.USER],
        },

        # Redirects
        default_signin_redirect="/dashboard",
        default_signout_redirect="/signin",
        api_auth_prefix="/api/auth",

        # Callbacks (optional hooks)
        # lambda user: print(f"User signed in: {user.get('email')}")
        on_sign_in=None,
        on_sign_out=None,  # lambda: print("User signed out")
        # lambda req: RedirectResponse("/custom-login", 303)
        on_auth_failure=None,
    ))

    # Register OAuth providers (secrets from .env)
    Auth.set_providers(
        GithubProvider(),  # Uses GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET from .env
        # Uses GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI from .env
        GoogleProvider(),
    )


setup_auth()

app = FastAPI(
    title=cfg.projectName,
    version=cfg.version,
    docs_url="/docs" if cfg.backendOnly else None,
    redoc_url="/redoc" if cfg.backendOnly else None,
    openapi_url="/openapi.json" if cfg.backendOnly else None,
)

# ====
# Configuration
# ====
SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', 7))
MAX_CONTENT_LENGTH_MB = int(os.getenv('MAX_CONTENT_LENGTH_MB', 16))
IS_PRODUCTION = os.getenv('APP_ENV') == 'production'
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'false').lower() == 'true'
DEFAULT_TTL = int(os.getenv('CACHE_TTL', 600))

# ====
# Static File Routes
# ====


@app.get('/css/{filename:path}')
async def serve_css(filename: str):
    file_path = Path('public/css') / filename
    if not file_path.exists():
        return Response(status_code=404)
    return FileResponse(file_path, media_type='text/css')


@app.get('/js/{filename:path}')
async def serve_js(filename: str):
    file_path = Path('public/js') / filename
    if not file_path.exists():
        return Response(status_code=404)
    return FileResponse(file_path, media_type='application/javascript')


@app.get('/assets/{filename:path}')
async def serve_assets(filename: str):
    file_path = Path('public/assets') / filename
    if not file_path.exists():
        return Response(status_code=404)
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(file_path, media_type=mime_type or 'application/octet-stream')


@app.get('/favicon.ico')
async def favicon():
    file_path = Path('public/favicon.ico')
    if not file_path.exists():
        return Response(status_code=404)
    return FileResponse(file_path, media_type='image/x-icon')

# ====
# Pure ASGI Middleware Classes
# ====


class CSRFMiddleware:
    """CSRF middleware that properly handles session modifications."""

    def __init__(self, app: ASGIApp): self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive, send)
        csrf_token = request.session.get("csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_hex(32)
            request.session["csrf_token"] = csrf_token

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                cookie_value = f"pp_csrf={csrf_token}; Path=/; SameSite=Lax"
                if IS_PRODUCTION:
                    cookie_value += "; Secure"
                new_headers = list(message.get("headers", []))
                new_headers.append((b"set-cookie", cookie_value.encode()))
                message = {**message, "headers": new_headers}
            await send(message)
        await self.app(scope, receive, send_wrapper)


class AuthMiddleware:
    """Auth middleware using pure ASGI pattern for proper session handling."""

    def __init__(self, app: ASGIApp): self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive, send)
        path = request.url.path
        if path.startswith(('/css/', '/js/', '/assets/', '/favicon.ico')):
            await self.app(scope, receive, send)
            return
        StateManager.init(request)
        Auth.set_request(request)
        auth_inst = Auth.get_instance()
        providers = Auth.get_providers()

        if providers:
            oauth_response = auth_inst.auth_providers(*providers)
            if oauth_response:
                await oauth_response(scope, receive, send)
                return
        if auth_inst.is_public_route(path):
            await self.app(scope, receive, send)
            return
        if auth_inst.is_auth_route(path):
            if auth_inst.is_authenticated():
                await RedirectResponse(
                    url=auth_inst.settings.default_signin_redirect,
                    status_code=303
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        if auth_inst.settings.is_role_based:
            required_roles = auth_inst.get_required_roles(path)
            if required_roles:
                if not auth_inst.is_authenticated():
                    await RedirectResponse(url=f'/signin?next={path}', status_code=303)(scope, receive, send)
                    return
                if not auth_inst.check_role(auth_inst.get_payload(), required_roles):
                    await RedirectResponse(url='/unauthorized', status_code=303)(scope, receive, send)
                    return

        if auth_inst.is_private_route(path):
            if not auth_inst.is_authenticated():
                if auth_inst.settings.on_auth_failure:
                    await auth_inst.settings.on_auth_failure(request)(scope, receive, send)
                    return
                await RedirectResponse(url=f'/signin?next={path}', status_code=303)(scope, receive, send)
                return

        await self.app(scope, receive, send)


class RPCMiddleware:
    """RPC middleware using pure ASGI pattern."""

    def __init__(self, app: ASGIApp): self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive, send)
        if request.headers.get('X-PP-RPC') == 'true' and request.method == 'POST':
            from casp.rpc import _handle_rpc_request
            session = dict(request.session) if hasattr(
                request, 'session') else {}
            response = await _handle_rpc_request(request, session)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

# ====
# Route Registration
# ====


def load_route_module(file_path: str):
    unique_id = hashlib.md5(file_path.encode()).hexdigest()[:8]
    module_name = f"page_{unique_id}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None, f"Cannot load spec for {file_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    setattr(module, 'render_page', render_page)
    return module


def _unwrap_optional(annotation: Any) -> Any:
    """
    Optional[T] is Union[T, NoneType]. Return T when applicable.
    """
    origin = get_origin(annotation)
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _coerce_scalar(value: Optional[str], annotation: Any) -> Any:
    """
    Coerce a single query value based on annotation (best-effort).
    If value is None -> returns None.
    If coercion fails -> returns original string.
    """
    if value is None:
        return None

    ann = _unwrap_optional(annotation)

    try:
        if ann is inspect._empty or ann is str or ann is Any:
            return value
        if ann is int:
            return int(value)
        if ann is float:
            return float(value)
        if ann is bool:
            v = value.strip().lower()
            if v in ("1", "true", "t", "yes", "y", "on"):
                return True
            if v in ("0", "false", "f", "no", "n", "off"):
                return False
            return bool(value)
        return value
    except Exception:
        return value


def _coerce_query_param(request: Request, name: str, param: inspect.Parameter) -> Any:
    """
    Supports:
      - scalar types: str/int/float/bool/Optional[...]
      - list types: list[str], list[int], etc. via ?x=a&x=b
      - Optional[list[T]]
    """
    ann = param.annotation
    origin = get_origin(ann)

    # list[T]
    if origin is list:
        inner = get_args(ann)[0] if get_args(ann) else str
        values = request.query_params.getlist(name)
        return [_coerce_scalar(v, inner) for v in values]

    # Optional[list[T]] -> Union[list[T], None]
    unwrapped = _unwrap_optional(ann)
    if get_origin(unwrapped) is list:
        inner = get_args(unwrapped)[0] if get_args(unwrapped) else str
        values = request.query_params.getlist(name)
        return [_coerce_scalar(v, inner) for v in values]

    # scalar
    return _coerce_scalar(request.query_params.get(name), ann)


def register_routes():
    idx = get_files_index()
    for route in idx.routes:
        base_path = f"src/app/{route.fs_dir}" if route.fs_dir else "src/app"
        file_name = "index.py" if route.has_py else "index.html"
        full_path = f"{base_path}/{file_name}".replace('//', '/')
        register_single_route(route.fastapi_rule, full_path)


def register_single_route(url_pattern: str, file_path: str):
    async def make_handler(request: Request):
        _runtime_metadata.set(None)
        _runtime_injections.set({"head": [], "body": []})

        kwargs = dict(request.path_params)
        current_uri = request.url.path

        # 1. Cache Check (Fast Path)
        if request.method == 'GET':
            cached_resp = CacheHandler.serve_cache(current_uri, DEFAULT_TTL)
            if cached_resp:
                return HTMLResponse(content=cached_resp)

        route_dir = os.path.dirname(file_path)
        page_metadata = {}
        page_layout_props = {}
        content = ""

        req_should_cache = None
        req_cache_ttl = 0

        if file_path.endswith('.py'):
            module = load_route_module(file_path)
            if not hasattr(module, 'page'):
                raise AttributeError(f"Missing 'def page():' in {file_path}")

            sig = inspect.signature(module.page)
            call_kwargs = {}
            call_args = []

            if kwargs:
                call_args.append(kwargs)
            if 'request' in sig.parameters:
                call_kwargs['request'] = request

            for name, param in sig.parameters.items():
                if name in call_kwargs:
                    continue
                if name in ("kwargs",):
                    continue
                if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                if name in request.query_params:
                    call_kwargs[name] = _coerce_query_param(
                        request, name, param)

            if inspect.iscoroutinefunction(module.page):
                result = await module.page(*call_args, **call_kwargs)
            else:
                result = module.page(*call_args, **call_kwargs)

            if isinstance(result, Response):
                return result

            if inspect.isasyncgen(result) or inspect.isgenerator(result):
                return SSE(result)

            cache_settings = getattr(module, 'cache_settings', None)
            if cache_settings:
                req_should_cache = cache_settings.enabled
                req_cache_ttl = cache_settings.ttl

            if isinstance(result, tuple):
                content = str(result[0])
                if len(result) >= 2 and isinstance(result[1], dict):
                    page_layout_props = result[1]
            else:
                content = str(result)

            dynamic_meta = _runtime_metadata.get()
            static_meta = getattr(module, 'metadata', None)

            def extract_meta(obj):
                d = {}
                if not obj:
                    return d
                if obj.title:
                    d['title'] = obj.title
                if obj.description:
                    d['description'] = obj.description
                if obj.extra:
                    d.update(obj.extra)
                return d

            page_metadata.update(extract_meta(static_meta))
            page_metadata.update(extract_meta(dynamic_meta))
        else:
            content = load_template_file(file_path)

        content = transform_components(content, base_dir=route_dir)
        full_context = {**kwargs, "request": request, **page_layout_props}

        html_output, root_layout_id = render_with_nested_layouts(
            children=content,
            route_dir=route_dir,
            page_metadata=page_metadata,
            page_layout_props=page_layout_props,
            context_data=full_context,
            component_compiler=transform_components
        )

        html_output = transform_scripts(html_output)
        response = HTMLResponse(content=html_output)
        response.headers['X-PP-Root-Layout'] = root_layout_id

        # Cache Save Logic
        should_cache = False
        if req_should_cache is True:
            should_cache = True
        elif req_should_cache is False:
            should_cache = False
        else:
            should_cache = CACHE_ENABLED

        if should_cache and request.method == 'GET':
            ttl_to_save = req_cache_ttl if req_cache_ttl > 0 else DEFAULT_TTL
            CacheHandler.save_cache(current_uri, html_output, ttl_to_save)

        return response

    endpoint = file_path.replace('/', '_').replace('\\', '_').replace(
        '.', '_').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
    app.add_api_route(url_pattern, make_handler, methods=[
                      'GET', 'POST'], name=endpoint)


register_routes()
register_rpc_routes(app)

# ====
# Custom Exception Handlers (404 & 500)
# ====


@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        not_found_path = os.path.join('src', 'app', 'not-found.html')
        if os.path.exists(not_found_path):
            with open(not_found_path, 'r', encoding='utf-8') as f:
                content = f.read()
            html_output, root_layout_id = render_with_nested_layouts(
                children=content,
                route_dir='src/app',
                page_metadata={
                    'title': "Page Not Found",
                    'description': "The page you are looking for does not exist."
                },
                page_layout_props=None,
                context_data={'request': request},
                transform_fn=transform_scripts
            )
            resp = HTMLResponse(content=html_output, status_code=404)
            resp.headers['X-PP-Root-Layout'] = root_layout_id
            return resp
    return HTMLResponse(content=f"<h1>{exc.detail}</h1>", status_code=exc.status_code)


@app.exception_handler(Exception)
async def custom_general_exception_handler(request: Request, exc: Exception):
    print(traceback.format_exc())
    error_message = str(exc)
    error_trace = traceback.format_exc() if not IS_PRODUCTION else None
    error_page_path = os.path.join('src', 'app', 'error.html')
    if os.path.exists(error_page_path):
        with open(error_page_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        context_data = {'request': request,
                        'error_message': error_message, 'error_trace': error_trace}
        try:
            rendered_content = string_env.from_string(
                raw_content).render(**context_data)
            html_output, root_layout_id = render_with_nested_layouts(
                children=rendered_content,
                route_dir='src/app',
                page_metadata={
                    'title': 'Application Error',
                    'description': 'An unexpected error occurred.'
                },
                page_layout_props=None,
                context_data=context_data,
                transform_fn=transform_scripts
            )
            resp = HTMLResponse(content=html_output, status_code=500)
            resp.headers['X-PP-Root-Layout'] = root_layout_id
            return resp
        except Exception as render_exc:
            print("Error rendering error.html:", render_exc)
    return HTMLResponse(
        content=f"<h1>500 - Internal Server Error</h1><p>{error_message}</p>",
        status_code=500
    )

# ====
# Middleware Order (LAST added runs FIRST)
# ====
app.add_middleware(RPCMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(CSRFMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('AUTH_SECRET', 'change-me'),
    session_cookie=os.getenv('AUTH_COOKIE_NAME', 'session'),
    max_age=SESSION_LIFETIME_HOURS * 3600,
    same_site='lax',
    https_only=IS_PRODUCTION,
    path='/',
)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5091))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
