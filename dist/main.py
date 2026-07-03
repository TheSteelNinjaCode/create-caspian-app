from casp.components_compiler import transform_components
from casp.scripts_type import transform_scripts
from casp.html_native import parse_fragment, serialize_fragment
import asyncio
import inspect
import os
import importlib.util
import secrets
import traceback
import json
import time
from pathlib import Path
from fastapi import (
    FastAPI,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
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
    GoogleProvider,
    GithubProvider,
    configure_auth,
)
from casp.rpc import register_rpc_routes
from casp.layout import (
    render_with_nested_layouts,
    compile_template,
    load_template_file,
    render_page,
    _runtime_injections,
    _runtime_metadata,
)
import hashlib
from casp.streaming import SSE
from typing import Any, AsyncGenerator, Generator, Optional, cast, get_args, get_origin, Union
from urllib.parse import urlparse
from src.lib.auth.auth_config import build_auth_settings
from casp.runtime_security import (
    build_security_headers,
    client_error_message,
    get_session_secret,
    public_file_response,
)
from contextlib import (
    asynccontextmanager,
    AsyncExitStack,
    AbstractAsyncContextManager,
)
from collections.abc import Callable

load_dotenv()
cfg = get_config()

# ====
# CORS configuration (shared .env convention, mirrors casp.rpc origin checks)
# ====


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _configured_cors_origins() -> list[str]:
    """Browser origins allowed to call the app, per the .env convention."""
    origins: list[str] = []
    for raw in (*_csv_env("CORS_ALLOWED_ORIGINS"), os.getenv("APP_BASE_URL", "")):
        value = (raw or "").strip().rstrip("/")
        if value and value not in origins:
            origins.append(value)
    return origins


def _build_mcp_cors_middleware() -> "Middleware":
    """Build the MCP CORS layer from .env, adding MCP-required headers.

    Browser MCP clients (e.g. MCP Inspector "Direct") send an OPTIONS preflight
    and rely on the mcp-session-id / mcp-protocol-version headers, which are not
    in the generic CORS_ALLOWED_HEADERS list, so they are merged in here.
    """
    origins = _configured_cors_origins()
    allow_credentials = _bool_env("CORS_ALLOW_CREDENTIALS")

    if not origins:
        # The CORS spec forbids "*" together with credentials, so when no
        # explicit origin is configured fall back to open + no credentials.
        origins = ["*"]
        allow_credentials = False

    methods = _csv_env("CORS_ALLOWED_METHODS") or [
        "GET", "POST", "DELETE", "OPTIONS"]

    headers = _csv_env("CORS_ALLOWED_HEADERS")
    for required in ("Content-Type", "Accept", "Authorization",
                     "mcp-session-id", "mcp-protocol-version"):
        if required.lower() not in {h.lower() for h in headers}:
            headers.append(required)

    expose = _csv_env("CORS_EXPOSE_HEADERS")
    for required in ("mcp-session-id", "mcp-protocol-version"):
        if required.lower() not in {h.lower() for h in expose}:
            expose.append(required)

    try:
        max_age = int(os.getenv("CORS_MAX_AGE", "600"))
    except ValueError:
        max_age = 600

    return Middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=methods,
        allow_headers=headers,
        expose_headers=expose,
        max_age=max_age,
    )


# ====
# MCP SERVER (mounted into this app so one deploy serves web + MCP)
# ====
mcp_app = None
if cfg.mcp:
    # Optional, feature-gated module: only generated when mcp is enabled in
    # caspian.config.json, so suppress the static "module not found" check.
    from src.lib.mcp.mcp_server import mcp  # type: ignore[import-not-found]
    # Inner path "/" so the mount prefix below is the full endpoint path.
    mcp_app = mcp.http_app(path="/", middleware=[_build_mcp_cors_middleware()])

# ====
# AUTH CONFIGURATION (App behavior - customize here)
# ====


