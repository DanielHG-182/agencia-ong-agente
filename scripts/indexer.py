"""
indexer.py
Loads chunks from data/chunks JSON files, generates OpenAI embeddings,
and stores them in a local ChromaDB collection with full metadata.
"""

import os
import json
import time
import logging
from pathlib import Path

from openai import OpenAI
import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
COLLECTION_NAME = "ong_documents"
BATCH_SIZE      = 50


# ─────────────────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────────────────

def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    return OpenAI(api_key=api_key)


def get_chroma_collection(
    chroma_dir: str,
    reset:      bool = False,
) -> chromadb.Collection:
    """
    Opens or creates the ChromaDB collection at the given directory.
    If reset=True drops and recreates it (full re-index).
    """
    client = chromadb.PersistentClient(
        path     = chroma_dir,
        settings = Settings(anonymized_telemetry=False)
    )

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.warning(f"Collection '{COLLECTION_NAME}' dropped for re-indexing")
        except Exception:
            pass

    return client.get_or_create_collection(
        name     = COLLECTION_NAME,
        metadata = {"hnsw:space": "cosine"}
    )


# ─────────────────────────────────────────────────────────
# EMBEDDING GENERATION
# ─────────────────────────────────────────────────────────

def generate_embeddings(texts: list[str], client: OpenAI) -> list[list[float]]:
    """
    Generates embeddings for a batch of texts.
    Includes retry logic for rate limit errors.
    """
    for attempt in range(3):
        try:
            response = client.embeddings.create(
                model = EMBEDDING_MODEL,
                input = texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            if attempt < 2:
                wait = (attempt + 1) * 5
                logger.warning(f"Embedding API error: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ─────────────────────────────────────────────────────────
# METADATA PREPARATION
# ─────────────────────────────────────────────────────────

def prepare_metadata(chunk: dict) -> dict:
    """
    ChromaDB only accepts str, int, float, bool metadata values.
    Converts None to empty string and filters unsupported types.
    """
    clean = {}
    for key, value in chunk.items():
        if key == "content":
            continue
        if value is None:
            clean[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


# ─────────────────────────────────────────────────────────
# INDEXING
# ─────────────────────────────────────────────────────────

def index_chunks_file(
    json_path:  Path,
    collection: chromadb.Collection,
    client:     OpenAI,
) -> int:
    """
    Loads a single chunks JSON file and indexes all chunks into ChromaDB.
    Skips chunks that are already indexed.
    Returns the number of chunks indexed.
    """
    chunks = json.loads(json_path.read_text(encoding="utf-8"))

    if not chunks:
        logger.warning(f"No chunks found in {json_path.name}")
        return 0

    # Filter already indexed chunks
    existing_ids = set(
        collection.get(ids=[c["chunk_id"] for c in chunks])["ids"]
    )
    new_chunks = [c for c in chunks if c["chunk_id"] not in existing_ids]

    if not new_chunks:
        logger.info(f"All chunks already indexed for {json_path.name} — skipping")
        return 0

    logger.info(
        f"{json_path.name} — indexing {len(new_chunks)} new chunks "
        f"(skipping {len(existing_ids)} existing)"
    )

    total_indexed = 0

    for i in range(0, len(new_chunks), BATCH_SIZE):
        batch = new_chunks[i: i + BATCH_SIZE]

        # Guard: filter empty content
        valid_batch = [c for c in batch if c.get("content", "").strip()]
        skipped     = len(batch) - len(valid_batch)

        if skipped:
            logger.warning(
                f"Skipped {skipped} chunks with empty content "
                f"in batch {i // BATCH_SIZE + 1}"
            )

        if not valid_batch:
            continue

        texts     = [c["content"] for c in valid_batch]
        ids       = [c["chunk_id"] for c in valid_batch]
        metadatas = [prepare_metadata(c) for c in valid_batch]

        embeddings = generate_embeddings(texts, client)

        collection.add(
            ids        = ids,
            documents  = texts,
            embeddings = embeddings,
            metadatas  = metadatas,
        )

        total_indexed += len(valid_batch)
        logger.info(
            f"  Batch {i // BATCH_SIZE + 1} indexed — "
            f"{total_indexed}/{len(new_chunks)} chunks"
        )

    return total_indexed


# ─────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────

def index_all(
    chunks_dir: Path,
    chroma_dir: str,
    reset:      bool = False,
) -> int:
    """
    Entry point. Indexes all JSON files in chunks_dir into ChromaDB.

    Args:
        chunks_dir: Path to folder containing *_chunks.json files
        chroma_dir: Path to ChromaDB storage directory
        reset:      If True drops and recreates the collection
    Returns:
        Total number of chunks indexed
    """
    client     = get_openai_client()
    collection = get_chroma_collection(chroma_dir, reset=reset)

    json_files = list(chunks_dir.glob("*_chunks.json"))

    if not json_files:
        logger.warning(f"No chunk files found in {chunks_dir}")
        return 0

    logger.info(f"Found {len(json_files)} chunk file(s) to index")
    logger.info(f"Embedding model : {EMBEDDING_MODEL}")
    logger.info(f"ChromaDB path   : {chroma_dir}")

    total = 0
    for json_path in sorted(json_files):
        total += index_chunks_file(json_path, collection, client)

    logger.info(
        f"Indexing complete — {total} chunks indexed "
        f"into '{COLLECTION_NAME}'"
    )
    return total