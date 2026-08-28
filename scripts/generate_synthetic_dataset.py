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

from scripts.chunker import Chunk, chunk_file

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

DEFAULT_QUESTIONS_PER_CHUNK = 1
DEFAULT_MAX_CHUNKS = 20         # cap to avoid runaway API costs
GENERATION_MODEL = "gpt-4o-mini"

CATEGORIES = ["factual", "eligibility", "deadlines", "procedure"]

GENERATION_PROMPT = """\
You are a QA dataset generator for a RAG evaluation pipeline.

Given the following document chunk, generate {n} question-answer pair(s).

Rules:
- Each question must be answerable ONLY from the chunk provided.
- The ground_truth must be a concise, faithful answer derived strictly from the chunk.
- Set "answerable" to true for every generated pair.
- Assign a category from: factual, eligibility, deadlines, procedure.
- Do not generate unanswerable questions in this step.
- Generate a short eval_id like: CAT_NNN (e.g. FACT_001, ELIG_002, PROC_003).

Respond ONLY with a valid JSON array. No markdown fences, no explanation.

Format:
[
  {{
    "eval_id": "FACT_001",
    "category": "factual",
    "answerable": true,
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

def load_project_chunks(project_name: str) -> list[Chunk]:
    """
    Loads processed Markdown files for a project and chunks them using
    the same structure-aware chunking logic as the real RAG pipeline.
    """
    from scripts.utils.paths import get_project_paths

    paths = get_project_paths(project_name)
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

    chunks: list[Chunk] = []

    for path in md_files:
        file_chunks = chunk_file(path)
        chunks.extend(file_chunks)

    logger.info(f"Loaded {len(chunks)} real RAG chunk(s)")
    return chunks

def generate_qa_pairs(
    client: OpenAI,
    chunk: str,
    n: int,
    source: str,
    chunk_id: str,
    section_title: str,
) -> list[dict]:
    """
    Calls OpenAI to generate n QA pairs from a chunk.

    Returns validated QA pairs enriched with source metadata.
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

        # Validate top-level response
        if not isinstance(pairs, list):
            raise ValueError("Model response must be a JSON array")

        validated_pairs = []

        for pair in pairs:
            if not isinstance(pair, dict):
                logger.warning(
                    f"[{source}] chunk {chunk_id} — invalid pair type. Skipping."
                )
                continue

            required_fields = {
                "eval_id",
                "category",
                "answerable",
                "question",
                "ground_truth",
            }

            missing = required_fields - pair.keys()

            if missing:
                logger.warning(
                    f"[{source}] chunk {chunk_id} — "
                    f"missing fields {missing}. Skipping."
                )
                continue

            if pair["category"] not in CATEGORIES:
                logger.warning(
                    f"[{source}] chunk {chunk_id} — "
                    f"invalid category '{pair['category']}'. Skipping."
                )
                continue

            if pair["answerable"] is not True:
                logger.warning(
                    f"[{source}] chunk {chunk_id} — "
                    "expected answerable=true. Skipping."
                )
                continue

            if not str(pair["question"]).strip():
                logger.warning(
                    f"[{source}] chunk {chunk_id} — "
                    "empty question. Skipping."
                )
                continue

            if not str(pair["ground_truth"]).strip():
                logger.warning(
                    f"[{source}] chunk {chunk_id} — "
                    "empty ground_truth. Skipping."
                )
                continue

            validated_pairs.append(pair)

        # Enrich valid pairs with real RAG metadata
        for pair in validated_pairs:
            pair["source"] = source
            pair["source_chunk_id"] = chunk_id
            pair["source_section"] = section_title

            # Ensure unique eval_id across files/chunks
            pair["eval_id"] = (
                f"{pair.get('eval_id', 'GEN_000')}_"
                f"{uuid.uuid4().hex[:4].upper()}"
            )

        return validated_pairs

    except json.JSONDecodeError as e:
        logger.warning(
            f"[{source}] chunk {chunk_id} — "
            f"JSON parse error: {e}. Skipping."
        )
        return []

    except Exception as e:
        logger.warning(
            f"[{source}] chunk {chunk_id} — "
            f"API/validation error: {e}. Skipping."
        )
        return []

