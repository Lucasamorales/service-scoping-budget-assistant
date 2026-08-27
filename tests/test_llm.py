"""Model selection: API key or neither.

No network calls. These only assert which backend ``build_model`` chooses.
"""

from __future__ import annotations

from app.core.config import Settings
from app.orchestrator.llm import (
    GeminiClient,
    ModelReply,
    _usage_of,
    build_model,
)


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


class TestTokenAccounting:
    """Usage is accounting, and accounting must never cost an answer.

    Every reading is defensive for the reason the client's own docstring
    gives: a new SDK version must not be able to crash a turn that would
    otherwise have worked. Anything missing, renamed or oddly typed counts as
    zero rather than raising.
    """

    class _Usage:
        def __init__(self, **fields: object) -> None:
            self.__dict__.update(fields)

    class _Response:
        def __init__(self, usage: object | None) -> None:
            self.usage_metadata = usage

    def test_it_reads_the_current_field_names(self) -> None:
        usage = self._Usage(prompt_token_count=120, candidates_token_count=45)
        assert _usage_of(self._Response(usage)) == (120, 45)

    def test_it_accepts_the_older_spelling(self) -> None:
        """The names have moved between SDK generations. Pinning to whichever
        is current today would silently zero the bill after an upgrade."""
        usage = self._Usage(input_token_count=90, output_token_count=30)
        assert _usage_of(self._Response(usage)) == (90, 30)

    def test_a_response_without_usage_is_free_not_broken(self) -> None:
        assert _usage_of(self._Response(None)) == (0, 0)
        assert _usage_of(object()) == (0, 0)

    def test_unexpected_types_do_not_raise(self) -> None:
        usage = self._Usage(prompt_token_count="lots", candidates_token_count=None)
        assert _usage_of(self._Response(usage)) == (0, 0)

    def test_total_is_the_sum(self) -> None:
        assert ModelReply("hi", "m", prompt_tokens=10, output_tokens=4).total_tokens == 14

    def test_a_reply_defaults_to_uncounted(self) -> None:
        """Zero means "not reported", which is also what the deterministic
        path costs, and nothing downstream needs to tell those apart."""
        assert ModelReply("hi", "m").total_tokens == 0
