"""
retriever.py
Queries ChromaDB to retrieve the most relevant chunks
for a given instruction or query text.
"""

import logging
from dataclasses import dataclass
from scripts.config import settings
from scripts.clients import create_chroma_client, create_openai_client

import chromadb

import re

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id:         str
    content:          str
    source_file:      str
    section_title:    str
    section_level:    int
    parent_section:   str | None
    is_continuation:  bool
    has_table:        bool
    relevance_score:  float

_RERANK_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or",
    "is", "are", "was", "were", "what", "how", "does", "do",
    "this", "that", "with", "by", "from", "project",
}


def _tokenize_for_reranking(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())

    return {
        word
        for word in words
        if len(word) > 2
        and word not in _RERANK_STOPWORDS
    }


def _rerank_score(
    query: str,
    chunk: RetrievedChunk,
    section_weight: float = 0.15,
    content_weight: float = 0.05,
) -> float:
    """
    Combine vector similarity with lightweight lexical overlap.

    Vector similarity remains the primary ranking signal.
    Lexical overlap is used only as a small ranking adjustment.
    """

    query_terms = _tokenize_for_reranking(query)

    if not query_terms:
        return chunk.relevance_score

    section_terms = _tokenize_for_reranking(
        chunk.section_title
    )
    content_terms = _tokenize_for_reranking(
        chunk.content
    )

    section_overlap = (
        len(query_terms & section_terms)
        / len(query_terms)
    )

    content_overlap = (
        len(query_terms & content_terms)
        / len(query_terms)
    )

    return (
        chunk.relevance_score
        + section_weight * section_overlap
        + content_weight * content_overlap
    )

# ─────────────────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────────────────

def get_collection(chroma_dir: str) -> chromadb.Collection:
    """
    Open the configured ChromaDB collection from the given directory.

    Raises:
        RuntimeError: If the collection does not exist.
    """

    client = create_chroma_client(chroma_dir)

    try:
        return client.get_collection(settings.chroma_collection_name)
    except Exception as exc:
        raise RuntimeError(
            f"Collection '{settings.chroma_collection_name}' not found "
            f"in '{chroma_dir}'. Run the indexing stage first: "
            "python main.py --stage indexing --project your_project_name"
        ) from exc

# ─────────────────────────────────────────────────────────
# RETRIEVAL
# ─────────────────────────────────────────────────────────

def retrieve(
    query:      str,
    top_k: int = settings.retriever_top_k,
    chroma_dir: str | None = None,
) -> list[RetrievedChunk]:
    """
    Generates a query embedding with OpenAI and retrieves
    the top_k most relevant chunks from ChromaDB.

    Args:
        query:      Natural language query
        top_k:      Number of chunks to return
        chroma_dir: Path to the active project's ChromaDB directory.
    """
    if not chroma_dir:
        raise ValueError(
            "chroma_dir is required. Pass the active project's vector database path."
        )

    resolved_dir = chroma_dir

    collection    = get_collection(resolved_dir)
    openai_client = create_openai_client()
    candidate_k = max(top_k, 8)

    logger.info(
        "Querying ChromaDB — candidate_k: %s | final_top_k: %s | query: '%s'",
        candidate_k,
        top_k,
        query[:80],
    )
    logger.debug("ChromaDB path: %s", resolved_dir)

    # Generate query embedding — must match model used during indexing
    response = openai_client.embeddings.create(
        model=settings.embedding_model,
        input = [query]
    )
    query_embedding = response.data[0].embedding

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"],
    )

    candidates = []

    for i in range(len(results["ids"][0])):
        metadata = results["metadatas"][0][i]
        distance = results["distances"][0][i]

        chunk = RetrievedChunk(
            chunk_id=results["ids"][0][i],
            content=results["documents"][0][i],
            source_file=metadata.get("source_file", ""),
            section_title=metadata.get("section_title", ""),
            section_level=int(metadata.get("section_level", 0)),
            parent_section=metadata.get("parent_section") or None,
            is_continuation=bool(metadata.get("is_continuation", False)),
            has_table=bool(metadata.get("has_table", False)),
            relevance_score=round(1 - distance, 4),
        )

        candidates.append(chunk)

    chunks = sorted(
        candidates,
        key=lambda chunk: _rerank_score(query, chunk),
        reverse=True,
    )[:top_k]

    for chunk in chunks:
        logger.debug(
            f"  [{chunk.relevance_score:.3f}] {chunk.source_file} "
            f"— {chunk.section_title}"
        )

    logger.info("Retrieved %s chunks", len(chunks))
    return chunks


# ─────────────────────────────────────────────────────────
# PROMPT FORMATTING
# ─────────────────────────────────────────────────────────

def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    """
    Formats retrieved chunks into a clean string ready to be
    injected into the LLM prompt as context.
    """
    parts = []
    for i, chunk in enumerate(chunks, 1):
        header = (
            f"[CONTEXT {i} | source: {chunk.source_file} "
            f"| section: {chunk.section_title}"
        )
        if chunk.parent_section:
            header += f" | parent: {chunk.parent_section}"
        if chunk.is_continuation:
            header += " | continuation"
        header += "]"

        parts.append(f"{header}\n{chunk.content}")

    return "\n\n---\n\n".join(parts)