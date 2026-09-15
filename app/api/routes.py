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

import hashlib
import hmac
import json
from collections.abc import Iterator

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.pending import open_pending, seal_pending
from app.api.schemas import (
    ActionModel,
    CandidateOption,
    CatalogCategory,
    CatalogItem,
    CatalogResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionRequest,
    SessionResponse,
    StateModel,
    Verdict,
)
from app.api.session import SessionClaims, SessionError, issue_token
from app.core.config import Settings
from app.core.types import Status
from app.knowledge.summary import one_line
from app.orchestrator.history import HistoryTurn
from app.orchestrator.pipeline import (
    Pipeline,
    StreamEnd,
    StreamStart,
    TextPiece,
    pending_from_state,
)
from app.orchestrator.resolver import Outcome, Resolution
from app.orchestrator.router import ConversationState
from app.tools.actions import Action
from app.tools.flows import SessionIdentity

__all__ = ["router"]

logger = structlog.get_logger(__name__)

router = APIRouter()


def _pipeline(request: Request) -> Pipeline:
    """The pipeline built once at startup."""
    pipeline: Pipeline = request.app.state.pipeline
    return pipeline


def _state_from(
    payload: ChatRequest,
    pipeline: Pipeline,
    settings: Settings,
) -> ConversationState:
    """Rebuild internal state, opening the sealed mail action if there is one."""
    if payload.state is None:
        return ConversationState()
    pending = open_pending(
        payload.state.pending_token,
        conversation_id=payload.state.conversation_id,
        secret=settings.session_token_secret,
        ttl_seconds=settings.pending_action_ttl_seconds,
    )
    return payload.state.to_state(pipeline.catalog.item_ids, pending=pending)


def _seal_for(state: ConversationState, settings: Settings) -> str | None:
    """Seal the outgoing pending action, if this turn left one."""
    if not state.pending_action_kind:
        return None
    return seal_pending(
        pending_from_state(state),
        conversation_id=state.conversation_id,
        secret=settings.session_token_secret,
    )


def _verdict_of(resolution: Resolution) -> Verdict | None:
    if resolution.status is None or not resolution.status_meaning:
        return None
    return Verdict(
        status=resolution.status,
        meaning=resolution.status_meaning,
        service=resolution.candidates[0].item.display_name,
    )


def _candidates_of(resolution: Resolution) -> list[dict[str, str]]:
    """Services to choose between when the resolver withheld a verdict."""
    if resolution.outcome is not Outcome.AMBIGUOUS:
        return []
    # Built from the same model the non-streaming route uses, so the two cannot
    # disagree about what an option carries.
    return [
        CandidateOption(
            id=item.item_id, label=item.display_name, summary=one_line(item)
        ).model_dump(by_alias=True, mode="json")
        for item in resolution.items
    ]


