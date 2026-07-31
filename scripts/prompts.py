"""Prompt templates and assembly helpers for proposal drafting."""


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
- **Drafting Constraint:** When answering or drafting, use the exact terminology, names, and technical standards present in the text.
- Copy all numbers, budgets, dates, and quantitative figures literally.
- Structure your response to be direct, professional, and completely aligned with the user's inquiry.

## 4. MISSING INFORMATION & STRICT ESCAPE PROTOCOL
- If the context completely lacks any facts, direct mentions, or specific technical fragments related to the question, state exactly:
"The provided context does not contain sufficient information to answer this question."
- Do not attempt to deduce, infer, or build an answer for questions where the specific technical term or activity is missing.
""".strip()


def build_user_prompt(
    section_name: str,
    user_instruction: str,
    context_chunks: str,
    approved_sections: dict[str, str],
    directives: str,
    call_context: str,
    mode: str = "draft",
) -> str:
    """Assemble the user prompt for drafting or evaluation."""

    blocks: list[str] = []

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

    if context_chunks:
        blocks.append(
            "## CONTEXT\n"
            "Use only this information — do not add anything not present here.\n\n"
            f"{context_chunks}"
        )
    else:
        blocks.append(
            "## CONTEXT\n"
            "No relevant context retrieved. Mark all data points as "
            "[DATA NOT FOUND]."
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
            "If the answer is explicitly present in the context, answer "
            "directly using the same terminology.\n"
            "If the answer is not explicitly present in the context, state "
            "exactly:\n"
            "\"The provided context does not contain sufficient information "
            "to answer this question.\"\n\n"
            f"Question: {user_instruction}"
        )
    else:
        blocks.append(
            "## TASK\n"
            f"Write the following section: **{section_name}**\n\n"
            f"{user_instruction}"
        )

    return "\n\n---\n\n".join(blocks)