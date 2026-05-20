"""
app.py
Entry point for the ONG Document Assistant Streamlit app.
Manages navigation between views using session_state.
"""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────
# PAGE CONFIG — must be first Streamlit call
# ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title = "ONG Document Assistant",
    page_icon  = "📄",
    layout     = "wide",
)

# ─────────────────────────────────────────────────────────
# SESSION STATE INITIALIZATION
# ─────────────────────────────────────────────────────────

DEFAULTS = {
    "view":             "home",       # current view
    "active_project":   None,         # selected project name
    "paths":            None,         # project paths dict
    "sections":         [],           # list of section dicts
    "active_section":   0,            # index of section being edited
    "current_draft":    None,         # draft text in redactor
    "unsaved_changes":  False,        # flag for unsaved draft
    "show_chunks":      False,        # show retrieved chunks (configurable)
    "export_selection": [],           # sections selected for export
}

for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ─────────────────────────────────────────────────────────
# NAVIGATION
# ─────────────────────────────────────────────────────────

def navigate_to(view: str):
    """
    Central navigation function.
    Always use this instead of setting session_state.view directly.
    """
    st.session_state.view = view
    st.rerun()


# ─────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────

def render_sidebar():
    """
    Persistent sidebar with project info and settings.
    Only shown when a project is active.
    """
    if not st.session_state.active_project:
        return

    with st.sidebar:
        st.markdown(f"### 📁 {st.session_state.active_project}")
        st.divider()

        # Progress summary
        sections    = st.session_state.sections
        total       = len(sections)
        approved    = sum(1 for s in sections if s.get("status") == "approved")
        needs_review = sum(1 for s in sections if s.get("status") == "needs_review")
        pending     = total - approved - needs_review

        if total > 0:
            st.markdown("**Progress**")
            st.progress(approved / total if total > 0 else 0)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("✅ Approved",  approved)
                st.metric("⬜ Pending",   pending)
            with col2:
                st.metric("⚠️ Review",   needs_review)
                st.metric("📄 Total",    total)

        st.divider()

        # Navigation buttons
        if st.session_state.view != "home":
            if st.button("🏠 Home", use_container_width=True):
                navigate_to("home")

        if st.session_state.view not in ("home", "sections_manager"):
            if st.button("📋 Sections", use_container_width=True):
                navigate_to("sections_manager")

        if st.session_state.view != "export" and approved > 0:
            if st.button("📤 Export", use_container_width=True):
                navigate_to("export")

        st.divider()

        # Settings
        st.markdown("**Settings**")
        st.session_state.show_chunks = st.toggle(
            "Show retrieved chunks",
            value=st.session_state.show_chunks,
            help="Show the context chunks retrieved from the vector DB before generating a draft"
        )


# ─────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────

def main():
    render_sidebar()

    view = st.session_state.view

    if view == "home":
        from views.home import render
        render(navigate_to)

    elif view == "sections_manager":
        from views.sections_manager import render
        render(navigate_to)

    elif view == "redactor":
        from views.redactor import render
        render(navigate_to)

    elif view == "export":
        from views.export import render
        render(navigate_to)

    else:
        st.error(f"Unknown view: '{view}'")
        if st.button("Go home"):
            navigate_to("home")


if __name__ == "__main__":
    main()