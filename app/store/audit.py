"""Conversation audit log — Firestore when configured, local JSONL otherwise.

Every chat turn is persisted for later review: who asked, when, full Q&A, and
whether the turn stayed in chat or produced an email (drafted / sent / failed).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

__all__ = [
    "OUTCOME_CHAT_ONLY",
    "OUTCOME_EMAIL_DRAFTED",
    "OUTCOME_EMAIL_FAILED",
    "OUTCOME_EMAIL_PENDING",
    "OUTCOME_EMAIL_SENT",
    "AuditEvent",
    "AuditLog",
    "AuditStore",
    "FirestoreAuditStore",
    "JsonlAuditStore",
    "build_audit_store",
    "new_conversation_id",
]

logger = structlog.get_logger(__name__)

OUTCOME_CHAT_ONLY = "chat_only"
OUTCOME_EMAIL_PENDING = "email_pending"
OUTCOME_EMAIL_DRAFTED = "email_drafted"
OUTCOME_EMAIL_SENT = "email_sent"
OUTCOME_EMAIL_FAILED = "email_failed"


def new_conversation_id() -> str:
    return uuid.uuid4().hex


@dataclass(slots=True)
class AuditEvent:
    conversation_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...

    def read(self, conversation_id: str) -> list[AuditEvent]: ...


class JsonlAuditStore:
    """One JSONL file per conversation under a local directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def append(self, event: AuditEvent) -> None:
        path = self.directory / f"{event.conversation_id}.jsonl"
        line = json.dumps(asdict(event), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        logger.info(
            "audit.appended",
            backend="jsonl",
            conversation_id=event.conversation_id,
            kind=event.kind,
            outcome=event.payload.get("outcome"),
        )

    def read(self, conversation_id: str) -> list[AuditEvent]:
        path = self.directory / f"{conversation_id}.jsonl"
        if not path.is_file():
            return []
        events: list[AuditEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            events.append(
                AuditEvent(
                    conversation_id=raw["conversation_id"],
                    kind=raw["kind"],
                    payload=raw.get("payload") or {},
                    at=raw.get("at") or "",
                )
            )
        return events


# Back-compat alias used by older imports / tests.
AuditLog = JsonlAuditStore


class FirestoreAuditStore:
    """conversations/{id} + turns/{turnId} in Firestore."""

    def __init__(self, client: Any, *, database: str = "(default)") -> None:
        self._client = client
        self._database = database

    def append(self, event: AuditEvent) -> None:
        conv_ref = self._client.collection("conversations").document(event.conversation_id)
        turn_id = uuid.uuid4().hex
        payload = dict(event.payload)
        subject = payload.get("subject")
        role = payload.get("role")
        country = payload.get("country")
        branch = payload.get("branch")
        outcome = payload.get("outcome")

        conv_snap = conv_ref.get()
        now = event.at
        if conv_snap.exists:
            data = conv_snap.to_dict() or {}
            updates: dict[str, Any] = {
                "updated_at": now,
                "turn_count": int(data.get("turn_count") or 0) + 1,
            }
            if outcome in {
                OUTCOME_EMAIL_SENT,
                OUTCOME_EMAIL_DRAFTED,
                OUTCOME_EMAIL_FAILED,
            }:
                updates["email_count"] = int(data.get("email_count") or 0) + 1
            if subject and not data.get("subject"):
                updates["subject"] = subject
            if role and not data.get("role"):
                updates["role"] = role
            if country and not data.get("country"):
                updates["country"] = country
            if branch and not data.get("branch"):
                updates["branch"] = branch
            conv_ref.update(updates)
        else:
            email_count = (
                1
                if outcome
                in {
                    OUTCOME_EMAIL_SENT,
                    OUTCOME_EMAIL_DRAFTED,
                    OUTCOME_EMAIL_FAILED,
                }
                else 0
            )
            conv_ref.set(
                {
                    "conversation_id": event.conversation_id,
                    "subject": subject,
                    "role": role,
                    "country": country,
                    "branch": branch,
                    "started_at": now,
                    "updated_at": now,
                    "turn_count": 1,
                    "email_count": email_count,
                }
            )

        conv_ref.collection("turns").document(turn_id).set(
            {
                "turn_id": turn_id,
                "kind": event.kind,
                "at": event.at,
                **payload,
            }
        )
        logger.info(
            "audit.appended",
            backend="firestore",
            conversation_id=event.conversation_id,
            kind=event.kind,
            outcome=outcome,
            turn_id=turn_id,
        )

    def read(self, conversation_id: str) -> list[AuditEvent]:
        conv_ref = self._client.collection("conversations").document(conversation_id)
        turns = (
            conv_ref.collection("turns")
            .order_by("at")
            .stream()
        )
        events: list[AuditEvent] = []
        for doc in turns:
            raw = doc.to_dict() or {}
            kind = str(raw.pop("kind", "turn"))
            at = str(raw.pop("at", ""))
            raw.pop("turn_id", None)
            events.append(
                AuditEvent(
                    conversation_id=conversation_id,
                    kind=kind,
                    payload=raw,
                    at=at,
                )
            )
        return events


class _MultiAuditStore:
    """Write to every backend; read from the first that has data."""

    def __init__(self, stores: tuple[AuditStore, ...]) -> None:
        self._stores = stores

    def append(self, event: AuditEvent) -> None:
        for store in self._stores:
            try:
                store.append(event)
            except Exception as exc:
                logger.error(
                    "audit.append_failed",
                    backend=type(store).__name__,
                    error=str(exc),
                )

    def read(self, conversation_id: str) -> list[AuditEvent]:
        for store in self._stores:
            try:
                events = store.read(conversation_id)
            except Exception as exc:
                logger.error(
                    "audit.read_failed",
                    backend=type(store).__name__,
                    error=str(exc),
                )
                continue
            if events:
                return events
        return []


def build_audit_store(
    *,
    backend: str = "auto",
    jsonl_path: Path,
    gcp_project_id: str = "",
    firestore_database: str = "(default)",
    credentials_path: str = "",
) -> AuditStore:
    """Build the audit store. ``auto`` prefers Firestore when a GCP project is set."""
    mode = (backend or "auto").strip().lower()
    jsonl = JsonlAuditStore(jsonl_path)

    want_firestore = mode == "firestore" or (
        mode == "auto" and bool(gcp_project_id.strip())
    )
    if mode == "jsonl" or not want_firestore:
        logger.info("audit.backend", backend="jsonl", path=str(jsonl_path))
        return jsonl

    try:
        from google.cloud import firestore  # type: ignore[import-untyped]
        from google.oauth2 import service_account
    except ImportError:
        logger.warning(
            "audit.firestore_unavailable",
            detail="google-cloud-firestore not installed; using JSONL",
        )
        return jsonl

    try:
        client_kwargs: dict[str, Any] = {
            "project": gcp_project_id.strip() or None,
            "database": firestore_database or "(default)",
        }
        if credentials_path.strip():
            creds = service_account.Credentials.from_service_account_file(
                credentials_path.strip(),
                scopes=("https://www.googleapis.com/auth/cloud-platform",),
            )
            client_kwargs["credentials"] = creds
        client = firestore.Client(**client_kwargs)
    except Exception as exc:
        logger.warning(
            "audit.firestore_client_failed",
            error=str(exc),
            detail="falling back to JSONL",
        )
        return jsonl

    firestore_store = FirestoreAuditStore(client, database=firestore_database)
    logger.info(
        "audit.backend",
        backend="firestore+jsonl",
        project=gcp_project_id,
        database=firestore_database,
    )
    # Dual-write so local files remain a safety net during the Firestore rollout.
    return _MultiAuditStore((firestore_store, jsonl))
