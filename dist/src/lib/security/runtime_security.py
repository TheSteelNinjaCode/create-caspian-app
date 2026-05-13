import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import Response
from fastapi.responses import FileResponse

INSECURE_SESSION_SECRET_VALUES = {"", "change-me", "changeme"}
GOOGLE_FONTS_STYLES_ORIGIN = "https://fonts.googleapis.com"
GOOGLE_FONTS_ASSETS_ORIGIN = "https://fonts.gstatic.com"
GOOGLE_ACCOUNTS_ORIGIN = "https://accounts.google.com"
GOOGLE_OAUTH_API_ORIGIN = "https://oauth2.googleapis.com"

DEFAULT_CSP_DIRECTIVES: tuple[tuple[str, list[str]], ...] = (
    ("default-src", ["'self'"]),
    ("base-uri", ["'self'"]),
    ("object-src", ["'none'"]),
    ("frame-ancestors", ["'self'"]),
    ("form-action", ["'self'"]),
    ("img-src", ["'self'", "data:", "blob:", GOOGLE_ACCOUNTS_ORIGIN]),
    ("font-src", ["'self'", "data:", GOOGLE_FONTS_ASSETS_ORIGIN]),
    ("connect-src", ["'self'", GOOGLE_ACCOUNTS_ORIGIN,
     GOOGLE_OAUTH_API_ORIGIN]),
    ("frame-src", ["'self'", GOOGLE_ACCOUNTS_ORIGIN]),
    ("script-src", ["'self'", "'unsafe-inline'", "'unsafe-eval'"]),
    ("script-src-elem", ["'self'", "'unsafe-inline'", GOOGLE_ACCOUNTS_ORIGIN]),
    ("style-src", ["'self'", "'unsafe-inline'", GOOGLE_FONTS_STYLES_ORIGIN]),
    ("style-src-elem", ["'self'", "'unsafe-inline'",
     GOOGLE_FONTS_STYLES_ORIGIN]),
)

# Add project-specific browser-side origins here only when the browser must
# load a third-party resource that is not already covered by the defaults.
# Example:
# PROJECT_CSP_EXTRA_SOURCES = {
#     "img-src": ["https://images.unsplash.com"],
#     "script-src-elem": ["https://cdn.jsdelivr.net"],
#     "connect-src": ["https://api.example.com"],
# }
PROJECT_CSP_EXTRA_SOURCES: dict[str, Any] = {}


def resolve_safe_public_path(base_dir: str | Path, relative_path: str) -> Optional[Path]:
    base_path = Path(base_dir).resolve()
    try:
        candidate = (base_path / relative_path).resolve()
        candidate.relative_to(base_path)
    except (OSError, RuntimeError, ValueError):
        return None

    if not candidate.is_file():
        return None

    return candidate


def public_file_response(
    base_dir: str | Path,
    relative_path: str,
    *,
    media_type: Optional[str] = None,
) -> Response:
    file_path = resolve_safe_public_path(base_dir, relative_path)
    if file_path is None:
        return Response(status_code=404)

    resolved_media_type = media_type
    if resolved_media_type is None:
        resolved_media_type, _ = mimetypes.guess_type(str(file_path))

    return FileResponse(
        file_path,
        media_type=resolved_media_type or "application/octet-stream",
    )


def client_error_message(exc: Exception, *, is_production: bool) -> str:
    return str(exc) if not is_production else "An unexpected error occurred."


def get_session_secret(*, is_production: bool) -> str:
    session_secret = (os.getenv("AUTH_SECRET") or "").strip()
    if session_secret and session_secret.lower() not in INSECURE_SESSION_SECRET_VALUES:
        return session_secret

    if not is_production:
        return "change-me"

    raise RuntimeError(
        "AUTH_SECRET must be set to a non-default value when APP_ENV=production."
    )


def _normalize_csp_sources(value: Any) -> list[str]:
    if isinstance(value, str):
        return [token.strip() for token in value.replace(",", " ").split() if token.strip()]

    if isinstance(value, (list, tuple, set)):
        normalized: list[str] = []
        for item in value:
            normalized.extend(_normalize_csp_sources(item))
        return normalized

    return []


def normalize_csp_extra_sources(parsed: Optional[dict[str, Any]]) -> dict[str, list[str]]:
    if not isinstance(parsed, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for directive, sources in parsed.items():
        if not isinstance(directive, str):
            continue

        directive_sources = _normalize_csp_sources(sources)
        if directive_sources:
            normalized[directive.strip()] = directive_sources

    return normalized


def _merge_sources(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for source in group:
            normalized = source.strip()
            if not normalized or normalized in seen:
                continue
            merged.append(normalized)
            seen.add(normalized)

    return merged


def build_content_security_policy() -> str:
    # PulsePoint currently relies on inline scripts/styles and runtime codegen,
    # so this policy narrows source scope without breaking the app runtime.
    extra_sources = normalize_csp_extra_sources(PROJECT_CSP_EXTRA_SOURCES)
    directives: list[str] = []

    for name, defaults in DEFAULT_CSP_DIRECTIVES:
        sources = _merge_sources(
            defaults,
            extra_sources.get(name, []),
        )
        directives.append(f"{name} {' '.join(sources)}")

    return "; ".join(directives)


def build_security_headers(*, is_production: bool) -> dict[str, str]:
    headers = {
        "content-security-policy": build_content_security_policy(),
        "permissions-policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
        "referrer-policy": "strict-origin-when-cross-origin",
        "x-content-type-options": "nosniff",
        "x-frame-options": "SAMEORIGIN",
    }
    if is_production:
        headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
    return headers
