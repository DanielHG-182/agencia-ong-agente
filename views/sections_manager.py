"""
views/sections_manager.py
Sections manager view — define, reorder and manage document sections.
"""

import json
from datetime import datetime

import streamlit as st


# ─────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────

STATUS_ICONS = {
    "pending":      "⬜",
    "draft":        "📝",
    "approved":     "✅",
    "needs_review": "⚠️",
}

HEADING_LEVELS = ["H1", "H2", "H3", "H4", "H5"]


# ─────────────────────────────────────────────────────────
# PROGRESS PERSISTENCE
# ─────────────────────────────────────────────────────────

def save_sections():
    """Persists current sections to progress.json."""
    paths         = st.session_state.paths
    progress_path = paths["progress"]

    try:
        existing = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

    existing["sections"]      = st.session_state.sections
    existing["last_modified"] = datetime.now().isoformat()

    progress_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def mark_downstream_needs_review(edited_index: int):
    """
    When a section is edited or re-approved, marks all subsequent
    approved sections as needs_review to flag potential incoherence.
    """
    sections = st.session_state.sections
    for i in range(edited_index + 1, len(sections)):
        if sections[i].get("status") == "approved":
            sections[i]["status"] = "needs_review"


# ─────────────────────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────────────────────

def make_section(name: str, level: str) -> dict:
    """Creates a new section dict with default values."""
    return {
        "name":           name,
        "level":          int(level.replace("H", "")),
        "instruction":    "",
        "status":         "pending",
        "content":        "",
        "last_generated": "",
    }


# ─────────────────────────────────────────────────────────
# INDEX LOADER
# ─────────────────────────────────────────────────────────

def load_index_from_file() -> list[dict] | None:
    """
    Reads index.json from the active project config folder.
    Returns None if file does not exist or is invalid.
    """
    paths      = st.session_state.paths
    index_path = paths["index"]

    if not index_path.exists():
        return None

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# DIALOGS
# ─────────────────────────────────────────────────────────

@st.dialog("Add section")
def add_section_dialog():
    st.markdown("Add a custom section to the document.")

    name  = st.text_input("Section name", placeholder="e.g. 1.4 Target Group Analysis")
    level = st.selectbox("Heading level", HEADING_LEVELS, index=1)

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Add", use_container_width=True, type="primary"):
            if not name.strip():
                st.error("Section name cannot be empty.")
                return
            st.session_state.sections.append(make_section(name.strip(), level))
            save_sections()
            st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("Load document index")
def load_index_dialog():
    index = load_index_from_file()

    if not index:
        st.error(
            "No index.json found in this project's config folder. "
            "Add one at: `config/index.json`"
        )
        if st.button("Close", use_container_width=True):
            st.rerun()
        return

    st.markdown(
        f"Found **{len(index)} sections** in `config/index.json`. "
        f"This will replace all existing sections."
    )
    st.warning("Any existing sections and drafts will be lost.", icon="⚠️")

    # Preview
    with st.expander("Preview sections"):
        for item in index:
            indent = "　" * (int(item["level"].replace("H", "")) - 1)
            st.markdown(f"{indent}`{item['level']}` {item['name']}")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Load", use_container_width=True, type="primary"):
            st.session_state.sections = [
                make_section(item["name"], item["level"])
                for item in index
            ]
            save_sections()
            st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("Delete section")
