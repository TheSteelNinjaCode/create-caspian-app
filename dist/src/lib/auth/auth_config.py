from __future__ import annotations
from casp.auth import AuthSettings


def build_auth_settings() -> AuthSettings:
    """
    Centralized auth configuration.

    Keep secrets (AUTH_SECRET, AUTH_COOKIE_NAME) in .env.
    Keep app-level session settings in .env (SESSION_LIFETIME_HOURS, etc).
    """

    return AuthSettings(
        # Token settings
        default_token_validity="1h",
        token_auto_refresh=False,

        # Route protection
        is_all_routes_private=False,
        public_routes=["/"],
        auth_routes=["/signin", "/signup"],
        private_routes=[],  # unused when all-routes-private is True

        # Role-based access
        is_role_based=False,
        role_identifier="role",

        # IMPORTANT: your current casp.auth expects PATH -> [ROLES]
        # Example (when enabled):
        # role_based_routes={
        #     "/report": ["admin"],
        #     "/admin": ["admin", "superadmin"],
        # },
        role_based_routes={},

        # Redirects / prefixes
        default_signin_redirect="/dashboard",
        default_signout_redirect="/signin",
        api_auth_prefix="/api/auth",
    )
