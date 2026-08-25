import json

import pytest

import scripts.project_service as project_service
from scripts.project_service import (
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectProgressError,
)


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("Demo Project", "demo_project"),
        ("  Demo Project  ", "demo_project"),
        ("Demo-Project", "demo_project"),
        ("Demo_Project", "demo_project"),
        ("Project 123", "project_123"),
        ("Demo!!! Project", "demo_project"),
    ],
)
def test_slugify_project_name(display_name, expected):
    assert project_service.slugify_project_name(display_name) == expected


def test_load_project_progress_returns_none_when_file_missing(
    monkeypatch,
    tmp_path,
):
    progress_path = tmp_path / "progress.json"

    monkeypatch.setattr(
        project_service,
        "get_project_paths",
        lambda project_name: {"progress": progress_path},
    )

    assert project_service.load_project_progress("demo") is None


def test_load_project_progress_reads_valid_json(
    monkeypatch,
    tmp_path,
):
    progress_path = tmp_path / "progress.json"
    expected = {
        "project_name": "Demo",
        "sections": [],
    }

    progress_path.write_text(
        json.dumps(expected),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        project_service,
        "get_project_paths",
        lambda project_name: {"progress": progress_path},
    )

    assert project_service.load_project_progress("demo") == expected


def test_load_project_progress_raises_for_corrupt_json(
    monkeypatch,
    tmp_path,
):
    progress_path = tmp_path / "progress.json"
    progress_path.write_text("{invalid json", encoding="utf-8")

    monkeypatch.setattr(
        project_service,
        "get_project_paths",
        lambda project_name: {"progress": progress_path},
    )

    with pytest.raises(ProjectProgressError):
        project_service.load_project_progress("demo")


def test_save_project_progress_writes_json(
    monkeypatch,
    tmp_path,
):
    progress_path = tmp_path / "progress.json"

    monkeypatch.setattr(
        project_service,
        "get_project_paths",
        lambda project_name: {"progress": progress_path},
    )

    progress = {
        "project_name": "Demo",
        "sections": [],
    }

    returned_path = project_service.save_project_progress(
        "demo",
        progress,
    )

    saved = json.loads(progress_path.read_text(encoding="utf-8"))

    assert returned_path == progress_path
    assert saved == progress


def test_create_project_creates_initial_progress(
    monkeypatch,
    tmp_path,
):
    project_paths = {
        "base": tmp_path / "demo_project",
        "progress": tmp_path / "demo_project" / "progress.json",
    }

    monkeypatch.setattr(project_service, "list_projects", lambda: [])
    monkeypatch.setattr(
        project_service,
        "init_project_structure",
        lambda project_name: project_paths,
    )

    saved = {}

    def fake_save(project_name, progress):
        saved["project_name"] = project_name
        saved["progress"] = progress
        return project_paths["progress"]

    monkeypatch.setattr(
        project_service,
        "save_project_progress",
        fake_save,
    )

    folder_name, paths, progress = project_service.create_project(
        "Demo Project"
    )

    assert folder_name == "demo_project"
    assert paths == project_paths

    assert progress["project_name"] == "Demo Project"
    assert progress["folder_name"] == "demo_project"
    assert progress["sections"] == []

    assert progress["created_at"]
    assert progress["last_modified"] == progress["created_at"]

    assert saved["project_name"] == "demo_project"
    assert saved["progress"] == progress


def test_create_project_rejects_duplicate(monkeypatch):
    monkeypatch.setattr(
        project_service,
        "list_projects",
        lambda: ["demo_project"],
    )

    with pytest.raises(ProjectAlreadyExistsError):
        project_service.create_project("Demo Project")


def test_create_project_rejects_name_without_letters_or_numbers():
    with pytest.raises(ProjectError):
        project_service.create_project("!!!")


def test_get_project_summary_returns_empty_when_progress_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        project_service,
        "load_project_progress",
        lambda project_name: None,
    )

    summary = project_service.get_project_summary("demo")

    assert summary == {
        "total": 0,
        "approved": 0,
        "last_modified": "No data",
    }


def test_get_project_summary_counts_approved_sections(
    monkeypatch,
):
    progress = {
        "last_modified": "2026-08-25T12:00:00",
        "sections": [
            {"status": "approved"},
            {"status": "draft"},
            {"status": "approved"},
            {"status": "needs_review"},
        ],
    }

    monkeypatch.setattr(
        project_service,
        "load_project_progress",
        lambda project_name: progress,
    )

    summary = project_service.get_project_summary("demo")

    assert summary == {
        "total": 4,
        "approved": 2,
        "last_modified": "2026-08-25T12:00:00",
    }