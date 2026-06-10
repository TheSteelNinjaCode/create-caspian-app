from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


def get_websocket_session(websocket: WebSocket) -> MutableMapping[str, Any]:
    session = getattr(websocket, "session", None)
    if isinstance(session, MutableMapping):
        return session

    scope_session = websocket.scope.get("session")
    if isinstance(scope_session, MutableMapping):
        return scope_session

    return {}


def get_authenticated_payload_from_session(
    session: MutableMapping[str, Any],
    auth_instance: Any,
) -> dict[str, Any] | None:
    payload_key = getattr(auth_instance, "PAYLOAD_SESSION_KEY", "")
    payload_name = getattr(auth_instance, "PAYLOAD_NAME", "")

    payload_wrapper = session.get(payload_key)
    if not isinstance(payload_wrapper, dict):
        return None

    exp = payload_wrapper.get("exp")
    if exp is not None:
        try:
            if float(exp) < datetime.now(timezone.utc).timestamp():
                session.pop(payload_key, None)
                return None
        except Exception:
            session.pop(payload_key, None)
            return None

    payload = payload_wrapper.get(payload_name)
    if payload is None:
        session.pop(payload_key, None)
        return None

    if isinstance(payload, dict):
        if getattr(getattr(auth_instance, "settings", None), "token_auto_refresh", False):
            refreshed_wrapper = dict(payload_wrapper)
            refreshed_wrapper["exp"] = auth_instance._calculate_expiration(
                auth_instance.settings.default_token_validity
            )
            session[payload_key] = refreshed_wrapper
        return payload

    return {"value": payload}


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


websocket_connections = WebSocketConnectionManager()
public_websocket_connections = WebSocketConnectionManager()
