from pathlib import Path
import pytest
from scripts.utils import paths

def test_validate_project_name_accepts_valid_names():
    valid_names = [
        "demo",
        "demo_project",
        "demo-project",
        "Project123",
        "project_123-test",
    ]

    for name in valid_names:
        assert paths._validate_project_name(name) == name


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        "../project",
        "..",
        "project/test",
        r"project\test",
        "project name",
        "project.name",
        "project@name",
    ],
)
def test_validate_project_name_rejects_invalid_names(invalid_name):
    with pytest.raises(ValueError):
        paths._validate_project_name(invalid_name)


def test_get_project_paths_builds_expected_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROJECTS_BASE_DIR", tmp_path)

    project_paths = paths.get_project_paths("demo_project")

    base = tmp_path / "demo_project"

    assert project_paths["base"] == base
    assert project_paths["raw"] == base / "data/raw"
    assert project_paths["processed"] == base / "data/processed"
    assert project_paths["chunks"] == base / "data/chunks"
    assert project_paths["vector_db"] == base / "vector_db"
    assert project_paths["config"] == base / "config"
    assert project_paths["output"] == base / "output"
    assert project_paths["directives"] == base / "config/directives.md"
    assert project_paths["template"] == base / "config/template.docx"
    assert project_paths["progress"] == base / "progress.json"
    assert project_paths["index"] == base / "config/index.json"
    assert project_paths["dataset_evaluation"] == base / "data/evaluation"


def test_get_project_paths_does_not_create_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROJECTS_BASE_DIR", tmp_path)

    project_paths = paths.get_project_paths("demo_project")

    assert not project_paths["base"].exists()

def test_list_projects_returns_sorted_directories_only(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROJECTS_BASE_DIR", tmp_path)

    (tmp_path / "project_b").mkdir()
    (tmp_path / "project_a").mkdir()
    (tmp_path / "not_a_project.txt").write_text("ignore me", encoding="utf-8")

    assert paths.list_projects() == ["project_a", "project_b"]


def test_init_project_structure_creates_expected_files(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "PROJECTS_BASE_DIR", tmp_path)

    project_paths = paths.init_project_structure("demo_project")

    expected_directories = [
        "raw",
        "processed",
        "chunks",
        "vector_db",
        "config",
        "output",
        "dataset_evaluation",
    ]

    for key in expected_directories:
        assert project_paths[key].is_dir()

    assert project_paths["directives"].is_file()
    assert project_paths["progress"].is_file()

    directives = project_paths["directives"].read_text(encoding="utf-8")
    assert "# Writing Directives" in directives

    import json

    progress = json.loads(
        project_paths["progress"].read_text(encoding="utf-8")
    )

    assert progress["project_name"] == "demo_project"
    assert progress["sections"] == []