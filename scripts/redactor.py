"""
redactor.py
Generates section drafts using retrieved context, directives,
and previously approved sections as narrative memory.
"""

import logging
from pathlib import Path
from dataclasses import dataclass

from typing import Any

from openai import OpenAI, OpenAIError, RateLimitError
from scripts.clients import create_openai_client
from scripts.config import settings

from scripts.retriever import retrieve, format_chunks_for_prompt
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
# SYSTEM PROMPT: AI Writer & Analyst for EU Project Proposals

## 1. ROLE & IDENTITY
You are an expert AI writer specializing in drafting and analyzing European NGO project proposals, specifically for Erasmus+ and similar EU funding programmes. Your writing style is formal, objective, technical, and strictly evidence-based. You write exclusively in English.

## 2. INFORMATION PRIORITIZATION & CONTEXT SCANNING
EU grant applications and reference texts contain extensive background data, complex project codes, and partner breakdowns.
- Prioritize high-level definitions, direct instructions, and explicit project components over surrounding technical or regional statistics.
- Scan partner descriptions and previous project lists thoroughly. Technical standards, frameworks, or metrics mentioned within these dense sections must be extracted directly if they correlate with the question.

## 3. STRICT BOUNDEDNESS & VERBATIM INTEGRITY (Anti-Hallucination Lock)
- Rely ONLY on the clear facts directly mentioned in the provided context. Do not use outside knowledge, external regulations, or speculative extrapolations.
- **Drafting Constraint:** When answering or drafting, use the exact terminology, names, and technical standards present in the text (e.g., if the text mentions "workshops", describe the activity as "workshops"). Do not introduce external synonyms, paraphrases, or descriptive adjectives that are not explicitly in the text, as this triggers evaluation failures.
- Copy all numbers, budgets, dates, and quantitative figures literally. Do not calculate, estimate, or modify any statistical data.
- Structure your response to be direct, professional, and completely aligned with the user's inquiry, avoiding unnecessary preambles or conversational filler.

