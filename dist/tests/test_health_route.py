"""Integration test for the app's HTTP surface via Starlette's TestClient.

`/health` is the simplest always-on route and exercises the full middleware
stack (session, CSRF, security headers, auth) end to end.
"""

from starlette.testclient import TestClient

import main


def _client() -> TestClient:
    # raise_server_exceptions=False so a 500 is returned as a response we can
    # assert on, matching real client behavior.
    return TestClient(main.app, raise_server_exceptions=False)


def test_health_returns_ok():
    with _client() as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_carries_security_headers():
    with _client() as client:
        response = client.get("/health")
    # SecurityHeadersMiddleware attaches baseline browser headers.
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_unknown_route_is_404():
    with _client() as client:
        response = client.get("/definitely-not-a-real-route")
    assert response.status_code == 404
