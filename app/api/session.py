"""Server-issued session tokens.

A token carries who is asking and which branch they belong to. Budget answers
and mail routing will need both; scoping does not, but issuing them from the
start means the widget never has to be revisited when those arrive.

Signed with HMAC-SHA256 over a JSON payload. No JWT library: the claims set is
small and fixed, and a dependency whose sole job is framing those claims is
not worth the supply-chain surface.

Tokens are **bearer secrets**. They are not stored server-side. Revocation is
expiry, or rotating ``SESSION_TOKEN_SECRET``. That is enough for an internal
tool; a customer-facing launch would want a denylist.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from app.core.signing import SignatureError, sign, unsign

__all__ = [
    "Role",
    "SessionClaims",
    "SessionError",
    "issue_token",
    "verify_token",
]


class SessionError(ValueError):
    """The token is missing, malformed, forged, or expired."""


class Role(StrEnum):
    ACCOUNT_MANAGER = "am"
    GENERAL_MANAGER = "gm"
    COUNTRY_MANAGER = "country"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class SessionClaims:
    """What a verified token asserts about the caller."""

    subject: str
    role: Role
    country: str | None = None
    branch: str | None = None
    expires_at: int = 0

    @property
    def expired(self) -> bool:
        return self.expires_at <= int(time.time())


def issue_token(
    *,
    secret: str,
    subject: str,
    role: Role,
    country: str | None = None,
    branch: str | None = None,
    ttl_seconds: int = 3600,
    now: int | None = None,
) -> tuple[str, SessionClaims]:
    """Mint a signed token and the claims it carries."""
    if not secret:
        raise SessionError("SESSION_TOKEN_SECRET is not configured.")

    issued_at = int(time.time() if now is None else now)
    claims = SessionClaims(
        subject=subject.strip() or "anonymous",
        role=role,
        country=_clean(country),
        branch=_clean(branch),
        expires_at=issued_at + max(ttl_seconds, 60),
    )
    payload = {
        "sub": claims.subject,
        "role": claims.role.value,
        "country": claims.country,
        "branch": claims.branch,
        "iat": issued_at,
        "exp": claims.expires_at,
    }
    return sign(payload, secret), claims


def verify_token(token: str, secret: str, *, now: int | None = None) -> SessionClaims:
    """Validate a bearer token and return its claims.

    Raises :class:`SessionError` for every failure mode. Callers should not
    distinguish forged from absent to the client — both are 401.
    """
    if not secret:
        raise SessionError("SESSION_TOKEN_SECRET is not configured.")

    try:
        payload = unsign(token, secret)
    except SignatureError as exc:
        raise SessionError(str(exc)) from exc

    try:
        claims = SessionClaims(
            subject=str(payload["sub"]),
            role=Role(str(payload["role"])),
            country=_clean(payload.get("country")),
            branch=_clean(payload.get("branch")),
            expires_at=int(payload["exp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SessionError("Malformed session token.") from exc

    moment = int(time.time() if now is None else now)
    if claims.expires_at <= moment:
        raise SessionError("Session has expired.")
    return claims


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
