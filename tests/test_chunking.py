"""Invariants of chunking and of the index artifact.

The property worth defending above all others: a service item's verdict is
never separated from the text it governs. A chunk describing what billboards
are, with no status attached, invites the model to supply a status of its own.
"""

from __future__ import annotations

import pytest

from app.core.types import AtAGlance, Chunk, DocType, ServiceItem, Status
from app.knowledge.chunking import (
    SERVICE_ITEM_MAX_CHARS,
    chunk_reference_document,
    chunk_service_item,
)
from app.knowledge.index import EmbeddingContract, IndexContractError, KnowledgeIndex
from app.knowledge.preprocess import (
    normalize_markdown,
    preprocess,
    repair_encoding,
    split_at_sentence_boundary,
)

DEFAULT_BODY = "# Billboards\n\n**Section:** Photography\n\n## Summary\nA billboard."


def make_item(*, body: str = "", aliases: tuple[str, ...] = ("poster ads",)) -> ServiceItem:
    return ServiceItem(
        item_id="photography--billboards",
        section="Photography",
        item="Billboards",
        status=Status.QUOTE_REQUIRED,
        status_raw="On demand",
        status_meaning="This is something we need to quote",
        aliases=aliases,
        at_a_glance=AtAGlance(),
        summary="A billboard.",
        sections={"Summary": "A billboard."},
        source="photography--billboards.md",
        body=body or DEFAULT_BODY,
    )


class TestPreprocess:
    def test_mojibake_is_repaired(self) -> None:
        assert repair_encoding("we\u00e2\u0080\u0099ll quote") == "we\u2019ll quote"

    def test_empty_headings_are_removed(self) -> None:
        assert normalize_markdown("## \n\nreal text") == "real text"

    def test_escaped_punctuation_is_unescaped(self) -> None:
        assert normalize_markdown(r"cost \- per \- click") == "cost - per - click"

    def test_windows_line_endings_are_normalised(self) -> None:
        assert "\r" not in normalize_markdown("one\r\ntwo\r\n")

    def test_preprocessing_leaves_a_clean_document_untouched(self) -> None:
        """Today's corpus needs no repair, so preprocessing must be a no-op on
        it. If this ever fails, preprocessing has started changing meaning."""
        clean = "# Billboards \u2014 Photography\n\n## Summary\nA billboard costs money."
        assert preprocess(clean) == clean

    def test_text_within_budget_is_returned_whole(self) -> None:
        assert split_at_sentence_boundary("Short text.", max_chars=100) == ("Short text.",)

    def test_splitting_never_cuts_mid_sentence(self) -> None:
        text = "First sentence here. Second sentence here. Third sentence here."
        pieces = split_at_sentence_boundary(text, max_chars=40)
        assert len(pieces) > 1
        assert all(piece.endswith(".") for piece in pieces)

    def test_an_oversized_sentence_is_emitted_whole_rather_than_truncated(self) -> None:
        """An over-long chunk is recoverable. A chunk missing its ending is not."""
        sentence = "word " * 50
        pieces = split_at_sentence_boundary(sentence.strip(), max_chars=20)
        assert "".join(pieces).replace(" ", "") == sentence.replace(" ", "")


class TestServiceItemChunking:
    def test_a_service_item_becomes_a_single_chunk(self) -> None:
        assert len(chunk_service_item(make_item())) == 1

    def test_the_chunk_carries_its_verdict_in_the_text(self) -> None:
        content = chunk_service_item(make_item())[0].content
        assert "On demand" in content
        assert "This is something we need to quote" in content

    def test_the_chunk_names_its_section_and_item(self) -> None:
        content = chunk_service_item(make_item())[0].content
        assert "Photography" in content
        assert "Billboards" in content

    def test_aliases_travel_with_the_chunk(self) -> None:
        chunk = chunk_service_item(make_item(aliases=("outdoor advertising",)))[0]
        assert "outdoor advertising" in chunk.content
        assert chunk.use_when == ("outdoor advertising",)

    def test_an_item_with_no_aliases_omits_the_hint_line(self) -> None:
        chunk = chunk_service_item(make_item(aliases=()))[0]
        assert "Use when:" not in chunk.content

    def test_the_chunk_links_back_to_the_catalog(self) -> None:
        chunk = chunk_service_item(make_item())[0]
        assert chunk.item_id == "photography--billboards"
        assert chunk.doc_type is DocType.SERVICE_ITEM

    def test_every_piece_of_a_split_item_repeats_the_verdict(self) -> None:
        """The invariant that matters. However a document is divided, no piece
        of it can describe a service without saying what it costs."""
        long_body = "## Summary\n" + "This is a sentence about billboards. " * 200
        chunks = chunk_service_item(make_item(body=long_body))
        assert len(chunks) > 1
        assert all("On demand" in chunk.content for chunk in chunks)
        assert all("Billboards" in chunk.content for chunk in chunks)

    def test_chunk_ids_are_unique_and_ordered(self) -> None:
        long_body = "## Summary\n" + "This is a sentence about billboards. " * 200
        chunks = chunk_service_item(make_item(body=long_body))
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
        assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


