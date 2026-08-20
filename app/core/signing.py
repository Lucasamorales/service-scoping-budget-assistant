"""HMAC-SHA256 signing for values the client is allowed to carry.

The service keeps nothing between turns, so continuity has to travel through
the client. Anything the client carries that the server later *acts on* must be
signed, or the client is free to rewrite it. Session claims and pending mail
actions both need that, so the framing lives here rather than being duplicated.

The payload is readable once decoded — this is a tamper seal, not encryption.
Never put anything in a signed payload that the holder should not read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

__all__ = ["SignatureError", "sign", "unsign"]


class SignatureError(ValueError):
    """The token is malformed, forged, or signed with a different secret."""


def sign(payload: dict[str, Any], secret: str) -> str:
    """Return ``body.mac``, where body is the base64url JSON payload."""
    if not secret:
        raise SignatureError("No signing secret configured.")
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return f"{body}.{_mac(body, secret)}"


def unsign(token: str, secret: str) -> dict[str, Any]:
    """Verify ``body.mac`` and return the decoded payload.

    The signature is checked before the payload is parsed, so malformed JSON
    from an unsigned source is never handed to :func:`json.loads`.
    """
    if not secret:
        raise SignatureError("No signing secret configured.")
    if not token or token.count(".") != 1:
        raise SignatureError("Malformed token.")

    body, signature = token.split(".", 1)
    if not hmac.compare_digest(signature, _mac(body, secret)):
        raise SignatureError("Invalid signature.")

    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SignatureError("Malformed token payload.") from exc
    if not isinstance(payload, dict):
        raise SignatureError("Token payload is not an object.")
    return payload


def _mac(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(raw: str | bytes) -> str:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
