"""Conversation audit log — Firestore when configured, local JSONL otherwise.

Every chat turn is persisted for later review: who asked, when, full Q&A, and
whether the turn stayed in chat or produced an email (drafted / sent / failed).

The Firestore layout is shaped for someone reading it in the console rather than
for a query planner. Document ids sort chronologically and name the person, so
the conversation list is browsable without opening anything; each conversation
carries a one-line ``summary`` so you can tell what it was about at a glance;
and timestamps are real Timestamps so the console can sort and filter on them.
"""

from __future__ import annotations

import json
import re
import secrets
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
    "AuditStore",
    "FirestoreAuditStore",
    "JsonlAuditStore",
    "build_audit_store",
    "new_conversation_id",
    "person_key",
]

logger = structlog.get_logger(__name__)

OUTCOME_CHAT_ONLY = "chat_only"
OUTCOME_EMAIL_PENDING = "email_pending"
OUTCOME_EMAIL_DRAFTED = "email_drafted"
OUTCOME_EMAIL_SENT = "email_sent"
OUTCOME_EMAIL_FAILED = "email_failed"

_EMAIL_COUNTERS = {
    OUTCOME_EMAIL_SENT: "emails_sent",
    OUTCOME_EMAIL_DRAFTED: "emails_drafted",
    OUTCOME_EMAIL_FAILED: "emails_failed",
}
"""Sent, drafted and failed are counted apart. One combined ``email_count``
could not answer "did this actually reach anyone?", which is the only question
the number is ever asked."""

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def person_key(name: str | None) -> str:
    """Normalise a display name into something filterable.

    Names are typed by hand at login, so "Alex", "alex " and "Alex Marsh" would
    otherwise be three different people to any lookup.
    """
    if not name:
        return ""
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")


def new_conversation_id(person: str | None = None, *, now: datetime | None = None) -> str:
    """A document id that sorts by time and says who was asking.

    Firestore lists documents by id, so a hex uuid made the console a wall of
    noise in no useful order. ``20260820-140312-alex-marsh-7f3a`` sorts
    chronologically, is recognisable, and keeps a random tail for uniqueness.
    """
    moment = now or datetime.now(UTC)
    slug = person_key(person)[:24] or "anon"
    return f"{moment.strftime('%Y%m%d-%H%M%S')}-{slug}-{secrets.token_hex(2)}"


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


