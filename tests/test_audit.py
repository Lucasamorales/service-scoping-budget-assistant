"""Conversation audit store — JSONL always; Firestore via a fake client."""

from __future__ import annotations

from pathlib import Path

from app.orchestrator.llm import DETERMINISTIC
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.router import Intent
from app.store.audit import (
    OUTCOME_CHAT_ONLY,
    OUTCOME_EMAIL_DRAFTED,
    OUTCOME_EMAIL_PENDING,
    AuditEvent,
    FirestoreAuditStore,
    JsonlAuditStore,
    build_audit_store,
)
from app.tools.flows import SessionIdentity
from tests.test_pipeline import RecordingModel


class _FakeDoc:
    def __init__(self, data: dict | None = None, *, exists: bool = False) -> None:
        self._data = data
        self.exists = exists

    def to_dict(self) -> dict | None:
        return self._data


class _FakeTurnCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def document(self, turn_id: str) -> _FakeTurnDoc:
        return _FakeTurnDoc(self, turn_id)

    def order_by(self, _field: str) -> _FakeTurnCollection:
        return self

    def stream(self) -> list[_FakeDoc]:
        ordered = sorted(self.docs.values(), key=lambda row: row.get("at") or "")
        return [_FakeDoc(row, exists=True) for row in ordered]


class _FakeTurnDoc:
    def __init__(self, collection: _FakeTurnCollection, turn_id: str) -> None:
        self._collection = collection
        self._turn_id = turn_id

    def set(self, data: dict) -> None:
        self._collection.docs[self._turn_id] = data


class _FakeConvDoc:
    def __init__(self, store: _FakeFirestore, conversation_id: str) -> None:
        self._store = store
        self._id = conversation_id
        self._turns = _FakeTurnCollection()

    def get(self) -> _FakeDoc:
        data = self._store.conversations.get(self._id)
        return _FakeDoc(data, exists=data is not None)

    def set(self, data: dict) -> None:
        self._store.conversations[self._id] = data
        self._store.turns[self._id] = self._turns

    def update(self, data: dict) -> None:
        current = self._store.conversations.setdefault(self._id, {})
        current.update(data)

    def collection(self, name: str) -> _FakeTurnCollection:
        assert name == "turns"
        if self._id not in self._store.turns:
            self._store.turns[self._id] = self._turns
        return self._store.turns[self._id]


class _FakeConvCollection:
    def __init__(self, store: _FakeFirestore) -> None:
        self._store = store

    def document(self, conversation_id: str) -> _FakeConvDoc:
        return _FakeConvDoc(self._store, conversation_id)


class _FakeFirestore:
    def __init__(self) -> None:
        self.conversations: dict[str, dict] = {}
        self.turns: dict[str, _FakeTurnCollection] = {}

    def collection(self, name: str) -> _FakeConvCollection:
        assert name == "conversations"
        return _FakeConvCollection(self)


class TestJsonlAuditStore:
    def test_append_and_read_round_trip(self, tmp_path: Path) -> None:
        store = JsonlAuditStore(tmp_path)
        store.append(
            AuditEvent(
                conversation_id="abc",
                kind="turn",
                payload={
                    "user_message": "hi",
                    "assistant_message": "hello",
                    "outcome": OUTCOME_CHAT_ONLY,
                    "subject": "Alex",
                },
            )
        )
        events = store.read("abc")
        assert len(events) == 1
        assert events[0].payload["subject"] == "Alex"
        assert events[0].payload["assistant_message"] == "hello"


class TestFirestoreAuditStore:
    def test_writes_conversation_and_turns(self) -> None:
        client = _FakeFirestore()
        store = FirestoreAuditStore(client)
        store.append(
            AuditEvent(
                conversation_id="c1",
                kind="turn",
                payload={
                    "user_message": "budget?",
                    "assistant_message": "500 left",
                    "outcome": OUTCOME_CHAT_ONLY,
                    "subject": "Sam",
                    "country": "Canada",
                },
            )
        )
        assert client.conversations["c1"]["subject"] == "Sam"
        assert client.conversations["c1"]["turn_count"] == 1
        events = store.read("c1")
        assert len(events) == 1
        assert events[0].payload["user_message"] == "budget?"

        store.append(
            AuditEvent(
                conversation_id="c1",
                kind="turn",
                payload={
                    "user_message": "yes",
                    "assistant_message": "draft",
                    "outcome": OUTCOME_EMAIL_DRAFTED,
                    "subject": "Sam",
                    "email": {"to": "am@example.com"},
                },
            )
        )
        assert client.conversations["c1"]["turn_count"] == 2
        assert client.conversations["c1"]["email_count"] == 1


class TestBuildAuditStore:
    def test_jsonl_backend(self, tmp_path: Path) -> None:
        store = build_audit_store(
            backend="jsonl",
            jsonl_path=tmp_path,
            gcp_project_id="proj",
        )
        assert isinstance(store, JsonlAuditStore)

    def test_auto_without_project_is_jsonl(self, tmp_path: Path) -> None:
        store = build_audit_store(
            backend="auto",
            jsonl_path=tmp_path,
            gcp_project_id="",
        )
        assert isinstance(store, JsonlAuditStore)


class TestPipelineAudit:
    def test_turn_writes_full_messages_and_outcome(
        self, corpus, tmp_path: Path
    ) -> None:
        from app.knowledge.chunking import chunk_service_item
        from app.knowledge.index import KnowledgeIndex

        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        store = JsonlAuditStore(tmp_path)
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=RecordingModel("should not run"),
            audit_log=store,
        )
        answer = pipeline.answer(
            "how much budget is left",
            identity=SessionIdentity(subject="Alex"),
        )
        assert answer.route.intent is Intent.BUDGET
        events = store.read(answer.next_state.conversation_id or "")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["subject"] == "Alex"
        assert payload["user_message"] == "how much budget is left"
        assert payload["assistant_message"] == answer.text
        assert payload["outcome"] == OUTCOME_CHAT_ONLY
        assert "text_preview" not in payload

    def test_in_scope_cta_marks_email_pending(self, corpus, tmp_path: Path) -> None:
        from app.knowledge.chunking import chunk_service_item
        from app.knowledge.index import KnowledgeIndex
        from app.store.contacts import load_contacts
        from pathlib import Path as P

        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        store = JsonlAuditStore(tmp_path)
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=RecordingModel("should not run"),
            audit_log=store,
            contacts=load_contacts(P("fixtures/contacts/country_ams.json")),
        )
        answer = pipeline.answer(
            "can we do campaign wrap-ups",
            identity=SessionIdentity(subject="Alex", country="United Kingdom"),
        )
        if answer.next_state.pending_action_kind:
            events = store.read(answer.next_state.conversation_id or "")
            assert events[-1].payload["outcome"] == OUTCOME_EMAIL_PENDING


class TestHrCapabilityDenial:
    def test_fire_jeremy_is_not_handover(self, corpus) -> None:
        from app.knowledge.chunking import chunk_service_item
        from app.knowledge.index import KnowledgeIndex

        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=None,
        )
        answer = pipeline.answer(
            "fire jeremy",
            identity=SessionIdentity(subject="Alex"),
        )
        assert answer.route.intent is not Intent.HANDOVER
        assert "capability" in answer.text.lower()
        assert answer.source == DETERMINISTIC
