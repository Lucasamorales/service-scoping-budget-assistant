"""Invariants of retrieval.

These assert how the retriever behaves, not what today's corpus contains.
Corpus-specific expectations live in ``evals/retrieval.json``, which is scored
rather than asserted, because retrieval quality is a number that moves.
"""

from __future__ import annotations

from app.core.types import Chunk, DocType
from app.knowledge.chunking import chunk_service_item
from app.knowledge.index import KnowledgeIndex
from app.knowledge.retriever import (
    KEYWORD_HALF_CONFIDENCE,
    MIN_SCORE,
    InMemoryRetriever,
    _dense_confidence,
    _keyword_confidence,
)
from app.orchestrator.resolver import MIN_CONFIDENCE


def build_retriever(corpus) -> InMemoryRetriever:
    chunks = [chunk for item in corpus.catalog for chunk in chunk_service_item(item)]
    return InMemoryRetriever(KnowledgeIndex.build(chunks))


class TestDegradedInputs:
    def test_an_empty_index_returns_nothing_and_says_so(self) -> None:
        result = InMemoryRetriever(KnowledgeIndex()).retrieve("billboards")
        assert not result
        assert result.mode == "empty"

    def test_a_query_of_only_stopwords_does_not_crash(self, corpus) -> None:
        result = build_retriever(corpus).retrieve("can we do it")
        assert "query produced no searchable tokens" in result.notes

    def test_an_empty_query_does_not_crash(self, corpus) -> None:
        assert not build_retriever(corpus).retrieve("")

    def test_nonsense_returns_nothing_rather_than_a_weak_guess(self, corpus) -> None:
        """Returning something irrelevant is what pushes a model into inventing
        an answer. Returning nothing lets it say it does not know."""
        assert not build_retriever(corpus).retrieve("xyzzy plugh frobnicate")


class TestScoring:
    def test_results_are_ordered_by_score(self, corpus) -> None:
        hits = build_retriever(corpus).retrieve("paid social media advertising").hits
        assert [hit.score for hit in hits] == sorted(
            (hit.score for hit in hits), reverse=True
        )

    def test_the_limit_is_respected(self, corpus) -> None:
        assert len(build_retriever(corpus).retrieve("marketing", limit=3)) <= 3

    def test_every_hit_clears_the_threshold(self, corpus) -> None:
        for hit in build_retriever(corpus).retrieve("email marketing").hits:
            assert hit.score >= MIN_SCORE

    def test_every_hit_reports_what_matched(self, corpus) -> None:
        """Retrieval you cannot explain is retrieval you cannot debug."""
        for hit in build_retriever(corpus).retrieve("billboards").hits:
            assert hit.matched

    def test_plural_and_singular_reach_the_same_item(self, corpus) -> None:
        retriever = build_retriever(corpus)
        assert (
            retriever.retrieve("billboard").item_ids[0]
            == retriever.retrieve("billboards").item_ids[0]
        )

    def test_a_document_scores_on_its_own_name(self, corpus) -> None:
        assert build_retriever(corpus).retrieve("merch").item_ids[0].endswith("--merch")


class TestForceInclude:
    def test_a_forced_item_is_returned_even_with_an_unrelated_query(self, corpus) -> None:
        """A job cannot be done without the slice it is about, and a similarity
        score is a hope rather than a guarantee."""
        item_id = "photography--billboards"
        result = build_retriever(corpus).retrieve("unrelated nonsense", force_item_ids=[item_id])
        assert item_id in result.item_ids

    def test_a_forced_item_leads_the_results(self, corpus) -> None:
        item_id = "photography--billboards"
        result = build_retriever(corpus).retrieve("email marketing", force_item_ids=[item_id])
        assert result.item_ids[0] == item_id
        assert result.hits[0].forced

    def test_forcing_does_not_push_the_pack_over_its_limit(self, corpus) -> None:
        forced = ["photography--billboards", "photography--hoarding"]
        result = build_retriever(corpus).retrieve("marketing", limit=3, force_item_ids=forced)
        assert len(result) <= 3

    def test_an_unknown_forced_item_is_reported_rather_than_ignored(self, corpus) -> None:
        result = build_retriever(corpus).retrieve("billboards", force_item_ids=["does-not-exist"])
        assert any("does-not-exist" in note for note in result.notes)


