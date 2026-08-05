"""Request hardening that sits in front of every route.

Three checks, each cheap enough to run on health probes too where relevant:

1. **Security headers** on every response.
2. **Origin allowlist** when ``ALLOWED_ORIGINS`` is set — browsers send Origin
   on cross-site calls; rejecting an unexpected one stops a page the operator
   did not authorise from driving the API with a visitor's token.
3. **Rate limiting** on chat and session issuance.
4. **Session auth** on chat when ``SESSION_TOKEN_SECRET`` is configured.

Local development with an empty secret and empty origin list skips (2) and
(4), which is the only way the interactive docs stay usable without a login
ceremony. Production must set both.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.rate_limit import RateLimiter, RateLimitExceededError
from app.api.session import SessionClaims, SessionError, verify_token
from app.core.config import Settings

__all__ = ["install_security"]

logger = structlog.get_logger(__name__)

# Paths that never require a session and never consume rate-limit budget.
_PUBLIC = frozenset({"/", "/api/health", "/docs", "/openapi.json", "/redoc"})


def install_security(application: FastAPI, settings: Settings) -> None:
    limiter = RateLimiter(
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    application.state.rate_limiter = limiter
    require_auth = bool(settings.session_token_secret)

    @application.middleware("http")
    async def security(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path

        if denied := _check_origin(request, settings):
            return denied

        if _should_rate_limit(path) and (limited := _check_rate_limit(request, limiter)):
            return limited

        if require_auth and path.startswith("/api/chat"):
            try:
                request.state.session = _authenticate(request, settings.session_token_secret)
            except SessionError as exc:
                logger.info("auth.rejected", reason=str(exc), path=path)
                return JSONResponse(status_code=401, content={"detail": "Unauthorised."})

        response = await call_next(request)
        _apply_security_headers(response, path=path)
        return response


def _should_rate_limit(path: str) -> bool:
    """Chat and session issuance only. Static assets and health stay free."""
    if path in _PUBLIC or path.startswith("/widget"):
        return False
    return path.startswith("/api/")


def _check_origin(request: Request, settings: Settings) -> JSONResponse | None:
    """Reject a present-but-unknown Origin. Absent Origin is allowed.

    Same-origin fetches and non-browser clients often omit the header. Blocking
    those would break the internal page and every curl-based check. The
    dangerous case is a browser on a foreign site sending a visitor's token,
    and that always includes Origin.
    """
    if not settings.origins:
        return None

    origin = request.headers.get("origin")
    if origin is None:
        return None

    normalised = origin.rstrip("/")
    allowed = {entry.rstrip("/") for entry in settings.origins}
    if normalised in allowed:
        return None

    logger.info("origin.rejected", origin=origin)
    return JSONResponse(status_code=403, content={"detail": "Origin not allowed."})


def _check_rate_limit(request: Request, limiter: RateLimiter) -> JSONResponse | None:
    key = _client_key(request)
    try:
        limiter.check(key)
    except RateLimitExceededError as exc:
        logger.info("rate_limit.exceeded", key=key, retry_after=exc.retry_after)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Try again shortly."},
            headers={"Retry-After": str(exc.retry_after)},
        )
    return None


def _authenticate(request: Request, secret: str) -> SessionClaims:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise SessionError("Missing bearer token.")
    return verify_token(token.strip(), secret)


def _client_key(request: Request) -> str:
    """Best-effort caller identity for the rate limiter.

    Cloud Run puts the real client in ``X-Forwarded-For``. Trusting it is
    acceptable here because the load balancer is the only thing that can set
    it; a direct caller without that header falls back to the peer address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def _apply_security_headers(response: Response, *, path: str) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")

    # API responses carry no executable content, so the strictest policy is safe.
    # The internal page needs its own script, fonts, and same-origin fetches.
    if path.startswith("/api/"):
        policy = "frame-ancestors 'none'; default-src 'none'"
    else:
        policy = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'"
        )
    response.headers.setdefault("Content-Security-Policy", policy)