## 4. MISSING INFORMATION & STRICT ESCAPE PROTOCOL
- If the context completely lacks any facts, direct mentions, or specific technical fragments related to the question, state exactly: "The provided context does not contain sufficient information to answer this question."
- Do not attempt to deduce, infer, or build an answer for questions where the specific technical term or activity is missing. If a question asks about an untraceable element, you MUST trigger the exact missing information phrase.
""".strip()


# ─────────────────────────────────────────────────────────
# DIRECTIVES LOADER
# ─────────────────────────────────────────────────────────

def load_directives(path: Path) -> str:
    """
    Reads the full directives.md file.
    Returns empty string if file not found — generation continues without it.
    """
    if not path.exists():
        logger.warning(f"Directives file not found: {path}")
        return ""

    content = path.read_text(encoding="utf-8")
    logger.info(f"Directives loaded from {path}")
    return content


def extract_section_directive(directives: str, section_name: str) -> str:
    """
    Extracts the specific directive block for a given section name.
    Falls back to global directives if section not found.
    """
    if not directives:
        return ""

    lines          = directives.splitlines()
    section_lines  = []
    inside_section = False
    search_term    = section_name.lower()

    for line in lines:
        stripped = line.strip().lower()

        if not inside_section:
            if stripped.startswith("#") and search_term in stripped:
                inside_section = True
                section_lines.append(line)
            continue

        if stripped.startswith("#"):
            break

        section_lines.append(line)

    if section_lines:
        logger.debug(f"Section directive found for: '{section_name}'")
        return "\n".join(section_lines)

    logger.debug(f"No specific directive for '{section_name}' — using global directives")
    return extract_global_directives(directives)


def extract_global_directives(directives: str) -> str:
    """
    Extracts Tone and Style + Global Restrictions + Call Notes.
    These always apply regardless of the section being written.
    """
    global_sections = ["1. tone and style", "4. global restrictions", "5. call notes"]
    lines           = directives.splitlines()
    result          = []
    inside          = False
    current_level   = None

    for line in lines:
        stripped = line.strip().lower()

        if stripped.startswith("#"):
            if any(s in stripped for s in global_sections):
                inside        = True
                current_level = len(line) - len(line.lstrip("#"))
                result.append(line)
                continue
            elif inside:
                new_level = len(line) - len(line.lstrip("#"))
                if new_level <= current_level:
                    inside = False
                    continue

        if inside:
            result.append(line)

    return "\n".join(result)


# ─────────────────────────────────────────────────────────
# PROMPT ASSEMBLY
# ─────────────────────────────────────────────────────────

def build_user_prompt(
    section_name:      str,
    user_instruction:  str,
    context_chunks:    str,
    approved_sections: dict[str, str],
    directives:        str,
    call_context:      str,
    mode: str = "draft",
) -> str:
    blocks = []

    # ── ESTÁTICO primero — se cachea ─────────────────────
    if call_context:
        blocks.append(
            "## CALL CONTEXT AND THEMATIC FRAMEWORK\n"
            "Integrate these themes as the project's own rationale — "
            "never cite them as external requirements.\n\n"
            f"{call_context}"
        )

    if directives:
        blocks.append(
            "## SECTION DIRECTIVES\n"
            f"{directives}"
        )

    # ── DINÁMICO después — cambia por sección ────────────
    if context_chunks:
        blocks.append(
            "## CONTEXT\n"
            "Use only this information — do not add anything not present here.\n\n"
            f"{context_chunks}"
        )
    else:
        blocks.append(
            "## CONTEXT\n"
            "No relevant context retrieved. Mark all data points as [DATA NOT FOUND]."
        )

    if approved_sections:
        approved_text = "\n\n---\n\n".join(
            f"### {name}\n{content}"
            for name, content in approved_sections.items()
        )
        blocks.append(
            "## APPROVED SECTIONS\n"
            "Maintain narrative coherence. Avoid contradictions.\n\n"
            f"{approved_text}"
        )

    if mode == "evaluation":
        blocks.append(
            "## TASK\n"
            "Answer the user's question using only the provided CONTEXT.\n"
            "If the answer is explicitly present in the context, answer directly using the same terminology.\n"
            "If the answer is not explicitly present in the context, state exactly:\n"
            "\"The provided context does not contain sufficient information to answer this question.\"\n\n"
            f"Question: {user_instruction}"
        )
    else:
        blocks.append(
            f"## TASK\n"
            f"Write the following section: **{section_name}**\n\n"
            f"{user_instruction}"
        )
    
    return "\n\n---\n\n".join(blocks)


# ─────────────────────────────────────────────────────────
# DRAFT GENERATION
# ─────────────────────────────────────────────────────────

@dataclass
class DraftResult:
    section_name:   str
    content:        str
    model:          str
    prompt_tokens:  int
    output_tokens:  int
    chunks_used:    int

# Best Practice: Define a robust, enterprise-grade retry policy
# This catches 429 (RateLimitError) and generic server errors, applying 
# an exponential backoff with random jitter (e.g., wait 2s, then 4s, then 8s... up to 60s)
@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_random_exponential(min=2, max=60, multiplier=1),
    retry=retry_if_exception_type((RateLimitError, OpenAIError)),
    before_sleep=lambda retry_state: logger.warning(
        f"Rate limit or API error detected. Retrying attempt {retry_state.attempt_number}... "
        f"Waiting {retry_state.next_action.sleep} seconds before next request."
    )
)

def _call_openai_with_retry(
    client: OpenAI,
    messages: list[dict[str, str]],
) -> tuple[str, Any]:
    """
    Execute the OpenAI request with exponential backoff and jitter.
    """

    response = client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        messages=messages,
        extra_body={
            "prompt_cache_key": "document_assistant_redactor",
            "prompt_cache_retention": "24h",
        },
    )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("OpenAI returned an empty draft.")

    return content.strip(), response.usage

def generate_draft(
    section_name: str,
    user_instruction: str,
    approved_sections: dict[str, str] | None = None,
    top_k: int = settings.retriever_top_k,
    directives_path: Path | None = None,
    chroma_dir: str | None = None,
    retrieval_query: str | None = None,
    mode: str = "draft",
) -> DraftResult:
    """
    Generate a section draft using retrieved context and project directives.

    Args:
        section_name: Name of the section being written.
        user_instruction: Specific instruction from the user.
        approved_sections: Previously approved sections used for coherence.
        top_k: Number of chunks to retrieve.
        directives_path: Path to the project's directives file.
        chroma_dir: Path to the active project's ChromaDB directory.
        retrieval_query: Optional custom query for retrieval.
        mode: Generation mode, such as "draft" or "evaluation".

    Returns:
        The generated draft and usage metadata.
    """

    resolved_directives = directives_path or Path("config/directives.md")

    directives = load_directives(resolved_directives)
    call_context = extract_call_context(directives)
    section_directive = extract_section_directive(
        directives,
        section_name,
    )

    query = retrieval_query or f"{section_name} {user_instruction}"

    chunks = retrieve(
        query,
        top_k=top_k,
        chroma_dir=chroma_dir,
    )
    context_text = format_chunks_for_prompt(chunks)

    logger.info("Generating draft for : '%s'", section_name)
    logger.info("Chunks retrieved     : %s", len(chunks))
    logger.info(
        "Approved sections    : %s",
        len(approved_sections or {}),
    )
    logger.info("Directives path      : %s", resolved_directives)
    logger.info("Call context present : %s", bool(call_context))

    user_prompt = build_user_prompt(
        section_name=section_name,
        user_instruction=user_instruction,
        context_chunks=context_text,
        approved_sections=approved_sections or {},
        directives=section_directive,
        call_context=call_context,
        mode=mode,
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    client = create_openai_client()

    try:
        draft, usage = _call_openai_with_retry(
            client,
            messages,
        )
    except RateLimitError as exc:
        logger.error(
            "Execution failed: API rate limit completely exhausted. "
            "Details: %s",
            exc,
        )
        raise
    except OpenAIError as exc:
        logger.error(
            "Execution failed: OpenAI service error. Details: %s",
            exc,
        )
        raise

    prompt_tokens_details = getattr(
        usage,
        "prompt_tokens_details",
        None,
    )

    if prompt_tokens_details is not None:
        cached_tokens = getattr(
            prompt_tokens_details,
            "cached_tokens",
            0,
        )
        logger.info("Cached tokens        : %s", cached_tokens)

    logger.info(
        "Draft generated — prompt tokens: %s | output tokens: %s",
        usage.prompt_tokens,
        usage.completion_tokens,
    )

    return DraftResult(
        section_name=section_name,
        content=draft,
        model=settings.llm_model,
        prompt_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        chunks_used=len(chunks),
    )

def extract_call_context(directives: str) -> str:
    """Extracts Section 2 — always injected first so it gets cached."""
    lines  = directives.splitlines()
    result = []
    inside = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# 2."):
            inside = True
            continue
        if inside and stripped.startswith("# ") and not stripped.startswith("# 2."):
            break
        if inside:
            result.append(line)

    return "\n".join(result).strip()