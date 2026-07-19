"""Tests for the app-owned auth policy in `src/lib/auth/auth_config.py`.

This is the single place the app decides route privacy and redirects, so the
defaults are worth pinning against accidental change.
"""

from casp.auth import AuthSettings

from src.lib.auth.auth_config import build_auth_settings


def test_returns_auth_settings():
    settings = build_auth_settings()
    assert isinstance(settings, AuthSettings)


def test_public_first_defaults():
    settings = build_auth_settings()
    assert settings.is_all_routes_private is False
    assert "/" in settings.public_routes
    assert "/health" in settings.public_routes


def test_signin_redirect_default():
    settings = build_auth_settings()
    assert settings.default_signin_redirect == "/dashboard"
    assert settings.default_signout_redirect == "/signin"
