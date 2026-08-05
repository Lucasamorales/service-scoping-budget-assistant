"""HTTP endpoints.

Two ways to ask the same question. ``/chat`` returns the finished answer;
``/chat/stream`` sends it as it is produced. They share every decision
underneath, so a verdict cannot differ between them.

The streaming route sends the verdict *before* any prose. The scope decision is
settled before generation begins - it is a dictionary lookup, not a completion
- so the widget can render the badge immediately, and a connection that drops
mid-answer has still delivered the part that carries the consequences.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest, ChatResponse, HealthResponse, StateModel, Verdict
from app.orchestrator.pipeline import Pipeline, StreamEnd, StreamStart, TextPiece
from app.orchestrator.resolver import Resolution
from app.orchestrator.router import ConversationState

__all__ = ["router"]

logger = structlog.get_logger(__name__)

router = APIRouter()


def _pipeline(request: Request) -> Pipeline:
    """The pipeline built once at startup.

    Loading the corpus and index per request would add tens of milliseconds
    and pointless allocation; both are immutable once built.
    """
    pipeline: Pipeline = request.app.state.pipeline
    return pipeline


def _state_from(payload: ChatRequest, pipeline: Pipeline) -> ConversationState:
    if payload.state is None:
        return ConversationState()
    return payload.state.to_state(pipeline.catalog.item_ids)


def _verdict_of(resolution: Resolution) -> Verdict | None:
    if resolution.status is None or not resolution.status_meaning:
        return None
    return Verdict(
        status=resolution.status,
        meaning=resolution.status_meaning,
        service=resolution.candidates[0].item.display_name,
    )


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Liveness and capability in one response.

    Reports ``ok`` without a model or an index, because the assistant answers
    correctly in both cases. Restarting a degraded-but-working service would
    turn a reduced capability into an outage.
    """
    pipeline = _pipeline(request)
    return HealthResponse(
        status="ok",
        services=len(pipeline.catalog),
        chunks=len(pipeline.index),
        index_build=pipeline.index.build_id,
        model=pipeline.model.name if pipeline.model else "deterministic",
        embeddings=pipeline.index.has_embeddings,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    pipeline = _pipeline(request)
    answer = pipeline.answer(payload.message, _state_from(payload, pipeline))
    return ChatResponse.from_answer(answer)


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    pipeline = _pipeline(request)
    state = _state_from(payload, pipeline)

    return StreamingResponse(
        _events(pipeline, payload.message, state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and several proxies buffer streamed responses by default,
            # delivering the whole answer at once and defeating the point.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _events(pipeline: Pipeline, message: str, state: ConversationState) -> Iterator[str]:
    """Server-sent events for one turn.

    Ordered so the client learns the decision first and the wording second:
    one ``verdict``, then any number of ``text``, then exactly one ``done``.
    ``done`` always arrives, including after a failure, so a client can rely on
    it rather than on the connection closing.
    """
    start: StreamStart | None = None

    for event in pipeline.stream(message, state):
        match event:
            case StreamStart():
                start = event
                verdict = _verdict_of(event.resolution)
                yield _sse(
                    "verdict",
                    {
                        "verdict": verdict.model_dump(by_alias=True, mode="json")
                        if verdict
                        else None,
                        "citations": list(event.citations),
                        "notes": list(event.notes),
                        "needsAHuman": event.route.needs_a_human,
                        "awaitingAnswer": event.awaiting_answer,
                    },
                )

            case TextPiece():
                yield _sse("text", {"text": event.text})

            case StreamEnd():
                yield _sse(
                    "done",
                    {
                        "text": event.text,
                        "source": event.source,
                        "degraded": event.degraded,
                        "truncated": event.truncated,
                        "state": StateModel.from_state(
                            start.next_state if start else ConversationState()
                        ).model_dump(by_alias=True, mode="json"),
                    },
                )
