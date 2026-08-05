from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.catalog import CatalogLoadResult, load_catalog
from app.knowledge.manifest import Manifest

DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "documents"


@pytest.fixture(scope="session")
def corpus() -> CatalogLoadResult:
    """The real corpus, loaded once for the whole session."""
    return load_catalog(Manifest.load(DOCUMENTS_DIR))
