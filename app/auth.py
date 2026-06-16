"""Session-based authentication.

Replaces HTTP Basic with a signed-cookie session (Starlette's SessionMiddleware).
Credentials are still validated against ENRICHER_USER / ENRICHER_PASSWORD, but
the user now logs in through a real form, gets a session cookie, and can sign
out cleanly. Single user; no role model.
"""

import secrets

from fastapi import Request

from .config import settings


class NotAuthenticatedError(Exception):
    """Raised by route dependencies when there's no valid session.

    Caught by an exception handler that redirects browsers to /login or
    returns 401 + HX-Redirect for HTMX requests.
    """
    pass


def verify_login_credentials(username: str, password: str) -> bool:
    """Constant-time credential check used by the POST /login handler."""
    user_ok = secrets.compare_digest(
        username.encode("utf-8"),
        settings.enricher_user.encode("utf-8"),
    )
    pass_ok = secrets.compare_digest(
        password.encode("utf-8"),
        settings.enricher_password.encode("utf-8"),
    )
    return user_ok and pass_ok


def require_session(request: Request) -> str:
    """FastAPI dependency: returns the session user or raises NotAuthenticatedError."""
    user = request.session.get("user")
    if not user:
        raise NotAuthenticatedError()
    return user
