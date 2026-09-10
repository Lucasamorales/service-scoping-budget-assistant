"""Tamper-proof carriage of a pending mail action across turns.

A call to action ("shall I email your Account Manager?") is offered on one turn
and confirmed on the next, but the service holds no server-side session — the
state travels through the client. That is fine for continuity hints like the
last branch; it is not fine for the fields that decide *who gets emailed and
for how much*. Those are sealed here and never accepted as loose input.

The seal also carries the conversation id and an issue time, which closes two
holes at once: a token minted in one chat cannot confirm in another, and a
token left in a reopened tab stops being confirmable once it ages out.

When ``SESSION_TOKEN_SECRET`` is unset (local development) a random per-process
secret is used instead. Pending actions then do not survive a restart, which is
the safe direction to fail: an unverifiable token is treated as no token.
"""

from __future__ import annotations

import secrets
import time

import structlog

from app.core.signing import SignatureError, sign, unsign
from app.tools.flows import PendingAction

__all__ = ["PENDING_KINDS", "open_pending", "seal_pending"]

logger = structlog.get_logger(__name__)

PENDING_KINDS = frozenset({"email_am", "email_cm_po", "email_am_variable"})
"""The only actions a sealed token may ask for. Anything else is discarded."""

_fallback_secret = ""


def _signing_secret(secret: str) -> str:
    """The configured secret, or a stable per-process stand-in."""
    global _fallback_secret
    if secret.strip():
        return secret
    if not _fallback_secret:
        _fallback_secret = secrets.token_urlsafe(32)
        logger.info(
            "pending.ephemeral_secret",
            detail="SESSION_TOKEN_SECRET unset; pending actions will not survive a restart",
        )
    return _fallback_secret


def seal_pending(
    pending: PendingAction,
    *,
    conversation_id: str | None,
    secret: str,
    now: int | None = None,
) -> str | None:
    """Seal a pending action for the client to carry back.

    Returns ``None`` for a kind we do not recognise, so a bug upstream cannot
    mint a token for an action the confirm path would not understand anyway.
    """
    if pending.kind not in PENDING_KINDS:
        logger.warning("pending.unknown_kind", kind=pending.kind)
        return None

    payload = {
        "kind": pending.kind,
        "service_id": pending.service_id,
        "quote_amount": pending.quote_amount,
        "currency": pending.currency,
        "recipient_country": pending.recipient_country,
        "recipient_name": pending.recipient_name,
        "needs_country": pending.needs_country,
        # Body text for the email, carried so it survives the country
        # question. Sealed like everything else here, so the client cannot
        # alter what it already wrote; it still cannot reach who is emailed or
        # for how much, which is what this seal exists to protect.
        "note": pending.note,
        "conversation_id": conversation_id,
        "iat": int(time.time() if now is None else now),
    }
    return sign(payload, _signing_secret(secret))


def open_pending(
    token: str | None,
    *,
    conversation_id: str | None,
    secret: str,
    ttl_seconds: int,
    now: int | None = None,
) -> PendingAction | None:
    """Verify a sealed pending action, or return ``None``.

    Every failure returns ``None`` rather than raising: a stale or forged token
    should degrade to "there is nothing pending", which makes the assistant ask
    again instead of sending something the user did not ask for.
    """
    if not token:
        return None

    try:
        payload = unsign(token, _signing_secret(secret))
    except SignatureError as exc:
        logger.warning("pending.rejected", reason=str(exc))
        return None

    kind = payload.get("kind")
    if kind not in PENDING_KINDS:
        logger.warning("pending.rejected", reason="unknown kind", kind=kind)
        return None

    # Bound to the chat it was offered in, so a token cannot be replayed into
    # a different conversation to confirm an action that was never proposed.
    if payload.get("conversation_id") != conversation_id:
        logger.warning("pending.rejected", reason="conversation mismatch")
        return None

    moment = int(time.time() if now is None else now)
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int) or moment - issued_at > max(ttl_seconds, 60):
        age = moment - issued_at if isinstance(issued_at, int) else None
        logger.info("pending.expired", age=age)
        return None

    amount = payload.get("quote_amount")
    return PendingAction(
        kind=str(kind),
        service_id=_text(payload.get("service_id")),
        quote_amount=float(amount) if isinstance(amount, (int, float)) else None,
        currency=_text(payload.get("currency")) or "GBP",
        recipient_country=_text(payload.get("recipient_country")),
        recipient_name=_text(payload.get("recipient_name")),
        needs_country=bool(payload.get("needs_country")),
        note=_text(payload.get("note")),
    )


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
