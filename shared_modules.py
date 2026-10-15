"""Safe discovery and editing primitives for project-local plotting modules."""

import base64
import ast
import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
MAX_SHARED_MODULE_SOURCE = 500_000


def encode_module_id(relative_path):
    raw = str(relative_path).replace("\\", "/").encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_module_id(module_id):
    try:
        value = str(module_id)
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("共享模块 ID 无效") from error
    relative = Path(decoded)
    if (
        not decoded
        or relative.is_absolute()
        or ":" in decoded
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise ValueError("共享模块 ID 无效")
    return Path(*relative.parts)


def _inside(root, candidate):
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _bundle_candidates(project, analysis):
    library = project / "lib"
    if analysis == "group":
        candidate = library / "behavior_analysis" / "group" / "visualization.py"
        return [candidate] if candidate.is_file() else []
    if analysis == "border":
        folder = library / "behavior_analysis" / "border" / "visualization"
        return sorted(folder.glob("*.py")) if folder.is_dir() else []
    return []


def discover_modules(project):
    project = Path(project)
    if not (project / "lib").is_dir():
        return []
    library = (project / "lib").resolve(strict=True)
    metadata = json.loads((project / "project.json").read_text(encoding="utf-8"))
    if metadata.get("data_source_type") == "plot_bundle":
        candidates = _bundle_candidates(project, metadata.get("analysis"))
    else:
        candidates = sorted((project / "lib").rglob("*.py"))

    modules = []
    for candidate in candidates:
        if candidate.name == "__init__.py" or not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        if not _inside(library, resolved):
            continue
        relative = resolved.relative_to(library).as_posix()
        modules.append(
            {
                "id": encode_module_id(relative),
                "name": candidate.stem,
                "path": relative,
            }
        )
    return sorted(modules, key=lambda item: item["path"])


def resolve_module(project, module_id):
    project = Path(project)
    relative = decode_module_id(module_id)
    allowed = {item["id"]: item for item in discover_modules(project)}
    if module_id not in allowed:
        raise ValueError("共享模块不存在或不可编辑")
    library = (project / "lib").resolve(strict=True)
    path = (library / relative).resolve(strict=True)
    if not _inside(library, path) or path.suffix.lower() != ".py":
        raise ValueError("共享模块不存在或不可编辑")
    return path


def _project_lock(project):
    key = str(Path(project).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _history_root(project, module_id):
    resolve_module(project, module_id)
    return Path(project) / "history" / "modules" / module_id


def read_module_history(project, module_id):
    root = _history_root(project, module_id)
    index = root / "history.json"
    return json.loads(index.read_text(encoding="utf-8")) if index.is_file() else []


def module_revision_source(project, module_id, revision):
    if not revision or not str(revision).isalnum():
        raise ValueError("共享模块历史版本无效")
    history = read_module_history(project, module_id)
    if not any(entry.get("id") == revision for entry in history):
        raise ValueError("共享模块历史版本不存在")
    return (_history_root(project, module_id) / (revision + ".py")).read_text(
        encoding="utf-8"
    )


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def apply_module(
    project,
    module_id,
    source,
    chart,
    render_candidate,
    note="手动修改共享绘图模块",
):
    """Validate a module in an isolated library copy, then save it atomically."""
    if not isinstance(source, str) or len(source) > MAX_SHARED_MODULE_SOURCE:
        raise ValueError("共享模块源码无效")
    ast.parse(source)
    project = Path(project)
    module = resolve_module(project, module_id)
    relative = module.relative_to((project / "lib").resolve(strict=True))

    with _project_lock(project):
        with tempfile.TemporaryDirectory(prefix="chart-module-") as temporary:
            candidate_library = Path(temporary) / "lib"
            shutil.copytree(project / "lib", candidate_library)
            candidate = candidate_library / relative
            candidate.write_text(source, encoding="utf-8")
            preview = render_candidate(chart, candidate_library)

        previous = module.read_text(encoding="utf-8")
        history = read_module_history(project, module_id)
        if previous == source:
            return {"preview": preview, "history": history, "changed": False}

        stamp = datetime.now(timezone.utc).isoformat()
        history_root = _history_root(project, module_id)
        history_root.mkdir(parents=True, exist_ok=True)
        if not history:
            initial = uuid.uuid4().hex[:12]
            _atomic_write(history_root / (initial + ".py"), previous)
            history.append({"id": initial, "time": stamp, "note": "初始版本"})
        revision = uuid.uuid4().hex[:12]
        _atomic_write(history_root / (revision + ".py"), source)
        updated = history + [{"id": revision, "time": stamp, "note": str(note)[:300]}]
        _atomic_write(module, source)
        _atomic_write(
            history_root / "history.json",
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        )
        return {
            "preview": preview,
            "history": updated,
            "revision": revision,
            "changed": True,
        }
