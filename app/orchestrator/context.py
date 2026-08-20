"""The always-on instructions the model is given.

This module used to assemble the whole prompt — a verdict block, trimmed
evidence and citations. That job moved to :meth:`app.orchestrator.facts.FactPack.briefing`
when turns became plan-execute-compose, and the two assemblies drifting apart
was a real hazard: only one of them was on the live path, and it was not the one
with the tests. What is left here is the piece that never moved, loading the
system instruction from disk.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import structlog

from app.core.errors import CatalogError
from app.core.types import DocType
from app.knowledge.manifest import Manifest

__all__ = ["load_system_prompt"]

logger = structlog.get_logger(__name__)

DEFAULT_PROMPT_PATH = Path("prompts/system.md")
DEFAULT_DOCUMENTS_DIR = Path("documents")


@lru_cache(maxsize=1)
def load_system_prompt(
    path: Path = DEFAULT_PROMPT_PATH,
    documents_dir: Path = DEFAULT_DOCUMENTS_DIR,
) -> str:
    """Read the always-on instructions, plus any meta corpus documents.

    ``prompts/system.md`` holds the rules. Meta documents (tone of voice, and
    later anything else that should shape wording but never be cited as
    evidence) are appended so marketing can edit the brand voice without
    touching the safety rules.
    """
    try:
        base = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        # Falling back to nothing would leave a model with no instructions at
        # all, which is far more dangerous than refusing to answer.
        logger.error("prompt.unreadable", path=str(path), error=str(exc))
        raise

    extras = _load_meta_documents(documents_dir)
    if not extras:
        return base
    return f"{base}\n\n---\n\n{extras}"


def _load_meta_documents(documents_dir: Path) -> str:
    try:
        manifest = Manifest.load(documents_dir)
    except (CatalogError, OSError, ValueError) as exc:
        logger.warning("prompt.meta_unavailable", error=str(exc))
        return ""

    sections: list[str] = []
    for entry in manifest.of_type(DocType.META):
        path = entry.path_in(documents_dir)
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("prompt.meta_unreadable", path=str(path), error=str(exc))
            continue
        if text:
            sections.append(f"# Brand reference — {entry.file}\n\n{text}")

    return "\n\n".join(sections)