def setup_auth():
    configure_auth(build_auth_settings())
    Auth.set_providers(GithubProvider(), GoogleProvider())


setup_auth()

LifespanFactory = Callable[[FastAPI], AbstractAsyncContextManager[Any]]


def get_app_lifespans() -> list[LifespanFactory]:
    """
    Register all application lifespan handlers here.

    Add a lifespan here when a feature needs startup/shutdown behavior.

    Examples:
    - Telegram bot/domain workers
    - MCP streamable HTTP server
    - Queue workers
    - Background schedulers
    - Database/cache connection managers
    - WebSocket background services

    Rule:
    Each item must be a callable that receives the FastAPI app and returns
    an async context manager.

    Example:
        lifespans.append(app_lifespan)

    For optional/generated features, guard the lifespan with the related
    config flag or runtime availability check.
    """
    lifespans: list[LifespanFactory] = []

    # MCP lifecycle
    # FastMCP needs its lifespan running so the MCP session manager starts.
    if mcp_app is not None:
        lifespans.append(mcp_app.lifespan)

    return lifespans


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """
    Run all registered lifespans using one FastAPI lifespan entrypoint.

    FastAPI accepts only one `lifespan`, so this function composes multiple
    independent startup/shutdown contexts into a single lifecycle.

    Startup order:
    - Same order as `get_app_lifespans()`

    Shutdown order:
    - Reverse order, handled automatically by AsyncExitStack
    """
    async with AsyncExitStack() as stack:
        for lifespan in get_app_lifespans():
            await stack.enter_async_context(lifespan(app))

        yield

app = FastAPI(
    title=cfg.projectName,
    version=cfg.version,
    docs_url="/docs" if cfg.backendOnly else None,
    redoc_url="/redoc" if cfg.backendOnly else None,
    openapi_url="/openapi.json" if cfg.backendOnly else None,
    lifespan=combined_lifespan,
)


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}

# ====
# Configuration
# ====
SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', 7))
MAX_CONTENT_LENGTH_MB = int(os.getenv('MAX_CONTENT_LENGTH_MB', 16))
IS_PRODUCTION = os.getenv('APP_ENV') == 'production'
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'false').lower() == 'true'
DEFAULT_TTL = int(os.getenv('CACHE_TTL', 600))
REQUEST_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv('CASPIAN_REQUEST_TIMEOUT_SECONDS', 20)),
)
# Path prefixes that serve long-lived streaming responses (SSE, etc.) and must
# not be subject to the per-request timeout. The MCP streamable-HTTP transport
# keeps GET /mcp/ open indefinitely; wrapping it in asyncio.wait_for cancels the
# stream mid-response and corrupts the ASGI message sequence.
STREAMING_PATH_PREFIXES = ('/mcp',)
MAX_CONTENT_LENGTH_BYTES = max(1, MAX_CONTENT_LENGTH_MB) * 1024 * 1024


class RequestBodyTooLarge(Exception):
    pass


def _client_error_message(exc: Exception) -> str:
    return client_error_message(exc, is_production=IS_PRODUCTION)


def _get_session_secret() -> str:
    return get_session_secret(is_production=IS_PRODUCTION)


def _build_security_headers() -> dict[str, str]:
    return build_security_headers(is_production=IS_PRODUCTION)


def _dev_cookie_scope() -> str:
    if IS_PRODUCTION:
        return ""

    scope = os.getenv("CASPIAN_BROWSER_SYNC_PORT")
    if scope and scope.isdigit():
        return scope

    if not scope:
        bs_config_path = Path("settings/bs-config.json")
        if bs_config_path.exists():
            try:
                local_url = json.loads(
                    bs_config_path.read_text(encoding="utf-8")
                ).get("local", "")
                parsed_url = urlparse(local_url)
                if parsed_url.hostname in {"localhost", "127.0.0.1"}:
                    scope = str(parsed_url.port or "")
                else:
                    scope = ""
            except (OSError, json.JSONDecodeError):
                scope = ""

    return scope if scope and scope.isdigit() else ""


