"""Catalog list answers use the loaded corpus, not random retrieval."""

from __future__ import annotations

from app.core.config import Settings
from app.orchestrator.llm import DETERMINISTIC
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.router import Intent, Router
from app.tools.catalog import list_services, wants_service_list


class TestRouterCatalogList:
    def test_list_phrases_are_capabilities(self) -> None:
        router = Router()
        for message in (
            "what are our services?",
            "please list the services",
            "give me a list of services",
            "list of services",
            "show me the service catalogue",
            "what services do you offer",
            "what do we have as an on demand services?",
            "on demand services",
        ):
            assert router.route(message).intent is Intent.CAPABILITIES, message


class TestListServices:
    def test_lists_real_catalog_items(self, corpus) -> None:
        text = list_services(corpus.catalog)
        assert "Merch" in text
        assert "Events" in text
        assert "in scope" in text
        assert "on demand" in text
        assert "not a guess" not in text.lower()
        assert "catalog" not in text.lower()

    def test_can_filter_by_section(self, corpus) -> None:
        text = list_services(corpus.catalog, "list services in Events")
        assert "**Events**" in text
        assert "Presentations" in text
        assert "**Photography**" not in text


class TestPipelineCatalogList:
    def test_list_does_not_resolve_a_random_service(self) -> None:
        pipeline = Pipeline.load(Settings(gemini_api_key="", gcp_project_id=""))
        answer = pipeline.answer("please list the services")
        assert answer.route.intent is Intent.CAPABILITIES
        assert answer.source == DETERMINISTIC
        assert answer.status is None
        assert not answer.actions
        assert "Merch" in answer.text
        assert "not a guess" not in answer.text.lower()

    def test_give_me_a_list_of_services(self) -> None:
        pipeline = Pipeline.load(Settings(gemini_api_key="", gcp_project_id=""))
        answer = pipeline.answer("give me a list of services")
        assert answer.route.intent is Intent.CAPABILITIES
        assert answer.status is None
        assert not answer.actions
        assert "Merch" in answer.text
        assert "Database clean-up" not in answer.text or answer.text.count("\n") > 5
        assert "ping my AM" not in answer.text.lower()
        assert "free of charge" not in answer.text.lower()


    def test_on_demand_filter(self) -> None:
        pipeline = Pipeline.load(Settings(gemini_api_key="", gcp_project_id=""))
        answer = pipeline.answer("what do we have as an on demand services?")
        assert answer.route.intent is Intent.CAPABILITIES
        assert answer.status is None
        assert "On demand" in answer.text or "on demand" in answer.text.lower()
        assert "Merch" in answer.text
        assert "[object Object]" not in answer.text
        # In-scope-only items should not appear as the whole answer shape
        assert "free of charge" not in answer.text.lower()