def _actions_of(actions: tuple[Action, ...]) -> list[dict[str, str | None]]:
    return [
        ActionModel.from_action(action).model_dump(by_alias=True, mode="json")
        for action in actions
    ]


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Liveness and capability in one response."""
    pipeline = _pipeline(request)
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        services=len(pipeline.catalog),
        chunks=len(pipeline.index),
        index_build=pipeline.index.build_id,
        model=pipeline.model.name if pipeline.model else "deterministic",
        embeddings=pipeline.index.has_embeddings,
        auth_required=settings.session_auth_enabled,
        mail=settings.mail_configured,
        budget=pipeline.budget_store is not None,
        quote=pipeline.quote_store is not None,
        budget_age_seconds=(
            pipeline.budget_store.cache_age_seconds
            if pipeline.budget_store is not None
            else None
        ),
        quote_age_seconds=(
            pipeline.quote_store.cache_age_seconds
            if pipeline.quote_store is not None
            else None
        ),
    )


# Ordered the way an Account Manager needs it: what is covered, what costs
# money, what is theirs already, what we will not do.
_CATALOG_ORDER: tuple[tuple[Status, str], ...] = (
    (Status.IN_SCOPE, "In scope"),
    (Status.QUOTE_REQUIRED, "Quote required"),
    (Status.LOCAL, "Local"),
    (Status.OUT_OF_SCOPE, "Out of scope"),
)


@router.get("/catalog", response_model=CatalogResponse)
def catalog(request: Request) -> CatalogResponse:
    """The service breakdown, for the reference panel.

    Served from the corpus already in memory rather than through a chat turn,
    so opening the list costs no model call and leaves no trace in the
    conversation. Behind the same bearer token as chat: this is the business's
    own account of what it does and does not cover.
    """
    pipeline = _pipeline(request)
    categories = []
    for status, label in _CATALOG_ORDER:
        items = sorted(
            pipeline.catalog.by_status(status), key=lambda i: (i.section, i.item)
        )
        categories.append(
            CatalogCategory(
                status=status,
                label=label,
                count=len(items),
                items=tuple(
                    CatalogItem(
                        id=item.item_id,
                        name=item.item,
                        section=item.section,
                        summary=one_line(item),
                    )
                    for item in items
                ),
            )
        )
    return CatalogResponse(
        categories=tuple(categories), total=len(pipeline.catalog)
    )


@router.post("/session", response_model=SessionResponse)
def create_session(payload: SessionRequest, request: Request) -> SessionResponse | JSONResponse:
    """Mint a bearer token for the internal MVP page."""
    settings: Settings = request.app.state.settings
    if not settings.session_issuance_enabled:
        return JSONResponse(
            status_code=503,
            content={"detail": "Session issuance is not configured."},
        )

    if not _password_matches(payload.password, settings.internal_access_password):
        logger.info("session.bad_password")
        return JSONResponse(status_code=401, content={"detail": "Unauthorised."})

    try:
        token, claims = issue_token(
            secret=settings.session_token_secret,
            subject=payload.subject,
            role=payload.role,
            country=payload.country,
            branch=payload.branch,
            ttl_seconds=settings.session_token_ttl_seconds,
        )
    except SessionError as exc:
        logger.error("session.issue_failed", error=str(exc))
        return JSONResponse(status_code=503, content={"detail": "Could not issue a session."})

    return SessionResponse(
        token=token,
        expires_at=claims.expires_at,
        role=claims.role,
        subject=claims.subject,
        country=claims.country,
        branch=claims.branch,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    pipeline = _pipeline(request)
    settings: Settings = request.app.state.settings
    answer = pipeline.answer(
        payload.message,
        _state_from(payload, pipeline, settings),
        history=payload.history_turns(),
        identity=_session_identity(request),
        note=payload.note,
    )
    return ChatResponse.from_answer(
        answer,
        pending_token=_seal_for(answer.next_state, settings),
    )


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    pipeline = _pipeline(request)
    settings: Settings = request.app.state.settings
    state = _state_from(payload, pipeline, settings)

    return StreamingResponse(
        _events(
            pipeline,
            payload.message,
            state,
            payload.history_turns(),
            identity=_session_identity(request),
            settings=settings,
            note=payload.note,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _session_identity(request: Request) -> SessionIdentity:
    """Claims from a verified session, when auth is on."""
    session = getattr(request.state, "session", None)
    if isinstance(session, SessionClaims):
        return SessionIdentity(
            subject=session.subject,
            role=session.role.value if hasattr(session.role, "value") else str(session.role),
            country=session.country,
            branch=session.branch,
        )
    return SessionIdentity()


def _password_matches(provided: str, expected: str) -> bool:
    """Constant-time compare that tolerates different lengths."""
    return hmac.compare_digest(
        hashlib.sha256(provided.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def _sse(event: str, data: object) -> str:
    """One SSE event. ``text`` fields must be plain strings for the widget."""
    if isinstance(data, dict) and "text" in data and data["text"] is not None:
        text = data["text"]
        data = {**data, "text": text if isinstance(text, str) else str(text)}
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _events(
    pipeline: Pipeline,
    message: str,
    state: ConversationState,
    history: tuple[HistoryTurn, ...] = (),
    *,
    identity: SessionIdentity | None = None,
    settings: Settings,
    note: str | None = None,
) -> Iterator[str]:
    """Server-sent events for one turn."""
    start: StreamStart | None = None
    identity = identity or SessionIdentity()

    for event in pipeline.stream(message, state, history, identity=identity, note=note):
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
                        "candidates": _candidates_of(event.resolution),
                        "actions": _actions_of(event.actions),
                    },
                )

            case TextPiece():
                yield _sse("text", {"text": event.text})

            case StreamEnd():
                final_state = start.next_state if start else ConversationState()
                yield _sse(
                    "done",
                    {
                        "text": event.text,
                        "source": event.source,
                        "degraded": event.degraded,
                        "truncated": event.truncated,
                        "state": StateModel.from_state(
                            final_state,
                            pending_token=_seal_for(final_state, settings),
                        ).model_dump(by_alias=True, mode="json"),
                    },
                )
