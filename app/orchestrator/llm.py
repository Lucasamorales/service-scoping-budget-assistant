"""The language model, behind a seam narrow enough to do without.

Gemini receives a prompt and returns prose. It is never asked to decide a
verdict, choose a service, or judge whether something is in scope - those are
settled before it is called, and the prompt hands it the conclusion. Its job is
wording.

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

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.core.config import Settings

__all__ = [
    "DETERMINISTIC",
    "LanguageModel",
    "ModelReply",
    "ModelUnavailableError",
    "VertexGemini",
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


class LanguageModel(Protocol):
    """Prompt in, prose out. Nothing else crosses this boundary."""

    @property
    def name(self) -> str: ...

    def generate(self, prompt: str) -> ModelReply: ...

    def stream(self, prompt: str) -> Iterator[str]: ...


class VertexGemini:
    """Gemini on Vertex AI.

    Connected lazily, so an unreachable or misconfigured Vertex does not stop
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
        return self._settings.vertex_chat_model

    @property
    def _config(self) -> dict[str, Any]:
        return {
            "temperature": self._settings.temperature,
            "max_output_tokens": self._settings.max_output_tokens,
        }

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
            self._client = genai.Client(
                vertexai=True,
                project=self._settings.gcp_project_id,
                location=self._settings.gcp_region,
            )
        except Exception as exc:
            self._unavailable = str(exc)
            logger.error("llm.connect_failed", error=self._unavailable)
            raise ModelUnavailableError(self._unavailable) from exc

        logger.info(
            "llm.connected",
            model=self.name,
            project=self._settings.gcp_project_id,
            region=self._settings.gcp_region,
        )
        return self._client

    def generate(self, prompt: str) -> ModelReply:
        client = self._connect()
        try:
            response = client.models.generate_content(
                model=self.name, contents=prompt, config=self._config
            )
        except Exception as exc:
            logger.error("llm.generate_failed", model=self.name, error=str(exc))
            raise ModelUnavailableError(str(exc)) from exc

        return ModelReply(getattr(response, "text", "") or "", self.name)

    def stream(self, prompt: str) -> Iterator[str]:
        client = self._connect()
        try:
            for chunk in client.models.generate_content_stream(
                model=self.name, contents=prompt, config=self._config
            ):
                if text := getattr(chunk, "text", ""):
                    yield text
        except Exception as exc:
            logger.error("llm.stream_failed", model=self.name, error=str(exc))
            raise ModelUnavailableError(str(exc)) from exc


def build_model(settings: Settings) -> LanguageModel | None:
    """Return a model if one is configured, otherwise ``None``.

    ``None`` is a supported state, not an error. The assistant answers from the
    catalog either way; the model only changes how the answer reads.
    """
    if not settings.vertex_configured:
        logger.info("llm.not_configured", detail="no GCP project set; answering deterministically")
        return None
    return VertexGemini(settings)