class FirestoreAuditStore:
    """conversations/{id} + turns/{turnId} in Firestore."""

    def __init__(self, client: Any, *, database: str = "(default)") -> None:
        self._client = client
        self._database = database

    def append(self, event: AuditEvent) -> None:
        conv_ref = self._client.collection("conversations").document(event.conversation_id)
        payload = dict(event.payload)
        moment = _as_datetime(event.at)
        outcome = payload.get("outcome")
        # ``subject`` is the historic key for the person's name. Documents
        # written before the rename still use it.
        person = payload.get("person") or payload.get("subject")
        email = payload.get("email")

        # One merged write with server-side increments. The previous get() then
        # update() lost turns whenever two turns of the same conversation
        # overlapped, and left the parent counter inflated when the turn write
        # that followed it failed.
        document: dict[str, Any] = {
            "conversation_id": event.conversation_id,
            "started_at": _started_at(event.conversation_id, moment),
            "updated_at": moment,
            "turn_count": _increment(1),
            "last_outcome": outcome,
            "last_status": payload.get("status"),
            "summary": _summarise(
                person=person,
                country=payload.get("country"),
                branch=payload.get("branch"),
                status=payload.get("status"),
                outcome=outcome,
                email=email if isinstance(email, dict) else None,
            ),
        }
        counter = _EMAIL_COUNTERS.get(str(outcome))
        if counter:
            document[counter] = _increment(1)

        # Last non-empty value wins. Merging unconditionally would let a turn
        # that happens to carry no country erase one an earlier turn resolved.
        for key, value in (
            ("person", person),
            ("person_key", person_key(person if isinstance(person, str) else None)),
            ("role", payload.get("role")),
            ("country", payload.get("country")),
            ("branch", payload.get("branch")),
        ):
            if value:
                document[key] = value

        conv_ref.set(document, merge=True)

        turn_id = _turn_document_id(moment)
        conv_ref.collection("turns").document(turn_id).set(
            {
                "turn_id": turn_id,
                "kind": event.kind,
                "at": moment,
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
        turns = conv_ref.collection("turns").order_by("at").stream()
        events: list[AuditEvent] = []
        for doc in turns:
            raw = doc.to_dict() or {}
            kind = str(raw.pop("kind", "turn"))
            at = raw.pop("at", "")
            raw.pop("turn_id", None)
            events.append(
                AuditEvent(
                    conversation_id=conversation_id,
                    kind=kind,
                    payload=raw,
                    at=at.isoformat() if isinstance(at, datetime) else str(at),
                )
            )
        return events


def _summarise(
    *,
    person: object,
    country: object,
    branch: object,
    status: object,
    outcome: object,
    email: dict[str, Any] | None,
) -> str:
    """The line that makes the conversation list readable.

    Rewritten every turn, so it describes where the conversation got to rather
    than where it started — which is what you want when scanning for one.
    """
    parts = [str(person) if person else "unnamed", str(country or ""), str(branch or "")]
    parts.append(str(status or outcome or ""))
    if email:
        recipient = email.get("to_name") or email.get("to")
        if recipient:
            verb = "emailed" if outcome == OUTCOME_EMAIL_SENT else "draft for"
            parts.append(f"{verb} {recipient}")
    return " | ".join(part for part in parts if part)


def _turn_document_id(moment: datetime) -> str:
    """Turn ids that sort in the console the way the turns actually happened.

    A sequence number would read better still, but deriving one needs a read of
    the parent, which is the race this store just stopped doing. Microsecond
    precision orders correctly and cannot collide within one conversation.
    """
    return moment.strftime("%Y%m%d-%H%M%S-%f")


def _started_at(conversation_id: str, fallback: datetime) -> datetime:
    """Derived from the id, so re-merging it every turn is a no-op.

    Without a read there is no "write only if absent", but the id already
    encodes the start, so the value written is stable. Ids in the old hex
    format have nothing to derive from and fall back to the event time.
    """
    try:
        return datetime.strptime(conversation_id[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return fallback


def _as_datetime(at: str) -> datetime:
    """ISO string to an aware datetime, so Firestore stores a real Timestamp."""
    try:
        parsed = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _increment(by: int) -> Any:
    """Server-side counter bump, or a plain int when Firestore is not installed."""
    try:
        from google.cloud import firestore
    except ImportError:
        return by
    return firestore.Increment(by)


class _MultiAuditStore:
    """Write to every backend; read from the first that has data."""

    def __init__(self, stores: tuple[AuditStore, ...]) -> None:
        self._stores = stores

    def append(self, event: AuditEvent) -> None:
        written = 0
        for store in self._stores:
            try:
                store.append(event)
            except Exception as exc:  # noqa: BLE001 - one backend must not take the others down
                logger.error(
                    "audit.append_failed",
                    backend=type(store).__name__,
                    error=str(exc),
                )
            else:
                written += 1
        if not written:
            # Distinct from a single backend failing: the turn is gone. Not
            # raised, because failing the user's chat over an audit write would
            # trade a lost record for a lost answer.
            logger.critical(
                "audit.lost",
                conversation_id=event.conversation_id,
                kind=event.kind,
                detail="no audit backend accepted this turn",
            )

    def read(self, conversation_id: str) -> list[AuditEvent]:
        """The fullest account any backend has.

        Taking the first backend with any rows at all meant a Firestore write
        that had partially failed would win over a complete local file, and the
        emailed transcript would quietly be missing turns.
        """
        best: list[AuditEvent] = []
        for store in self._stores:
            try:
                events = store.read(conversation_id)
            except Exception as exc:  # noqa: BLE001 - a dead backend must not hide a live one
                logger.error(
                    "audit.read_failed",
                    backend=type(store).__name__,
                    error=str(exc),
                )
                continue
            if len(events) > len(best):
                best = events
        return best


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
        from google.cloud import firestore
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
    except Exception as exc:  # noqa: BLE001 - any client failure degrades to JSONL
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
