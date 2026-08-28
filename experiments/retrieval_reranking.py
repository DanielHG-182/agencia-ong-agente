import json
import re

from scripts.clients import create_openai_client
from scripts.config import settings
from scripts.evaluator import load_golden_dataset
from scripts.retriever import retrieve
from scripts.utils.paths import get_project_paths

STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or",
    "is", "are", "was", "were", "what", "how", "does", "do",
    "this", "that", "with", "by", "from", "project",
}


WEIGHT_SETS = [
    (0.10, 0.02),
    (0.15, 0.05),
    (0.20, 0.05),
    (0.25, 0.05),
    (0.30, 0.10),
]


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())

    return {
        word
        for word in words
        if len(word) > 2 and word not in STOPWORDS
    }


def rerank_score(
    query: str,
    chunk,
    section_weight: float,
    content_weight: float,
) -> float:
    query_terms = tokenize(query)
    section_terms = tokenize(chunk.section_title)
    content_terms = tokenize(chunk.content)

    if not query_terms:
        return chunk.relevance_score

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


project = "erasmus_bb_2026"
paths = get_project_paths(project)

dataset = load_golden_dataset(
    paths["dataset_evaluation"]
    / "synthetic_golden_dataset.json"
)


# Retrieve once so we don't repeat API calls for every weight combination.
evaluation_cases = []

for item in dataset:
    if item["answerable"] is not True:
        continue

    chunks = retrieve(
        query=item["question"],
        top_k=8,
        chroma_dir=str(paths["vector_db"]),
    )

    if item.get("source_chunk_id"):
        expected_ids = [item["source_chunk_id"]]
    else:
        expected_ids = item.get("source_chunk_ids", [])

    if not expected_ids:
        continue

    evaluation_cases.append(
        {
            "item": item,
            "chunks": chunks,
            "expected_ids": expected_ids,
        }
    )


def evaluate_ranking(section_weight, content_weight):
    hit1 = 0
    hit3 = 0
    recall = 0.0

    for case in evaluation_cases:
        item = case["item"]
        chunks = case["chunks"]
        expected_set = set(case["expected_ids"])

        reranked = sorted(
            chunks,
            key=lambda chunk: rerank_score(
                item["question"],
                chunk,
                section_weight,
                content_weight,
            ),
            reverse=True,
        )

        ranked_ids = [
            chunk.chunk_id
            for chunk in reranked
        ]

        hit1 += int(
            ranked_ids[0] in expected_set
        )

        hit3 += int(
            any(
                chunk_id in expected_set
                for chunk_id in ranked_ids[:3]
            )
        )

        recall += (
            len(expected_set & set(ranked_ids[:3]))
            / len(expected_set)
        )

    cases = len(evaluation_cases)

    return {
        "hit1": hit1 / cases,
        "hit3": hit3 / cases,
        "recall": recall / cases,
    }


# Baseline: original vector ranking, top 3
baseline_hit1 = 0
baseline_hit3 = 0
baseline_recall = 0.0

for case in evaluation_cases:
    chunks = case["chunks"]
    expected_set = set(case["expected_ids"])

    ranked_ids = [
        chunk.chunk_id
        for chunk in chunks
    ]

    baseline_hit1 += int(
        ranked_ids[0] in expected_set
    )

    baseline_hit3 += int(
        any(
            chunk_id in expected_set
            for chunk_id in ranked_ids[:3]
        )
    )

    baseline_recall += (
        len(expected_set & set(ranked_ids[:3]))
        / len(expected_set)
    )


cases = len(evaluation_cases)

print()
print("BASELINE VECTOR TOP-3")
print("-" * 60)
print(f"Hit@1: {baseline_hit1 / cases:.3f}")
print(f"Hit@3: {baseline_hit3 / cases:.3f}")
print(
    f"Expected chunk recall@3: "
    f"{baseline_recall / cases:.3f}"
)

print()
print("RERANK WEIGHT COMPARISON")
print("-" * 60)

for section_weight, content_weight in WEIGHT_SETS:
    result = evaluate_ranking(
        section_weight,
        content_weight,
    )

    print(
        f"section={section_weight:.2f} "
        f"content={content_weight:.2f} "
        f"| Hit@1={result['hit1']:.3f} "
        f"| Hit@3={result['hit3']:.3f} "
        f"| Recall@3={result['recall']:.3f}"
    )

print()
print("PER-CASE RANKING CHANGES")
print("-" * 80)

SECTION_WEIGHT = 0.15
CONTENT_WEIGHT = 0.05

for case in evaluation_cases:
    item = case["item"]
    chunks = case["chunks"]
    expected_ids = case["expected_ids"]

    baseline_ids = [
        chunk.chunk_id
        for chunk in chunks
    ]

    reranked = sorted(
        chunks,
        key=lambda chunk: rerank_score(
            item["question"],
            chunk,
            SECTION_WEIGHT,
            CONTENT_WEIGHT,
        ),
        reverse=True,
    )

    reranked_ids = [
        chunk.chunk_id
        for chunk in reranked
    ]

    baseline_positions = []
    reranked_positions = []

    for expected_id in expected_ids:
        baseline_positions.append(
            baseline_ids.index(expected_id) + 1
            if expected_id in baseline_ids
            else None
        )

        reranked_positions.append(
            reranked_ids.index(expected_id) + 1
            if expected_id in reranked_ids
            else None
        )

    if baseline_positions != reranked_positions:
        print(
            f"{item['eval_id']:18} "
            f"| {item['category']:13} "
            f"| vector={baseline_positions} "
            f"| rerank={reranked_positions}"
        )

