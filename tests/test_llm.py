"""Model selection: API key or neither.

No network calls. These only assert which backend ``build_model`` chooses.
"""

from __future__ import annotations

from app.core.config import Settings
from app.orchestrator.llm import GeminiClient, build_model


def test_no_credentials_means_no_model() -> None:
    assert build_model(Settings(gemini_api_key="", gcp_project_id="")) is None


def test_gcp_project_does_not_enable_gemini() -> None:
    """Firestore/Sheets project must not imply a Gemini client without an API key."""
    assert build_model(Settings(gemini_api_key="", gcp_project_id="some-project")) is None
    assert not Settings(gemini_api_key="", gcp_project_id="some-project").gemini_configured


def test_api_key_enables_model() -> None:
    model = build_model(Settings(gemini_api_key="test-key", gcp_project_id="some-project"))
    assert isinstance(model, GeminiClient)
    assert model.name == "gemini-2.5-flash"


def test_gemini_configured_requires_api_key() -> None:
    assert Settings(gemini_api_key="k", gcp_project_id="").gemini_configured
    assert not Settings(gemini_api_key="", gcp_project_id="").gemini_configured
    assert not Settings(gemini_api_key="", gcp_project_id="p").gemini_configured


def test_model_name_comes_from_settings() -> None:
    model = build_model(
        Settings(gemini_api_key="k", gemini_chat_model="gemini-2.5-flash")
    )
    assert model is not None
    assert model.name == "gemini-2.5-flash"
