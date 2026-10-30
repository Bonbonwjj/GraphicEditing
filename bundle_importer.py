"""Validation and project registration for behavior-analysis Plot Bundles."""
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from data_sources import DataSourceDescriptor


BUNDLE_FORMAT = "behavior-analysis-plot-bundle"
BUNDLE_VERSION = 1


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("Bundle 文件不存在：{}".format(path.name))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("无法读取 Bundle JSON {}：{}".format(path.name, exc))
    if not isinstance(value, dict):
        raise ValueError("Bundle JSON 必须是对象：{}".format(path.name))
    return value


def _safe_bundle_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("Bundle 文件路径无效")
    root = root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("Bundle 文件路径超出 Bundle 目录：{}".format(relative))
    if not candidate.is_file():
        raise ValueError("Bundle 文件不存在：{}".format(relative))
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_record(root: Path, label: str, record: object) -> Path:
    if not isinstance(record, dict):
        raise ValueError("Bundle 清单记录无效：{}".format(label))
    path = _safe_bundle_file(root, record.get("path"))
    expected_size = record.get("bytes")
    if not isinstance(expected_size, int) or path.stat().st_size != expected_size:
        raise ValueError("Bundle 文件长度不一致：{}".format(label))
    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or _sha256(path) != expected_hash.lower():
        raise ValueError("Bundle 文件 SHA-256 不一致：{}".format(label))
    return path


