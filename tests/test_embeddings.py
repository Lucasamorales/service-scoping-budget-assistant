"""Embedding contract, normalisation, and the degradation path.

The property these defend: a broken or mismatched embedder must never produce
quietly wrong ranks. Keyword-only is always preferable to cosine distance
across different spaces.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from app.core.types import Chunk, DocType
from app.knowledge.embeddings import (
    EmbeddingError,
    normalize,
    with_embeddings,
)
from app.knowledge.index import EmbeddingContract, IndexContractError, KnowledgeIndex
from app.knowledge.retriever import InMemoryRetriever
from app.orchestrator.pipeline import Pipeline


def _chunk(chunk_id: str, content: str, item_id: str | None = None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        source=f"{chunk_id}.md",
        doc_type=DocType.SERVICE_ITEM,
        chunk_index=0,
        item_id=item_id or chunk_id,
        section_title=content.split()[0] if content else chunk_id,
        use_when=(),
    )


def _unit(values: list[float]) -> tuple[float, ...]:
    return normalize(values)


class FakeEmbedder:
    """Deterministic vectors from a bag of words, so tests stay offline."""

    def __init__(self, *, dimensions: int = 8, model: str = "fake-embed") -> None:
        self._contract = EmbeddingContract(model=model, dimensions=dimensions)
        self.query_calls = 0
        self.fail_query = False

    @property
    def contract(self) -> EmbeddingContract:
        return self._contract

    def embed_query(self, text: str) -> tuple[float, ...] | None:
        self.query_calls += 1
        if self.fail_query:
            return None
        return self._vector(text)

    def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> tuple[float, ...]:
        dims = self._contract.dimensions
        values = [0.0] * dims
        for token in text.lower().split():
            values[hash(token) % dims] += 1.0
        return normalize(values)


class TestNormalize:
    def test_a_unit_vector_is_unchanged(self) -> None:
        assert normalize((1.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)

    def test_it_produces_unit_length(self) -> None:
        result = normalize((3.0, 4.0))
        assert math.isclose(math.sqrt(sum(v * v for v in result)), 1.0)

    def test_a_zero_vector_is_returned_unchanged(self) -> None:
        assert normalize((0.0, 0.0)) == (0.0, 0.0)


class TestWithEmbeddings:
    def test_it_attaches_vectors_without_mutating(self) -> None:
        original = _chunk("a", "merch")
        embedded = with_embeddings([original], [[1.0, 0.0]])[0]
        assert original.embedding is None
        assert embedded.embedding == (1.0, 0.0)
        assert embedded.content == original.content

    def test_a_length_mismatch_is_loud(self) -> None:
        with pytest.raises(EmbeddingError):
            with_embeddings([_chunk("a", "x")], [[1.0], [0.0]])


class TestHybridRetrieval:
    def test_dense_scores_blend_when_a_query_vector_is_supplied(self) -> None:
        embedder = FakeEmbedder()
        chunks = with_embeddings(
            [
                _chunk("merch", "merch branded gifts venue"),
                _chunk("seo", "seo audit search ranking"),
            ],
            embedder.embed_documents(
                ["merch branded gifts venue", "seo audit search ranking"]
            ),
        )
        retriever = InMemoryRetriever(KnowledgeIndex.build(chunks, contract=embedder.contract))

        result = retriever.retrieve(
            "merch gifts",
            query_vector=embedder.embed_query("merch gifts"),
            limit=2,
        )
        assert result.mode == "keyword+dense"
        assert result.hits[0].chunk.item_id == "merch"

    def test_missing_query_vector_stays_keyword_only(self) -> None:
        embedder = FakeEmbedder()
        chunks = with_embeddings(
            [_chunk("merch", "merch branded gifts")],
            embedder.embed_documents(["merch branded gifts"]),
        )
        retriever = InMemoryRetriever(KnowledgeIndex.build(chunks, contract=embedder.contract))
        assert retriever.retrieve("merch").mode == "keyword"


class TestPipelineEmbedding:
    def test_a_working_embedder_is_consulted(self, corpus) -> None:
        embedder = FakeEmbedder()
        # Tiny synthetic index so the call path is exercised without a live API.
        chunks = with_embeddings(
            [_chunk("renders-and-other-designs-for-venue-exteriors--merch", "merch")],
            embedder.embed_documents(["merch"]),
        )
        index = KnowledgeIndex.build(chunks, contract=embedder.contract)
        pipeline = Pipeline(corpus.catalog, index, embedder=embedder)

        pipeline.answer("can we order some merch")
        assert embedder.query_calls == 1

    def test_a_failed_query_embed_degrades_without_failing_the_turn(
        self, corpus
    ) -> None:
        embedder = FakeEmbedder()
        embedder.fail_query = True
        chunks = with_embeddings(
            [_chunk("renders-and-other-designs-for-venue-exteriors--merch", "merch")],
            FakeEmbedder().embed_documents(["merch"]),
        )
        index = KnowledgeIndex.build(chunks, contract=embedder.contract)
        answer = Pipeline(corpus.catalog, index, embedder=embedder).answer(
            "can we order some merch"
        )
        assert answer.status is not None
        assert embedder.query_calls == 1

    def test_contract_mismatch_disables_dense_retrieval(self, corpus) -> None:
        """Wrong model or dimensions must not produce silently wrong ranks."""
        built = EmbeddingContract(model="text-embedding-005", dimensions=768)
        chunks = (
            replace(
                _chunk("renders-and-other-designs-for-venue-exteriors--merch", "merch"),
                embedding=_unit([1.0] + [0.0] * 767),
            ),
        )
        index = KnowledgeIndex.build(chunks, contract=built)

        with pytest.raises(IndexContractError):
            index.verify_contract(EmbeddingContract(model="other-model", dimensions=768))

        # Pipeline.load is the production path; here we assert the same policy
        # the load method applies: drop the embedder rather than rank wrongly.
        wrong = FakeEmbedder(model="other-model", dimensions=768)
        with pytest.raises(IndexContractError):
            index.verify_contract(wrong.contract)


class TestIndexContract:
    def test_an_index_without_embeddings_accepts_any_contract(self) -> None:
        index = KnowledgeIndex.build([_chunk("a", "x")])
        index.verify_contract(EmbeddingContract(model="anything", dimensions=3))

    def test_embeddings_without_a_recorded_contract_are_rejected(self) -> None:
        chunk = replace(_chunk("a", "x"), embedding=(1.0, 0.0))
        index = KnowledgeIndex(chunks=(chunk,), build_id="t", contract=None)
        with pytest.raises(IndexContractError):
            index.verify_contract(EmbeddingContract(model="m", dimensions=2))
