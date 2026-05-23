from __future__ import annotations
from casp.auth import AuthSettings


def build_auth_settings() -> AuthSettings:
    """
    Centralized app auth policy controller.

    Keep secrets (AUTH_SECRET, AUTH_COOKIE_NAME) in .env.
    Keep app-level session settings in .env (SESSION_LIFETIME_HOURS, etc).
    Decide route privacy, redirects, and RBAC here at app setup time instead of
    changing Caspian core runtime files.

    Rule of thumb:
    - If most routes should require auth, set is_all_routes_private=True and list only the public exceptions.
    - If many routes should stay public, keep is_all_routes_private=False and list only the protected routes.
    """

    return AuthSettings(
        # Token settings
        default_token_validity="1h",
        # Sliding-session refresh only matters when the request flow calls auth.refresh_session().
        token_auto_refresh=False,

        # Route protection
        # This app-owned starter config begins public-first; switch to True only when most routes require auth.
        # Use all-private mode when only a few routes should stay public.
        is_all_routes_private=False,
        public_routes=["/"],
        # Sign-in and signup stay public by default; only change this when the app explicitly needs it.
        auth_routes=["/signin", "/signup"],
        private_routes=[],  # unused when all-routes-private is True

        # Role-based access
        is_role_based=False,
        role_identifier="role",

        # RBAC policy is app-owned here; the runtime expects ROUTE/PATTERN -> [ROLES].
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
