"""The ASGI application.

    uvicorn app.main:app --reload

The corpus and index are loaded once, at startup, into application state. On
Cloud Run that cost is paid during container start rather than on somebody's
first question, and both are immutable once built so there is nothing to
refresh per request.

Startup is deliberately intolerant of one thing and tolerant of everything
else. A corpus that will not parse is fatal, because without it there are no
verdicts and the service has nothing truthful to say. A missing index, an
unconfigured model or an unreachable Gemini backend are all survivable: the assistant
answers from the catalog and says so.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import install_security
from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import CatalogError
from app.core.logging import configure_logging
from app.orchestrator.pipeline import Pipeline

WIDGET_DIR = Path("widget")
WIDGET_DIST = WIDGET_DIR / "dist"
WIDGET_ASSETS = WIDGET_DIR / "assets"
WIDGET_INDEX = WIDGET_DIR / "index.html"

__all__ = ["app", "create_app"]

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    configure_logging(level=settings.log_level, json_output=not settings.is_local)

    pipeline = Pipeline.load(settings)
    application.state.pipeline = pipeline

    logger.info(
        "startup",
        environment=settings.environment,
        services=len(pipeline.catalog),
        chunks=len(pipeline.index),
        model=pipeline.model.name if pipeline.model else "deterministic",
        embeddings=pipeline.index.has_embeddings,
        embedder=pipeline.embedder.contract.model if pipeline.embedder else None,
        budget=pipeline.budget_store is not None,
        quote=pipeline.quote_store is not None,
        contacts=len(pipeline.contacts.contacts),
        mail=settings.mail_configured,
        mail_redirect=settings.mail_redirect_to or None,
        origins=settings.origins or "unchecked (local only)",
        auth=settings.session_auth_enabled,
    )
    yield
    logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    application = FastAPI(
        title="Acme Scoping Assistant",
        version="0.1.0",
        summary="Is this marketing request in scope, and what happens next?",
        lifespan=_lifespan,
        # The interactive docs are useful internally and are not something to
        # publish alongside a customer-facing widget.
        docs_url="/docs" if settings.is_local else None,
        redoc_url=None,
    )
    application.state.settings = settings

    # An empty allowlist means same-origin only. Permitting every origin by
    # default would let any site drive this API using a visitor's session.
    if settings.origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.origins),
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Authorization"],
        )

    application.include_router(router, prefix="/api")
    _mount_widget(application)
    install_security(application, settings)
    _install_middleware(application)
    return application


def _mount_widget(application: FastAPI) -> None:
    """Serve the internal chat page and its bundled script.

    Absent files are fine: the API still runs, and a missing widget just means
    the bundle has not been built yet (``npm run build`` in ``widget/``).
    """
    # Before /widget, because routes match in the order they are added and
    # /widget would otherwise swallow every path beneath it.
    if WIDGET_ASSETS.is_dir():
        application.mount(
            "/widget/assets",
            StaticFiles(directory=WIDGET_ASSETS),
            name="widget-brand-assets",
        )

    if WIDGET_DIST.is_dir():
        application.mount(
            "/widget",
            StaticFiles(directory=WIDGET_DIST),
            name="widget-assets",
        )

    if WIDGET_INDEX.is_file():

        @application.get("/", include_in_schema=False)
        def internal_page() -> FileResponse:
            return FileResponse(
                WIDGET_INDEX,
                headers={"Cache-Control": "no-store"},
            )


def _install_middleware(application: FastAPI) -> None:
    @application.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()

        # Bound to the context so every log line in this request carries it,
        # including ones written deep in the pipeline.
        structlog.contextvars.bind_contextvars(
            path=request.url.path, method=request.method
        )
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request.failed", elapsed_ms=_elapsed(started))
            raise
        finally:
            structlog.contextvars.unbind_contextvars("path", "method")

        # Health checks run constantly and would drown everything else.
        if request.url.path != "/api/health":
            logger.info(
                "request",
                status=response.status_code,
                elapsed_ms=_elapsed(started),
            )
        return response

    @application.exception_handler(CatalogError)
    async def catalog_error(_request: Request, exc: CatalogError) -> JSONResponse:
        logger.error("catalog.error", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"detail": "The service breakdown could not be read."},
        )


def _elapsed(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


app = create_app()
