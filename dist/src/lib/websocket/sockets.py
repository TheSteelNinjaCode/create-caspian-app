"""Named sockets: the server half of `pp.socket(...)`.

An rpc is a question with one answer, and an rpc stream is an answer that
arrives in pieces. A socket is the third shape: both sides may speak, at any
time, for as long as the page is open. The client half is `pp.socket(...)` in
the shipped PulsePoint runtime; this module is the server half, and
`@socket()` is what puts a function on it:

    from src.lib.websocket.sockets import Socket, socket

    @socket()
    async def echo(label: str, socket: Socket):
        while (text := await socket.recv()) is not None:
            if not await socket.send(f"{label}: {text}"):
                break  # The browser is gone.

From the browser:

    const sock = pp.socket("echo", { label: "you" }, {
        onMessage: (value) => append(value),
    });
    sock.send("hello");

## The wire

Every socket connects to one endpoint, `SOCKET_PATH`, naming its function in
the `name` query parameter. The arguments do not travel in the URL -- a URL is
logged by every proxy on the way -- but as the first text frame, one JSON
object, exactly the payload `pp.rpc` would have posted. Every frame after
that is one JSON value, in either direction.

One endpoint rather than one per page because an upgrade is a GET, and the
page already owns GET on its own URL. The names are therefore
application-wide, like global component rpc names, and a duplicate is refused
at registration time.

## Failure

There is no status line inside an open connection, so failure is a frame:
`{"error": "..."}` -- that key alone -- followed by a close. The client
runtime routes it to `onError` rather than `onMessage`.

## Registration timing

A `@socket()` in a route's `index.py` registers when that module is first
imported, which happens when the route first renders. The page that opens
`pp.socket(...)` has necessarily rendered first, so its sockets exist by the
time the browser connects. A shared socket used by several routes belongs in
`src/lib/**`, imported by each owning route.

## Security posture

The endpoint keeps the same protections as the channel endpoints in
`main.py`: the anti-CSWSH origin check runs before the handshake is accepted,
auth delegates to Caspian's `Auth` (HTTP middleware never sees websocket
scopes), and every connection is subject to the shared connection cap,
message-size limit, per-connection message rate, and idle timeout. The socket
session is read-only: mutations are not persisted back to the cookie over a
WebSocket.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import WebSocket, status

from casp.auth import Auth

# Private, but deliberately the same serializer rpc responses go through, so a
# dataclass or model travels identically over both wires.
from casp.rpc import _serialize_result
from casp.runtime_security import is_production_environment

# Where every named socket connects. The path carries the PulsePoint
# runtime's name, not the server framework's, because `pp.socket(...)` is the
# same client whichever backend serves it — its DEFAULT_PATH and this
# constant must stay identical.
SOCKET_PATH = "/__pulsepoint/ws"

# How long the server waits for the first frame -- the arguments -- before
# giving up on a connection that opened and said nothing.
ARGS_TIMEOUT_SECONDS = 10

# How far a sender may run ahead of the wire before `send` applies
# backpressure by awaiting queue space.
SEND_QUEUE_SIZE = 32


def _idle_timeout_seconds() -> int:
    return max(10, int(os.getenv("WEBSOCKET_IDLE_TIMEOUT_SECONDS", 120)))


def _max_message_bytes() -> int:
    return max(256, int(os.getenv("MAX_WEBSOCKET_MESSAGE_BYTES", 4096)))


def _messages_per_window() -> int:
    return max(1, int(os.getenv("MAX_WEBSOCKET_MESSAGES_PER_WINDOW", 20)))


def _rate_window_seconds() -> int:
    return max(1, int(os.getenv("WEBSOCKET_RATE_WINDOW_SECONDS", 10)))


# ==== HANDSHAKE SECURITY ====
#
# The anti-CSWSH origin check and the connection ceiling, run before the
# handshake upgrades. Authorization itself is per socket (`require_auth=` /
# `allowed_roles=` delegated to Caspian's `Auth`), because HTTP middleware in
# `main.py` early-returns on every non-`http` scope -- a WebSocket handshake
# (`scope["type"] == "websocket"`) is never seen by `AuthMiddleware`, so this
# endpoint authorizes each connection itself.

# Ceiling on simultaneous open sockets. Every open connection is a live task
# plus a broadcast target, so an unbounded count lets cheap clients grow
# server memory and turn each broadcast into an amplification.
MAX_WEBSOCKET_CONNECTIONS = max(1, int(os.getenv("MAX_WEBSOCKET_CONNECTIONS", 200)))


def _is_production() -> bool:
    # Shared fail-closed resolution: an unset or misspelled APP_ENV must not
    # silently enable the development handshake relaxations below.
    return is_production_environment()


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

    return {_normalized_origin(origin) for origin in raw_values if _normalized_origin(origin)}


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

    # The same-origin fallback is derived from the Host header, which a client
    # controls directly and a misconfigured proxy will forward verbatim: sending
    # `Host: evil.tld` with `Origin: https://evil.tld` would otherwise satisfy
    # this check against itself. It is a convenience for development only --
    # production must name its origins explicitly.
    if not _is_production():
        allowed_origins.add(_websocket_same_origin(websocket))

    return origin in allowed_origins


# ==== REGISTRY ====

SocketHandler = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class SocketEntry:
    name: str
    source: str
    require_auth: bool
    allowed_roles: tuple[str, ...]
    handler: SocketHandler


SOCKET_REGISTRY: dict[str, SocketEntry] = {}


def socket(require_auth: bool = False, allowed_roles: list[str] | None = None):
    """Register an async function as a named socket.

    The function's own name is the name the browser connects with, so it must
    be unique application-wide. The function declares its arguments as normal
    parameters -- they arrive in the connection's first frame -- plus one
    parameter named `socket`, which receives the open `Socket`.

    - `require_auth=True` refuses the connection unless the request carries an
      authenticated session, before the handler runs.
    - `allowed_roles=[...]` adds RBAC via `Auth.check_role`, the same rule as
      HTTP routes and rpc.
    """

    def decorator(func: SocketHandler) -> SocketHandler:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@socket() function `{func.__name__}` must be `async def`: "
                "a socket is a long-lived conversation, not a call."
            )

        parameters = inspect.signature(func).parameters
        if "socket" not in parameters:
            raise TypeError(
                f"@socket() function `{func.__name__}` must declare a "
                "`socket` parameter -- it receives the open connection."
            )

        source = f"{func.__module__}.{func.__qualname__}"
        existing = SOCKET_REGISTRY.get(func.__name__)
        if existing is not None and existing.source != source:
            raise ValueError(
                f"Two sockets are named `{func.__name__}`:\n"
                f"  {existing.source}\n  {source}\n"
                "The client connects with a name and nothing else, so socket "
                "names must be unique application-wide."
            )

        SOCKET_REGISTRY[func.__name__] = SocketEntry(
            name=func.__name__,
            source=source,
            require_auth=require_auth,
            allowed_roles=tuple(allowed_roles or ()),
            handler=func,
        )
        return func

    return decorator


# ==== WIRE HELPERS ====


def _error_frame(message: str) -> str:
    """`{"error": "..."}` -- the frame shape the client routes to `onError`.

    Reserved on this wire the way the `error` key is reserved in an rpc
    failure; `send` refuses to emit it as an ordinary message.
    """
    return json.dumps({"error": message})


def _is_reserved_error_shape(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value.keys()) == {"error"}
        and isinstance(value.get("error"), str)
    )


class _MessageRate:
    """Sliding-window receive budget for one connection.

    Per-socket rather than per-IP: whatever pool the handler broadcasts into
    is the shared resource being protected, and one abusive connection must
    not spend another client's budget.
    """

    def __init__(self, limit: int, window_seconds: int):
        self._limit = limit
        self._window_seconds = window_seconds
        self._timestamps: list[float] = []

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self._limit:
            return False
        self._timestamps.append(now)
        return True


# ==== SOCKET ====


class _Shared:
    """State the `Socket` and every cloned `SocketSender` see together."""

    def __init__(self) -> None:
        self.outgoing: asyncio.Queue[str | None] = asyncio.Queue(maxsize=SEND_QUEUE_SIZE)
        self.closed = False
        self.last_activity = time.monotonic()


class SocketSender:
    """The sending half of a [`Socket`], detached from the conversation.

    Cheap to hand around, so a broadcast pool is a list of these: keep one per
    connection in shared state, and a send that returns False is a connection
    to forget. See [`SocketPool`].
    """

    def __init__(self, shared: _Shared) -> None:
        self._shared = shared

    @property
    def is_open(self) -> bool:
        return not self._shared.closed

    async def send(self, value: Any) -> bool:
        """Send one JSON value. False means nobody is listening any more --
        the browser navigated away or closed the tab. That is the signal to
        stop, not an error to report."""
        if self._shared.closed:
            return False
        serialized = _serialize_result(value)
        if _is_reserved_error_shape(serialized):
            raise ValueError(
                'The frame shape {"error": "..."} is reserved for failures. '
                "Wrap the value or rename the key."
            )
        try:
            frame = json.dumps(serialized)
        except (TypeError, ValueError) as e:
            print(f"[Socket] A frame cannot be written as JSON: {e}")
            return False
        await self._shared.outgoing.put(frame)
        return not self._shared.closed

    async def _error(self, message: str) -> None:
        """The error frame, then the close. The conversation is over."""
        if self._shared.closed:
            return
        await self._shared.outgoing.put(_error_frame(message))
        await self._shared.outgoing.put(None)


class SocketPool:
    """A broadcast pool: one `SocketSender` per open connection.

    Holds senders rather than raw websockets so a handler can share its
    connection without sharing the receive side. Keep authenticated and guest
    traffic in separate pools so a private broadcast can never fan out to a
    guest connection.
    """

    def __init__(self) -> None:
        self._senders: list[SocketSender] = []

    @property
    def count(self) -> int:
        return len(self._senders)

    def add(self, sender: SocketSender) -> None:
        self._senders.append(sender)

    def discard(self, sender: SocketSender) -> None:
        self._senders = [s for s in self._senders if s is not sender]

    async def broadcast(self, value: Any) -> None:
        """Send one value to everyone; connections whose browser is gone are
        pruned on the way."""
        stale: list[SocketSender] = []
        for sender in list(self._senders):
            if not await sender.send(value):
                stale.append(sender)
        for sender in stale:
            self.discard(sender)


class Socket:
    """One open connection, as the handler holds it.

    The `socket` parameter of every `@socket()` function. Receiving is the
    handler's alone; sending may be shared -- `sender()` hands out a handle
    another task or a [`SocketPool`] may hold, which is how a chat room
    reaches the people in it.

    When the handler returns, the connection closes: a handler that returns
    is a conversation that ends.
    """

    def __init__(self, name: str, websocket: WebSocket) -> None:
        self._name = name
        self._websocket = websocket
        self._shared = _Shared()
        self._sender = SocketSender(self._shared)
        self._rate = _MessageRate(_messages_per_window(), _rate_window_seconds())
        # One task owns the write side of the wire, so cloned senders on other
        # tasks never interleave partial sends.
        self._writer = asyncio.create_task(self._pump_outgoing())

    async def _pump_outgoing(self) -> None:
        try:
            while True:
                frame = await self._shared.outgoing.get()
                if frame is None:
                    break
                await self._websocket.send_text(frame)
                self._shared.last_activity = time.monotonic()
        except Exception:
            # The browser is gone; every later `send` answers False.
            pass
        finally:
            self._shared.closed = True
            try:
                await self._websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            except Exception:
                pass

    async def send(self, value: Any) -> bool:
        """Send one JSON value. False means the browser is gone."""
        return await self._sender.send(value)

    async def recv(self) -> Any | None:
        """The next value the browser sent, or None when the connection
        closes -- which is how every socket conversation eventually ends. The
        natural loop is `while (value := await socket.recv()) is not None:`.

        Raises ValueError on a frame that arrived and is not valid JSON: a
        frame the handler cannot read is a client bug worth surfacing, and an
        uncaught raise travels back as the error frame.
        """
        text = await self.recv_text()
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"`{self._name}` could not read a frame -- {e}. Each frame is one JSON value."
            ) from e

    async def recv_text(self) -> str | None:
        """The next frame as it arrived, for a handler that would rather
        parse it itself. None is the connection closing.

        Enforces the shared limits: an oversized frame closes with 1009, a
        flooding connection closes with 1008, and a connection idle in both
        directions past the timeout closes with 1000.
        """
        idle_timeout = _idle_timeout_seconds()
        while not self._shared.closed:
            try:
                text = await asyncio.wait_for(self._websocket.receive_text(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                # Outbound traffic counts as liveness: a passive listener in
                # an active room is not idle, it is listening.
                if time.monotonic() - self._shared.last_activity >= idle_timeout:
                    await self.close()
                    return None
                continue
            except Exception:
                # Disconnect, or receive after close: the conversation ended.
                self._shared.closed = True
                return None

            self._shared.last_activity = time.monotonic()

            if len(text.encode("utf-8")) > _max_message_bytes():
                await self._close_with(status.WS_1009_MESSAGE_TOO_BIG)
                return None
            if not self._rate.allow():
                await self._sender._error("Too many messages. Slow down.")
                return None
            return text
        return None

    def sender(self) -> SocketSender:
        """A sending handle another task, or a [`SocketPool`], may hold."""
        return self._sender

    @property
    def is_open(self) -> bool:
        return not self._shared.closed

    async def close(self) -> None:
        """Say goodbye first. Returning from the handler closes too; this is
        for closing mid-conversation."""
        if not self._shared.closed:
            await self._shared.outgoing.put(None)
        await self._finish()

    async def _close_with(self, code: int) -> None:
        self._shared.closed = True
        self._writer.cancel()
        try:
            await self._websocket.close(code=code)
        except Exception:
            pass

    async def _finish(self) -> None:
        """Let queued frames drain, then reclaim the writer task."""
        try:
            await asyncio.wait_for(self._writer, timeout=5)
        except asyncio.CancelledError, Exception:
            self._writer.cancel()
        self._shared.closed = True


# ==== ENDPOINT ====

# Named sockets share one cap with everything else that holds a connection
# open: every open socket is a live task plus a broadcast target.
_open_connections = 0


def open_connection_count() -> int:
    return _open_connections


@dataclass
class _Refusal:
    message: str
    close_code: int = field(default=status.WS_1008_POLICY_VIOLATION)


def _resolve_entry(websocket: WebSocket) -> SocketEntry | _Refusal:
    name = (websocket.query_params.get("name") or "").strip()
    if not name:
        return _Refusal(
            "This connection named no socket. Open it as "
            'pp.socket("name", { ... }) -- the client runtime sends the name '
            "in the `name` query parameter."
        )
    entry = SOCKET_REGISTRY.get(name)
    if entry is None:
        return _Refusal(
            f"No socket named `{name}`. Mark the function @socket() -- the "
            "name the client connects with is the function's own -- and note "
            "that a socket declared in a route's index.py registers when that "
            "route first renders."
        )
    return entry


def _authorize(websocket: WebSocket, entry: SocketEntry) -> _Refusal | None:
    """Auth for one handshake, delegated to Caspian's `Auth`.

    HTTP middleware never sees websocket scopes, so the endpoint authorizes
    itself by binding the socket as the request context -- `Auth` reads only
    `.session`, which `SessionMiddleware` exposes on websockets too. Failures
    travel as this wire's `{"error": ...}` frame. The session is read-only.
    """
    Auth.set_request(websocket)  # type: ignore[arg-type]
    auth = Auth.get_instance()

    if auth.is_authenticated():
        payload = auth.get_payload() or {}
        if entry.allowed_roles and not auth.check_role(payload, list(entry.allowed_roles)):
            return _Refusal(f"The socket `{entry.name}` is not available to this account.")
        return None

    if entry.require_auth or entry.allowed_roles:
        return _Refusal(
            f"The socket `{entry.name}` needs a signed-in session. It is "
            "@socket(require_auth=True), so it answers only while the browser "
            "carries one."
        )
    return None


async def _first_frame(websocket: WebSocket) -> dict[str, Any] | _Refusal | None:
    """The arguments: one JSON object, as the first text frame.

    None is a connection that closed before saying anything -- a refresh
    mid-handshake. Not an error, and nobody left to tell.
    """
    try:
        text = await asyncio.wait_for(websocket.receive_text(), timeout=ARGS_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return _Refusal(
            "This socket opened and sent no arguments. The first frame is the "
            "payload -- one JSON object, {} when the function takes nothing. "
            "pp.socket sends it on open."
        )
    except Exception:
        return None

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, dict):
        return _Refusal(
            "The first frame of a socket is not a JSON object. Arguments are "
            'named, so they arrive as { "room": ... } -- '
            'pp.socket("name", { room }) is what sends them.'
        )
    return value


def _call_kwargs(
    entry: SocketEntry, args: dict[str, Any], sock: Socket
) -> dict[str, Any] | _Refusal:
    """Filter the payload against the handler's own signature.

    The payload is client-controlled, so -- exactly as with rpc -- a parameter
    is settable only when declared, and `socket` itself can never be supplied
    from the wire.
    """
    parameters = inspect.signature(entry.handler).parameters.values()
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters)

    accepted = {
        p.name
        for p in parameters
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        and p.name != "socket"
    }
    missing = [
        p.name
        for p in parameters
        if p.name in accepted and p.default is inspect.Parameter.empty and p.name not in args
    ]
    if missing:
        return _Refusal(
            f"`{entry.name}` is missing its `{missing[0]}` argument. The "
            f'browser opens pp.socket("{entry.name}", '
            f"{{ {missing[0]}: ... }})."
        )

    if accepts_kwargs:
        kwargs = {k: v for k, v in args.items() if k != "socket"}
    else:
        kwargs = {k: v for k, v in args.items() if k in accepted}
    kwargs["socket"] = sock
    return kwargs


async def _refuse_open(websocket: WebSocket, refusal: _Refusal) -> None:
    """Refuse after the handshake: the error frame, then the close, so the
    browser gets a readable message instead of a bare close code."""
    try:
        await websocket.send_text(_error_frame(refusal.message))
        await websocket.close(code=refusal.close_code)
    except Exception:
        pass


async def serve_named_socket(websocket: WebSocket) -> None:
    """The whole endpoint: who is calling, whether they may, then the pump.

    Wired in `main.py` as `@app.websocket(SOCKET_PATH)`, gated on
    `caspian.config.json` `websocket: true`.
    """
    global _open_connections

    # Refused before the handshake upgrades, like every channel endpoint.
    if not is_websocket_origin_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if _open_connections >= MAX_WEBSOCKET_CONNECTIONS:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    await websocket.accept()

    entry = _resolve_entry(websocket)
    if isinstance(entry, _Refusal):
        await _refuse_open(websocket, entry)
        return

    refusal = _authorize(websocket, entry)
    if refusal is not None:
        await _refuse_open(websocket, refusal)
        return

    args = await _first_frame(websocket)
    if args is None:
        return
    if isinstance(args, _Refusal):
        await _refuse_open(websocket, args)
        return

    sock = Socket(entry.name, websocket)
    kwargs = _call_kwargs(entry, args, sock)
    if isinstance(kwargs, _Refusal):
        await sock.sender()._error(kwargs.message)
        await sock._finish()
        return

    _open_connections += 1
    try:
        await entry.handler(**kwargs)
        await sock.close()
    except ValueError as e:
        # The rpc convention: a ValueError is a message meant for the caller.
        await sock.sender()._error(str(e))
        await sock._finish()
    except Exception as e:
        print(f"[Socket Error] {entry.name}: {e}")
        traceback.print_exc()
        message = "Internal server error" if is_production_environment() else f"{entry.name}: {e}"
        await sock.sender()._error(message)
        await sock._finish()
    finally:
        _open_connections -= 1
