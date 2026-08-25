"""Business logic for proposal section state and persistence."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class SectionServiceError(RuntimeError):
    """Raised when section state cannot be persisted."""


def save_sections(
    progress_path: Path,
    sections: list[dict[str, Any]],
) -> None:
    """
    Persist section state into the project's progress.json file.
    """

    try:
        if progress_path.exists():
            existing = json.loads(
                progress_path.read_text(encoding="utf-8")
            )
        else:
            existing = {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SectionServiceError(
            f"Could not read project progress from '{progress_path}'."
        ) from exc

    existing["sections"] = sections
    existing["last_modified"] = datetime.now().isoformat()

    try:
        progress_path.write_text(
            json.dumps(
                existing,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        raise SectionServiceError(
            f"Could not save project progress to '{progress_path}'."
        ) from exc


def mark_downstream_needs_review(
    sections: list[dict[str, Any]],
    edited_index: int,
) -> None:
    """
    Mark approved sections after the edited section as needing review.
    """

    for section in sections[edited_index + 1:]:
        if section.get("status") == "approved":
            section["status"] = "needs_review"


def get_approved_sections_before(
    sections: list[dict[str, Any]],
    index: int,
) -> dict[str, str]:
    """
    Return approved section content preceding the given index.
    """

    return {
        section["name"]: section["content"]
        for section in sections[:index]
        if (
            section.get("status") == "approved"
            and section.get("content")
        )
    }


def update_section(
    section: dict[str, Any],
    content: str,
    status: str,
) -> None:
    """
    Update a section's content and workflow status.
    """

    section["content"] = content
    section["status"] = status
    section["last_generated"] = datetime.now().isoformat()