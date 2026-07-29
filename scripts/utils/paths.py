"""
scripts/utils/paths.py
Derives all project paths from .env configuration.
No paths are hardcoded — everything is configurable.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directory where all projects live — from .env
PROJECTS_BASE_DIR = Path(os.getenv("PROJECTS_BASE_DIR", "projects"))

# Internal structure — all relative to project root — from .env
_DIR_RAW        = os.getenv("DIR_RAW",        "data/raw")
_DIR_PROCESSED  = os.getenv("DIR_PROCESSED",  "data/processed")
_DIR_CHUNKS     = os.getenv("DIR_CHUNKS",     "data/chunks")
_DIR_VECTOR_DB  = os.getenv("DIR_VECTOR_DB",  "vector_db")
_DIR_CONFIG     = os.getenv("DIR_CONFIG",     "config")
_DIR_OUTPUT     = os.getenv("DIR_OUTPUT",     "output")
_DIR_DATASET_EVAL     = os.getenv("_DIR_DATASET_EVAL",     "data/evaluation")
_FILE_DIRECTIVES = os.getenv("FILE_DIRECTIVES", "config/directives.md")
_FILE_TEMPLATE   = os.getenv("FILE_TEMPLATE",   "config/template.docx")
_FILE_PROGRESS   = os.getenv("FILE_PROGRESS",   "progress.json")
_FILE_INDEX      = os.getenv("FILE_INDEX", "config/index.json")

def _validate_project_name(project_name: str) -> str:
    """
    Validates project names to prevent path traversal.
    Only letters, numbers, hyphens and underscores are allowed.
    """
    if not project_name:
        raise ValueError("Project name cannot be empty")

    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

    if any(char not in allowed for char in project_name):
        raise ValueError(
            "Project name may only contain letters, numbers, hyphens and underscores"
        )

    return project_name

def get_project_paths(project_name: str) -> dict[str, Path]:
    """
    Returns all paths for a given project.
    Every path is derived from .env values — nothing hardcoded.

    Usage:
        paths = get_project_paths("demo_project")
        paths["raw"]        → projects/demo_project/data/raw
        paths["vector_db"]  → projects/demo_project/vector_db
        paths["directives"] → projects/demo_project/config/directives.md
    """

    project_name = _validate_project_name(project_name)
    base = PROJECTS_BASE_DIR / project_name

    return {
        "base":       base,
        "raw":        base / _DIR_RAW,
        "processed":  base / _DIR_PROCESSED,
        "chunks":     base / _DIR_CHUNKS,
        "vector_db":  base / _DIR_VECTOR_DB,
        "config":     base / _DIR_CONFIG,
        "output":     base / _DIR_OUTPUT,
        "directives": base / _FILE_DIRECTIVES,
        "template":   base / _FILE_TEMPLATE,
        "progress":   base / _FILE_PROGRESS,
        "index": base / _FILE_INDEX,
        "dataset_evaluation": base / _DIR_DATASET_EVAL,
    }


def list_projects() -> list[str]:
    """
    Scans PROJECTS_BASE_DIR and returns all existing project names.
    Used by Streamlit to populate the project selector.
    """
    if not PROJECTS_BASE_DIR.exists():
        return []
    return [
        d.name for d in sorted(PROJECTS_BASE_DIR.iterdir())
        if d.is_dir()
    ]


def init_project_structure(project_name: str) -> dict[str, Path]:
    """
    Creates the full folder structure for a new project.
    Folder names come from .env — not hardcoded.
    Returns the paths dict.
    """
    paths = get_project_paths(project_name)

    # Create all directories
    for key in ["raw", "processed", "chunks", "vector_db", "config", "output","dataset_evaluation"]:
        paths[key].mkdir(parents=True, exist_ok=True)

    # Create empty directives.md if it doesn't exist
    if not paths["directives"].exists():
        paths["directives"].write_text(
            "# Writing Directives\n\n"
            "## 1. Tone and Style\n\n"
            "## 2. Call Context\n\n"
            "## 3. Section-Specific Rules\n\n"
            "## 4. Global Restrictions\n\n"
            "## 5. Call Notes\n",
            encoding="utf-8"
        )

    # Create empty progress.json if it doesn't exist
    if not paths["progress"].exists():
        import json
        paths["progress"].write_text(
            json.dumps({
                "project_name": project_name,
                "created_at":   "",
                "last_modified": "",
                "sections":     []
            }, indent=2),
            encoding="utf-8"
        )

    return paths