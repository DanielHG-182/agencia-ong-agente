import json

import pytest

from scripts.section_service import (
    SectionServiceError,
    get_approved_sections_before,
    mark_downstream_needs_review,
    save_sections,
    update_section,
)


def test_save_sections_creates_progress_file(tmp_path):
    progress_path = tmp_path / "progress.json"

    sections = [
        {
            "name": "Objectives",
            "content": "Test content",
            "status": "draft",
        }
    ]

    save_sections(progress_path, sections)

    saved = json.loads(progress_path.read_text(encoding="utf-8"))

    assert saved["sections"] == sections
    assert saved["last_modified"]


def test_save_sections_preserves_existing_progress_fields(tmp_path):
    progress_path = tmp_path / "progress.json"

    existing = {
        "project_name": "Demo Project",
        "folder_name": "demo_project",
        "created_at": "2026-08-01T10:00:00",
        "sections": [],
    }

    progress_path.write_text(
        json.dumps(existing),
        encoding="utf-8",
    )

    new_sections = [
        {
            "name": "Objectives",
            "content": "Updated content",
            "status": "approved",
        }
    ]

    save_sections(progress_path, new_sections)

    saved = json.loads(progress_path.read_text(encoding="utf-8"))

    assert saved["project_name"] == "Demo Project"
    assert saved["folder_name"] == "demo_project"
    assert saved["created_at"] == "2026-08-01T10:00:00"
    assert saved["sections"] == new_sections
    assert saved["last_modified"]


def test_save_sections_raises_for_corrupt_progress(tmp_path):
    progress_path = tmp_path / "progress.json"
    progress_path.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(SectionServiceError):
        save_sections(progress_path, [])


def test_mark_downstream_needs_review_changes_only_approved_sections():
    sections = [
        {"name": "A", "status": "approved"},
        {"name": "B", "status": "approved"},
        {"name": "C", "status": "draft"},
        {"name": "D", "status": "approved"},
    ]

    mark_downstream_needs_review(sections, 0)

    assert sections == [
        {"name": "A", "status": "approved"},
        {"name": "B", "status": "needs_review"},
        {"name": "C", "status": "draft"},
        {"name": "D", "status": "needs_review"},
    ]


def test_mark_downstream_needs_review_does_not_change_previous_sections():
    sections = [
        {"name": "A", "status": "approved"},
        {"name": "B", "status": "approved"},
        {"name": "C", "status": "approved"},
    ]

    mark_downstream_needs_review(sections, 1)

    assert sections[0]["status"] == "approved"
    assert sections[1]["status"] == "approved"
    assert sections[2]["status"] == "needs_review"


def test_get_approved_sections_before_returns_only_approved_with_content():
    sections = [
        {
            "name": "A",
            "content": "uno",
            "status": "approved",
        },
        {
            "name": "B",
            "content": "",
            "status": "approved",
        },
        {
            "name": "C",
            "content": "tres",
            "status": "draft",
        },
        {
            "name": "D",
            "content": "cuatro",
            "status": "approved",
        },
    ]

    result = get_approved_sections_before(sections, 3)

    assert result == {
        "A": "uno",
    }


def test_get_approved_sections_before_respects_index():
    sections = [
        {
            "name": "A",
            "content": "uno",
            "status": "approved",
        },
        {
            "name": "B",
            "content": "dos",
            "status": "approved",
        },
    ]

    result = get_approved_sections_before(sections, 1)

    assert result == {
        "A": "uno",
    }


def test_update_section_updates_content_status_and_timestamp():
    section = {
        "name": "Objectives",
        "content": "Old content",
        "status": "draft",
    }

    update_section(
        section,
        content="New content",
        status="approved",
    )

    assert section["content"] == "New content"
    assert section["status"] == "approved"
    assert section["last_generated"]