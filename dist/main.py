from casp.components_compiler import transform_components
from casp.html_native import (
    _ESCAPED_BRACE_PLACEHOLDER_RE,
    mask_escaped_brace_entities,
    parse_fragment,
    restore_escaped_brace_entities,
    serialize_fragment,
)
import asyncio
import inspect
import os
import importlib.util
import re
import secrets
import traceback
import json
import math
import time
from pathlib import Path
from fastapi import (
    FastAPI,
    Request,
    Response,
    WebSocket,
)
from fastapi.responses import (
    RedirectResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
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
from casp.rpc import register_rpc_routes, rpc_limiter
from casp.layout import (
    render_with_nested_layouts,
    _finalize_page_region,
    _runtime_injections,
    _runtime_metadata,
)
import hashlib
from casp.streaming import SSE
from typing import Any, AsyncGenerator, Generator, Optional, cast, get_args, get_origin, Union
from urllib.parse import urlparse
from bs4.element import NavigableString, Tag
from src.lib.auth.auth_config import build_auth_settings
from casp.app_time import get_app_timezone
from casp.runtime_security import (
    INLINE_SAFE_UPLOAD_MEDIA_TYPES,
    build_security_headers,
    client_error_message,
    get_session_secret,
    is_production_environment,
    PublicFilesMiddleware,
    resolve_safe_public_path,
)
from contextlib import (
    asynccontextmanager,
    AsyncExitStack,
    AbstractAsyncContextManager,
)
from collections.abc import Callable

load_dotenv()
cfg = get_config()

# Declared before the MCP block below, which needs it to decide whether an
# unauthenticated endpoint or an open CORS policy is tolerable. Resolved
# fail-closed: only an explicit development APP_ENV turns the relaxations on.
IS_PRODUCTION = is_production_environment()

# Resolve APP_TIMEZONE once at import so an unknown zone name fails at boot with
# a named error, rather than on whichever request first formats a date. Only the
# calendar is affected -- session expiry and cache TTLs stay on UTC by design.
APP_TIMEZONE = get_app_timezone()

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
        # No configured origin. In development, fall back to open + no
        # credentials so browser MCP clients (Inspector "Direct") still work --
        # the CORS spec forbids "*" together with credentials anyway. In
        # production, "*" would let any site on the internet read the MCP
        # endpoint's responses, so deny cross-origin instead of guessing.
        if IS_PRODUCTION:
            origins = []
        else:
            origins = ["*"]
        allow_credentials = False

    methods = _csv_env("CORS_ALLOWED_METHODS") or ["GET", "POST", "DELETE", "OPTIONS"]

    headers = _csv_env("CORS_ALLOWED_HEADERS")
    for required in (
        "Content-Type",
        "Accept",
        "Authorization",
        "mcp-session-id",
        "mcp-protocol-version",
    ):
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


class MCPAuthMiddleware:
    """Bearer-token gate for the mounted MCP endpoint.

    The MCP app is mounted outside the page-routing tree, so `AuthMiddleware`
    never protects it: `is_private_route("/mcp")` is false under the app's
    public-first policy, and an MCP client is not a browser carrying a session
    cookie anyway. Without this guard the endpoint answers anyone on the
    internet, and its tools enumerate the workspace's generated file inventory
    and component map.

    `MCP_AUTH_TOKEN` in .env is the credential. When it is unset the endpoint
    stays open in development (local tooling, MCP Inspector) but refuses every
    request in production rather than silently serving workspace metadata.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CORS preflight carries no Authorization header by design, and the
        # CORS layer outside this one answers it without reaching the tools.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        expected_token = (os.getenv("MCP_AUTH_TOKEN") or "").strip()

        if not expected_token:
            if IS_PRODUCTION:
                await self._deny(
                    send,
                    503,
                    "MCP endpoint is disabled: MCP_AUTH_TOKEN is not configured.",
                )
                return
            await self.app(scope, receive, send)
            return

        header = Request(scope, receive, send).headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            presented.strip(), expected_token
        ):
            await self._deny(send, 401, "Invalid or missing MCP bearer token.")
            return

        await self.app(scope, receive, send)

    async def _deny(self, send: Send, status_code: int, message: str):
        response = JSONResponse({"error": message}, status_code=status_code)

        async def receive_empty_body():
            return {"type": "http.request", "body": b"", "more_body": False}

        await response(
            {"type": "http", "method": "POST", "path": "/", "headers": []},
            receive=receive_empty_body,
            send=send,
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
    # CORS is outermost so preflight is answered before the token check.
    mcp_app = mcp.http_app(
        path="/",
        middleware=[
            _build_mcp_cors_middleware(),
            Middleware(MCPAuthMiddleware),
        ],
    )

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
SESSION_LIFETIME_HOURS = int(os.getenv("SESSION_LIFETIME_HOURS", 7))
MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH_MB", 16))
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "false").lower() == "true"
DEFAULT_TTL = int(os.getenv("CACHE_TTL", 600))
REQUEST_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("CASPIAN_REQUEST_TIMEOUT_SECONDS", 20)),
)
# Path prefixes that serve long-lived streaming responses (SSE, etc.) and must
# not be subject to the per-request timeout. The MCP streamable-HTTP transport
# keeps GET /mcp/ open indefinitely; wrapping it in asyncio.wait_for cancels the
# stream mid-response and corrupts the ASGI message sequence.
STREAMING_PATH_PREFIXES = ("/mcp",)
# Public assets: exempt from auth, request logging, and rate limiting, since one
# page load pulls many of them.
MAX_CONTENT_LENGTH_BYTES = max(1, MAX_CONTENT_LENGTH_MB) * 1024 * 1024


class RequestBodyTooLarge(Exception):
    pass


def _client_error_message(exc: Exception) -> str:
    return client_error_message(exc, is_production=IS_PRODUCTION)


def _get_session_secret() -> str:
    return get_session_secret(is_production=IS_PRODUCTION)


def _build_security_headers() -> dict[str, str]:
    return build_security_headers(is_production=IS_PRODUCTION)


# The header set depends only on IS_PRODUCTION, so build it once at import time
# instead of allocating an identical dict on every single response.
SECURITY_HEADERS: tuple[tuple[str, str], ...] = tuple(_build_security_headers().items())


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
                local_url = json.loads(bs_config_path.read_text(encoding="utf-8")).get("local", "")
                parsed_url = urlparse(local_url)
                if parsed_url.hostname in {"localhost", "127.0.0.1"}:
                    scope = str(parsed_url.port or "")
                else:
                    scope = ""
            except OSError, json.JSONDecodeError:
                scope = ""

    return scope if scope and scope.isdigit() else ""


def _scoped_cookie_name(base_name: str) -> str:
    scope = _dev_cookie_scope()
    return f"{base_name}_{scope}" if scope else base_name


CSRF_COOKIE_NAME = _scoped_cookie_name("pp_csrf")
SESSION_COOKIE_NAME = _scoped_cookie_name(os.getenv("AUTH_COOKIE_NAME", "session"))

# ====
# Pure ASGI Middleware Classes
# ====


class CSRFMiddleware:
    """CSRF middleware that properly handles session modifications."""

    def __init__(self, app: ASGIApp):
        self.app = app

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

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                headers = MutableHeaders(raw=raw_headers)
                for name, value in SECURITY_HEADERS:
                    if headers.get(name) is None:
                        headers[name] = value
                message = {**message, "headers": raw_headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Top-level directories under `public/` are asset namespaces, not page routes:
# `public/js/**` owns `/js/**` and nothing in `src/app/` can answer there. Built
# once, like SECURITY_HEADERS -- adding a new asset *directory* is a restart-level
# change, unlike adding a file to an existing one, which stays live.
PUBLIC_ASSET_NAMESPACES: frozenset[str] = (
    frozenset(entry.name.casefold() for entry in Path("public").iterdir() if entry.is_dir())
    if Path("public").is_dir()
    else frozenset()
)


class MissingPublicAssetMiddleware:
    """404 a missing file in a public asset namespace instead of falling through.

    `PublicFilesMiddleware` deliberately falls through when no file matches, so
    normal routing keeps working. With `is_all_routes_private=True` that means a
    missing asset reaches `AuthMiddleware` and answers `303 -> /signin`, which is
    the wrong answer twice over: a `<script src="/js/typo.js">` then receives the
    sign-in *page* as `200 text/html` and fails with a parse error that names the
    wrong file, and every bogus asset path returns a full HTML page to anonymous
    traffic. A path whose first segment is a real `public/` directory can only be
    an asset request, so a miss there is a genuine 404.

    Runs inside the rate limiter -- a 404 flood is still a flood -- but outside
    sessions, CSRF, and auth, so a missing asset costs no session decryption.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope.get("method", "GET").upper() not in {
            "GET",
            "HEAD",
        }:
            await self.app(scope, receive, send)
            return

        segment = str(scope.get("path", "")).lstrip("/").split("/", 1)[0].casefold()
        if segment not in PUBLIC_ASSET_NAMESPACES:
            await self.app(scope, receive, send)
            return

        # PublicFilesMiddleware sits outside this one, so reaching here means it
        # already declined: the file does not exist or escapes the public root.
        await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)


