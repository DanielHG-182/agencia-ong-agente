"""
views/redactor.py
Redactor view — generate, edit and approve section drafts.
"""

from pathlib import Path

import streamlit as st

from scripts.redactor import generate_draft
from scripts.exporter import export_document, Section

from scripts.section_service import (
    get_approved_sections_before,
    mark_downstream_needs_review,
    save_sections,
    update_section,
)

# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def export_single_section(section: dict) -> Path:
    """Exports a single section as a .docx file."""
    paths   = st.session_state.paths
    project = st.session_state.active_project

    return export_document(
        sections      = [Section(
            name    = section["name"],
            content = section["content"],
            level   = section["level"],
        )],
        project_name  = project,
        output_dir    = paths["output"],
        template_path = paths["template"],
    )


# ─────────────────────────────────────────────────────────
# UNSAVED CHANGES DIALOG
# ─────────────────────────────────────────────────────────

@st.dialog("Unsaved draft")
def unsaved_changes_dialog(destination: str, navigate_to):
    st.warning(
        "You have an unsaved draft. What do you want to do?",
        icon="⚠️"
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("💾 Save draft", use_container_width=True, type="primary"):
            index   = st.session_state.active_section
            section = st.session_state.sections[index]

            update_section(section=section,content=st.session_state.current_draft,status="draft",)
            save_sections(st.session_state.paths["progress"],st.session_state.sections,)

            st.session_state.unsaved_changes = False
            navigate_to(destination)

    with col2:
        if st.button("🗑 Discard", use_container_width=True):
            st.session_state.unsaved_changes = False
            st.session_state.current_draft   = None
            st.session_state.current_retrieved_chunks = []
            navigate_to(destination)

    with col3:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# ─────────────────────────────────────────────────────────
# NAVIGATION WITHIN REDACTOR
# ─────────────────────────────────────────────────────────

def navigate_section(direction: int, navigate_to):
    """Moves to previous (-1) or next (+1) section."""
    if st.session_state.unsaved_changes:
        unsaved_changes_dialog("redactor", navigate_to)
        return

    index     = st.session_state.active_section
    sections  = st.session_state.sections
    new_index = index + direction

    if 0 <= new_index < len(sections):
        st.session_state.active_section  = new_index
        st.session_state.current_draft   = sections[new_index].get("content") or None
        st.session_state.current_retrieved_chunks = []
        st.session_state.unsaved_changes = False
        st.rerun()


# ─────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────

def render(navigate_to):
    sections = st.session_state.sections
    index    = st.session_state.active_section
    paths    = st.session_state.paths

    if not sections:
        st.error("No sections defined. Go back and add sections first.")
        if st.button("← Back to Sections"):
            navigate_to("sections_manager")
        return

    # Clamp index
    index = max(0, min(index, len(sections) - 1))
    st.session_state.active_section = index

    section = sections[index]
    total   = len(sections)

    # ── Header ──────────────────────────────────────────
    col_back, col_title, col_nav = st.columns([1, 4, 2])

    with col_back:
        if st.button("← Sections"):
            if st.session_state.unsaved_changes:
                unsaved_changes_dialog("sections_manager", navigate_to)
            else:
                navigate_to("sections_manager")

    with col_title:
        st.markdown(f"### ✏️ {section['name']}")
        st.caption(f"Section {index + 1} of {total}  ·  H{section['level']}")

    with col_nav:
        prev_col, next_col = st.columns(2)
        with prev_col:
            if st.button(
                "⬅ Prev",
                disabled=index == 0,
                use_container_width=True
            ):
                navigate_section(-1, navigate_to)
        with next_col:
            if st.button(
                "Next ➡",
                disabled=index == total - 1,
                use_container_width=True
            ):
                navigate_section(1, navigate_to)

    st.divider()

    # ── Layout: controls | draft ─────────────────────────
    col_controls, col_draft = st.columns([1, 2])

    with col_controls:
        st.markdown("**Instruction**")
        instruction = st.text_area(
            label            = "instruction",
            value            = section.get("instruction", ""),
            height           = 150,
            placeholder      = "Describe what this section should cover...",
            label_visibility = "collapsed",
        )

        if instruction != section.get("instruction", ""):
            section["instruction"] = instruction
            save_sections(st.session_state.paths["progress"],st.session_state.sections,)

        st.divider()

        # Vector DB check
        vector_db_path   = paths["vector_db"]
        vector_db_exists = (
            vector_db_path.exists() and
            any(vector_db_path.iterdir())
        )

        if not vector_db_exists:
            st.error(
                "This project is not ready for drafting yet. "
                "Build the document index first, then return here to generate grounded drafts."
            )

            st.caption(
                "CLI: "
                f"`python main.py --stage indexing --project "
                f"{st.session_state.active_project}`"
            )

        generate_disabled = not vector_db_exists or not instruction.strip()

        # Generate button
        if st.button(
            "⚡ Generate draft",
            use_container_width = True,
            type                = "primary",
            disabled            = generate_disabled,
            help                = "Write an instruction first" if not instruction.strip() else ""
        ):
            approved_before = get_approved_sections_before(st.session_state.sections,index,)

            with st.spinner(f"Generating '{section['name']}'..."):
                try:
                    result = generate_draft(
                        section_name      = section["name"],
                        user_instruction  = instruction,
                        approved_sections = approved_before,
                        directives_path   = paths["directives"],   # ← from session
                        chroma_dir        = str(paths["vector_db"]), # ← from session
                    )
                    st.session_state.current_draft   = result.content
                    st.session_state.current_retrieved_chunks = result.retrieved_chunks
                    st.session_state.unsaved_changes = True
                    st.caption(
                        f"Tokens — in: {result.prompt_tokens} "
                        f"/ out: {result.output_tokens} "
                        f"· Chunks: {result.chunks_used}"
                    )
                except Exception as e:
                    st.error(f"Generation failed: {e}")

        st.divider()

        # Show the exact chunks used to generate the current draft
        if st.session_state.show_chunks:
            st.markdown("**Retrieved context used for this draft**")

            chunks = st.session_state.get(
                "current_retrieved_chunks",
                [],
            )

            if chunks:
                for chunk in chunks:
                    with st.expander(
                        f"[{chunk.relevance_score:.2f}] "
                        f"{chunk.source_file} — {chunk.section_title}"
                    ):
                        st.markdown(chunk.content)
            else:
                st.caption(
                    "No retrieved context available for the current draft."
                )

    with col_draft:
        st.markdown("**Draft**")

        draft_content = st.text_area(
            label            = "draft",
            value            = st.session_state.current_draft or "",
            height           = 500,
            placeholder      = "Draft will appear here after generation. "
                               "You can also type or paste content directly.",
            label_visibility = "collapsed",
        )

        if draft_content != (st.session_state.current_draft or ""):
            st.session_state.current_draft   = draft_content
            st.session_state.unsaved_changes = True

        st.divider()

        act1, act2, act3, act4 = st.columns(4)

        with act1:
            if st.button(
                "✅ Approve",
                use_container_width = True,
                type                = "primary",
                disabled            = not draft_content.strip(),
            ):
                update_section( section,content=draft_content,status="approved",)
                mark_downstream_needs_review(st.session_state.sections,index,)
                save_sections(st.session_state.paths["progress"],st.session_state.sections,)
                st.session_state.unsaved_changes = False
                st.session_state.current_draft   = draft_content
                st.success(f"Section '{section['name']}' approved!")
                st.rerun()

        with act2:
            if st.button(
                "💾 Save draft",
                use_container_width = True,
                disabled            = not draft_content.strip(),
            ):
                update_section(section,content=draft_content,status="draft",)
                save_sections(st.session_state.paths["progress"],st.session_state.sections,)
                st.session_state.unsaved_changes = False
                st.success("Draft saved!")
                st.rerun()

        with act3:
            if st.button(
                "🔄 Regenerate",
                use_container_width = True,
                disabled            = not instruction.strip() or not vector_db_exists,
            ):
                approved_before = get_approved_sections_before(st.session_state.sections,index,)
                with st.spinner("Regenerating..."):
                    try:
                        result = generate_draft(
                            section_name      = section["name"],
                            user_instruction  = instruction,
                            approved_sections = approved_before,
                            directives_path   = paths["directives"],    # ← from session
                            chroma_dir        = str(paths["vector_db"]), # ← from session
                        )
                        st.session_state.current_draft   = result.content
                        st.session_state.current_retrieved_chunks = result.retrieved_chunks
                        st.session_state.unsaved_changes = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Regeneration failed: {e}")

        with act4:
            if st.button(
                "📄 Export section",
                use_container_width = True,
                disabled            = not draft_content.strip(),
            ):
                with st.spinner("Exporting..."):
                    try:
                        output_path = export_single_section({
                            "name":    section["name"],
                            "content": draft_content,
                            "level":   section["level"],
                        })
                        with open(output_path, "rb") as f:
                            st.download_button(
                                label       = "⬇ Download .docx",
                                data        = f,
                                file_name   = output_path.name,
                                mime        = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                use_container_width = True,
                            )
                    except Exception as e:
                        st.error(f"Export failed: {e}")