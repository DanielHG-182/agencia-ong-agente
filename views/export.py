"""
views/export.py
Export view — select sections and export to .docx
"""

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from scripts.exporter import export_document, Section


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def build_export_sections(selected: list[dict]) -> list[Section]:
    """Converts session section dicts to Section dataclass objects."""
    return [
        Section(
            name    = s["name"],
            content = s["content"],
            level   = s["level"],
        )
        for s in selected
    ]


def do_export(
    sections:  list[dict],
    key:       str,
    paths:     dict,
    project:   str,
    label:     str,
):
    """
    Renders export button and download link.
    Reusable across all three tabs.
    Passes output_dir and template_path directly from session paths.
    """
    col1, col2 = st.columns([1, 2])

    with col1:
        if st.button(label, key=key, use_container_width=True, type="primary"):
            with st.spinner("Generating document..."):
                try:
                    export_sections = build_export_sections(sections)
                    output_path     = export_document(
                        sections      = export_sections,
                        project_name  = project,
                        output_dir    = paths["output"],        # ← from session
                        template_path = paths.get("template"),  # ← from session
                    )
                    st.session_state[f"{key}_output"] = str(output_path)
                    st.success(f"Document generated: `{output_path.name}`")

                except Exception as e:
                    st.error(f"Export failed: {e}")

    # Download button — appears after successful export
    output_key = f"{key}_output"
    if output_key in st.session_state and st.session_state[output_key]:
        output_path = Path(st.session_state[output_key])
        if output_path.exists():
            with col2:
                with open(output_path, "rb") as f:
                    st.download_button(
                        label               = f"⬇ Download {output_path.name}",
                        data                = f,
                        file_name           = output_path.name,
                        mime                = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key                 = f"{key}_download",
                        use_container_width = True,
                    )


# ─────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────

def render(navigate_to):
    project  = st.session_state.active_project
    paths    = st.session_state.paths
    sections = st.session_state.sections

    # ── Header ──────────────────────────────────────────
    col_title, col_back = st.columns([3, 1])

    with col_title:
        st.title("📤 Export Document")
        st.caption(f"Project: {project}")

    with col_back:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("← Back to Sections", use_container_width=True):
            navigate_to("sections_manager")

    st.divider()

    # ── Status summary ───────────────────────────────────
    total        = len(sections)
    approved     = [s for s in sections if s.get("status") == "approved"]
    draft        = [s for s in sections if s.get("status") == "draft"]
    needs_review = [s for s in sections if s.get("status") == "needs_review"]
    pending      = [s for s in sections if s.get("status") == "pending"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total",       total)
    m2.metric("✅ Approved", len(approved))
    m3.metric("📝 Draft",    len(draft))
    m4.metric("⚠️ Review",  len(needs_review))
    m5.metric("⬜ Pending",  len(pending))

    st.divider()

    # ── Warning: needs review ────────────────────────────
    if needs_review:
        with st.expander(
            f"⚠️ {len(needs_review)} section(s) marked as needs review",
            expanded=True
        ):
            st.warning(
                "These sections were approved before a previous section "
                "was edited. Consider reviewing them before exporting.",
                icon="⚠️"
            )
            for s in needs_review:
                st.markdown(f"- {s['name']}")

    # ── Export tabs ──────────────────────────────────────
    st.markdown("### Export options")

    tab1, tab2, tab3 = st.tabs([
        "✅ Approved only",
        "📋 Custom selection",
        "📝 Include drafts",
    ])

    # ── Tab 1: Approved only ─────────────────────────────
    with tab1:
        if not approved:
            st.info(
                "No approved sections yet. "
                "Approve sections in the redactor first."
            )
        else:
            st.markdown(f"**{len(approved)} approved section(s):**")
            for s in approved:
                indent = "　" * (s["level"] - 1)
                st.markdown(f"{indent}✅ {s['name']}")

            st.divider()
            do_export(
                sections = approved,
                key      = "export_approved",
                paths    = paths,
                project  = project,
                label    = f"📤 Export {len(approved)} approved sections",
            )

    # ── Tab 2: Custom selection ──────────────────────────
    with tab2:
        exportable = [
            s for s in sections
            if s.get("content", "").strip()
        ]

        if not exportable:
            st.info("No sections with content available for export.")
        else:
            st.markdown("Select the sections you want to export:")

            col_all, col_none, _ = st.columns([1, 1, 3])
            with col_all:
                if st.button("Select all", use_container_width=True):
                    for s in exportable:
                        st.session_state[f"sel_{s['name']}"] = True
                    st.rerun()
            with col_none:
                if st.button("Deselect all", use_container_width=True):
                    for s in exportable:
                        st.session_state[f"sel_{s['name']}"] = False
                    st.rerun()

            st.divider()

            selected = []
            for s in exportable:
                status_icon = {
                    "approved":     "✅",
                    "draft":        "📝",
                    "needs_review": "⚠️",
                }.get(s.get("status"), "⬜")

                indent  = "　" * (s["level"] - 1)
                checked = st.checkbox(
                    f"{indent}{status_icon} {s['name']}",
                    key   = f"sel_{s['name']}",
                    value = s.get("status") == "approved",
                )
                if checked:
                    selected.append(s)

            st.divider()

            if selected:
                do_export(
                    sections = selected,
                    key      = "export_custom",
                    paths    = paths,
                    project  = project,
                    label    = f"📤 Export {len(selected)} selected sections",
                )
            else:
                st.info("Select at least one section to export.")

    # ── Tab 3: Include drafts ────────────────────────────
    with tab3:
        with_drafts = approved + draft + needs_review

        if not with_drafts:
            st.info("No sections with content available.")
        else:
            st.markdown(
                f"**{len(with_drafts)} section(s)** will be exported "
                f"(approved + drafts + needs review):"
            )

            if needs_review:
                st.warning(
                    "This export includes sections marked as needs review.",
                    icon="⚠️"
                )

            for s in with_drafts:
                status_icon = {
                    "approved":     "✅",
                    "draft":        "📝",
                    "needs_review": "⚠️",
                }.get(s.get("status"), "⬜")
                indent = "　" * (s["level"] - 1)
                st.markdown(f"{indent}{status_icon} {s['name']}")

            st.divider()
            do_export(
                sections = with_drafts,
                key      = "export_with_drafts",
                paths    = paths,
                project  = project,
                label    = f"📤 Export {len(with_drafts)} sections",
            )
