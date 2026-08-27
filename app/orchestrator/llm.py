"""The language model, behind a seam narrow enough to do without.

Gemini receives a prompt and returns prose. It is never asked to decide a
verdict, choose a service, or judge whether something is in scope - those are
settled before it is called, and the prompt hands it the conclusion. Its job is
wording.

Access is via the Gemini Developer API (``GEMINI_API_KEY``). No GCP project is
required for chat.

Failure is raised, not returned. :class:`ModelUnavailableError` is the single
signal for "this model produced nothing", and the caller answers from
:mod:`app.orchestrator.composer` instead. Raising rather than returning a
sentinel matters for streaming: a generator that fails halfway through has
already emitted text, and the caller has to be able to tell that apart from a
generator that ended normally.

An empty completion is *not* an error here. It is a successful call with
useless output, which the pipeline handles separately, because safety filters
and token exhaustion both produce one and they deserve different logs.

The SDK is imported inside the client rather than at module scope so the whole
application stays importable without the ``cloud`` extra installed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.core.config import Settings

__all__ = [
    "DETERMINISTIC",
    "GeminiClient",
    "LanguageModel",
    "ModelReply",
    "ModelUnavailableError",
    "build_model",
]

logger = structlog.get_logger(__name__)

DETERMINISTIC = "deterministic"


class ModelUnavailableError(RuntimeError):
    """The model could not be reached, or failed while answering."""


@dataclass(frozen=True, slots=True)
class ModelReply:
    text: str
    model: str


def json_object(raw: str) -> dict[str, Any] | None:
    """Read the JSON object out of a reply, fenced or not.

    Lenient on purpose. Models wrap JSON in code fences, prefix it with a
    sentence, or add a trailing note, and none of that is a reason to throw a
    turn away. What it will not do is guess: anything that does not parse
    returns ``None``, and the caller falls back to wording it did not have to
    trust.
    """
    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class LanguageModel(Protocol):
    """Prompt in, prose out. Nothing else crosses this boundary."""

    @property
    def name(self) -> str: ...

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply: ...

    def stream(self, prompt: str, *, system_instruction: str | None = None) -> Iterator[str]: ...


class GeminiClient:
    """Gemini via the Developer API (API key).

    Connected lazily, so an unreachable or misconfigured backend does not stop
    the service starting and answering from the catalog.

    Every SDK call is wrapped in a bare ``except Exception``, deliberately. The
    client raises transport errors, quota errors, authentication errors and
    safety refusals as unrelated types across several packages, and the caller
    treats all of them identically: fall back to the composer. Enumerating them
    would mean a new SDK version could crash a turn that should have degraded.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._unavailable: str | None = None

    @property
    def name(self) -> str:
        return self._settings.gemini_chat_model

    def _config(self, system_instruction: str | None) -> dict[str, Any]:
        # Gemini 2.5 Flash spends thinking tokens against max_output_tokens by
        # default. For short chat wording that eats the whole budget and cuts
        # the visible answer mid-sentence — so thinking stays off here.
        config: dict[str, Any] = {
            "temperature": self._settings.temperature,
            "max_output_tokens": self._settings.max_output_tokens,
            "thinking_config": {"thinking_budget": 0},
        }
        if system_instruction:
            config["system_instruction"] = system_instruction
        return config

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        if self._unavailable is not None:
            # Remembered, so a broken configuration costs one attempt rather
            # than one per turn for the life of the container.
            raise ModelUnavailableError(self._unavailable)

        try:
            from google import genai
        except ImportError as exc:
            self._unavailable = "google-genai is not installed; install the 'cloud' extra"
            logger.warning("llm.sdk_missing", detail=self._unavailable)
            raise ModelUnavailableError(self._unavailable) from exc

        try:
            self._client = genai.Client(api_key=self._settings.gemini_api_key)
        except Exception as exc:
            self._unavailable = str(exc)
            logger.error("llm.connect_failed", error=self._unavailable)
            raise ModelUnavailableError(self._unavailable) from exc

        logger.info("llm.connected", model=self.name)
        return self._client

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> ModelReply:
        client = self._connect()
        try:
            response = client.models.generate_content(
                model=self.name,
                contents=prompt,
                config=self._config(system_instruction),
            )
        except Exception as exc:
            logger.error("llm.generate_failed", model=self.name, error=str(exc))
            raise ModelUnavailableError(str(exc)) from exc

        return ModelReply(getattr(response, "text", "") or "", self.name)

    def stream(self, prompt: str, *, system_instruction: str | None = None) -> Iterator[str]:
        client = self._connect()
        try:
            for chunk in client.models.generate_content_stream(
                model=self.name,
                contents=prompt,
                config=self._config(system_instruction),
            ):
                text = getattr(chunk, "text", None)
                if isinstance(text, str) and text:
                    yield text
                elif text:
                    # SDK occasionally surfaces non-str parts; never yield objects.
                    yield str(text)
        except Exception as exc:
            logger.error("llm.stream_failed", model=self.name, error=str(exc))
            raise ModelUnavailableError(str(exc)) from exc


def build_model(settings: Settings) -> LanguageModel | None:
    """Return a model if ``GEMINI_API_KEY`` is set, otherwise ``None``.

    ``None`` is a supported state, not an error. The assistant answers from the
    catalog either way; the model only changes how the answer reads.
    """
    if settings.gemini_api_key_configured:
        logger.info("llm.using_api_key", model=settings.gemini_chat_model)
        return GeminiClient(settings)

    logger.info(
        "llm.not_configured",
        detail="no GEMINI_API_KEY; answering deterministically",
    )
    return None
