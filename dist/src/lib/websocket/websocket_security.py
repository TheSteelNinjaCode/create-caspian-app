from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from fastapi import WebSocket, status

from casp.auth import Auth

# ====
# WebSocket security: ONE guard that reuses Caspian's `Auth` as the source of
# truth, so socket auth lines up with HTTP route auth instead of duplicating it.
#
# Why this lives here and not in `AuthMiddleware`:
# HTTP middleware in `main.py` early-returns on every non-`http` scope, so a
# WebSocket handshake (`scope["type"] == "websocket"`) is never seen by
# `AuthMiddleware`. Each socket endpoint must therefore authorize itself. We do
# that by delegating to the same `Auth` instance that powers page privacy.
# ====


def _is_production() -> bool:
    return os.getenv("APP_ENV") == "production"


def _normalized_origin(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _configured_websocket_origins() -> set[str]:
    raw_values: list[str] = []
    for env_name in (
        "WEBSOCKET_ALLOWED_ORIGINS",
        "CORS_ALLOWED_ORIGINS",
        "APP_BASE_URL",
    ):
        raw_values.extend(os.getenv(env_name, "").split(","))

    return {
        _normalized_origin(origin)
        for origin in raw_values
        if _normalized_origin(origin)
    }


def _websocket_same_origin(websocket: WebSocket) -> str:
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    return _normalized_origin(f"{scheme}://{websocket.url.netloc}")


def is_websocket_origin_allowed(websocket: WebSocket) -> bool:
    """Anti-CSWSH origin check. NOT authentication.

    A browser cannot forge the `Origin` header, so this blocks cross-site
    script-driven handshakes. A raw client (wscat, python websockets) can send
    any origin, which is exactly why authentication is a separate gate.
    """
    origin = _normalized_origin(websocket.headers.get("origin", ""))
    if not origin:
        # No Origin header: tolerate local tooling in dev, reject in production.
        return not _is_production()

    parsed_origin = urlparse(origin)
    if not parsed_origin.scheme or not parsed_origin.netloc:
        return False

    if not _is_production() and parsed_origin.hostname in {"localhost", "127.0.0.1"}:
        return parsed_origin.scheme == "http"

    allowed_origins = _configured_websocket_origins()
    allowed_origins.add(_websocket_same_origin(websocket))
    return origin in allowed_origins


async def authorize_websocket(
    websocket: WebSocket,
    *,
    require_auth: bool,
    roles: list[str] | None = None,
) -> dict[str, Any] | None:
    """Single entry point for socket authorization.

    Returns the connecting identity on success, or `None` after closing the
    socket on failure. The return value gates the connection only; do not echo
    it to other clients (it may contain the authenticated user's payload).

    - `require_auth=True`  -> authenticated session required, else close 1008.
    - `require_auth=False` -> guests allowed; authenticated users keep identity.
    - `roles`              -> RBAC via `Auth.check_role`, same rule as HTTP routes.

    Auth is read from the session cookie that `SessionMiddleware` (the one
    middleware that runs on websocket scopes) exposes as `websocket.session`.
    Treat this as read-only: session writes are not persisted back to the cookie
    over a WebSocket, so this guard must not rely on `refresh_session`.
    """
    # 1. Origin / CSWSH check runs before accept so rejected handshakes never
    #    upgrade.
    if not is_websocket_origin_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    # 2. Reuse Caspian `Auth` as the single source of truth. `Auth` only reads
    #    `request.session`, and a WebSocket exposes `.session`, so binding the
    #    socket as the request context lets us reuse the exact HTTP auth logic.
    Auth.set_request(websocket)  # type: ignore[arg-type]
    auth = Auth.get_instance()

    if auth.is_authenticated():
        payload = auth.get_payload() or {}
        if roles and not auth.check_role(payload, roles):
            await _reject(websocket, "Forbidden.")
            return None
        return payload

    if require_auth:
        await _reject(websocket, "Authentication required.")
        return None

    return {"guest": True, "scope": "public"}


async def _reject(websocket: WebSocket, message: str) -> None:
    """Accept, surface a JSON error so the browser UI can react, then close."""
    await websocket.accept()
    await websocket.send_json({"type": "error", "message": message})
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast_json(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)

        for websocket in stale:
            self.disconnect(websocket)


# Separate pools keep authenticated traffic isolated from guest traffic, so a
# private broadcast can never fan out to a public (guest) connection.
websocket_connections = WebSocketConnectionManager()
public_websocket_connections = WebSocketConnectionManager()
