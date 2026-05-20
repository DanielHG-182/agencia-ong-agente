"""
retriever.py
Queries ChromaDB to retrieve the most relevant chunks
for a given instruction or query text.
"""

import os
import logging
from dataclasses import dataclass

import chromadb
from chromadb.config import Settings
from openai import OpenAI

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────

DEFAULT_TOP_K   = int(os.getenv("RETRIEVER_TOP_K", 3))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

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


# ─────────────────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────────────────

def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    return OpenAI(api_key=api_key)


def get_collection(chroma_dir: str) -> chromadb.Collection:
    """
    Opens the ChromaDB collection from the given directory.
    Raises a clear error if the collection does not exist.
    """
    client = chromadb.PersistentClient(
        path     = chroma_dir,
        settings = Settings(anonymized_telemetry=False)
    )
    try:
        return client.get_collection("ong_documents")
    except Exception:
        raise RuntimeError(
            f"Collection 'ong_documents' not found in '{chroma_dir}'. "
            f"Run the indexing stage first: "
            f"python main.py --stage indexing --project your_project_name"
        )


# ─────────────────────────────────────────────────────────
# RETRIEVAL
# ─────────────────────────────────────────────────────────

def retrieve(
    query:      str,
    top_k:      int = DEFAULT_TOP_K,
    chroma_dir: str | None = None,
) -> list[RetrievedChunk]:
    """
    Generates a query embedding with OpenAI and retrieves
    the top_k most relevant chunks from ChromaDB.

    Args:
        query:      Natural language query
        top_k:      Number of chunks to return
        chroma_dir: Path to ChromaDB directory.
                    Falls back to CHROMA_DB_DIR env var if not provided.
    """
    # Resolve chroma_dir — parameter takes priority over env var
    resolved_dir = chroma_dir or os.getenv("CHROMA_DB_DIR", "vector_db")

    collection    = get_collection(resolved_dir)
    openai_client = get_openai_client()

    logger.info(f"Querying ChromaDB — top_k: {top_k} | query: '{query[:80]}'")
    logger.debug(f"ChromaDB path: {resolved_dir}")

    # Generate query embedding — must match model used during indexing
    response = openai_client.embeddings.create(
        model = EMBEDDING_MODEL,
        input = [query]
    )
    query_embedding = response.data[0].embedding

    results = collection.query(
        query_embeddings = [query_embedding],
        n_results        = top_k,
        include          = ["documents", "metadatas", "distances"]
    )

    chunks = []
    for i in range(len(results["ids"][0])):
        metadata = results["metadatas"][0][i]
        distance = results["distances"][0][i]

        chunk = RetrievedChunk(
            chunk_id        = results["ids"][0][i],
            content         = results["documents"][0][i],
            source_file     = metadata.get("source_file", ""),
            section_title   = metadata.get("section_title", ""),
            section_level   = int(metadata.get("section_level", 0)),
            parent_section  = metadata.get("parent_section") or None,
            is_continuation = bool(metadata.get("is_continuation", False)),
            has_table       = bool(metadata.get("has_table", False)),
            relevance_score = round(1 - distance, 4),
        )
        chunks.append(chunk)
        logger.debug(
            f"  [{chunk.relevance_score:.3f}] {chunk.source_file} "
            f"— {chunk.section_title}"
        )

    logger.info(f"Retrieved {len(chunks)} chunks")
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