def confirm_delete_section_dialog(index: int):
    section = st.session_state.sections[index]
    st.warning(
        f"Delete section **{section['name']}**? "
        f"This cannot be undone.",
        icon="⚠️"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Yes, delete", use_container_width=True, type="primary"):
            st.session_state.sections.pop(index)
            save_sections()
            st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# ─────────────────────────────────────────────────────────
# SECTION ROW
# ─────────────────────────────────────────────────────────

def render_section_row(section: dict, index: int, navigate_to):
    """Renders a single section row with actions."""
    status       = section.get("status", "pending")
    status_icon  = STATUS_ICONS.get(status, "⬜")
    level        = section.get("level", 2)
    indent       = "　" * (level - 1)

    with st.container(border=True):
        col_status, col_name, col_level, col_actions = st.columns([0.5, 4, 1, 2])

        with col_status:
            st.markdown(f"### {status_icon}")

        with col_name:
            st.markdown(f"{indent}**{section['name']}**")
            if section.get("last_generated"):
                st.caption(f"Last generated: {section['last_generated'][:10]}")

        with col_level:
            st.markdown(f"`H{level}`")

        with col_actions:
            btn1, btn2, btn3, btn4 = st.columns(4)

            with btn1:
                if st.button(
                    "✏️", key=f"write_{index}",
                    help="Write this section"
                ):
                    st.session_state.active_section = index
                    st.session_state.current_draft  = section.get("content") or None
                    navigate_to("redactor")

            with btn2:
                if st.button(
                    "⬆", key=f"up_{index}",
                    help="Move up",
                    disabled=index == 0
                ):
                    sections = st.session_state.sections
                    sections[index], sections[index - 1] = (
                        sections[index - 1], sections[index]
                    )
                    save_sections()
                    st.rerun()

            with btn3:
                total = len(st.session_state.sections)
                if st.button(
                    "⬇", key=f"down_{index}",
                    help="Move down",
                    disabled=index == total - 1
                ):
                    sections = st.session_state.sections
                    sections[index], sections[index + 1] = (
                        sections[index + 1], sections[index]
                    )
                    save_sections()
                    st.rerun()

            with btn4:
                if st.button(
                    "🗑", key=f"del_{index}",
                    help="Delete section"
                ):
                    confirm_delete_section_dialog(index)


# ─────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────

def render(navigate_to):
    project = st.session_state.active_project
    paths   = st.session_state.paths

    # ── Header ──────────────────────────────────────────
    col_title, col_back = st.columns([3, 1])

    with col_title:
        st.title(f"📋 {project}")
        st.caption("Define and manage the sections of your document.")

    with col_back:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("← Back to Home", use_container_width=True):
            navigate_to("home")

    st.divider()

    # ── Toolbar ─────────────────────────────────────────
    tool1, tool2, tool3, tool4 = st.columns(4)

    with tool1:
        if st.button("＋ Add section", use_container_width=True):
            add_section_dialog()

    with tool2:
        if st.button(
            "📑 Load document index",
            use_container_width=True,
            help="Load sections from config/index.json"
        ):
            load_index_dialog()

    with tool3:
        sections = st.session_state.sections
        approved = [s for s in sections if s.get("status") == "approved"]
        if st.button(
            f"📤 Export approved ({len(approved)})",
            use_container_width=True,
            disabled=len(approved) == 0
        ):
            navigate_to("export")

    with tool4:
        # Pipeline status check
        vector_db_path   = paths["vector_db"]
        vector_db_exists = (
            vector_db_path.exists() and
            any(vector_db_path.iterdir())
        )
        if not vector_db_exists:
            st.warning(
                "⚠️ Index not built",
                help="Run the indexing stage before generating drafts"
            )
        else:
            st.success("✅ Index ready", )

    st.divider()

    # ── Sections list ────────────────────────────────────
    sections = st.session_state.sections

    if not sections:
        st.info(
            "No sections defined yet. "
            "Add sections manually or load a document index from config/index.json",
            icon="📋"
        )
        return

    # Summary metrics
    total        = len(sections)
    approved_n   = sum(1 for s in sections if s.get("status") == "approved")
    needs_review = sum(1 for s in sections if s.get("status") == "needs_review")
    pending      = sum(1 for s in sections if s.get("status") == "pending")
    draft_n      = sum(1 for s in sections if s.get("status") == "draft")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total",          total)
    m2.metric("✅ Approved",    approved_n)
    m3.metric("📝 Draft",       draft_n)
    m4.metric("⚠️ Review",     needs_review)
    m5.metric("⬜ Pending",     pending)

    st.divider()

    # Section rows
    for i, section in enumerate(sections):
        render_section_row(section, i, navigate_to)

    st.divider()

    # Start writing — jumps to first pending or needs_review section
    next_pending = next(
        (i for i, s in enumerate(sections)
         if s.get("status") in ("pending", "needs_review")),
        None
    )

    if next_pending is not None:
        if st.button(
            f"✏️ Start writing → {sections[next_pending]['name']}",
            type="primary",
            use_container_width=True
        ):
            st.session_state.active_section = next_pending
            st.session_state.current_draft  = None
            navigate_to("redactor")
    else:
        st.success("All sections approved! Ready to export.", icon="🎉")
        if st.button(
            "📤 Export document",
            type="primary",
            use_container_width=True
        ):
            navigate_to("export")