def diversify_by_section(chunks, final_k=4):
    """
    Prefer one chunk per section first, then fill remaining slots
    with the next best-ranked chunks.
    """
    selected = []
    seen_sections = set()

    # First pass: maximize section diversity
    for chunk in chunks:
        if chunk.section_title in seen_sections:
            continue

        selected.append(chunk)
        seen_sections.add(chunk.section_title)

        if len(selected) == final_k:
            return selected

    # Second pass: fill remaining slots
    for chunk in chunks:
        if chunk in selected:
            continue

        selected.append(chunk)

        if len(selected) == final_k:
            break

    return selected


print()
print("DIVERSITY TEST")
print("-" * 80)

for case in evaluation_cases:
    item = case["item"]

    if item["category"] != "multi_context":
        continue

    chunks = case["chunks"]

    # Apply current reranker first
    reranked = sorted(
        chunks,
        key=lambda chunk: rerank_score(
            item["question"],
            chunk,
            0.15,
            0.05,
        ),
        reverse=True,
    )

    diversified = diversify_by_section(
        reranked,
        final_k=4,
    )

    print()
    print(item["eval_id"])

    for i, chunk in enumerate(diversified, 1):
        print(
            f" {i}. {chunk.section_title} "
            f"| {chunk.chunk_id}"
        )

        if item["eval_id"] == "MULTI_001_FBCB":
            print(
                "    SMART GREEN:",
                "SMART GREEN" in chunk.content,
                "| OFFSET:",
                "OFFSET" in chunk.content,
            )

            print()
print("SECTION-AWARE TEST")
print("-" * 80)

for case in evaluation_cases:
    item = case["item"]

    if item["category"] != "multi_context":
        continue

    chunks = case["chunks"]

    reranked = sorted(
        chunks,
        key=lambda chunk: rerank_score(
            item["question"],
            chunk,
            0.15,
            0.05,
        ),
        reverse=True,
    )

    best_by_section = {}

    for chunk in reranked:
        section = chunk.section_title

        lexical_score = rerank_score(
            item["question"],
            chunk,
            0.0,
            0.10,
        )

        current = best_by_section.get(section)

        if current is None:
            best_by_section[section] = (
                chunk,
                lexical_score,
            )
            continue

        if lexical_score > current[1]:
            best_by_section[section] = (
                chunk,
                lexical_score,
            )

    section_candidates = [
        value[0]
        for value in best_by_section.values()
    ]

    final_chunks = sorted(
        section_candidates,
        key=lambda chunk: rerank_score(
            item["question"],
            chunk,
            0.15,
            0.05,
        ),
        reverse=True,
    )[:4]

    print()
    print(item["eval_id"])

    for i, chunk in enumerate(final_chunks, 1):
        print(
            f" {i}. {chunk.section_title} "
            f"| {chunk.chunk_id}"
        )

        if item["eval_id"] == "MULTI_001_FBCB":
            print(
                "    SMART GREEN:",
                "SMART GREEN" in chunk.content,
                "| OFFSET:",
                "OFFSET" in chunk.content,
            )

def llm_rerank(
    question: str,
    chunks,
    final_k: int = 4,
):
    """
    Rerank retrieved chunks by semantic relevance to the question
    using the configured LLM as a judge.
    """

    client = create_openai_client()

    candidates = []

    for i, chunk in enumerate(chunks, 1):
        candidates.append(
            {
                "index": i,
                "chunk_id": chunk.chunk_id,
                "section_title": chunk.section_title,
                "content": chunk.content,
            }
        )

    prompt = (
        "You are reranking retrieved document chunks for a RAG system.\n\n"
        "Question:\n"
        f"{question}\n\n"
        "Below are candidate chunks.\n"
        "Rank them by how useful they are for answering the question.\n"
        "Consider semantic relevance, not only exact keyword overlap.\n"
        "Prefer chunks containing concrete evidence needed for a complete answer.\n\n"
        "Return ONLY valid JSON in this format:\n"
        '{"ranking": [1, 2, 3, 4]}\n\n'
    )

    for candidate in candidates:
        prompt += (
            f"\n--- CANDIDATE {candidate['index']} ---\n"
            f"Section: {candidate['section_title']}\n"
            f"{candidate['content']}\n"
        )

    response = client.chat.completions.create(
        model=settings.llm_model,
        temperature=0,
        max_tokens=200,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise semantic reranker for retrieval systems. "
                    "Always return valid JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )    

    raw = (response.choices[0].message.content or "").strip()

    print("\nRAW RERANK RESPONSE:")
    print(repr(raw))

    if raw.startswith("```"):
        raw = raw.strip("`")

        if raw.startswith("json"):
            raw = raw[4:].strip()

    data = json.loads(raw)

    ranking = data["ranking"]

    ranked_chunks = []

    for index in ranking:
        if 1 <= index <= len(chunks):
            ranked_chunks.append(chunks[index - 1])

        if len(ranked_chunks) == final_k:
            break

    return ranked_chunks


print()
print("LLM SEMANTIC RERANK TEST")
print("-" * 80)

for case in evaluation_cases:
    item = case["item"]

    if item["category"] != "multi_context":
        continue

    chunks = case["chunks"]

    reranked = llm_rerank(
        item["question"],
        chunks,
        final_k=4,
    )

    print()
    print(item["eval_id"])

    for i, chunk in enumerate(reranked, 1):
        print(
            f" {i}. {chunk.section_title} "
            f"| {chunk.chunk_id}"
        )

        if item["eval_id"] == "MULTI_001_FBCB":
            print(
                "    SMART GREEN:",
                "SMART GREEN" in chunk.content,
                "| OFFSET:",
                "OFFSET" in chunk.content,
            )