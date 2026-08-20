"""Smoke-test Firestore audit write + read.

Requires GCP_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS, and a Native Firestore DB.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.store.audit import (
    OUTCOME_CHAT_ONLY,
    AuditEvent,
    FirestoreAuditStore,
    _MultiAuditStore,
    build_audit_store,
    new_conversation_id,
)


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.gcp_project_id.strip():
        print("GCP_PROJECT_ID is empty.")
        return 1
    if not settings.google_application_credentials.strip():
        print("GOOGLE_APPLICATION_CREDENTIALS is empty.")
        return 1

    store = build_audit_store(
        backend=settings.audit_backend,
        jsonl_path=Path(settings.audit_log_path) / "_smoke",
        gcp_project_id=settings.gcp_project_id,
        firestore_database=settings.firestore_database,
        credentials_path=settings.google_application_credentials,
    )
    backends = (
        [type(s).__name__ for s in store._stores]  # type: ignore[attr-defined]
        if isinstance(store, _MultiAuditStore)
        else [type(store).__name__]
    )
    print(f"project={settings.gcp_project_id}")
    print(f"database={settings.firestore_database}")
    print(f"backends={backends}")
    if "FirestoreAuditStore" not in backends:
        print("Firestore is NOT active — check API, IAM, and credentials.")
        return 1

    conversation_id = new_conversation_id("Firestore Smoke")
    store.append(
        AuditEvent(
            conversation_id=conversation_id,
            kind="turn",
            payload={
                "person": "Firestore Smoke",
                "role": "account_manager",
                "country": "United Kingdom",
                "branch": "Acme London",
                # Same keys the pipeline writes, so the smoke row is shaped like
                # a real one and a schema change here cannot pass unnoticed.
                "user_message": "smoke test question",
                "assistant_message": "smoke test answer",
                "outcome": OUTCOME_CHAT_ONLY,
            },
        )
    )

    firestore_store = next(
        (s for s in getattr(store, "_stores", (store,)) if isinstance(s, FirestoreAuditStore)),
        None,
    )
    if firestore_store is None:
        print("No FirestoreAuditStore in the chain.")
        return 1
    try:
        events = firestore_store.read(conversation_id)
    except Exception as exc:  # noqa: BLE001 - a smoke script reports any failure and exits
        print(f"Firestore read failed: {exc}")
        return 1
    print(f"conversation_id={conversation_id}")
    print(f"firestore_events={len(events)}")
    if not events:
        print("Write appeared to succeed but read returned nothing.")
        return 1
    print("ok - open Console > Firestore > Data > conversations /", conversation_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
