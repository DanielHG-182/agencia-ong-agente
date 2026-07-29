"""
generate_synthetic_dataset.py
Generates a synthetic golden dataset (question + ground_truth) for a given project
by reading its processed Markdown files and using OpenAI to derive realistic QA pairs.

Usage:
    python generate_synthetic_dataset.py --project demo_project
    python generate_synthetic_dataset.py --project demo_project --questions-per-chunk 2 --max-chunks 10
"""

import argparse
import json
import logging
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 800        # characters per chunk when splitting .md files
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_QUESTIONS_PER_CHUNK = 1
DEFAULT_MAX_CHUNKS = 20         # cap to avoid runaway API costs
GENERATION_MODEL = "gpt-4o-mini"

CATEGORIES = ["factual", "eligibility", "deadlines", "procedure", "unanswerable"]

GENERATION_PROMPT = """\
You are a QA dataset generator for a RAG evaluation pipeline.

Given the following document chunk, generate {n} question-answer pair(s).

Rules:
- Each question must be answerable ONLY from the chunk provided.
- The ground_truth must be a concise, faithful answer derived strictly from the chunk.
- Include at least one "unanswerable" pair where the question asks about something NOT in the chunk.
  For unanswerable pairs, the ground_truth must explain that the documentation does not contain that information.
- Assign a category from: factual, eligibility, deadlines, procedure, unanswerable.
- Generate a short eval_id like: CAT_NNN (e.g. ELIG_001, DEAD_002, UNANS_003).

Respond ONLY with a valid JSON array. No markdown fences, no explanation.
Format:
[
  {{
    "eval_id": "FACT_001",
    "category": "factual",
    "question": "...",
    "ground_truth": "..."
  }}
]

Document chunk:
\"\"\"
{chunk}
\"\"\"
"""

# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def split_markdown(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Simple character-level sliding window splitter."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        start += chunk_size - overlap
    return [c for c in chunks if len(c) > 100]  # discard very short tail chunks


def load_markdown_files(project_name: str) -> list[dict]:
    """
    Returns a list of {source, text} dicts from projects/{project_name}/data/processed/*.md
    """
    from scripts.utils.paths import get_project_paths
    paths    = get_project_paths(project_name)

    processed_dir = paths["processed"]

    if not processed_dir.exists():
        raise FileNotFoundError(
            f"Processed directory not found: {processed_dir.resolve()}\n"
            f"Run: python main.py --stage conversion --project {project_name}"
        )

    md_files = sorted(processed_dir.glob("*.md"))

    if not md_files:
        raise ValueError(f"No .md files found in {processed_dir.resolve()}")

    logger.info(f"Found {len(md_files)} markdown file(s) in {processed_dir}")

    documents = []
    for path in md_files:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            documents.append({"source": path.name, "text": text})

    return documents


def generate_qa_pairs(
    client: OpenAI,
    chunk: str,
    n: int,
    source: str,
    chunk_index: int,
) -> list[dict]:
    """
    Calls OpenAI to generate n QA pairs from a chunk.
    Returns a list of dicts with eval_id, category, question, ground_truth, source, chunk_index.
    """
    prompt = GENERATION_PROMPT.format(n=n, chunk=chunk)

    try:
        response = client.chat.completions.create(
            model=GENERATION_MODEL,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()

        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()

        pairs = json.loads(raw)

        # Enrich with metadata
        for pair in pairs:
            pair["source"] = source
            pair["chunk_index"] = chunk_index
            # Ensure unique eval_id across files
            pair["eval_id"] = f"{pair.get('eval_id', 'GEN_000')}_{uuid.uuid4().hex[:4].upper()}"

        return pairs

    except json.JSONDecodeError as e:
        logger.warning(f"[{source}] chunk {chunk_index} — JSON parse error: {e}. Skipping.")
        return []
    except Exception as e:
        logger.warning(f"[{source}] chunk {chunk_index} — API error: {e}. Skipping.")
        return []


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main(project_name: str = None):
    from scripts.utils.paths import get_project_paths
    paths    = get_project_paths(project_name)

    parser = argparse.ArgumentParser(
        description="Generate a synthetic golden dataset for RAG evaluation"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project folder name (e.g. demo_project)",
    )
    parser.add_argument(
        "--questions-per-chunk",
        type=int,
        default=DEFAULT_QUESTIONS_PER_CHUNK,
        help=f"QA pairs to generate per chunk (default: {DEFAULT_QUESTIONS_PER_CHUNK})",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=DEFAULT_MAX_CHUNKS,
        help=f"Max number of chunks to process across all files (default: {DEFAULT_MAX_CHUNKS})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Characters per chunk (default: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP,
        help=f"Overlap between chunks in characters (default: {DEFAULT_CHUNK_OVERLAP})",
    )
    args, unknown = parser.parse_known_args()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ── Load documents ──
    try:
        documents = load_markdown_files(args.project)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return

    # ── Split into chunks ──
    all_chunks = []
    for doc in documents:
        chunks = split_markdown(doc["text"], args.chunk_size, args.chunk_overlap)
        for i, chunk in enumerate(chunks):
            all_chunks.append({"source": doc["source"], "chunk_index": i, "text": chunk})

    logger.info(f"Total chunks across all files: {len(all_chunks)}")

    # ── Cap to max_chunks (evenly sample across files) ──
    if len(all_chunks) > args.max_chunks:
        step = len(all_chunks) / args.max_chunks
        selected = [all_chunks[int(i * step)] for i in range(args.max_chunks)]
        logger.info(f"Sampling {args.max_chunks} chunks (evenly distributed)")
    else:
        selected = all_chunks

    # ── Generate QA pairs ──
    all_pairs = []
    for item in selected:
        logger.info(f"Generating from [{item['source']}] chunk {item['chunk_index']}...")
        pairs = generate_qa_pairs(
            client=client,
            chunk=item["text"],
            n=args.questions_per_chunk,
            source=item["source"],
            chunk_index=item["chunk_index"],
        )
        all_pairs.extend(pairs)
        logger.info(f"  → {len(pairs)} pair(s) generated")

    if not all_pairs:
        logger.error("No QA pairs were generated. Check your documents and API key.")
        return

    # ── Save output ──
    output_dir =  paths["dataset_evaluation"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "synthetic_golden_dataset.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_pairs, f, ensure_ascii=False, indent=2)

    logger.info(f"\nDone. {len(all_pairs)} QA pair(s) saved to: {output_path}")


if __name__ == "__main__":
    main()
