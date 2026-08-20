"""Semantic inventory intent — paraphrase without phrase lists."""

from __future__ import annotations

from app.orchestrator.intent_semantics import InventoryIntentDetector
from app.orchestrator.router import Intent, Router
from app.tools.catalog import wants_service_list


class _FixedEmbedder:
    """Maps inventory-ish text near (1,0), scoping-ish near (0,1)."""

    def embed_query(self, text: str) -> tuple[float, ...] | None:
        lower = text.lower()
        inventory_hits = (
            "list",
            "catalogue",
            "catalog",
            "offerings",
            "inventory",
            "breakdown",
            "everything you cover",
            "what do you cover",
            "services we offer",
            "services does central",
            "full catalogue",
            "on demand versus",
            "what work can you do",
        )
        scoping_hits = (
            "can we do",
            "is database",
            "billboard",
            "photoshoot",
            "merch for",
            "included in scope",
            "local or central",
        )
        if any(h in lower for h in inventory_hits):
            return (1.0, 0.0)
        if any(h in lower for h in scoping_hits):
            return (0.0, 1.0)
        # Unknown paraphrase of inventory for the test below.
        if "dump everything" in lower or "menu of work" in lower:
            return (0.92, 0.08)
        return (0.5, 0.5)


def test_semantic_catches_paraphrase_regex_misses() -> None:
    detector = InventoryIntentDetector(_FixedEmbedder(), min_score=0.5, margin=0.05)
    phrase = "dump everything you handle for marketing"
    assert not wants_service_list(phrase)
    assert detector.looks_like_inventory(phrase)


def test_semantic_does_not_steal_scoping() -> None:
    detector = InventoryIntentDetector(_FixedEmbedder(), min_score=0.5, margin=0.05)
    assert not detector.looks_like_inventory("can we do merch for the new branch")


def test_router_uses_semantic_detector() -> None:
    router = Router(inventory_detector=InventoryIntentDetector(_FixedEmbedder()))
    route = router.route("dump everything you handle for marketing")
    assert route.intent is Intent.CAPABILITIES
    assert "semantic" in (route.matched or "")
