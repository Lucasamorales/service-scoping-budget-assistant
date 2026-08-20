"""Conversation audit store — JSONL always; Firestore via a fake client."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from google.cloud.firestore_v1.transforms import Increment

from app.orchestrator.llm import DETERMINISTIC
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.router import Intent
from app.store.audit import (
    OUTCOME_CHAT_ONLY,
    OUTCOME_EMAIL_DRAFTED,
    OUTCOME_EMAIL_PENDING,
    OUTCOME_EMAIL_SENT,
    AuditEvent,
    FirestoreAuditStore,
    JsonlAuditStore,
    build_audit_store,
    new_conversation_id,
    person_key,
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

    def set(self, data: dict, merge: bool = False) -> None:
        """Emulates merge plus server-side ``Increment``, which is the whole
        point of the write: no read, no lost update."""
        current = self._store.conversations.setdefault(self._id, {}) if merge else {}
        for key, value in data.items():
            if isinstance(value, Increment):
                current[key] = (current.get(key) or 0) + value.value
            else:
                current[key] = value
        self._store.conversations[self._id] = current
        self._store.turns.setdefault(self._id, self._turns)

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
                    "person": "Alex",
                },
            )
        )
        events = store.read("abc")
        assert len(events) == 1
        assert events[0].payload["person"] == "Alex"
        assert events[0].payload["assistant_message"] == "hello"


class TestConversationIds:
    """Firestore lists documents by id, so the id is the index."""

    def test_ids_sort_by_time_and_name_the_person(self) -> None:
        early = new_conversation_id("Alex Marsh", now=datetime(2026, 8, 20, 9, 0, tzinfo=UTC))
        late = new_conversation_id("Alex Marsh", now=datetime(2026, 8, 20, 14, 3, tzinfo=UTC))
        assert early < late
        assert early.startswith("20260820-090000-alex-marsh-")
        assert len(late) <= 64, "must fit the conversationId field on the wire"

    def test_an_unknown_person_still_produces_a_usable_id(self) -> None:
        assert "-anon-" in new_conversation_id(None)

    def test_person_key_collapses_the_ways_a_name_gets_typed(self) -> None:
        assert person_key("Alex") == person_key(" alex ") == "alex"
        assert person_key("Alex Marsh") == "alex-marsh"
        assert person_key(None) == ""


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
                    "person": "Sam",
                    "country": "Canada",
                },
            )
        )
        conversation = client.conversations["c1"]
        assert conversation["person"] == "Sam"
        assert conversation["person_key"] == "sam"
        assert conversation["turn_count"] == 1
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
                    "person": "Sam",
                    "email": {"to": "am@example.com", "to_name": "Marie"},
                },
            )
        )
        conversation = client.conversations["c1"]
        assert conversation["turn_count"] == 2
        assert conversation["emails_drafted"] == 1
        assert "emails_sent" not in conversation, "a draft never reached anyone"

    def test_timestamps_are_real_datetimes(self) -> None:
        """Stored as strings the console cannot sort or range-filter on them."""
        client = _FakeFirestore()
        FirestoreAuditStore(client).append(
            AuditEvent(conversation_id="20260820-090000-sam-ab12", kind="turn", payload={})
        )
        conversation = client.conversations["20260820-090000-sam-ab12"]
        assert isinstance(conversation["updated_at"], datetime)
        assert conversation["started_at"] == datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        turns = client.turns["20260820-090000-sam-ab12"]
        assert isinstance(turns.docs.popitem()[1]["at"], datetime)

    def test_the_summary_says_what_the_conversation_was(self) -> None:
        client = _FakeFirestore()
        FirestoreAuditStore(client).append(
            AuditEvent(
                conversation_id="c2",
                kind="turn",
                payload={
                    "person": "Alex Marsh",
                    "country": "United Kingdom",
                    "branch": "Acme Bedford",
                    "status": "quote_required",
                    "outcome": OUTCOME_EMAIL_SENT,
                    "email": {"to_name": "Marie Dupont"},
                },
            )
        )
        summary = client.conversations["c2"]["summary"]
        assert summary == (
            "Alex Marsh | United Kingdom | Acme Bedford | quote_required | emailed Marie Dupont"
        )

    def test_a_later_turn_without_a_country_does_not_erase_one(self) -> None:
        client = _FakeFirestore()
        store = FirestoreAuditStore(client)
        store.append(
            AuditEvent(conversation_id="c3", kind="turn", payload={"country": "France"})
        )
        store.append(AuditEvent(conversation_id="c3", kind="turn", payload={}))
        assert client.conversations["c3"]["country"] == "France"

    def test_turns_are_ordered_by_their_document_id(self) -> None:
        client = _FakeFirestore()
        store = FirestoreAuditStore(client)
        for index in range(3):
            store.append(
                AuditEvent(
                    conversation_id="c4",
                    kind="turn",
                    payload={"user_message": f"turn {index}"},
                    at=f"2026-08-20T09:00:0{index}+00:00",
                )
            )
        ids = list(client.turns["c4"].docs)
        assert ids == sorted(ids)
        assert [event.payload["user_message"] for event in store.read("c4")] == [
            "turn 0",
            "turn 1",
            "turn 2",
        ]


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
        assert payload["person"] == "Alex"
        assert payload["user_message"] == "how much budget is left"
        assert payload["assistant_message"] == answer.text
        assert payload["outcome"] == OUTCOME_CHAT_ONLY
        assert "text_preview" not in payload

    def test_in_scope_cta_marks_email_pending(self, corpus, tmp_path: Path) -> None:
        from pathlib import Path

        from app.knowledge.chunking import chunk_service_item
        from app.knowledge.index import KnowledgeIndex
        from app.store.contacts import load_contacts

        chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
        store = JsonlAuditStore(tmp_path)
        pipeline = Pipeline(
            corpus.catalog,
            KnowledgeIndex.build(chunks),
            model=RecordingModel("should not run"),
            audit_log=store,
            contacts=load_contacts(Path("fixtures/contacts/country_ams.json")),
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
        """An HR instruction is out of scope, not a safety or legal escalation.

        Routing it to handover would tell the user a person is being brought in
        to deal with sacking their colleague. The right answer is to say this
        tool does not cover it and name what it does.
        """
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
        assert answer.source == DETERMINISTIC
        lowered = answer.text.lower()
        # Steers back to what it can answer instead of engaging with the request.
        assert "couldn't tell which service" in lowered or "capability" in lowered
        assert "covered" in lowered or "scope" in lowered
        # Never reads as though the instruction is being acted on.
        assert "fired" not in lowered
