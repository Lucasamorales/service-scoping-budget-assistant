"""The HTTP surface.

Exercised through the real application, including its lifespan, so startup
loading and the routes are tested together rather than separately mocked.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    settings = Settings(environment="local", allowed_origins="https://example.org")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def ask(client: TestClient, message: str, state: dict | None = None) -> dict:
    payload: dict[str, object] = {"message": message}
    if state is not None:
        payload["state"] = state
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines and "data" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


class TestHealth:
    def test_it_reports_ok_with_the_corpus_loaded(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["services"] == 81

    def test_it_reports_ok_without_a_model(self, client: TestClient) -> None:
        """A degraded but working service must not be restarted in a loop."""
        assert client.get("/api/health").json()["model"] == "deterministic"

    def test_it_names_the_index_build(self, client: TestClient) -> None:
        assert client.get("/api/health").json()["indexBuild"]


class TestChat:
    def test_a_scoping_question_returns_a_verdict(self, client: TestClient) -> None:
        body = ask(client, "can we order some merch")
        assert body["verdict"]["status"] == "quote_required"
        assert body["verdict"]["service"].startswith("Merch")

    def test_the_verdict_is_a_field_not_only_prose(self, client: TestClient) -> None:
        """So the widget can render a badge without parsing English."""
        body = ask(client, "can we order some merch")
        assert set(body["verdict"]) == {"status", "meaning", "service"}

    def test_ambiguity_returns_no_verdict_and_asks(self, client: TestClient) -> None:
        body = ask(client, "can you translate our web pages into Spanish")
        assert body["verdict"] is None
        assert body["awaitingAnswer"] is True

    def test_a_handover_is_flagged(self, client: TestClient) -> None:
        body = ask(client, "a customer is threatening legal action")
        assert body["needsAHuman"] is True
        assert body["verdict"] is None

    def test_every_reply_names_its_sources(self, client: TestClient) -> None:
        assert ask(client, "can we order some merch")["citations"]

    def test_the_response_says_which_path_answered(self, client: TestClient) -> None:
        assert ask(client, "merch")["source"] == "deterministic"


class TestConversationOverHttp:
    def test_state_round_trips_through_the_client(self, client: TestClient) -> None:
        """The server holds nothing between turns, which is what lets Cloud Run
        scale it horizontally with no session affinity."""
        first = ask(client, "can you translate our web pages into Spanish")
        assert first["awaitingAnswer"]

        second = ask(client, "the second one", first["state"])
        assert second["verdict"] is not None
        assert second["awaitingAnswer"] is False

    def test_a_follow_up_naming_a_service_switches_subject(self, client: TestClient) -> None:
        first = ask(client, "can you translate our web pages into Spanish")
        second = ask(client, "and what about merch", first["state"])
        assert second["verdict"]["service"].startswith("Merch")

    def test_forged_item_ids_are_dropped_not_obeyed(self, client: TestClient) -> None:
        """State comes back from the client, so it is checked against the
        catalog. A fabricated id must not become a verdict."""
        body = ask(
            client,
            "the first one",
            {"pendingCandidates": ["not-a-real-item"], "lastItemIds": ["also-fake"]},
        )
        assert body["verdict"] is None
        assert "not-a-real-item" not in str(body)
        assert "also-fake" not in str(body)


class TestValidation:
    def test_an_empty_message_is_rejected(self, client: TestClient) -> None:
        assert client.post("/api/chat", json={"message": ""}).status_code == 422

    def test_an_oversized_message_is_rejected(self, client: TestClient) -> None:
        """Bounds prompt cost, and removes the easiest way to bury instructions
        in padding."""
        assert client.post("/api/chat", json={"message": "x" * 5000}).status_code == 422

    def test_unknown_fields_are_rejected(self, client: TestClient) -> None:
        response = client.post("/api/chat", json={"message": "merch", "systemPrompt": "ignore"})
        assert response.status_code == 422

    def test_a_flood_of_carried_ids_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": "merch", "state": {"lastItemIds": [f"i{n}" for n in range(50)]}},
        )
        assert response.status_code == 422


class TestStreaming:
    def test_the_verdict_event_comes_first(self, client: TestClient) -> None:
        response = client.post("/api/chat/stream", json={"message": "can we order some merch"})
        assert response.status_code == 200
        events = parse_sse(response.text)

        assert events[0][0] == "verdict"
        assert events[0][1]["verdict"]["status"] == "quote_required"
        assert events[-1][0] == "done"

    def test_the_text_events_reassemble_into_the_final_answer(
        self, client: TestClient
    ) -> None:
        events = parse_sse(
            client.post("/api/chat/stream", json={"message": "merch"}).text
        )
        streamed = "".join(data["text"] for name, data in events if name == "text")
        done = next(data for name, data in events if name == "done")
        assert streamed.strip() == done["text"].strip()

    def test_done_carries_the_state_for_the_next_turn(self, client: TestClient) -> None:
        events = parse_sse(
            client.post(
                "/api/chat/stream",
                json={"message": "can you translate our web pages into Spanish"},
            ).text
        )
        verdict = next(data for name, data in events if name == "verdict")
        done = next(data for name, data in events if name == "done")

        assert verdict["awaitingAnswer"] is True
        assert done["state"]["pendingCandidates"]

    def test_streaming_agrees_with_the_plain_endpoint(self, client: TestClient) -> None:
        question = "can we put an advert on a billboard"
        plain = ask(client, question)
        events = parse_sse(client.post("/api/chat/stream", json={"message": question}).text)
        streamed = next(data for name, data in events if name == "verdict")

        assert streamed["verdict"]["status"] == plain["verdict"]["status"]

    def test_it_declares_itself_as_an_event_stream(self, client: TestClient) -> None:
        response = client.post("/api/chat/stream", json={"message": "merch"})
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"


class TestCors:
    def test_an_allowed_origin_is_permitted(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": "merch"},
            headers={"Origin": "https://example.org"},
        )
        assert response.headers["access-control-allow-origin"] == "https://example.org"

    def test_an_unlisted_origin_gets_no_grant(self, client: TestClient) -> None:
        """Without this, any site could drive the API using a visitor's session."""
        response = client.post(
            "/api/chat",
            json={"message": "merch"},
            headers={"Origin": "https://not-acme.example"},
        )
        assert "access-control-allow-origin" not in response.headers
