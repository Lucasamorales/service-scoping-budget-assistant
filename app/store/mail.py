"""Transactional mail — Resend when configured, otherwise a no-op recorder."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import structlog

__all__ = [
    "MailAttachment",
    "MailMessage",
    "MailResult",
    "Mailer",
    "NullMailer",
    "ResendMailer",
    "build_mailer",
]

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MailAttachment:
    filename: str
    content: bytes
    mime: str = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class MailMessage:
    to_name: str
    to_email: str
    subject: str
    body: str
    attachments: tuple[MailAttachment, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MailResult:
    sent: bool
    provider_id: str = ""
    detail: str = ""
    attempted: bool = False
    """Whether a provider was actually called.

    Distinguishes "mail is not configured here, so this is a draft" from "we
    tried to send and it was rejected". Both leave ``sent`` false, but only the
    second is a failure someone needs to chase.
    """


class Mailer(Protocol):
    def send(self, message: MailMessage) -> MailResult: ...


class NullMailer:
    """Used when mail credentials are missing — never pretends a send succeeded."""

    def send(self, message: MailMessage) -> MailResult:
        logger.info(
            "mail.skipped",
            to=message.to_email,
            subject=message.subject,
            attachments=[item.filename for item in message.attachments],
            reason="mail not configured",
        )
        return MailResult(sent=False, detail="Mail is not configured on this environment.")


class ResendMailer:
    def __init__(self, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from = from_address

    def send(self, message: MailMessage) -> MailResult:
        payload: dict[str, object] = {
            "from": self._from,
            "to": [message.to_email],
            "subject": message.subject,
            "text": message.body,
        }
        if message.attachments:
            payload["attachments"] = [
                {
                    "filename": item.filename,
                    "content": base64.b64encode(item.content).decode("ascii"),
                    "content_type": item.mime,
                }
                for item in message.attachments
            ]
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            logger.error("mail.resend_error", error=str(exc))
            return MailResult(sent=False, detail=f"Mail provider error: {exc}", attempted=True)

        if response.status_code >= 400:
            logger.error("mail.resend_rejected", status=response.status_code, body=response.text)
            return MailResult(
                sent=False,
                detail=f"Mail provider rejected send ({response.status_code}).",
                attempted=True,
            )

        data = response.json() if response.content else {}
        provider_id = str(data.get("id") or "")
        return MailResult(sent=True, provider_id=provider_id, detail="sent", attempted=True)


def build_mailer(*, api_key: str, from_address: str, provider: str = "resend") -> Mailer:
    if api_key and from_address and provider.lower() == "resend":
        return ResendMailer(api_key, from_address)
    return NullMailer()
