"""
redactor.py
Generates section drafts using retrieved context, directives,
and previously approved sections as narrative memory.
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass

from openai import OpenAI
from scripts.retriever import retrieve, format_chunks_for_prompt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────

LLM_MODEL       = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", 2048))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0.3))


# ─────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are an expert writer specializing in European NGO project proposals,
specifically for Erasmus+ and similar EU funding programmes.

Your writing is formal, technical and evidence-based.
You write exclusively in English.

STRICT RULES — these are non-negotiable:
1. Only use information explicitly present in the provided context
2. If required data is not in the context, write [DATA NOT FOUND] — never fill the gap
3. Never calculate, estimate or invent figures — copy them literally from context
4. Tables must never be modified — reference them but do not rewrite them
5. Flag any partner or consortium information with [NEEDS REVIEW]
6. If you are unsure about any fact, flag it with [VERIFY]
7. Do not add conclusions, recommendations or opinions not grounded in the context

Your goal is to produce a draft that is faithful to the source documents,
coherent with already approved sections, and aligned with the provided directives.
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

def generate_draft(
    section_name:      str,
    user_instruction:  str,
    approved_sections: dict[str, str] | None = None,
    top_k:             int = 3,
    directives_path:   Path | None = None,
    chroma_dir:        str | None = None,
) -> DraftResult:
    """
    Main entry point for draft generation.

    Args:
        section_name:      Name of the section being written
        user_instruction:  Specific instruction from the user
        approved_sections: Dict of {section_name: content} already approved
        top_k:             Number of chunks to retrieve
        directives_path:   Path to directives.md — passed from Streamlit session
        chroma_dir:        Path to ChromaDB directory — passed from Streamlit session
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Step 1 — Load directives
    resolved_directives = directives_path or Path(
        os.getenv("DIRECTIVES_PATH", "config/directives.md")
    )
    directives   = load_directives(resolved_directives)
    call_context = extract_call_context(directives)
    section_dir  = extract_section_directive(directives, section_name)

    # Step 2 — Retrieve context chunks
    query        = f"{section_name} {user_instruction}"
    chunks       = retrieve(query, top_k=top_k, chroma_dir=chroma_dir)
    context_text = format_chunks_for_prompt(chunks)

    logger.info(f"Generating draft for : '{section_name}'")
    logger.info(f"Chunks retrieved     : {len(chunks)}")
    logger.info(f"Approved sections    : {len(approved_sections or {})}")
    logger.info(f"Directives path      : {resolved_directives}")
    logger.info(f"Call context present : {bool(call_context)}")

    # Step 3 — Assemble prompt
    # Call context goes first — static block, gets cached by OpenAI
    user_prompt = build_user_prompt(
        section_name      = section_name,
        user_instruction  = user_instruction,
        context_chunks    = context_text,
        approved_sections = approved_sections or {},
        directives        = section_dir,
        call_context      = call_context,
    )

    # Step 4 — Call OpenAI with prompt cache params
    response = client.chat.completions.create(
        model       = LLM_MODEL,
        max_tokens  = LLM_MAX_TOKENS,
        temperature = LLM_TEMPERATURE,
        messages    = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        extra_body = {
            "prompt_cache_key":       "trustlabs_redactor",
            "prompt_cache_retention": "24h",
        }
    )

    draft = response.choices[0].message.content.strip()
    usage = response.usage

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