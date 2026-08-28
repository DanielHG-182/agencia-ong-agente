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

from scripts.retriever import (
    RetrievedChunk,
    retrieve,
    format_chunks_for_prompt,
)

from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type
from scripts.directives import (
    extract_call_context,
    extract_section_directive,
    load_directives,
)

from scripts.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

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
    retrieved_chunks: list[RetrievedChunk] | None = None,
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

    if retrieved_chunks is not None:
        chunks = retrieved_chunks
    else:
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