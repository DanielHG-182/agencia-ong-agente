"""
Project lifecycle operations.

Keeps project creation, loading, validation, and progress persistence
independent from the Streamlit interface.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.utils.paths import (
    get_project_paths,
    init_project_structure,
    list_projects,
)


class ProjectError(Exception):
    """Base exception for project lifecycle errors."""


class ProjectAlreadyExistsError(ProjectError):
    """Raised when attempting to create an existing project."""


class ProjectProgressError(ProjectError):
    """Raised when project progress cannot be read or written."""


def slugify_project_name(display_name: str) -> str:
    """
    Converts a display name into a safe project folder name.

    Only lowercase ASCII letters, numbers, hyphens, and underscores
    are retained so the result is compatible with path validation.
    """
    normalized = display_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9\s_-]", "", normalized)
    normalized = re.sub(r"[\s_-]+", "_", normalized)
    return normalized.strip("_")


def load_project_progress(project_name: str) -> dict[str, Any] | None:
    """
    Loads a project's progress file.

    Returns None when the file does not exist.
    Raises ProjectProgressError when the file exists but is invalid.
    """
    paths = get_project_paths(project_name)
    progress_path = paths["progress"]

    if not progress_path.exists():
        return None

    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectProgressError(
            f"Could not read progress for project '{project_name}'"
        ) from exc


def save_project_progress(
    project_name: str,
    progress: dict[str, Any],
) -> Path:
    """Writes project progress safely and returns the file path."""
    paths = get_project_paths(project_name)
    progress_path = paths["progress"]

    try:
        progress_path.write_text(
            json.dumps(progress, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        raise ProjectProgressError(
            f"Could not save progress for project '{project_name}'"
        ) from exc

    return progress_path


def create_project(display_name: str) -> tuple[str, dict[str, Path], dict[str, Any]]:
    """
    Creates a new project and its initial progress state.

    Returns:
        folder_name, paths, progress
    """
    folder_name = slugify_project_name(display_name)

    if not folder_name:
        raise ProjectError(
            "Project name must contain at least one letter or number"
        )

    if folder_name in list_projects():
        raise ProjectAlreadyExistsError(
            f"A project named '{folder_name}' already exists"
        )

    paths = init_project_structure(folder_name)
    now = datetime.now().isoformat()

    progress: dict[str, Any] = {
        "project_name": display_name.strip(),
        "folder_name": folder_name,
        "created_at": now,
        "last_modified": now,
        "sections": [],
    }

    save_project_progress(folder_name, progress)

    return folder_name, paths, progress


def get_project_summary(project_name: str) -> dict[str, Any]:
    """Returns the data required to display a project summary."""
    progress = load_project_progress(project_name)

    if progress is None:
        return {
            "total": 0,
            "approved": 0,
            "last_modified": "No data",
        }

    sections = progress.get("sections", [])
    approved = sum(
        1 for section in sections
        if section.get("status") == "approved"
    )

    return {
        "total": len(sections),
        "approved": approved,
        "last_modified": progress.get("last_modified") or "Not started",
    }