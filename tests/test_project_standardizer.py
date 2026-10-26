import json
from pathlib import Path

from project_standardizer import list_standardized_projects, standardize_project


def test_standardize_project_creates_standard_layout(tmp_path):
    source = tmp_path / "raw_project"
    (source / "code" / "charts").mkdir(parents=True)
    (source / "code" / "lib").mkdir(parents=True)
    (source / "data").mkdir(parents=True)
    (source / "code" / "charts" / "demo_chart.py").write_text(
        "import matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])\n", encoding="utf-8"
    )
    (source / "code" / "lib" / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "data" / "sample.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    target_root = tmp_path / "nas_projects"
    project_path = standardize_project(source, "demo_project", target_root)

    assert project_path.name == "demo_project"
    assert (project_path / "project.json").is_file()
    assert (project_path / "code" / "charts" / "demo_chart.py").is_file()
    assert (project_path / "code" / "lib" / "helpers.py").is_file()
    assert (project_path / "data" / "sample.csv").is_file()
    assert (project_path / "previews").is_dir()
    assert (project_path / "history").is_dir()

    meta = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    assert meta["name"] == "demo_project"


def test_list_standardized_projects_discovers_project_folders(tmp_path):
    root = tmp_path / "nas_projects"
    first = standardize_project(tmp_path / "source_a", "alpha", root)
    second = standardize_project(tmp_path / "source_b", "beta", root)

    result = list_standardized_projects(root)
    ids = {item["id"] for item in result}

    assert first.name in ids
    assert second.name in ids
    for item in result:
        assert item["path"].endswith(item["id"]) or item["path"].endswith(str(item["id"]))