class TestProvenance:
    def test_the_mode_is_always_stated(self, corpus) -> None:
        assert build_retriever(corpus).retrieve("billboards").mode == "keyword"

    def test_dense_is_not_claimed_without_embeddings(self, corpus) -> None:
        """The index carries no vectors, so passing one must not change the
        reported mode. Claiming a retrieval path that did not run is worse than
        having no label at all."""
        result = build_retriever(corpus).retrieve("billboards", query_vector=[0.1] * 768)
        assert result.mode == "keyword"

    def test_the_citation_line_names_what_was_read(self, corpus) -> None:
        line = build_retriever(corpus).retrieve("billboards", limit=2).citation_line()
        assert "Read from" in line
        assert "keyword" in line

    def test_the_citation_line_handles_an_empty_result(self, corpus) -> None:
        assert "No supporting documents" in InMemoryRetriever(
            KnowledgeIndex()
        ).retrieve("anything").citation_line()


class TestFiltering:
    def test_results_can_be_restricted_by_document_type(self, corpus) -> None:
        result = build_retriever(corpus).retrieve("billboards", doc_types=[DocType.GLOSSARY])
        assert not result

    def test_meta_chunks_are_never_returned(self) -> None:
        meta = Chunk(
            chunk_id="p:0",
            content="Always be concise about billboards and pricing.",
            source="prompt.md",
            doc_type=DocType.META,
            chunk_index=0,
        )
        assert not InMemoryRetriever(KnowledgeIndex.build([meta])).retrieve("billboards")


def test_item_ids_are_deduplicated_in_order(corpus) -> None:
    result = build_retriever(corpus).retrieve("video editing", limit=5)
    assert len(set(result.item_ids)) == len(result.item_ids)


class TestConfidence:
    """Confidence answers "is this worth acting on at all", and has to mean the
    same thing whether or not embeddings are in the blend. The resolver's
    absolute threshold is read off it, so a scale that drifted between modes
    would silently move that threshold."""

    def test_it_is_bounded(self, corpus) -> None:
        retriever = build_retriever(corpus)
        for query in ("merch", "billboards for the new branch", "xyzzy", ""):
            for hit in retriever.retrieve(query, limit=5).hits:
                assert 0.0 <= hit.confidence <= 1.0, (query, hit.confidence)

    def test_it_rises_with_the_score(self, corpus) -> None:
        """Ranking must survive the rescale: a confidence that reordered hits
        would make the two numbers disagree about which item is best."""
        hits = build_retriever(corpus).retrieve("photoshoot at the new site", limit=5).hits
        by_score = sorted(hits, key=lambda hit: hit.score, reverse=True)
        by_confidence = sorted(hits, key=lambda hit: hit.confidence, reverse=True)
        assert [hit.chunk.item_id for hit in by_score] == [
            hit.chunk.item_id for hit in by_confidence
        ]

    def test_the_half_point_matches_the_resolver_threshold(self) -> None:
        """The guarantee that made this change safe to land.

        ``confidence >= MIN_CONFIDENCE`` accepts exactly the hits the resolver's
        previous raw floor of 1.6 accepted, so introducing the scale changed no
        behaviour in keyword-only mode. Asserted rather than trusted, because
        the two constants live in different modules and nothing else would
        notice them drifting apart.
        """
        assert _keyword_confidence(KEYWORD_HALF_CONFIDENCE) == MIN_CONFIDENCE
        assert _keyword_confidence(KEYWORD_HALF_CONFIDENCE - 0.01) < MIN_CONFIDENCE
        assert _keyword_confidence(KEYWORD_HALF_CONFIDENCE + 0.01) > MIN_CONFIDENCE

    def test_an_unrelated_cosine_is_not_confident(self) -> None:
        """Raw cosine is not a confidence. Measured on this corpus, an item
        with nothing to do with the query still scores about 0.57, which used
        directly would read as 57% sure."""
        assert _dense_confidence(0.57) < 0.2
        assert _dense_confidence(0.641) < MIN_CONFIDENCE  # 95th percentile of irrelevant
        assert _dense_confidence(0.673) > MIN_CONFIDENCE  # 5th percentile of relevant
        assert _dense_confidence(0.730) > 0.75  # median relevant

    def test_dense_confidence_is_clamped(self) -> None:
        assert _dense_confidence(-1.0) == 0.0
        assert _dense_confidence(1.0) == 1.0
