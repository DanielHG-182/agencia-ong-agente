from types import SimpleNamespace

import pytest

import scripts.retriever as retriever


def test_get_collection_returns_existing_collection(monkeypatch):
    expected_collection = object()

    class FakeChromaClient:
        def get_collection(self, name):
            assert name == retriever.settings.chroma_collection_name
            return expected_collection

    monkeypatch.setattr(
        retriever,
        "create_chroma_client",
        lambda chroma_dir: FakeChromaClient(),
    )

    result = retriever.get_collection("vector_db")

    assert result is expected_collection


def test_get_collection_raises_when_collection_missing(monkeypatch):
    class FakeChromaClient:
        def get_collection(self, name):
            raise RuntimeError("missing collection")

    monkeypatch.setattr(
        retriever,
        "create_chroma_client",
        lambda chroma_dir: FakeChromaClient(),
    )

    with pytest.raises(RuntimeError) as exc_info:
        retriever.get_collection("vector_db")

    assert "Run the indexing stage first" in str(exc_info.value)


def test_retrieve_requires_chroma_dir():
    with pytest.raises(ValueError):
        retriever.retrieve("project objectives", chroma_dir=None)


def test_retrieve_transforms_results_and_uses_candidate_pool(monkeypatch):
    captured = {}

    class FakeCollection:
        def query(
            self,
            query_embeddings,
            n_results,
            include,
        ):
            captured["query_embeddings"] = query_embeddings
            captured["n_results"] = n_results
            captured["include"] = include

            return {
                "ids": [["chunk_1", "chunk_2"]],
                "documents": [[
                    "First chunk content",
                    "Second chunk content",
                ]],
                "metadatas": [[
                    {
                        "source_file": "proposal.md",
                        "section_title": "Objectives",
                        "section_level": 2,
                        "parent_section": "Project",
                        "is_continuation": False,
                        "has_table": False,
                    },
                    {
                        "source_file": "proposal.md",
                        "section_title": "Objectives",
                        "section_level": "2",
                        "parent_section": "",
                        "is_continuation": True,
                        "has_table": True,
                    },
                ]],
                "distances": [[0.2, 0.45]],
            }

    fake_embedding_response = SimpleNamespace(
        data=[
            SimpleNamespace(
                embedding=[0.1, 0.2, 0.3]
            )
        ]
    )

    class FakeEmbeddings:
        def create(self, model, input):
            captured["embedding_model"] = model
            captured["embedding_input"] = input
            return fake_embedding_response

    fake_openai_client = SimpleNamespace(
        embeddings=FakeEmbeddings()
    )

    monkeypatch.setattr(
        retriever,
        "get_collection",
        lambda chroma_dir: FakeCollection(),
    )

    monkeypatch.setattr(
        retriever,
        "create_openai_client",
        lambda: fake_openai_client,
    )

    chunks = retriever.retrieve(
        "project objectives",
        top_k=2,
        chroma_dir="vector_db",
    )

    assert captured["embedding_model"] == retriever.settings.embedding_model
    assert captured["embedding_input"] == ["project objectives"]

    assert captured["query_embeddings"] == [[0.1, 0.2, 0.3]]
    assert captured["n_results"] == 8
    assert captured["include"] == [
        "documents",
        "metadatas",
        "distances",
    ]

    assert len(chunks) == 2

    first = chunks[0]

    assert first.chunk_id == "chunk_1"
    assert first.content == "First chunk content"
    assert first.source_file == "proposal.md"
    assert first.section_title == "Objectives"
    assert first.section_level == 2
    assert first.parent_section == "Project"
    assert first.is_continuation is False
    assert first.has_table is False
    assert first.relevance_score == 0.8

    second = chunks[1]

    assert second.section_level == 2
    assert second.parent_section is None
    assert second.is_continuation is True
    assert second.has_table is True
    assert second.relevance_score == 0.55


def test_retrieve_returns_empty_list_when_chroma_returns_no_results(
    monkeypatch,
):
    class FakeCollection:
        def query(self, query_embeddings, n_results, include):
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

    fake_openai_client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda model, input: SimpleNamespace(
                data=[
                    SimpleNamespace(
                        embedding=[0.1, 0.2]
                    )
                ]
            )
        )
    )

    monkeypatch.setattr(
        retriever,
        "get_collection",
        lambda chroma_dir: FakeCollection(),
    )
    monkeypatch.setattr(
        retriever,
        "create_openai_client",
        lambda: fake_openai_client,
    )

    result = retriever.retrieve(
        "missing information",
        chroma_dir="vector_db",
    )

    assert result == []


def test_format_chunks_for_prompt_formats_metadata():
    chunks = [
        retriever.RetrievedChunk(
            chunk_id="chunk_1",
            content="First content",
            source_file="proposal.md",
            section_title="Objectives",
            section_level=2,
            parent_section="Project",
            is_continuation=False,
            has_table=False,
            relevance_score=0.9,
        ),
        retriever.RetrievedChunk(
            chunk_id="chunk_2",
            content="Second content",
            source_file="proposal.md",
            section_title="Objectives",
            section_level=2,
            parent_section=None,
            is_continuation=True,
            has_table=False,
            relevance_score=0.8,
        ),
    ]

    formatted = retriever.format_chunks_for_prompt(chunks)

    assert (
        "[CONTEXT 1 | source: proposal.md "
        "| section: Objectives | parent: Project]"
        in formatted
    )

    assert "First content" in formatted

    assert (
        "[CONTEXT 2 | source: proposal.md "
        "| section: Objectives | continuation]"
        in formatted
    )

    assert "Second content" in formatted
    assert "\n\n---\n\n" in formatted


def test_format_chunks_for_prompt_returns_empty_string_for_no_chunks():
    assert retriever.format_chunks_for_prompt([]) == ""

def test_rerank_score_can_promote_better_matching_chunk():
    weak_match = retriever.RetrievedChunk(
        chunk_id="chunk-1",
        content="General project information and administrative details.",
        source_file="proposal.md",
        section_title="Background",
        section_level=2,
        parent_section=None,
        is_continuation=False,
        has_table=False,
        relevance_score=0.90,
    )

    strong_match = retriever.RetrievedChunk(
        chunk_id="chunk-2",
        content=(
            "The impact assessment uses Theory of Change "
            "and Social Return on Investment."
        ),
        source_file="proposal.md",
        section_title="Impact assessment",
        section_level=2,
        parent_section=None,
        is_continuation=False,
        has_table=False,
        relevance_score=0.82,
    )

    query = "What methodologies are used for impact assessment?"

    weak_score = retriever._rerank_score(query, weak_match)
    strong_score = retriever._rerank_score(query, strong_match)

    assert strong_score > weak_score