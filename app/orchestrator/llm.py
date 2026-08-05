"""The language model, behind a seam narrow enough to do without.

Gemini receives a prompt and returns prose. It is never asked to decide a
verdict, choose a service, or judge whether something is in scope - those are
settled before it is called, and the prompt hands it the conclusion. Its job is
wording.

That keeps this module small and its failure modes cheap. Every error path here
returns rather than raises, and the caller falls back to
:mod:`app.orchestrator.composer`, which answers correctly from the same facts
without a model. A timeout costs polish, not correctness.

The SDK is imported inside the client rather than at module scope so the whole
application stays importable without the ``cloud`` extra installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.core.config import Settings

__all__ = ["LanguageModel", "ModelReply", "VertexGemini", "build_model"]

logger = structlog.get_logger(__name__)

DETERMINISTIC = "deterministic"

REQUEST_TIMEOUT_SECONDS = 20
"""Past this, a person waiting on a scoping answer is better served by the
terse deterministic reply than by a slow polished one."""


@dataclass(frozen=True, slots=True)
class ModelReply:
    """What the model produced, and whether it really produced it."""

    text: str
    model: str
    degraded: bool = False
    """True when the model could not be reached and the text came from
    elsewhere. Surfaced to the caller so a quiet outage is visible rather than
    being mistaken for a terse day."""

    error: str | None = None


class LanguageModel(Protocol):
    """Prompt in, prose out. Nothing else crosses this boundary."""

    @property
    def name(self) -> str: ...

    def generate(self, prompt: str) -> ModelReply: ...


class VertexGemini:
    """Gemini on Vertex AI.

    Constructed lazily: the client is not built until the first call, so an
    unreachable or misconfigured Vertex does not prevent the service starting
    and answering from the catalog.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._unavailable: str | None = None

    @property
    def name(self) -> str:
        return self._settings.vertex_chat_model

    def _connect(self) -> Any | None:
        if self._client is not None:
            return self._client
        if self._unavailable is not None:
            return None

        try:
            from google import genai
        except ImportError:
            self._unavailable = "google-genai is not installed; install the 'cloud' extra"
            logger.warning("llm.sdk_missing", detail=self._unavailable)
            return None

        try:
            self._client = genai.Client(
                vertexai=True,
                project=self._settings.gcp_project_id,
                location=self._settings.gcp_region,
            )
        except Exception as exc:  # noqa: BLE001 - the SDK raises many types
            # Remembered, so a broken configuration costs one attempt rather
            # than one per turn for the life of the container.
            self._unavailable = str(exc)
            logger.error("llm.connect_failed", error=self._unavailable)
            return None

        logger.info(
            "llm.connected",
            model=self.name,
            project=self._settings.gcp_project_id,
            region=self._settings.gcp_region,
        )
        return self._client

    def generate(self, prompt: str) -> ModelReply:
        client = self._connect()
        if client is None:
            return ModelReply("", self.name, degraded=True, error=self._unavailable)

        try:
            response = client.models.generate_content(
                model=self.name,
                contents=prompt,
                config={
                    "temperature": self._settings.temperature,
                    "max_output_tokens": self._settings.max_output_tokens,
                },
            )
        except Exception as exc:  # noqa: BLE001 - transport, quota, safety, all opaque
            logger.error("llm.generate_failed", model=self.name, error=str(exc))
            return ModelReply("", self.name, degraded=True, error=str(exc))

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            # An empty completion is a real outcome: safety filters and token
            # exhaustion both produce one. Treated as a failure so the caller
            # falls back rather than showing a blank reply.
            logger.warning("llm.empty_response", model=self.name)
            return ModelReply("", self.name, degraded=True, error="empty response")

        return ModelReply(text, self.name)


def build_model(settings: Settings) -> LanguageModel | None:
    """Return a model if one is configured, otherwise ``None``.

    ``None`` is a supported state, not an error. The assistant answers from the
    catalog either way; the model only changes how the answer reads.
    """
    if not settings.vertex_configured:
        logger.info("llm.not_configured", detail="no GCP project set; answering deterministically")
        return None
    return VertexGemini(settings)