def _scoped_cookie_name(base_name: str) -> str:
    scope = _dev_cookie_scope()
    return f"{base_name}_{scope}" if scope else base_name


CSRF_COOKIE_NAME = _scoped_cookie_name("pp_csrf")
SESSION_COOKIE_NAME = _scoped_cookie_name(
    os.getenv('AUTH_COOKIE_NAME', 'session')
)

# ====
# Static File Routes
# ====


@app.get('/css/{filename:path}')
async def serve_css(filename: str):
    return public_file_response('public/css', filename, media_type='text/css')


@app.get('/js/{filename:path}')
async def serve_js(filename: str):
    return public_file_response(
        'public/js',
        filename,
        media_type='application/javascript',
    )


@app.get('/assets/{filename:path}')
async def serve_assets(filename: str):
    return public_file_response('public/assets', filename)


@app.get('/uploads/{filename:path}')
async def serve_uploads(filename: str):
    return public_file_response('public/uploads', filename)


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
                cookie_value = f"{CSRF_COOKIE_NAME}={csrf_token}; Path=/; SameSite=Lax"
                if IS_PRODUCTION:
                    cookie_value += "; Secure"
                new_headers = list(message.get("headers", []))
                new_headers.append((b"set-cookie", cookie_value.encode()))
                message = {**message, "headers": new_headers}
            await send(message)
        await self.app(scope, receive, send_wrapper)


