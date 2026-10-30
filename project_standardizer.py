"""Standardize user projects into a fixed NAS-friendly project layout.

The canonical layout is:

    <nas-root>/<project-name>/
        project.json
        data/
        code/
            charts/
            lib/
        previews/
        history/
        validation/
        notes/

This file is intentionally small and focused: it turns an arbitrary local source
folder into the stable structure you want for tool-driven chart editing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List


DEFAULT_NAS_ROOT = Path(
    os.environ.get("CHART_STUDIO_NAS_ROOT", str(Path.home() / "nas" / "plotforge" / "projects"))
)


def sanitize_project_name(name: str) -> str:
    cleaned = (name or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", cleaned).strip("_")
    if not cleaned:
        raise ValueError("项目名称不能为空")
    return cleaned


def standard_project_root(target_root: str | Path | None = None, project_name: str | None = None) -> Path:
    root = Path(target_root) if target_root is not None else DEFAULT_NAS_ROOT
    root = root.expanduser().resolve()
    if project_name:
        return root / sanitize_project_name(project_name)
    return root


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _copy_or_skip(src: Path, dst: Path) -> None:
    if src.is_dir():
        return
    _ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def _is_data_file(path: Path) -> bool:
    return path.suffix.lower() in {".csv", ".tsv", ".json", ".xlsx", ".xls", ".parquet", ".txt", ".md"}


def _is_python_file(path: Path) -> bool:
    return path.suffix.lower() == ".py"


def _normalize_source_layout(source_root: Path, target_root: Path) -> None:
    """Copy all source files into a standard project layout."""
    source_root = source_root.expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        return

    data_root = target_root / "data"
    code_root = target_root / "code"
    charts_root = code_root / "charts"
    lib_root = code_root / "lib"
    previews_root = target_root / "previews"
    history_root = target_root / "history"
    validation_root = target_root / "validation"
    notes_root = target_root / "notes"

    for folder in (data_root, charts_root, lib_root, previews_root, history_root, validation_root, notes_root):
        _ensure_dir(folder)

    # Copy explicit data/code folders first when they already exist in the source.
    for explicit_name in ("data", "code"):
        explicit_dir = source_root / explicit_name
        if explicit_dir.is_dir():
            if explicit_name == "data":
                for item in sorted(explicit_dir.rglob("*")):
                    if item.is_dir():
                        continue
                    rel = item.relative_to(explicit_dir)
                    _copy_or_skip(item, data_root / rel)
            elif explicit_name == "code":
                for item in sorted(explicit_dir.rglob("*")):
                    if item.is_dir():
                        continue
                    rel = item.relative_to(explicit_dir)
                    if rel.parts and rel.parts[0] == "charts":
                        target = charts_root / rel.relative_to("charts")
                    elif rel.parts and rel.parts[0] == "lib":
                        target = lib_root / rel.relative_to("lib")
                    elif _is_python_file(item):
                        target = charts_root / rel
                    else:
                        target = lib_root / rel
                    _copy_or_skip(item, target)

    # Copy any remaining root-level data files and python files from the source root.
    for item in sorted(source_root.rglob("*")):
        if item.is_dir():
            continue
        if item.name in {".DS_Store", "Thumbs.db"}:
            continue
        rel = item.relative_to(source_root)
        if rel.parts and rel.parts[0] in {"data", "code", ".git", ".venv", "__pycache__"}:
            continue
        if _is_python_file(item):
            target = charts_root / rel
        elif _is_data_file(item):
            target = data_root / rel
        else:
            target = notes_root / rel
        _copy_or_skip(item, target)


def _default_meta(project_name: str, source_root: Path) -> dict:
    return {
        "name": project_name,
        "source_root": str(source_root),
        "schema_version": "1.0",
        "standardized_at": datetime.now(timezone.utc).isoformat(),
        "description": "Standardized for local chart editing.",
    }


def _catalog_project(project_root: Path) -> dict:
    charts = []
    data_files = []
    if (project_root / "code" / "charts").exists():
        charts = sorted(p.name for p in (project_root / "code" / "charts").glob("*.py"))
    if (project_root / "data").exists():
        data_files = sorted(str(p.relative_to(project_root)) for p in (project_root / "data").rglob("*") if p.is_file())
    return {"charts": charts, "data_files": data_files}


def standardize_project(source_dir: str | Path, project_name: str, target_root: str | Path | None = None) -> Path:
    """Create a standardized project under the NAS root.

    For a user-supplied source directory, this function copies the relevant code and
    data into the standard layout required by the chart editing tool.

    When the source directory does not exist yet, this function still creates the
    canonical project skeleton so the user can later add or import content.
    """
    source_path = Path(source_dir).expanduser().resolve()
    name = sanitize_project_name(project_name)
    root = standard_project_root(target_root, name)

    if source_path.exists() and not source_path.is_dir():
        raise ValueError(f"项目地址不是目录: {source_path}")

    _ensure_dir(root)
    _normalize_source_layout(source_path, root)

    project_json = root / "project.json"
    meta = _default_meta(name, source_path)
    meta["status"] = "pending" if not source_path.exists() else "ready"
    project_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for folder in (root / "code" / "charts", root / "code" / "lib", root / "previews", root / "history"):
        _ensure_dir(folder)

    return root


def manual_add_project(project_name: str, target_root: str | Path | None = None) -> Path:
    """Create an empty standardized project skeleton for later normalization."""
    name = sanitize_project_name(project_name)
    root = standard_project_root(target_root, name)
    _ensure_dir(root)
    for folder in (root / "data", root / "code" / "charts", root / "code" / "lib", root / "previews", root / "history", root / "validation", root / "notes"):
        _ensure_dir(folder)
    meta = _default_meta(name, root)
    meta["status"] = "pending_standardization"
    (root / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return root


def list_standardized_projects(target_root: str | Path | None = None) -> List[dict]:
    root = Path(target_root) if target_root is not None else DEFAULT_NAS_ROOT
    root = root.expanduser().resolve()
    if not root.exists():
        return []
    items = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        project_json = directory / "project.json"
        if not project_json.exists():
            continue
        try:
            meta = json.loads(project_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        info = _catalog_project(directory)
        items.append(
            {
                "id": directory.name,
                "name": meta.get("name", directory.name),
                "path": str(directory),
                "status": meta.get("status", "ready"),
                "charts": info["charts"],
                "data_files": info["data_files"],
                "updated_at": meta.get("standardized_at"),
            }
        )
    return items


__all__ = [
    "DEFAULT_NAS_ROOT",
    "sanitize_project_name",
    "standard_project_root",
    "standardize_project",
    "manual_add_project",
    "list_standardized_projects",
]
