"""Integration test for the app's HTTP surface via httpx2's ASGI transport.

`/health` is the simplest always-on route and exercises the full middleware
stack (session, CSRF, security headers, auth) end to end. We drive the ASGI
app directly with httpx2's AsyncClient over its ASGITransport rather than
Starlette's TestClient.

Route expectations are derived from the app's own auth policy rather than
hard-coded, because `is_all_routes_private` in `src/lib/auth/auth_config.py`
changes what the same request does. Under public-first (`False`) an unmatched
path reaches the router and renders the 404 page; under all-private (`True`)
`AuthMiddleware` sends a signed-out visitor to the sign-in route with a `next`
parameter before routing ever runs. Both are correct — which one applies is a
configuration choice, so the test asks the configured policy instead of
assuming one of them.
"""

import asyncio

import httpx2
import pytest
from casp.auth import Auth

import main

UNKNOWN_PATH = "/definitely-not-a-real-route"


async def _get(path: str) -> httpx2.Response:
    # ASGITransport speaks to the app in-process; no server/socket required.
    transport = httpx2.ASGITransport(app=main.app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def _get_sync(path: str) -> httpx2.Response:
    # Run the async request from a plain sync test (no pytest-asyncio needed).
    return asyncio.run(_get(path))


def _guest_redirect_for(path: str) -> str | None:
    """Sign-in URL a signed-out visitor is sent to, or None if `path` is allowed through.

    Mirrors the guest branches of `AuthMiddleware` in the order it applies them.
    Importing `main` has already run `configure_auth(build_auth_settings())`, so
    the shared `Auth` instance carries this app's real policy.
    """
    auth = Auth.get_instance()
    if auth.is_public_route(path) or auth.is_auth_route(path):
        return None
    if auth.settings.is_role_based and auth.get_required_roles(path):
        return auth.get_signin_redirect(path)
    if auth.is_private_route(path):
        return auth.get_signin_redirect(path)
    return None


def test_health_returns_ok():
    redirect = _guest_redirect_for("/health")
    if redirect is not None:
        pytest.skip(f"/health is auth-gated by this app's auth policy (redirects to {redirect})")
    response = _get_sync("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_carries_security_headers():
    # Runs whatever the policy decides: the headers are attached to the redirect
    # too, because SecurityHeadersMiddleware sits outside AuthMiddleware.
    response = _get_sync("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_unknown_route_matches_auth_policy():
    """An unknown path 404s when it is reachable, and redirects when it is not."""
    response = _get_sync(UNKNOWN_PATH)
    redirect = _guest_redirect_for(UNKNOWN_PATH)

    if redirect is None:
        # Public-first: nothing guards the path, so routing answers with the 404 page.
        assert response.status_code == 404
    else:
        # All-private: the guest never reaches the router.
        assert response.status_code == 303
        assert response.headers.get("location") == redirect
