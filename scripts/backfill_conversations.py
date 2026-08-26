"""Bring existing Firestore conversations up to the readable schema.

New conversations are written with a ``person`` name, a ``person_key`` to filter
on, a one-line ``summary``, real Timestamps and split email counters. Documents
written before that are missing all of it, which makes the console list a mix of
two shapes. This walks what is already there and fills the gaps.

Document ids are left alone. A conversation id is quoted in sent emails and in
the PDF footer, so rewriting one would break the reference for anybody holding
it; old conversations keep their hex ids and simply sort separately.

Read-only by default. Pass ``--commit`` to write.

    python -m scripts.backfill_conversations
    python -m scripts.backfill_conversations --commit
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.store.audit import (
    OUTCOME_EMAIL_DRAFTED,
    OUTCOME_EMAIL_FAILED,
    OUTCOME_EMAIL_SENT,
    person_key,
)

_LEGACY_EMAIL_OUTCOMES = {
    OUTCOME_EMAIL_SENT: "emails_sent",
    OUTCOME_EMAIL_DRAFTED: "emails_drafted",
    OUTCOME_EMAIL_FAILED: "emails_failed",
}


def _client(settings: Any) -> Any:
    from google.cloud import firestore
    from google.oauth2 import service_account

    kwargs: dict[str, Any] = {
        "project": settings.gcp_project_id.strip() or None,
        "database": settings.firestore_database or "(default)",
    }
    if settings.google_application_credentials.strip():
        kwargs["credentials"] = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials.strip(),
            scopes=("https://www.googleapis.com/auth/cloud-platform",),
        )
    return firestore.Client(**kwargs)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _summary_for(data: dict[str, Any], last_turn: dict[str, Any]) -> str:
    person = data.get("person") or data.get("subject") or "unnamed"
    parts = [str(person), str(data.get("country") or ""), str(data.get("branch") or "")]
    parts.append(str(last_turn.get("status") or last_turn.get("outcome") or ""))
    email = last_turn.get("email")
    if isinstance(email, dict):
        recipient = email.get("to_name") or email.get("to")
        if recipient:
            verb = "emailed" if last_turn.get("outcome") == OUTCOME_EMAIL_SENT else "draft for"
            parts.append(f"{verb} {recipient}")
    return " | ".join(part for part in parts if part)


def _updates_for(doc: Any) -> dict[str, Any]:
    """What this conversation is missing. Empty means it is already current."""
    data = doc.to_dict() or {}
    updates: dict[str, Any] = {}

    person = data.get("person") or data.get("subject")
    if person and not data.get("person"):
        updates["person"] = person
    if person and not data.get("person_key"):
        updates["person_key"] = person_key(str(person))

    for field in ("started_at", "updated_at"):
        moment = _as_datetime(data.get(field))
        if moment is not None and not isinstance(data.get(field), datetime):
            updates[field] = moment

    turns = sorted(
        (turn.to_dict() or {} for turn in doc.reference.collection("turns").stream()),
        key=lambda row: str(row.get("at") or ""),
    )
    if turns:
        last = turns[-1]
        if not data.get("summary"):
            updates["summary"] = _summary_for({**data, **updates}, last)
        if not data.get("last_outcome") and last.get("outcome"):
            updates["last_outcome"] = last["outcome"]
        if not data.get("last_status") and last.get("status"):
            updates["last_status"] = last["status"]

        # The old schema kept one combined count. Recover the split from the
        # turns themselves rather than guessing how the total was made up.
        if "email_count" in data:
            for outcome, counter in _LEGACY_EMAIL_OUTCOMES.items():
                total = sum(1 for turn in turns if turn.get("outcome") == outcome)
                if total and not data.get(counter):
                    updates[counter] = total
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    if not settings.gcp_project_id.strip():
        print("GCP_PROJECT_ID is empty; nothing to backfill.")
        return 1

    client = _client(settings)
    seen = changed = 0
    for doc in client.collection("conversations").stream():
        seen += 1
        updates = _updates_for(doc)
        if not updates:
            continue
        changed += 1
        print(f"{doc.id}: {', '.join(sorted(updates))}")
        if args.commit:
            doc.reference.set(updates, merge=True)

    verb = "updated" if args.commit else "would update"
    print(f"\n{seen} conversations, {verb} {changed}.")
    if changed and not args.commit:
        print("Re-run with --commit to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