class BodySizeLimitMiddleware:
    """Reject oversized HTTP request bodies before route or RPC parsing."""

    def __init__(self, app: ASGIApp):
        self.app = app

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

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive, send)
        path = request.url.path
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
                    url=auth_inst.settings.default_signin_redirect, status_code=303
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        if auth_inst.settings.is_role_based:
            required_roles = auth_inst.get_required_roles(path)
            if required_roles:
                if not is_authenticated:
                    await RedirectResponse(
                        url=auth_inst.get_signin_redirect(path),
                        status_code=303,
                    )(scope, receive, send)
                    return
                if not auth_inst.check_role(auth_inst.get_payload(), required_roles):
                    await RedirectResponse(url="/unauthorized", status_code=303)(
                        scope, receive, send
                    )
                    return

        if auth_inst.is_private_route(path):
            if not is_authenticated:
                await RedirectResponse(
                    url=auth_inst.get_signin_redirect(path),
                    status_code=303,
                )(scope, receive, send)
                return

        await self.app(scope, receive, send)


class RPCMiddleware:
    """RPC middleware using pure ASGI pattern."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive, send)
        if request.headers.get("X-PP-RPC") == "true" and request.method == "POST":
            from casp.rpc import _handle_rpc_request

            session = dict(request.session) if hasattr(request, "session") else {}
            response = await _handle_rpc_request(request, session)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


RATE_LIMIT_PAGES = os.getenv("RATE_LIMIT_PAGES", "200/minute")


def client_ip(request: Request) -> str:
    """Best-effort client address for rate-limit bucketing.

    Behind a reverse proxy every request arrives from the proxy's address, which
    would collapse all users into one bucket and make limiting useless. The
    forwarded chain is only consulted when the deployment opts in via
    `TRUST_FORWARDED_HEADERS`, because a client can otherwise set that header
    itself and mint a fresh bucket per request.
    """
    if _bool_env("TRUST_FORWARDED_HEADERS"):
        forwarded = request.headers.get("x-forwarded-for", "")
        first_hop = forwarded.split(",", 1)[0].strip()
        if first_hop:
            return first_hop

    return request.client.host if request.client else "unknown"


class RateLimitMiddleware:
    """Per-IP request cap on page routes.

    Caspian ships `slowapi` with a `RATE_LIMIT_DEFAULT`, but its
    `SlowAPIMiddleware` is never added to the stack, so that setting has no
    effect and page routes -- including sign-in -- accept unlimited attempts.
    This restores an actual limit using the same bucket implementation the RPC
    layer already uses.

    Static assets and `/health` are exempt on purpose: one page load pulls many
    CSS/JS/image requests, so counting them against a page budget would throttle
    normal browsing long before it throttled an attacker.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or not RATE_LIMIT_PAGES:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/health":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive, send)
        allowed, wait_seconds = rpc_limiter.check("__page__", client_ip(request), RATE_LIMIT_PAGES)

        if not allowed:
            response = HTMLResponse(
                content=(
                    "<h1>429 - Too Many Requests</h1><p>Please slow down and try again shortly.</p>"
                ),
                status_code=429,
                headers={"Retry-After": str(math.ceil(wait_seconds))},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class RequestDiagnosticsMiddleware:
    """Log request start/end in dev and fail visibly when a route stalls."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        is_public_file = (
            method in {"GET", "HEAD"}
            and resolve_safe_public_path(
                "public",
                path.lstrip("/"),
            )
            is not None
        )
        should_log = not is_public_file
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
                print(f"[request:error] {method} {path} after {elapsed_ms}ms", flush=True)
            raise
        finally:
            if should_log and not IS_PRODUCTION:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                print(f"[request:end] {method} {path} {elapsed_ms}ms", flush=True)


# ====
# WebSocket Routes (optional - gated by caspian.config.json `websocket`)
# ====

if cfg.websocket:
    # Optional, feature-gated module: only generated when websocket is enabled
    # in caspian.config.json, so suppress the static "module not found" check.
    from src.lib.websocket.sockets import (  # type: ignore[import-not-found]
        SOCKET_PATH,
        serve_named_socket,
    )

    # Named sockets: the server half of `pp.socket(...)`. One endpoint for
    # every `@socket()` function; the function is named in the `name` query
    # parameter and the arguments arrive as the connection's first frame.
    # Auth policy is per socket -- `@socket(require_auth=True, allowed_roles=
    # [...])` -- so there are no separate public/private channel endpoints.
    # Origin check, auth delegation, and connection/message limits live in
    # `serve_named_socket` so this stays a pure wiring point.
    @app.websocket(SOCKET_PATH)
    async def websocket_named_socket_endpoint(websocket: WebSocket):
        await serve_named_socket(websocket)

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


def is_request_cacheable(request: Request) -> bool:
    """Whether this request's rendered HTML may enter the shared page cache.

    `CacheHandler` keys entries on the URI alone, with no session component, so
    a page rendered for a signed-in user would be written to `caches/` in plain
    text and later served verbatim to whoever asks for that URL next --
    including a different user or an anonymous visitor. Only GETs from
    unauthenticated sessions are eligible.

    The check is deliberately on the *request*, not the route: a route does not
    know whether the page it just rendered contains per-user data, so the
    presence of an authenticated session is the safe signal.
    """
    if request.method != "GET":
        return False

    try:
        return not Auth.get_instance().is_authenticated()
    except Exception:
        # An unreadable session means we cannot prove the response is generic.
        return False


def register_routes():
    idx = get_files_index()
    for route in idx.routes:
        base_path = f"src/app/{route.fs_dir}" if route.fs_dir else "src/app"
        full_path = f"{base_path}/index.py".replace("//", "/")
        register_single_route(route.fastapi_rule, full_path)


def register_single_route(url_pattern: str, file_path: str):
    async def make_handler(request: Request):
        _runtime_metadata.set(None)
        _runtime_injections.set({"head": [], "body": []})

        kwargs = dict(request.path_params)
        current_uri = request.url.path
        request_is_cacheable = is_request_cacheable(request)

        # 1. Cache Check (Fast Path)
        if CACHE_ENABLED and request_is_cacheable:
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

        module = load_route_module(file_path)
        if not hasattr(module, "page"):
            raise AttributeError(f"Missing 'def page():' in {file_path}")

        sig = get_page_signature(file_path, module.page)
        call_kwargs = {}
        call_args = []

        if kwargs:
            call_args.append(kwargs)
        if "request" in sig.parameters:
            call_kwargs["request"] = request

        for name, param in sig.parameters.items():
            if name in call_kwargs:
                continue
            if name in ("kwargs",):
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if name in request.query_params:
                call_kwargs[name] = _coerce_query_param(request, name, param)

        if inspect.iscoroutinefunction(module.page):
            result = await module.page(*call_args, **call_kwargs)
        else:
            result = module.page(*call_args, **call_kwargs)

        if isinstance(result, Response):
            return result

        if inspect.isasyncgen(result) or inspect.isgenerator(result):
            return SSE(cast("AsyncGenerator | Generator", result))

        cache_settings = getattr(module, "cache_settings", None)
        if cache_settings:
            req_should_cache = cache_settings.enabled
            req_cache_ttl = cache_settings.ttl

        if isinstance(result, tuple):
            page_content = result[0]
            content = str(page_content)
            page_content_source = getattr(page_content, "source_path", file_path)
            if len(result) >= 2 and isinstance(result[1], dict):
                page_layout_props = result[1]
        else:
            content = str(result)
            page_content_source = getattr(result, "source_path", file_path)

        dynamic_meta = _runtime_metadata.get()
        static_meta = getattr(module, "metadata", None)

        def extract_meta(obj):
            d = {}
            if not obj:
                return d
            if obj.title:
                d["title"] = obj.title
            if obj.description:
                d["description"] = obj.description
            if obj.extra:
                d.update(obj.extra)
            return d

        page_metadata.update(extract_meta(static_meta))
        page_metadata.update(extract_meta(dynamic_meta))

        full_context = {**kwargs, "request": request, **page_layout_props}

        html_output, root_layout_id = await render_with_nested_layouts(
            children=content,
            route_dir=route_dir,
            page_metadata=page_metadata,
            page_layout_props=page_layout_props,
            context_data=full_context,
            page_component_source=page_content_source,
            control_mode=True,
            component_compiler=transform_components,
        )

        html_output = finalize_html(html_output)
        response = HTMLResponse(content=html_output)
        response.headers["X-PP-Root-Layout"] = root_layout_id

        # Cache Save Logic
        should_cache = False
        if req_should_cache is True:
            should_cache = True
        elif req_should_cache is False:
            should_cache = False
        else:
            should_cache = CACHE_ENABLED

        # A route opting in with `Cache(...)` still cannot override the
        # per-request check: an authenticated render must never be written to
        # the shared, URI-keyed cache on disk.
        if should_cache and request_is_cacheable:
            ttl_to_save = req_cache_ttl if req_cache_ttl > 0 else DEFAULT_TTL
            CacheHandler.save_cache(current_uri, html_output, ttl_to_save)

        return response

    endpoint = (
        file_path.replace("/", "_")
        .replace("\\", "_")
        .replace(".", "_")
        .replace("[", "")
        .replace("]", "")
        .replace("(", "")
        .replace(")", "")
    )

    route_methods = ["GET", "POST"]
    module = load_route_module(file_path)
    declared_route_methods = getattr(module, "route_methods", None)
    if isinstance(declared_route_methods, (list, tuple)) and declared_route_methods:
        normalized_methods = [
            str(method).strip().upper() for method in declared_route_methods if str(method).strip()
        ]
        if normalized_methods:
            route_methods = list(dict.fromkeys(normalized_methods))

    app.add_api_route(url_pattern, make_handler, methods=route_methods, name=endpoint)


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
    if "pp-component" not in html_output:
        return html_output

    # Fast path: the render pipeline recorded the page subtree's exact
    # serialized bytes. That string is finished bs4-serializer output -- fully
    # normalized, so re-parsing it is pure cost -- and it is usually almost the
    # entire document. Mask it behind a token, run the (now tiny) parse over
    # the layout shell, and apply the same wrap/entity-protection transforms to
    # the region string-level. Every mismatch falls back to the full parse.
    if not _DEFER_FAST_DISABLED:
        region = _finalize_page_region.get()
        if region and len(region) >= _DEFER_REGION_MIN_BYTES and html_output.count(region) == 1:
            deferred = _defer_with_verbatim_region(html_output, region)
            if deferred is not None:
                return deferred

    masked_html, placeholders = mask_escaped_brace_entities(html_output)
    soup = parse_fragment(masked_html)
    return _defer_component_roots_in_soup(soup, placeholders, html_output)


_DEFER_FAST_DISABLED = os.getenv("CASP_DEFER_FAST", "").strip().lower() in {
    "0",
    "off",
    "false",
    "no",
}
# Below this, masking the region saves less than the two extra scans it costs.
_DEFER_REGION_MIN_BYTES = 4096


def _protect_region_brace_entities(value: str) -> str:
    """String-level equivalent of the in-tree brace-entity protection.

    Inside a deferred ``<template>``, each literal brace entity must gain one
    extra encoding layer (``&#123;`` -> ``&amp;#123;``) so the browser's parse
    of the response consumes the outer layer and PulsePoint still sees the
    entity. The tree path achieves this by restoring masked entities into the
    parsed template and letting the serializer escape the ``&``; on a verbatim
    region the same result is a direct substitution.
    """
    from casp.html_native import _ESCAPED_BRACE_ENTITY_RE

    return _ESCAPED_BRACE_ENTITY_RE.sub(lambda match: "&amp;" + match.group(0)[1:], value)


def _defer_with_verbatim_region(html_output: str, region: str) -> Optional[str]:
    """Defer pass with the page subtree masked as an opaque token.

    Returns ``None`` whenever the document does not match the shape this fast
    path understands, in which case the caller re-runs the full-parse pass.
    """
    from casp.html_native import _PLACEHOLDER_COUNTER

    # The region's own root boundary key, when its first tag carries one. The
    # region is serializer output, so '>' cannot appear inside an attribute
    # value and the first '>' reliably ends the opening tag. Edge whitespace is
    # common (a template authored as a triple-quoted string), so probe the
    # stripped core.
    region_root_key = None
    region_core = region.strip()
    open_tag_end = region_core.find(">")
    if region_core.startswith("<") and open_tag_end > 0:
        key_match = re.search(r'\spp-component="([^"]+)"', region_core[: open_tag_end + 1])
        if key_match:
            region_root_key = key_match.group(1)

    token = f"__PP_DEFER_REGION_{next(_PLACEHOLDER_COUNTER)}__"
    masked_doc = html_output.replace(region, token, 1)

    masked_html, placeholders = mask_escaped_brace_entities(masked_doc)
    soup = parse_fragment(masked_html)
    body = soup.body
    if body is None:
        return None

    token_node = None
    for node in body.descendants:
        if isinstance(node, NavigableString) and token in node:
            token_node = node
            break
    if token_node is None:
        # The region did not land in the body (or the parse split the token);
        # nothing this path can reason about.
        return None

    # Inside ANY boundary ancestor means the region ends up inside a deferred
    # template (the outermost one gets wrapped below, or already is one), so
    # its entities need the protection layer but no wrapper of its own.
    region_enclosed = any(
        isinstance(parent, Tag) and parent.has_attr("pp-component") for parent in token_node.parents
    )

    if not region_enclosed and region_root_key is None and "pp-component" in region:
        # Boundaries live inside the region but its root is not one: they
        # would need wrapping at arbitrary depth, which only the tree pass can
        # locate.
        return None

    roots = []
    stack = [child for child in reversed(body.contents) if isinstance(child, Tag)]
    while stack:
        el = stack.pop()
        if el.has_attr("pp-component"):
            if el.name != "template":
                roots.append(el)
            continue
        stack.extend(child for child in reversed(el.contents) if isinstance(child, Tag))

    for root in roots:
        key = root.get("pp-component")
        if key is None:
            continue
        template = soup.new_tag("template")
        template["pp-component"] = key
        root.insert_before(template)
        template.append(root.extract())

    if placeholders:

        def protect_brace_entities(value: str) -> str:
            return _ESCAPED_BRACE_PLACEHOLDER_RE.sub(
                lambda match: placeholders.get(match.group(0), match.group(0)),
                value,
            )

        for template in body.select("template[pp-component]"):
            for node in list(template.descendants):
                if isinstance(node, NavigableString):
                    original = str(node)
                    if "__PP_ESCAPED_BRACE_" not in original:
                        continue
                    content = protect_brace_entities(original)
                    if content != original:
                        node.replace_with(content)
                elif isinstance(node, Tag):
                    for name, value in node.attrs.items():
                        if isinstance(value, str):
                            if "__PP_ESCAPED_BRACE_" in value:
                                node.attrs[name] = protect_brace_entities(value)
                        elif isinstance(value, list):
                            for index, item in enumerate(value):
                                item = str(item)
                                if "__PP_ESCAPED_BRACE_" in item:
                                    item = protect_brace_entities(item)
                                value[index] = item

    serialized = restore_escaped_brace_entities(serialize_fragment(soup), placeholders)
    if token not in serialized:
        return None

    if region_enclosed:
        region_out = _protect_region_brace_entities(region)
    elif region_root_key is not None:
        # The tree path wraps only the root ELEMENT; whitespace at the region's
        # edges stays outside the template. Mirror that here. An edge comment
        # would be ambiguous to split off string-level, so leave that shape to
        # the full parse.
        core = region_core
        if not core.startswith("<") or core[1] in ("!", "?") or core.endswith("-->"):
            return None
        prefix_len = region.find("<")
        prefix = region[:prefix_len]
        suffix = region[prefix_len + len(core) :]
        region_out = (
            f'{prefix}<template pp-component="{region_root_key}">'
            f"{_protect_region_brace_entities(core)}"
            f"</template>{suffix}"
        )
    else:
        region_out = region

    return serialized.replace(token, region_out, 1)


def _defer_component_roots_in_soup(
    soup,
    placeholders,
    fallback_html: str,
) -> str:
    """Shared body of :func:`defer_component_roots`, operating on a parsed soup.

    Split out so callers that already parsed the document can reuse the
    component-deferral pass.
    """

    def unchanged() -> str:
        return fallback_html

    body = soup.body
    if body is None:
        return unchanged()

    # Outermost boundaries only, found in one pruned walk. The previous
    # ``body.select('[pp-component]')`` matched every nested boundary and then
    # walked each match's full ancestor chain to discard it -- O(depth) per
    # boundary on documents whose boundary count is the whole point of the
    # page. Stopping the descent at the first boundary visits each outermost
    # subtree root exactly once and never enumerates the nested ones. An
    # element already inside a ``<template pp-component>`` stays untouched,
    # matching the ancestor-check semantics.
    roots = []
    stack = [child for child in reversed(body.contents) if isinstance(child, Tag)]
    while stack:
        el = stack.pop()
        if el.has_attr("pp-component"):
            if el.name != "template":
                roots.append(el)
            continue
        stack.extend(child for child in reversed(el.contents) if isinstance(child, Tag))
    if not roots:
        return unchanged()

    for root in roots:
        key = root.get("pp-component")
        if key is None:
            continue
        template = soup.new_tag("template")
        template["pp-component"] = key
        root.insert_before(template)
        template.append(root.extract())

    # An HTML parser decodes ``&#123;`` to ``{`` even inside an inert template.
    # Restore each masked entity into the parsed tree before serialization so
    # the serializer escapes its ampersand one additional time:
    #
    #     &#123; -> &amp;#123;
    #
    # The browser consumes that outer layer while parsing the response, leaving
    # the inner entity intact for PulsePoint to mask before expression scanning.
    # Placeholders outside deferred component templates are restored normally
    # after serialization.
    if placeholders:
        # One compiled-regex pass per string instead of one full ``replace``
        # scan per placeholder, and nodes that carry no token (the vast
        # majority) are skipped by a C-level substring probe.
        def protect_brace_entities(value: str) -> str:
            return _ESCAPED_BRACE_PLACEHOLDER_RE.sub(
                lambda match: placeholders.get(match.group(0), match.group(0)),
                value,
            )

        for template in body.select("template[pp-component]"):
            for node in list(template.descendants):
                if isinstance(node, NavigableString):
                    original = str(node)
                    if "__PP_ESCAPED_BRACE_" not in original:
                        continue
                    content = protect_brace_entities(original)
                    if content != original:
                        node.replace_with(content)
                elif isinstance(node, Tag):
                    for name, value in node.attrs.items():
                        if isinstance(value, str):
                            if "__PP_ESCAPED_BRACE_" in value:
                                node.attrs[name] = protect_brace_entities(value)
                        elif isinstance(value, list):
                            for index, item in enumerate(value):
                                item = str(item)
                                if "__PP_ESCAPED_BRACE_" in item:
                                    item = protect_brace_entities(item)
                                value[index] = item

    return restore_escaped_brace_entities(serialize_fragment(soup), placeholders)


# Dev-only: the browser console bridge. `CASPIAN_BROWSER_SYNC_PORT` is normally
# set only by settings/python-server.ts when the dev stack spawns this process,
# so the tag does not reach production, a static export, or a directly-run
# server. That is a convention about who sets the variable, though, not a
# guarantee -- so the production check below enforces it, mirroring
# `_dev_cookie_scope`, which returns "" outside development for the same reason.
#
# The script itself is served by BrowserSync's devLogMiddleware at this path; it
# forwards `[PP-ERROR]` / `[PP-WARN]` output and uncaught errors to the terminal
# running `npm run dev`. Without it, a broken template reports only to DevTools,
# which is how JSX-in-a-template kept shipping unnoticed.
#
# Injected as a classic script in <head> so it runs during parse, before the
# deferred module that boots PulsePoint — otherwise the first mount errors, the
# ones worth seeing, would fire before the hook exists.
_DEV_CONSOLE_BRIDGE_TAG = '<script src="/__pp-devlog.js"></script>'


def _inject_dev_console_bridge(html_output: str) -> str:
    if IS_PRODUCTION:
        return html_output
    if not os.getenv("CASPIAN_BROWSER_SYNC_PORT"):
        return html_output
    if "</head>" not in html_output or "__pp-devlog.js" in html_output:
        return html_output
    return html_output.replace("</head>", f"{_DEV_CONSOLE_BRIDGE_TAG}</head>", 1)


def finalize_html(html_output: str) -> str:
    """Final full-document transforms applied just before the response.

    Injects the development console bridge when enabled, then wraps outermost
    ``pp-component`` roots in inert ``<template>`` elements. Component scripts
    remain plain ``<script>`` elements: the surrounding template keeps them
    inert until PulsePoint materializes and mounts the component boundary.
    """
    html_output = _inject_dev_console_bridge(html_output)
    return defer_component_roots(html_output)


register_routes()
register_rpc_routes(app)

# Mount the FastMCP app at /mcp so the endpoint is exactly /mcp.
if mcp_app is not None:
    app.mount("/mcp", mcp_app)

# ====
# Custom Exception Handlers (404 & 500)
# ====


async def _render_special_page(
    page_path: str,
    request: Request,
    default_metadata: dict[str, str],
    context_data: dict[str, Any],
) -> tuple[str, str]:
    """Render an app-level Python page through the normal page/layout pipeline."""
    _runtime_metadata.set(None)
    _runtime_injections.set({"head": [], "body": []})

    module = load_route_module(page_path)
    if not hasattr(module, "page"):
        raise AttributeError(f"Missing 'def page():' in {page_path}")

    signature = get_page_signature(page_path, module.page)
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    call_context = {"request": request, **context_data}
    call_kwargs = {
        name: value
        for name, value in call_context.items()
        if accepts_kwargs or name in signature.parameters
    }

    result = module.page(**call_kwargs)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, Response):
        raise TypeError(f"Special page {page_path} must return markup, not a Response")

    page_layout_props: dict[str, Any] = {}
    page_content = result
    if isinstance(result, tuple):
        page_content = result[0]
        if len(result) >= 2 and isinstance(result[1], dict):
            page_layout_props = result[1]

    page_metadata = default_metadata.copy()
    for metadata_obj in (getattr(module, "metadata", None), _runtime_metadata.get()):
        if not metadata_obj:
            continue
        if metadata_obj.title:
            page_metadata["title"] = metadata_obj.title
        if metadata_obj.description:
            page_metadata["description"] = metadata_obj.description
        if metadata_obj.extra:
            page_metadata.update(metadata_obj.extra)

    page_source = getattr(page_content, "source_path", page_path)
    html_output, root_layout_id = await render_with_nested_layouts(
        children=str(page_content),
        route_dir=os.path.dirname(page_path),
        page_metadata=page_metadata,
        page_layout_props=page_layout_props,
        context_data={**call_context, **page_layout_props},
        page_component_source=page_source,
        control_mode=True,
        component_compiler=transform_components,
    )
    return finalize_html(html_output), root_layout_id


@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        not_found_path = os.path.join("src", "app", "not_found.py")
        if os.path.exists(not_found_path):
            html_output, root_layout_id = await _render_special_page(
                page_path=not_found_path,
                request=request,
                default_metadata={
                    "title": "Page Not Found",
                    "description": "The page you are looking for does not exist.",
                },
                context_data={},
            )
            resp = HTMLResponse(content=html_output, status_code=404)
            resp.headers["X-PP-Root-Layout"] = root_layout_id
            return resp
    return HTMLResponse(content=f"<h1>{exc.detail}</h1>", status_code=exc.status_code)


@app.exception_handler(Exception)
async def custom_general_exception_handler(request: Request, exc: Exception):
    full_trace = traceback.format_exc()
    print(full_trace)
    error_message = _client_error_message(exc)
    error_trace = full_trace if not IS_PRODUCTION else None

    error_page_path = os.path.join("src", "app", "error.py")
    if os.path.exists(error_page_path):
        context_data = {
            "request": request,
            "error_message": error_message,
            "error_trace": error_trace,
        }
        try:
            html_output, root_layout_id = await _render_special_page(
                page_path=error_page_path,
                request=request,
                default_metadata={
                    "title": "Application Error",
                    "description": "An unexpected error occurred.",
                },
                context_data=context_data,
            )
            resp = HTMLResponse(content=html_output, status_code=500)
            resp.headers["X-PP-Root-Layout"] = root_layout_id
            return resp
        except Exception as render_exc:
            print("Error rendering error.py:", render_exc)
    return HTMLResponse(
        content=f"<h1>500 - Internal Server Error</h1><p>{error_message}</p>", status_code=500
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
    same_site="lax",
    https_only=IS_PRODUCTION,
    path="/",
)
app.add_middleware(BodySizeLimitMiddleware)
# Sits between the limiter and the session/auth layers: a miss under a public
# asset namespace is a 404, not a sign-in redirect, and costs no session work.
app.add_middleware(MissingPublicAssetMiddleware)
# Outermost of the security layers: reject flooding before any session
# decryption, template rendering, or database work is spent on the request.
app.add_middleware(RateLimitMiddleware)
# The public directory is itself the URL contract: any existing nested file is
# served without adding a directory-specific route above. Keep upload content
# in attachment mode unless its MIME type is explicitly safe to render inline.
app.add_middleware(
    PublicFilesMiddleware,
    directory="public",
    inline_safe_subdirectories={
        "uploads": INLINE_SAFE_UPLOAD_MEDIA_TYPES,
    },
)
app.add_middleware(SecurityHeadersMiddleware)

if not IS_PRODUCTION:
    app.add_middleware(RequestDiagnosticsMiddleware)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5091))
    workers = max(1, int(os.getenv("UVICORN_WORKERS", "1")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=workers,
    )
