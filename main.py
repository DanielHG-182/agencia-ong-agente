"""
main.py
Entry point for the ONG document assistant pipeline.

Usage:
    python main.py --stage conversion
"""

import logging
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from scripts.document_processor import process_document
from scripts.chunker import chunk_file, chunks_to_json
from scripts.indexer import index_all
from scripts.retriever import retrieve, format_chunks_for_prompt
from scripts.redactor import generate_draft
from scripts.exporter import export_document, Section
from scripts.utils.paths import init_project_structure

# ─────────────────────────────────────────────────────────
# ENVIRONMENT & LOGGING
# ─────────────────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────

RAW_DIR       = Path(os.getenv("RAW_DOCS_DIR", "data/raw"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DOCS_DIR", "data/processed"))
CHUNKS_DIR    = Path(os.getenv("CHUNKS_DIR", "data/chunks")) 

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


# ─────────────────────────────────────────────────────────
# STAGES
# ─────────────────────────────────────────────────────────

def run_conversion():
    """
    Stage 1: Convert all documents in data/raw to Markdown
    and save them to data/processed.
    """
    logger.info("Starting conversion stage")
    logger.info(f"Source : {RAW_DIR.resolve()}")
    logger.info(f"Output : {PROCESSED_DIR.resolve()}")

    if not RAW_DIR.exists():
        logger.error(f"Raw directory not found: {RAW_DIR}")
        return

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    documents = [
        f for f in RAW_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not documents:
        logger.warning("No documents found in data/raw")
        return

    logger.info(f"Found {len(documents)} document(s) to process")

    success, failed = 0, 0

    for doc_path in sorted(documents):
        logger.info(f"Processing: {doc_path.name}")
        try:
            markdown = process_document(doc_path)

            if markdown is None:
                logger.warning(f"Skipped (unsupported format): {doc_path.name}")
                failed += 1
                continue

            output_path = PROCESSED_DIR / (doc_path.stem + ".md")
            output_path.write_text(
                f"<!-- SOURCE: {doc_path.name} -->\n\n{markdown}",
                encoding="utf-8"
            )
            logger.info(f"Saved: {output_path.name}")
            success += 1

        except Exception as e:
            logger.error(f"Failed to process {doc_path.name}: {e}")
            failed += 1

    logger.info(f"Conversion complete — success: {success}, failed: {failed}")


def run_chunking():
    """
    Stage 2: Chunk all Markdown files in data/processed
    and save results to data/chunks as JSON.
    """
    logger.info("Starting chunking stage")
    logger.info(f"Source : {PROCESSED_DIR.resolve()}")
    logger.info(f"Output : {CHUNKS_DIR.resolve()}")

    if not PROCESSED_DIR.exists():
        logger.error(f"Processed directory not found: {PROCESSED_DIR}")
        logger.error("Run --stage conversion first")
        return

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    md_files = list(PROCESSED_DIR.glob("*.md"))

    if not md_files:
        logger.warning("No markdown files found in data/processed")
        return

    logger.info(f"Found {len(md_files)} markdown file(s) to chunk")

    total_chunks = 0
    success, failed = 0, 0

    for md_path in sorted(md_files):
        logger.info(f"Chunking: {md_path.name}")
        try:
            chunks = chunk_file(md_path)
            output_path = CHUNKS_DIR / (md_path.stem + "_chunks.json")
            chunks_to_json(chunks, output_path)
            total_chunks += len(chunks)
            success += 1
        except Exception as e:
            logger.error(f"Failed to chunk {md_path.name}: {e}")
            failed += 1

    logger.info(f"Chunking complete — files: {success}, total chunks: {total_chunks}, failed: {failed}")

def run_indexing(project_name: str | None = None):
    """
    Stage 3: Generate embeddings and index chunks into ChromaDB.
    """
    from scripts.utils.paths import get_project_paths

    if not project_name:
        logger.error(
            "No project specified. "
            "Use: python main.py --stage indexing --project your_project_name"
        )
        return

    paths = get_project_paths(project_name)
    reset = os.getenv("REINDEX", "false").lower() == "true"

    if reset:
        logger.warning("REINDEX=true — dropping existing collection")

    logger.info(f"Active project : {project_name}")
    logger.info(f"ChromaDB path  : {paths['vector_db']}")
    logger.info(f"Chunks dir     : {paths['chunks']}")

    index_all(
        chunks_dir = paths["chunks"],
        chroma_dir = str(paths["vector_db"]),
        reset      = reset,
    )

def run_retrieval_test(project_name: str | None = None):
    """
    Quick test to verify ChromaDB retrieval is working.
    """
    from scripts.utils.paths import get_project_paths

    if not project_name:
        logger.error(
            "No project specified. "
            "Use: python main.py --stage retrieval-test --project your_project_name"
        )
        return

    paths      = get_project_paths(project_name)
    test_query = "project objectives and expected impact"

    logger.info(f"Active project : {project_name}")
    logger.info(f"ChromaDB path  : {paths['vector_db']}")

    chunks = retrieve(
        query      = test_query,
        chroma_dir = str(paths["vector_db"])
    )
    print(format_chunks_for_prompt(chunks))


def run_draft_test(project_name: str | None = None):
    """
    Quick test to verify the redactor is working end to end.
    """
    from scripts.utils.paths import get_project_paths

    if not project_name:
        logger.error(
            "No project specified. "
            "Use: python main.py --stage draft-test --project your_project_name"
        )
        return

    paths  = get_project_paths(project_name)
    result = generate_draft(
        section_name     = "1.1 Background and General Objectives",
        user_instruction = "Write the background based on context documents.",
        directives_path  = paths["directives"],
        chroma_dir       = str(paths["vector_db"]),
    )

    print(f"\n{'='*60}")
    print(f"SECTION : {result.section_name}")
    print(f"Model   : {result.model}")
    print(f"Chunks  : {result.chunks_used}")
    print(f"Tokens  : in {result.prompt_tokens} / out {result.output_tokens}")
    print(f"{'='*60}\n")
    print(result.content)


def run_export_test(project_name: str | None = None):
    """
    Quick test to verify export is working.
    """
    from scripts.utils.paths import get_project_paths

    if not project_name:
        logger.error(
            "No project specified. "
            "Use: python main.py --stage export-test --project your_project_name"
        )
        return

    paths    = get_project_paths(project_name)
    sections = [
        Section(
            name    = "1.1 Background and General Objectives",
            content = "This project addresses the challenge of adult learning "
                      "participation across Europe. In line with the EU 2030 target "
                      "of 60% adult participation in learning, the initiative focuses "
                      "on reaching adults with low basic skills.",
            level   = 2,
        ),
    ]

    output_path = export_document(
        sections     = sections,
        project_name = project_name,
        output_dir   = paths["output"],
    )
    print(f"\nDocument generated: {output_path}")

# ─────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────

STAGES = {
    "conversion": run_conversion,
    "chunking":   run_chunking,   
    "indexing":   run_indexing,
    "retrieval-test": run_retrieval_test,
    "draft-test":   run_draft_test,
    "export-test":    run_export_test,
}

def main():
    parser = argparse.ArgumentParser(
        description="ONG Document Assistant — pipeline runner"
    )
    parser.add_argument(
        "--stage",
        choices=[
            "conversion",
            "chunking",
            "indexing",
            "retrieval-test",
            "draft-test",
            "export-test",
        ],
        required=True,
        help="Pipeline stage to run"
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project folder name (e.g. erasmus_bb_2026)"
    )
    args = parser.parse_args()

    # Stages that require --project
    project_stages = {
        "indexing":       run_indexing,
        "retrieval-test": run_retrieval_test,
        "draft-test":     run_draft_test,
        "export-test":    run_export_test,
    }

    # Stages that don't need --project
    basic_stages = {
        "conversion": run_conversion,
        "chunking":   run_chunking,
    }

    if args.stage in project_stages:
        project_stages[args.stage](project_name=args.project)
    else:
        basic_stages[args.stage]()


if __name__ == "__main__":
    main()