def generate_multi_context_pairs(
    client: OpenAI,
    chunks: list[Chunk],
    n: int,
) -> list[dict]:
    """
    Generates QA pairs that require combining information
    from multiple related RAG chunks.
    """
    if len(chunks) < 2:
        return []

    context_blocks = []

    for chunk in chunks:
        context_blocks.append(
            f"[chunk_id={chunk.chunk_id}]\n"
            f"[section={chunk.section_title}]\n"
            f"{chunk.content}"
        )

    combined_context = "\n\n---\n\n".join(context_blocks)

    prompt = f"""
    You are generating multi-context QA pairs for a RAG evaluation dataset.

    Using the related document chunks below, generate exactly {n} question-answer pair(s).

    Rules:
    - Each question must require information from at least TWO different chunks.
    - Do not generate a question that can be fully answered from only one chunk.
    - The ground_truth must combine the relevant information faithfully.
    - Set "answerable" to true.
    - Set "category" to "multi_context".
    - Do not invent information.
    - Keep the question realistic for a user of the project.
    - The question must require integrating information from both chunks into one coherent answer.
    - Avoid simply combining two independent questions with "and".
    - Prefer relationships such as cause/effect, comparison, complementarity, dependencies, or how one section informs another.
    - Reject questions that could be fully answered from only one of the chunks.

    Respond ONLY with a valid JSON array.

    Format:
    [
    {{
        "eval_id": "MULTI_001",
        "category": "multi_context",
        "answerable": true,
        "question": "...",
        "ground_truth": "..."
    }}
    ]

    Related chunks:
    \"\"\"
    {combined_context}
    \"\"\"
    """

    try:
        response = client.chat.completions.create(
            model=GENERATION_MODEL,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.choices[0].message.content.strip()

        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()

        pairs = json.loads(raw)

        if not isinstance(pairs, list):
            raise ValueError("Model response must be a JSON array")

        validated_pairs = []

        source_chunk_ids = [chunk.chunk_id for chunk in chunks]
        source_sections = list(dict.fromkeys(
            chunk.section_title for chunk in chunks
        ))

        for pair in pairs:
            if not isinstance(pair, dict):
                continue

            required_fields = {
                "eval_id",
                "category",
                "answerable",
                "question",
                "ground_truth",
            }

            if required_fields - pair.keys():
                continue

            if pair["category"] != "multi_context":
                continue

            if pair["answerable"] is not True:
                continue

            if not str(pair["question"]).strip():
                continue

            if not str(pair["ground_truth"]).strip():
                continue

            pair["source"] = chunks[0].source_file
            pair["source_chunk_ids"] = source_chunk_ids
            pair["source_sections"] = source_sections
            pair["eval_id"] = (
                f"{pair.get('eval_id', 'MULTI_000')}_"
                f"{uuid.uuid4().hex[:4].upper()}"
            )

            validated_pairs.append(pair)

        return validated_pairs

    except json.JSONDecodeError as e:
        logger.warning(
            f"Multi-context generation — JSON parse error: {e}. Skipping."
        )
        return []

    except Exception as e:
        logger.warning(
            f"Multi-context generation — API/validation error: {e}. Skipping."
        )
        return []

def build_multi_context_candidate_groups(
    chunks: list[Chunk],
    max_groups: int = 4,
) -> list[list[Chunk]]:
     """
    Build adjacent chunk groups as candidates for synthetic
    multi-context question generation.

    Generated pairs should be manually reviewed before being
    accepted into the golden evaluation dataset.
    """
    groups: list[list[Chunk]] = []

    excluded_sections = {
        "ADMINISTRATIVE FORMS (PART A)",
        "COVER PAGE",
        "LIST OF ANNEXES",
        "Security",
    }

    for i in range(len(chunks) - 1):
        current = chunks[i]
        following = chunks[i + 1]

        if current.source_file != following.source_file:
            continue

        if current.section_title in excluded_sections:
            continue

        if following.section_title in excluded_sections:
            continue

        groups.append([current, following])

        if len(groups) >= max_groups:
            break

    return groups

# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    from scripts.utils.paths import get_project_paths

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
        help=(
            f"QA pairs to generate per chunk "
            f"(default: {DEFAULT_QUESTIONS_PER_CHUNK})"
        ),
    )

    parser.add_argument(
        "--max-chunks",
        type=int,
        default=DEFAULT_MAX_CHUNKS,
        help=(
            f"Max number of real RAG chunks to process "
            f"(default: {DEFAULT_MAX_CHUNKS})"
        ),
    )

    args, unknown = parser.parse_known_args()

    # Resolve project paths from the actual CLI project name
    paths = get_project_paths(args.project)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ── Load real RAG chunks ──
    try:
        all_chunks = load_project_chunks(args.project)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return

    logger.info(f"Total real RAG chunks: {len(all_chunks)}")

    # ── Cap to max_chunks ──
    if len(all_chunks) > args.max_chunks:
        step = len(all_chunks) / args.max_chunks

        selected = [
            all_chunks[int(i * step)]
            for i in range(args.max_chunks)
        ]

        logger.info(
            f"Sampling {args.max_chunks} chunks "
            f"(evenly distributed)"
        )
    else:
        selected = all_chunks

    # ── Generate answerable single-context QA pairs ──
    all_pairs = []

    for chunk in selected:
        logger.info(
            f"Generating from [{chunk.source_file}] "
            f"section [{chunk.section_title}] "
            f"chunk [{chunk.chunk_id}]..."
        )

        pairs = generate_qa_pairs(
            client=client,
            chunk=chunk.content,
            n=args.questions_per_chunk,
            source=chunk.source_file,
            chunk_id=chunk.chunk_id,
            section_title=chunk.section_title,
        )

        all_pairs.extend(pairs)

        logger.info(
            f"  → {len(pairs)} answerable pair(s) generated"
        )

    # ── Generate multi-context QA pairs ──
    # Multi-context output is synthetic candidate data and should be
    # manually reviewed before inclusion in the golden dataset.
    multi_context_groups = build_multi_context_candidate_groups(
        all_chunks,
        max_groups=4,
    )

    for group in multi_context_groups:
        logger.info(
            "Generating multi-context pair from "
            f"[{group[0].section_title}] + "
            f"[{group[1].section_title}]..."
        )

        pairs = generate_multi_context_pairs(
            client=client,
            chunks=group,
            n=1,
        )

        all_pairs.extend(pairs)

        logger.info(
            f"  → {len(pairs)} multi-context pair(s) generated"
        )

    # ── Validate final dataset ──
    if not all_pairs:
        logger.error(
            "No QA pairs were generated. "
            "Check your documents and API key."
        )
        return

    # ── Save output ──
    output_dir = paths["dataset_evaluation"]
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = (
        output_dir / "synthetic_dataset_candidates.json"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            all_pairs,
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(
        f"\nDone. {len(all_pairs)} QA pair(s) "
        f"saved to: {output_path}"
    )

if __name__ == "__main__":
    main()