def inspect_plot_bundle(source: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    root = Path(source).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Plot Bundle 必须是目录")
    manifest = _read_json(root / "manifest.json")
    if manifest.get("format") != BUNDLE_FORMAT:
        raise ValueError("不支持的 Bundle 格式")
    if manifest.get("version") != BUNDLE_VERSION:
        raise ValueError("不支持的 Bundle 版本：{}".format(manifest.get("version")))
    analysis = manifest.get("analysis")
    if analysis not in ("group", "border"):
        raise ValueError("不支持的 Bundle analysis：{}".format(analysis))

    specs_path = _verify_record(root, "plot_specs", manifest.get("plot_specs"))
    specs = _read_json(specs_path)
    if specs.get("analysis") != analysis or not isinstance(specs.get("plots"), list):
        raise ValueError("plot_specs 与 Bundle analysis 不一致或 plots 无效")

    payloads = manifest.get("payloads")
    if not isinstance(payloads, dict) or not payloads:
        raise ValueError("Bundle 没有 payloads")
    for key, record in payloads.items():
        _verify_record(root, "payload:{}".format(key), record)

    for index, spec in enumerate(specs["plots"]):
        if not isinstance(spec, dict):
            raise ValueError("plot_specs.plots[{}] 无效".format(index))
        if analysis == "border":
            payload_key = spec.get("payload")
            if payload_key not in payloads:
                raise ValueError("绘图规格引用了不存在的 payload：{}".format(payload_key))
        elif "kind" not in spec:
            raise ValueError("group 绘图规格缺少 kind")
    return manifest, specs


class PlotBundleAdapter:
    kind = "plot_bundle"

    def can_handle(self, source: Path) -> bool:
        source = Path(source)
        return source.is_dir() and (source / "manifest.json").is_file()

    def inspect(
        self, source: Path, *, mode: str, trusted: bool
    ) -> DataSourceDescriptor:
        root = Path(source).resolve(strict=True)
        manifest, specs = inspect_plot_bundle(root)
        payload_bytes = sum(
            int(record["bytes"]) for record in manifest["payloads"].values()
        )
        manifest_hash = _sha256(root / "manifest.json")
        return DataSourceDescriptor(
            source_id="plot-bundle-{}".format(manifest_hash[:16]),
            kind=self.kind,
            mode=mode,
            location=str(root),
            read_only=True,
            trusted=trusted,
            metadata={
                "analysis": manifest["analysis"],
                "version": manifest["version"],
                "created_at": manifest.get("created_at"),
                "plot_count": len(specs["plots"]),
                "payload_count": len(manifest["payloads"]),
                "payload_bytes": payload_bytes,
                "pickle_warning": "仅可导入受信任来源的 Plot Bundle",
            },
        )


def _chart_name(spec: Dict[str, Any], index: int, used: set) -> str:
    if spec.get("filename"):
        raw = Path(str(spec["filename"])).stem
    else:
        raw = str(spec.get("kind") or "plot")
    base = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_") or "plot"
    base = "{:03d}_{}".format(index + 1, base[:80])
    name = base
    suffix = 2
    while name in used:
        name = "{}_{}".format(base, suffix)
        suffix += 1
    used.add(name)
    return name


def _chart_source(analysis: str, spec_index: int, spec: Dict[str, Any]) -> str:
    available = spec.get("payload_keys") or spec.get("data_keys") or []
    return (
        "import os\n"
        "from pathlib import Path\n"
        "from bundle_runtime import render_bundle_chart\n\n"
        "# Plot kind: {!r}; processed fields: {!r}\n"
        "def customize(context):\n"
        "    \"\"\"Optionally draw this chart and return an image path.\n"
        "\n"
        "    Border context exposes context.artifact; group context exposes\n"
        "    context.result and context.config. Write only inside\n"
        "    context.output_dir. Return None to preserve the verified default.\n"
        "    \"\"\"\n"
        "    return None\n\n"
        "project = Path(os.environ['CHART_PROJECT_DIR'])\n"
        "render_bundle_chart(\n"
        "    project, {!r}, {}, Path(os.environ['CHART_OUTPUT']), customize=customize\n"
        ")\n"
    ).format(spec.get("kind"), list(available), analysis, spec_index)


def _copy_runtime_files(platform_root: Path, target: Path) -> None:
    for name in ("bundle_runtime.py", "bundle_bindings.py"):
        runtime = Path(platform_root) / name
        if runtime.is_file():
            shutil.copy2(runtime, target / "lib" / runtime.name)


def import_plot_bundle(
    platform_root: Path,
    source: Path,
    *,
    project_id: str,
    name: str,
    mode: str,
    trusted: bool,
    runtime_source: Path = None,
) -> Dict[str, Any]:
    if not project_id or not project_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("项目 ID 只能包含字母、数字、_ 或 -")
    if mode not in ("upload", "server_path"):
        raise ValueError("不支持的 Bundle 来源模式")
    if not trusted:
        raise ValueError("Plot Bundle 包含 pickle，只能导入受信任来源")

    platform_root = Path(platform_root).resolve()
    source = Path(source).resolve(strict=True)
    target = platform_root / "projects" / project_id
    if target.exists():
        raise ValueError("Project already exists")

    try:
        manifest, specs = inspect_plot_bundle(source)
        descriptor = PlotBundleAdapter().inspect(
            source, mode=mode, trusted=trusted
        )
        for directory in ("data", "charts", "lib", "outputs", "history"):
            (target / directory).mkdir(parents=True, exist_ok=True)

        bundle_location = source
        if mode == "upload":
            bundle_location = target / "data" / "bundle"
            shutil.copytree(source, bundle_location)
            source_dict = descriptor.as_dict()
            source_dict["metadata"]["uploaded_from"] = str(source)
            source_dict["location"] = str(bundle_location)
        else:
            source_dict = descriptor.as_dict()

        if runtime_source is not None:
            package = Path(runtime_source) / "behavior_analysis"
            if not package.is_dir():
                raise ValueError("behavior_analysis 运行时代码目录不存在")
            shutil.copytree(package, target / "lib" / "behavior_analysis")
        _copy_runtime_files(platform_root, target)

        used = set()
        chart_records: List[Dict[str, Any]] = []
        for index, spec in enumerate(specs["plots"]):
            chart = _chart_name(spec, index, used)
            (target / "charts" / (chart + ".py")).write_text(
                _chart_source(manifest["analysis"], index, spec), encoding="utf-8"
            )
            chart_records.append(
                {
                    "id": chart,
                    "spec_index": index,
                    "kind": spec.get("kind"),
                    "theme": spec.get("theme"),
                    "filename": spec.get("filename"),
                    "payload": spec.get("payload"),
                    "data_keys": spec.get("data_keys", []),
                }
            )

        source_dict["location"] = str(bundle_location.resolve())
        source_dict["charts"] = chart_records
        (target / "data_sources.json").write_text(
            json.dumps({"version": 1, "sources": [source_dict]}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        (target / "project.json").write_text(
            json.dumps(
                {
                    "name": str(name)[:80] or project_id,
                    "description": "Imported {} Plot Bundle with {} plots.".format(
                        manifest["analysis"], len(chart_records)
                    ),
                    "data_source_type": "plot_bundle",
                    "analysis": manifest["analysis"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "project": project_id,
            "adapter": "plot_bundle",
            "analysis": manifest["analysis"],
            "charts": [record["id"] for record in chart_records],
            "plot_count": len(chart_records),
            "data_source": source_dict,
        }
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
