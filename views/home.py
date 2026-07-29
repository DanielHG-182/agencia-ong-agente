"""
views/home.py
Home view — project selector and project creation.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from scripts.utils.paths import list_projects, init_project_structure, get_project_paths


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def load_progress(paths: dict) -> dict | None:
    """Loads progress.json for a project. Returns None if not found."""
    try:
        return json.loads(paths["progress"].read_text(encoding="utf-8"))
    except Exception:
        return None


def get_project_summary(project_name: str) -> dict:
    """
    Returns a summary dict for a project card:
    sections total, approved, last modified.
    """
    paths    = get_project_paths(project_name)
    progress = load_progress(paths)

    if not progress:
        return {
            "total":         0,
            "approved":      0,
            "last_modified": "No data",
        }

    sections     = progress.get("sections", [])
    approved     = sum(1 for s in sections if s.get("status") == "approved")
    last_modified = progress.get("last_modified", "")

    return {
        "total":         len(sections),
        "approved":      approved,
        "last_modified": last_modified or "Not started",
    }


def slugify(name: str) -> str:
    """Converts a project name to a safe folder name."""
    name = name.lower().strip()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s_-]+', '_', name)
    return name


def open_project(project_name: str, navigate_to):
    """Loads a project into session_state and navigates to sections manager."""
    paths    = get_project_paths(project_name)
    progress = load_progress(paths)

    st.session_state.active_project = project_name
    st.session_state.paths          = paths
    st.session_state.sections       = progress.get("sections", []) if progress else []

    navigate_to("sections_manager")


# ─────────────────────────────────────────────────────────
# NEW PROJECT DIALOG
# ─────────────────────────────────────────────────────────

@st.dialog("Create new project")
def new_project_dialog(navigate_to):
    st.markdown("Fill in the details for your new project.")

    project_display_name = st.text_input(
        "Project name",
        placeholder="e.g. Demo Project",
        help="This will be used as the folder name"
    )

    st.caption(
        f"Folder name: `{slugify(project_display_name)}`"
        if project_display_name else "Folder name will appear here"
    )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Create", use_container_width=True, type="primary"):
            if not project_display_name.strip():
                st.error("Project name cannot be empty.")
                return

            folder_name = slugify(project_display_name)

            # Check if project already exists
            if folder_name in list_projects():
                st.error(f"A project named '{folder_name}' already exists.")
                return

            # Create structure
            with st.spinner("Creating project structure..."):
                try:
                    paths = init_project_structure(folder_name)

                    # Save initial progress.json
                    progress = {
                        "project_name":  project_display_name,
                        "folder_name":   folder_name,
                        "created_at":    datetime.now().isoformat(),
                        "last_modified": datetime.now().isoformat(),
                        "sections":      [],
                    }
                    paths["progress"].write_text(
                        json.dumps(progress, indent=2, ensure_ascii=False),
                        encoding="utf-8"
                    )

                    st.success(f"Project '{project_display_name}' created!")

                    # Load into session and navigate
                    st.session_state.active_project = folder_name
                    st.session_state.paths          = paths
                    st.session_state.sections       = []

                    navigate_to("sections_manager")

                except Exception as e:
                    st.error(f"Error creating project: {e}")

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# ─────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────

def render(navigate_to):
    st.title("📄 ONG Document Assistant")
    st.caption("Select an existing project or create a new one to get started.")
    st.divider()

    projects = list_projects()

    col_left, col_right = st.columns([2, 1])

    with col_right:
        if st.button(
            "＋ New project",
            use_container_width=True,
            type="primary"
        ):
            new_project_dialog(navigate_to)

    with col_left:
        if not projects:
            st.info("No projects found. Create your first one to get started.")
            return

        st.markdown(f"**{len(projects)} project(s) found**")

    st.divider()

    # Project cards
    if not projects:
        return

    # Render 2 cards per row
    for i in range(0, len(projects), 2):
        cols = st.columns(2)

        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(projects):
                break

            project_name = projects[idx]
            summary      = get_project_summary(project_name)

            with col:
                with st.container(border=True):
                    # Header
                    st.markdown(f"#### 📁 {project_name}")

                    # Progress bar
                    total    = summary["total"]
                    approved = summary["approved"]

                    if total > 0:
                        progress_pct = approved / total
                        st.progress(progress_pct)
                        st.caption(
                            f"✅ {approved}/{total} sections approved"
                            f" · Last modified: {summary['last_modified'][:10] if len(summary['last_modified']) > 10 else summary['last_modified']}"
                        )
                    else:
                        st.progress(0)
                        st.caption("No sections yet · Not started")

                    st.divider()

                    # Actions
                    btn_col1, btn_col2 = st.columns(2)

                    with btn_col1:
                        if st.button(
                            "Open",
                            key=f"open_{project_name}",
                            use_container_width=True,
                            type="primary"
                        ):
                            open_project(project_name, navigate_to)

                    with btn_col2:
                        if st.button(
                            "🗑 Delete",
                            key=f"delete_{project_name}",
                            use_container_width=True,
                        ):
                            confirm_delete_dialog(project_name, navigate_to)


@st.dialog("Delete project")
def confirm_delete_dialog(project_name: str, navigate_to):
    """Confirmation dialog before deleting a project."""
    st.warning(
        f"Are you sure you want to delete **{project_name}**? "
        f"This will permanently remove all documents, chunks, "
        f"vector index and approved sections.",
        icon="⚠️"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Yes, delete", use_container_width=True, type="primary"):
            import shutil
            paths = get_project_paths(project_name)
            try:
                shutil.rmtree(paths["base"])
                st.success(f"Project '{project_name}' deleted.")

                # Clear session if deleted project was active
                if st.session_state.active_project == project_name:
                    st.session_state.active_project = None
                    st.session_state.paths          = None
                    st.session_state.sections       = []

                st.rerun()
            except Exception as e:
                st.error(f"Error deleting project: {e}")

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()