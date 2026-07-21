"""Integration test for the app's HTTP surface via httpx2's ASGI transport.

`/health` is the simplest always-on route and exercises the full middleware
stack (session, CSRF, security headers, auth) end to end. We drive the ASGI
app directly with httpx2's AsyncClient over its ASGITransport rather than
Starlette's TestClient.
"""

import asyncio

import httpx2

import main


async def _get(path: str) -> httpx2.Response:
    # ASGITransport speaks to the app in-process; no server/socket required.
    transport = httpx2.ASGITransport(app=main.app)
    async with httpx2.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.get(path)


def _get_sync(path: str) -> httpx2.Response:
    # Run the async request from a plain sync test (no pytest-asyncio needed).
    return asyncio.run(_get(path))


def test_health_returns_ok():
    response = _get_sync("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_carries_security_headers():
    response = _get_sync("/health")
    # SecurityHeadersMiddleware attaches baseline browser headers.
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_unknown_route_is_404():
    response = _get_sync("/definitely-not-a-real-route")
    assert response.status_code == 404
