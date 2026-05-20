from pathlib import Path

from engines.grok.image_worker_flow import _project_path


def test_project_path_resolves_relative_paths_against_project_root():
    root = Path("D:/project/root")

    assert _project_path(root, "project.json") == root / "project.json"
    assert _project_path(root, "refs/ref1.png") == root / "refs/ref1.png"


def test_project_path_preserves_absolute_paths():
    root = Path("D:/project/root")
    absolute = Path("C:/assets/ref1.png")

    assert _project_path(root, str(absolute)) == absolute