class SecurityHeadersMiddleware:
    """Attach baseline browser security headers to HTTP responses."""

    def __init__(self, app: ASGIApp): self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                headers = MutableHeaders(raw=raw_headers)
                for name, value in _build_security_headers().items():
                    if headers.get(name) is None:
                        headers[name] = value
                message = {**message, "headers": raw_headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Reject oversized HTTP request bodies before route or RPC parsing."""

    def __init__(self, app: ASGIApp): self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_CONTENT_LENGTH_BYTES:
                    await self._send_too_large(send)
                    return
            except ValueError:
                pass

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_CONTENT_LENGTH_BYTES:
                    raise RequestBodyTooLarge()
            return message

        async def send_wrapper(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except RequestBodyTooLarge:
            if not response_started:
                await self._send_too_large(send)

    async def _send_too_large(self, send: Send):
        response = Response(
            content="Request body too large.",
            status_code=413,
            media_type="text/plain",
        )

        async def receive_empty_body():
            return {"type": "http.request", "body": b"", "more_body": False}

        await response(
            {"type": "http", "method": "POST", "path": "/", "headers": []},
            receive=receive_empty_body,
            send=send,
        )


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
            oauth_response = await auth_inst.auth_providers(*providers)
            if oauth_response:
                await oauth_response(scope, receive, send)
                return
        is_authenticated = auth_inst.is_authenticated()
        if is_authenticated:
            auth_inst.refresh_session()
        if auth_inst.is_public_route(path):
            await self.app(scope, receive, send)
            return
        if auth_inst.is_auth_route(path):
            if is_authenticated:
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
                if not is_authenticated:
                    await RedirectResponse(url=f'/signin?next={path}', status_code=303)(scope, receive, send)
                    return
                if not auth_inst.check_role(auth_inst.get_payload(), required_roles):
                    await RedirectResponse(url='/unauthorized', status_code=303)(scope, receive, send)
                    return

        if auth_inst.is_private_route(path):
            if not is_authenticated:
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


class RequestDiagnosticsMiddleware:
    """Log request start/end in dev and fail visibly when a route stalls."""

    def __init__(self, app: ASGIApp): self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        should_log = not path.startswith(
            ('/css/', '/js/', '/assets/', '/favicon.ico'))
        started = time.perf_counter()

        if should_log and not IS_PRODUCTION:
            print(f"[request:start] {method} {path}", flush=True)

        # Long-lived streaming endpoints (MCP SSE) must bypass the timeout, or
        # asyncio.wait_for cancels the stream and the ASGI send sequence breaks.
        if path.startswith(STREAMING_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            print(
                f"[request:timeout] {method} {path} exceeded "
                f"{REQUEST_TIMEOUT_SECONDS:g}s after {elapsed_ms}ms",
                flush=True,
            )
            response = HTMLResponse(
                content=(
                    "<h1>504 - Request Timeout</h1>"
                    "<p>The route took too long to respond. "
                    "Check the development terminal for the stalled path.</p>"
                ),
                status_code=504,
            )
            await response(scope, receive, send)
            return
        except Exception:
            if should_log and not IS_PRODUCTION:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                print(
                    f"[request:error] {method} {path} after {elapsed_ms}ms", flush=True)
            raise
        finally:
            if should_log and not IS_PRODUCTION:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                print(
                    f"[request:end] {method} {path} {elapsed_ms}ms", flush=True)


# ====
# WebSocket Routes (optional - gated by caspian.config.json `websocket`)
# ====
WEBSOCKET_PATH = "/ws/live"
PUBLIC_WEBSOCKET_PATH = "/ws/public"
WEBSOCKET_IDLE_TIMEOUT_SECONDS = max(
    10,
    int(os.getenv('WEBSOCKET_IDLE_TIMEOUT_SECONDS', 120)),
)
MAX_WEBSOCKET_MESSAGE_BYTES = max(
    256,
    int(os.getenv('MAX_WEBSOCKET_MESSAGE_BYTES', 4096)),
)


async def _run_websocket_channel(
    websocket: WebSocket,
    manager: Any,
    payload: dict[str, Any] | None,
    ready_message: str,
):
    await manager.connect(websocket)
    ready_payload: dict[str, Any] = {
        "type": "ready",
        "message": ready_message,
    }
    if payload is not None:
        ready_payload["payload"] = payload
    await websocket.send_json(ready_payload)

    try:
        while True:
            try:
                raw_message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WEBSOCKET_IDLE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                return

            if len(raw_message.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                return

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Messages must be valid JSON.",
                })
                continue

            if not isinstance(message, dict):
                await websocket.send_json({
                    "type": "error",
                    "message": "Messages must be JSON objects.",
                })
                continue

            message_type = str(message.get("type", "message"))
            if message_type == "ping":
                await websocket.send_json({"type": "pong", "time": int(time.time())})
                continue

            text = str(message.get("text", "")).strip()
            if not text:
                await websocket.send_json({
                    "type": "error",
                    "message": "Message text is required.",
                })
                continue

            outgoing_payload: dict[str, Any] = {
                "type": "message",
                "text": text[:1000],
                "time": int(time.time()),
            }
            if payload is not None:
                outgoing_payload["payload"] = payload
            await manager.broadcast_json(outgoing_payload)
    except WebSocketDisconnect:
        return
    finally:
        manager.disconnect(websocket)


if cfg.websocket:
    # Optional, feature-gated module: only generated when websocket is enabled
    # in caspian.config.json, so suppress the static "module not found" check.
    from src.lib.websocket.websocket_security import (  # type: ignore[import-not-found]
        authorize_websocket,
        public_websocket_connections,
        websocket_connections,
    )

    # Both endpoints share ONE guard (`authorize_websocket`) that delegates to
    # Caspian's `Auth`, and ONE transport loop (`_run_websocket_channel`). They
    # differ only by auth policy and broadcast pool. To role-gate a channel,
    # pass `roles=[...]`; to add another channel, add an endpoint that calls the
    # same guard.

    @app.websocket(WEBSOCKET_PATH)
    async def websocket_live_endpoint(websocket: WebSocket):
        if await authorize_websocket(websocket, require_auth=True) is None:
            return

        await _run_websocket_channel(
            websocket,
            websocket_connections,
            None,
            "Private WebSocket connected.",
        )

    @app.websocket(PUBLIC_WEBSOCKET_PATH)
    async def websocket_public_endpoint(websocket: WebSocket):
        if await authorize_websocket(websocket, require_auth=False) is None:
            return

        await _run_websocket_channel(
            websocket,
            public_websocket_connections,
            {"guest": True, "scope": "public"},
            "Public WebSocket connected.",
        )

# ====
# Route Registration
# ====


_route_module_cache = {}
_route_signature_cache = {}


def load_route_module(file_path: str):
    abs_path = os.path.abspath(file_path)
    try:
        mtime_ns = os.stat(abs_path).st_mtime_ns
    except OSError:
        raise FileNotFoundError(f"Route module not found: {abs_path}")

    cached = _route_module_cache.get(abs_path)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]

    unique_id = hashlib.md5(abs_path.encode()).hexdigest()[:8]
    module_name = f"page_{unique_id}"
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    assert spec is not None and spec.loader is not None, f"Cannot load spec for {file_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    setattr(module, 'render_page', render_page)
    _route_module_cache[abs_path] = (mtime_ns, module)
    _route_signature_cache.pop(abs_path, None)
    return module


def get_page_signature(file_path: str, page_func):
    abs_path = os.path.abspath(file_path)
    cached = _route_signature_cache.get(abs_path)
    if cached is not None and cached[0] is page_func:
        return cached[1]

    sig = inspect.signature(page_func)
    _route_signature_cache[abs_path] = (page_func, sig)
    return sig


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
        if CACHE_ENABLED and request.method == 'GET':
            cached_resp = CacheHandler.serve_cache(current_uri, DEFAULT_TTL)
            if cached_resp:
                return HTMLResponse(content=cached_resp)

        route_dir = os.path.dirname(file_path)
        page_metadata = {}
        page_layout_props = {}
        content = ""

        req_should_cache = None
        req_cache_ttl = 0

        page_content_source = file_path

        if file_path.endswith('.py'):
            module = load_route_module(file_path)
            if not hasattr(module, 'page'):
                raise AttributeError(f"Missing 'def page():' in {file_path}")

            sig = get_page_signature(file_path, module.page)
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
                return SSE(cast("AsyncGenerator | Generator", result))

            cache_settings = getattr(module, 'cache_settings', None)
            if cache_settings:
                req_should_cache = cache_settings.enabled
                req_cache_ttl = cache_settings.ttl

            if isinstance(result, tuple):
                page_content = result[0]
                content = str(page_content)
                page_content_source = getattr(
                    page_content, 'source_path', file_path)
                if len(result) >= 2 and isinstance(result[1], dict):
                    page_layout_props = result[1]
            else:
                content = str(result)
                page_content_source = getattr(result, 'source_path', file_path)

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

        content = await transform_components(content, base_dir=route_dir)
        full_context = {**kwargs, "request": request, **page_layout_props}

        html_output, root_layout_id = await render_with_nested_layouts(
            children=content,
            route_dir=route_dir,
            page_metadata=page_metadata,
            page_layout_props=page_layout_props,
            context_data=full_context,
            page_component_source=page_content_source,
            control_mode=True,
            component_compiler=transform_components
        )

        html_output = finalize_html(html_output)
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

    route_methods = ['GET', 'POST']
    if file_path.endswith('.py'):
        module = load_route_module(file_path)
        declared_route_methods = getattr(module, 'route_methods', None)
        if isinstance(declared_route_methods, (list, tuple)) and declared_route_methods:
            normalized_methods = [
                str(method).strip().upper()
                for method in declared_route_methods
                if str(method).strip()
            ]
            if normalized_methods:
                route_methods = list(dict.fromkeys(normalized_methods))

    app.add_api_route(url_pattern, make_handler,
                      methods=route_methods, name=endpoint)


def defer_component_roots(html_output: str) -> str:
    """Wrap top-level ``[pp-component]`` roots in an inert ``<template>``.

    The browser never parses/validates/fetches the contents of a ``<template>``
    element, so raw ``{...}`` placeholders inside SVG geometry attributes, form
    ``value``/date inputs, ``src``/``href`` URLs, or table/select structure no
    longer trigger console errors, bogus ``404`` requests, value coercion, or
    HTML foster-parenting before hydration. PulsePoint's ``mount()`` bootstrap
    materializes ``template[pp-component]`` back into live DOM (reusing the
    existing ``materializeTemplateComponentBoundaries`` path) before it scans
    for component roots, so post-hydration behavior is identical to today.

    Only the outermost (non-nested) roots are wrapped; nested component
    boundaries ride along inside the inert content and become live when the
    outer template is materialized, so morphing and RPC re-render still operate
    on live ``[pp-component]`` DOM.
    """
    if 'pp-component' not in html_output:
        return html_output

    soup = parse_fragment(html_output)
    body = soup.body
    if body is None:
        return html_output

    roots = [
        el for el in body.select('[pp-component]')
        if el.name != 'template'
        and not any(
            parent.has_attr('pp-component') for parent in el.parents
        )
    ]
    if not roots:
        return html_output

    for root in roots:
        key = root.get('pp-component')
        if key is None:
            continue
        template = soup.new_tag('template')
        template['pp-component'] = key
        root.insert_before(template)
        template.append(root.extract())

    return serialize_fragment(soup)


def finalize_html(html_output: str) -> str:
    """Final full-document transforms applied just before the response.

    Runs ``transform_scripts`` (author ``<script>`` -> ``type="text/pp"``) then
    ``defer_component_roots`` so scripts are tagged before they are moved into
    the inert component ``<template>``.
    """
    return defer_component_roots(transform_scripts(html_output))


register_routes()
register_rpc_routes(app)

# Mount the FastMCP app at /mcp so the endpoint is exactly /mcp.
if mcp_app is not None:
    app.mount("/mcp", mcp_app)

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
            html_output, root_layout_id = await render_with_nested_layouts(
                children=content,
                route_dir='src/app',
                page_metadata={
                    'title': "Page Not Found",
                    'description': "The page you are looking for does not exist."
                },
                page_layout_props=None,
                context_data={'request': request},
                page_component_source=not_found_path,
                control_mode=True,
                transform_fn=finalize_html
            )
            resp = HTMLResponse(content=html_output, status_code=404)
            resp.headers['X-PP-Root-Layout'] = root_layout_id
            return resp
    return HTMLResponse(content=f"<h1>{exc.detail}</h1>", status_code=exc.status_code)


@app.exception_handler(Exception)
async def custom_general_exception_handler(request: Request, exc: Exception):
    full_trace = traceback.format_exc()
    print(full_trace)
    error_message = _client_error_message(exc)
    error_trace = full_trace if not IS_PRODUCTION else None

    error_page_path = os.path.join('src', 'app', 'error.html')
    if os.path.exists(error_page_path):
        with open(error_page_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        context_data = {'request': request,
                        'error_message': error_message, 'error_trace': error_trace}
        try:
            rendered_content = compile_template(
                raw_content).render(**context_data)
            html_output, root_layout_id = await render_with_nested_layouts(
                children=rendered_content,
                route_dir='src/app',
                page_metadata={
                    'title': 'Application Error',
                    'description': 'An unexpected error occurred.'
                },
                page_layout_props=None,
                context_data=context_data,
                page_component_source=error_page_path,
                control_mode=True,
                transform_fn=finalize_html
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
    secret_key=_get_session_secret(),
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_LIFETIME_HOURS * 3600,
    same_site='lax',
    https_only=IS_PRODUCTION,
    path='/',
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

if not IS_PRODUCTION:
    app.add_middleware(RequestDiagnosticsMiddleware)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5091))
    workers = max(1, int(os.getenv('UVICORN_WORKERS', '1')))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=workers,
    )