class TestReferenceChunking:
    def test_meta_documents_are_never_retrievable(self) -> None:
        """A document that is both instruction and evidence lets the assistant
        cite its own instructions back as proof."""
        text = "## Tone\n" + "Be concise and never invent a price. " * 10
        assert chunk_reference_document(text, "prompt.md", DocType.META) == ()

    def test_headings_become_separate_chunks(self) -> None:
        text = (
            "## Bedford\n" + "The Bedford branch is in the United Kingdom. " * 4 + "\n\n"
            "## Basingstoke\n" + "The Basingstoke branch is also in the UK. " * 4
        )
        chunks = chunk_reference_document(text, "branches.md", DocType.GLOSSARY)
        assert len(chunks) == 2
        assert [chunk.section_title for chunk in chunks] == ["Bedford", "Basingstoke"]

    def test_each_chunk_is_labelled_with_its_source(self) -> None:
        text = "## Bedford\n" + "The Bedford branch is in the United Kingdom. " * 4
        chunk = chunk_reference_document(text, "branches.md", DocType.GLOSSARY)[0]
        assert chunk.content.startswith("[branches.md \u2014 Bedford]")

    def test_fragments_below_the_minimum_are_dropped(self) -> None:
        assert chunk_reference_document("## Empty\ntiny", "x.md", DocType.GLOSSARY) == ()


class TestKnowledgeIndex:
    def test_an_index_survives_a_round_trip(self) -> None:
        chunks = chunk_service_item(make_item())
        restored = KnowledgeIndex.from_json(KnowledgeIndex.build(chunks).to_json())
        assert restored.chunks == chunks

    def test_a_missing_index_loads_as_empty_rather_than_raising(self, tmp_path) -> None:
        """Retrieval degrading is an inconvenience. Failing to start is an outage."""
        index = KnowledgeIndex.load_local(tmp_path / "absent.json")
        assert index.is_empty

    def test_a_corrupt_index_loads_as_empty_rather_than_raising(self, tmp_path) -> None:
        path = tmp_path / "index.json"
        path.write_text("{ not json", encoding="utf-8")
        assert KnowledgeIndex.load_local(path).is_empty

    def test_a_mismatched_embedding_contract_is_fatal(self) -> None:
        """Cosine distance between vectors from different models is meaningless,
        and nothing downstream can detect it. So it has to fail here."""
        chunk = Chunk(
            chunk_id="a:0",
            content="text",
            source="a.md",
            doc_type=DocType.SERVICE_ITEM,
            chunk_index=0,
            embedding=(0.1, 0.2),
        )
        index = KnowledgeIndex.build([chunk], contract=EmbeddingContract("model-a", 2))

        index.verify_contract(EmbeddingContract("model-a", 2))
        with pytest.raises(IndexContractError, match="meaningless"):
            index.verify_contract(EmbeddingContract("model-b", 2))
        with pytest.raises(IndexContractError):
            index.verify_contract(EmbeddingContract("model-a", 768))

    def test_an_index_without_embeddings_needs_no_contract(self) -> None:
        """Keyword-only is a supported mode, not a broken one."""
        index = KnowledgeIndex.build(chunk_service_item(make_item()))
        index.verify_contract(EmbeddingContract("anything", 768))

    def test_meta_chunks_are_excluded_from_retrieval(self) -> None:
        meta = Chunk(
            chunk_id="p:0",
            content="instructions",
            source="prompt.md",
            doc_type=DocType.META,
            chunk_index=0,
        )
        index = KnowledgeIndex.build([meta, *chunk_service_item(make_item())])
        assert len(index) == 2
        assert len(index.retrievable()) == 1


def test_corpus_chunks_stay_within_budget(corpus) -> None:
    """An anchor, not an invariant: it describes today's documents. If it fails
    the corpus has grown, and the split path above is worth reading by eye."""
    for item in corpus.catalog:
        for chunk in chunk_service_item(item):
            assert len(chunk.content) <= SERVICE_ITEM_MAX_CHARS


def test_every_corpus_item_yields_exactly_one_chunk(corpus) -> None:
    assert all(len(chunk_service_item(item)) == 1 for item in corpus.catalog)
