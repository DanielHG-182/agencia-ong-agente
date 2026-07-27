"""
redactor.py
Generates section drafts using retrieved context, directives,
and previously approved sections as narrative memory.
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

from openai import OpenAI, OpenAIError, RateLimitError
from scripts.retriever import retrieve, format_chunks_for_prompt
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)
load_dotenv()

openai_client = OpenAI()

# ─────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────

LLM_MODEL       = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", 2048))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0.0))


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
            "Integrate these themes as TRUSTLABS own rationale — "
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

def _call_openai_with_retry(messages: list[dict[str, str]]) -> tuple[str, any]:
    """
    Isolated wrapper for OpenAI API execution protected by exponential backoff with jitter.
    """
    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        messages=messages,
        extra_body={
            "prompt_cache_key": "trustlabs_redactor",
            "prompt_cache_retention": "24h",
        }
    )
    draft = response.choices[0].message.content.strip()
    return draft, response.usage


def generate_draft(
    section_name: str,
    user_instruction: str,
    approved_sections: dict[str, str] | None = None,
    top_k: int = 3,
    directives_path: Path | None = None,
    chroma_dir: str | None = None,
    retrieval_query: str | None = None,
    mode: str = "draft"
) -> DraftResult:
    """
    Main entry point for draft generation. Protected against 429 Rate Limit Errors 
    via automated exponential backoff with jitter.

    Args:
        section_name:      Name of the section being written
        user_instruction:  Specific instruction from the user
        approved_sections: Dict of {section_name: content} already approved
        top_k:             Number of chunks to retrieve
        directives_path:   Path to directives.md — passed from Streamlit session
        chroma_dir:        Path to ChromaDB directory — passed from Streamlit session
    """
    # Step 1 — Load directives
    resolved_directives = directives_path or Path(
        os.getenv("DIRECTIVES_PATH", "config/directives.md")
    )
    directives   = load_directives(resolved_directives)
    call_context = extract_call_context(directives)
    section_dir  = extract_section_directive(directives, section_name)

    # Step 2 — Retrieve context chunks
    query = retrieval_query or f"{section_name} {user_instruction}"
    chunks       = retrieve(query, top_k=top_k, chroma_dir=chroma_dir)
    context_text = format_chunks_for_prompt(chunks)

    logger.info(f"Generating draft for : '{section_name}'")
    logger.info(f"Chunks retrieved     : {len(chunks)}")
    logger.info(f"Approved sections    : {len(approved_sections or {})}")
    logger.info(f"Directives path      : {resolved_directives}")
    logger.info(f"Call context present : {bool(call_context)}")

    # Step 3 — Assemble prompt
    user_prompt = build_user_prompt(
        section_name      = section_name,
        user_instruction  = user_instruction,
        context_chunks    = context_text,
        approved_sections = approved_sections or {},
        directives        = section_dir,
        call_context      = call_context,
        mode              = mode,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]

    # Step 4 — Call OpenAI using the highly-resilient isolated function
    try:
        draft, usage = _call_openai_with_retry(messages)
    except RateLimitError as e:
        logger.error(f"Execution failed: API Rate limit completely exhausted. Details: {e}")
        raise e
    except OpenAIError as e:
        logger.error(f"Execution failed: OpenAI service error. Details: {e}")
        raise e

    # Log cache usage if available
    if hasattr(usage, "prompt_tokens_details"):
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0)
        logger.info(f"Cached tokens        : {cached}")

    logger.info(
        f"Draft generated — "
        f"prompt tokens: {usage.prompt_tokens} | "
        f"output tokens: {usage.completion_tokens}"
    )

    return DraftResult(
        section_name  = section_name,
        content       = draft,
        model         = LLM_MODEL,
        prompt_tokens = usage.prompt_tokens,
        output_tokens = usage.completion_tokens,
        chunks_used   = len(chunks),
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