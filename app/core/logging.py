"""Logging configuration, chosen by environment.

Locally, readable colour. On Cloud Run, one JSON object per line with the
severity field Cloud Logging expects, so entries arrive parsed and searchable
rather than as a wall of text.

Configured once at startup. Every module calls ``structlog.get_logger`` at
import time and picks this up automatically.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

__all__ = ["configure_logging"]

# Cloud Logging keys off "severity", not "level", and silently treats
# everything as default-level without it.
_SEVERITY: dict[str, str] = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
}


Event = MutableMapping[str, Any]


def _rename_to_severity(_logger: Any, _name: str, event_dict: Event) -> Event:
    level = event_dict.pop("level", "info")
    event_dict["severity"] = _SEVERITY.get(level, "INFO")
    return event_dict


def _to_message(_logger: Any, _name: str, event_dict: Event) -> Event:
    """Cloud Logging shows ``message`` in the summary line; ``event`` it ignores."""
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderers: list[structlog.typing.Processor] = (
        [_rename_to_severity, _to_message, structlog.processors.JSONRenderer()]
        if json_output
        else [structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())]
    )

    structlog.configure(
        processors=[*shared, *renderers],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # uvicorn's own loggers stay on stdlib. Levelled up so its access log does
    # not duplicate what the request middleware already records structurally.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
