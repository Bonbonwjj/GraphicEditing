"""Trusted, lazy runtime used by generated Plot Bundle chart scripts.

This module deliberately opens only the payload required by the selected chart.
Plot Bundle payloads are pickle files and must never be loaded from an untrusted
source.
"""
import gzip
import hashlib
import json
import pickle
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List


GROUP_KIND_KEYS = {
    "distance_1mm_distribution": {
        "distance_1mm_results",
        "distance_1mm_num",
    },
    "distance_zone_bars": {"spec_dist_results"},
    "frequency_by_distance": {
        "distance_each_hour",
        "distance_references",
        "missing_distance_references",
    },
    "roaming_by_distance": {
        "roam_dis_each_hour",
        "distance_references",
        "missing_distance_references",
    },
    "linear_velocity_by_distance": {"lv_dis_each_hour"},
    "angular_speed_by_distance": {"as_dis_each_hour"},
    "distance_to_edge_time_bins": {"dis2edge_each_hour"},
    "distance_to_edge_points": {"dis2edge_eachpoint_final"},
    "roaming_rate": {"rrate_each_hour"},
    "linear_velocity_time": {"lv_time", "metric_statistics"},
    "angular_speed_time": {"as_time", "metric_statistics"},
    "distance_to_edge_time": {"distance_time", "metric_statistics"},
    "special_time_windows": {"special_window", "rrate_each_window"},
    "roaming_proportion": {"roaming_proportion"},
}


def _read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: {}".format(path))
    return value


def _safe_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("Bundle payload path is invalid")
    root = root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("Bundle payload path escapes the bundle root")
    if not candidate.is_file():
        raise ValueError("Bundle payload does not exist: {}".format(relative))
    return candidate


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _verified_file(bundle_root: Path, record: object) -> Path:
    if not isinstance(record, dict):
        raise ValueError("Bundle manifest record is invalid")
    path = _safe_file(bundle_root, record.get("path"))
    if path.stat().st_size != record.get("bytes"):
        raise ValueError("Bundle payload length mismatch: {}".format(path.name))
    if _digest(path) != record.get("sha256"):
        raise ValueError("Bundle payload SHA-256 mismatch: {}".format(path.name))
    return path


def load_verified_pickle(
    bundle_root: Path, manifest: Dict[str, Any], payload_key: str
) -> Any:
    """Verify and deserialize exactly one trusted payload."""
    payloads = manifest.get("payloads", {})
    if payload_key not in payloads:
        raise ValueError("Bundle payload key not found: {}".format(payload_key))
    path = _verified_file(Path(bundle_root), payloads[payload_key])
    with gzip.open(path, "rb") as stream:
        return pickle.load(stream)


def _bundle_source(project: Path) -> Path:
    sources = _read_json(project / "data_sources.json").get("sources", [])
    source = next(
        (item for item in sources if item.get("kind") == "plot_bundle"), None
    )
    if source is None:
        raise ValueError("Project has no Plot Bundle data source")
    if not source.get("trusted"):
        raise ValueError("Refusing to load an untrusted pickle bundle")
    if not source.get("read_only"):
        raise ValueError("Plot Bundle source must be marked read-only")
    return Path(source["location"]).resolve(strict=True)


def _load_bundle_index(project: Path, expected_analysis: str):
    bundle_root = _bundle_source(project)
    manifest = _read_json(bundle_root / "manifest.json")
    if manifest.get("format") != "behavior-analysis-plot-bundle":
        raise ValueError("Unsupported Plot Bundle format")
    if manifest.get("version") != 1:
        raise ValueError("Unsupported Plot Bundle version")
    if manifest.get("analysis") != expected_analysis:
        raise ValueError("Chart analysis does not match Plot Bundle")
    specs_path = _verified_file(bundle_root, manifest.get("plot_specs"))
    specs = _read_json(specs_path)
    if specs.get("analysis") != expected_analysis:
        raise ValueError("Plot specification analysis mismatch")
    return bundle_root, manifest, specs


def _normalise_artifacts(value: object) -> List[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    try:
        return [Path(item) for item in value]
    except TypeError:
        return []


def _write_output(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == destination.suffix.lower():
        shutil.copy2(source, destination)
        return
    if source.suffix.lower() != ".png":
        raise ValueError("Cannot convert renderer output {}".format(source.name))
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    image = mpimg.imread(source)
    height, width = image.shape[:2]
    figure = plt.figure(figsize=(width / 100.0, height / 100.0), dpi=100)
    axis = figure.add_axes([0, 0, 1, 1])
    axis.imshow(image)
    axis.axis("off")
    figure.savefig(destination, dpi=100)
    plt.close(figure)


def _pick_artifact(
    candidates: Iterable[Path], output_dir: Path, preferred_name: str = None
) -> Path:
    paths = [Path(path) for path in candidates if Path(path).is_file()]
    if preferred_name:
        preferred = output_dir / preferred_name
        if preferred.is_file():
            return preferred
        same_stem = [path for path in paths if path.stem == Path(preferred_name).stem]
        if same_stem:
            return sorted(same_stem, key=lambda path: path.name)[0]
    pngs = sorted(
        set(paths + list(output_dir.rglob("*.png"))), key=lambda path: path.name
    )
    if pngs:
        return pngs[0]
    existing = sorted(set(paths), key=lambda path: path.name)
    if existing:
        return existing[0]
    raise ValueError("Bundle renderer did not create an output image")


def _render_border(
    bundle_root: Path,
    manifest: Dict[str, Any],
    spec: Dict[str, Any],
    output: Path,
    customize=None,
) -> None:
    artifact = load_verified_pickle(bundle_root, manifest, spec["payload"])
    theme = spec.get("theme")
    if getattr(artifact, "theme", theme) != theme:
        raise ValueError("Border payload theme does not match plot specification")
    if theme not in ("counts", "eta", "fate", "roaming_dwell"):
        raise ValueError("Unsupported border plot theme: {}".format(theme))
    with tempfile.TemporaryDirectory(prefix="bundle-border-") as temp:
        output_dir = Path(temp)
        context = SimpleNamespace(
            analysis="border",
            artifact=artifact,
            spec=spec,
            output_dir=output_dir,
        )
        rendered = customize(context) if customize is not None else None
        if rendered is None:
            from behavior_analysis.border.visualization import (
                render_count_artifact,
                render_eta_artifact,
                render_fate_artifact,
                render_roaming_dwell_artifact,
            )

            renderers = {
                "counts": render_count_artifact,
                "eta": render_eta_artifact,
                "fate": render_fate_artifact,
                "roaming_dwell": render_roaming_dwell_artifact,
            }
            rendered = renderers[theme](artifact, output_dir)
        source = _pick_artifact(
            _normalise_artifacts(rendered), output_dir, spec.get("filename")
        )
        _write_output(source, output)


def _group_dataset(manifest: Dict[str, Any]) -> SimpleNamespace:
    metadata = manifest.get("metadata", {}).get("dataset", {})
    data_names = {
        int(group): {int(index): name for index, name in files.items()}
        for group, files in metadata.get("data_names", {}).items()
    }
    return SimpleNamespace(
        group_names=list(metadata.get("group_names", [])),
        data_names=data_names,
        data_type_name=metadata.get("data_type_name", "group"),
    )


def _render_group(
    bundle_root: Path,
    manifest: Dict[str, Any],
    spec: Dict[str, Any],
    output: Path,
    customize=None,
) -> None:
    kind = spec.get("kind")
    metrics: Dict[str, Any] = {}
    reconstructed = []
    analysis_type = "total"
    if kind == "reconstructed_tracks":
        reconstructed = load_verified_pickle(
            bundle_root, manifest, "reconstructed_tracks"
        )
        analysis_type = "single"
    else:
        all_metrics = load_verified_pickle(bundle_root, manifest, "metrics")
        if not isinstance(all_metrics, dict):
            raise ValueError("Group metrics payload must be a dictionary")
        keys = GROUP_KIND_KEYS.get(kind)
        if keys is None:
            raise ValueError("Unsupported group plot kind: {}".format(kind))
        keys = set(keys) | {"figure_description"}
        metrics = {key: all_metrics[key] for key in keys if key in all_metrics}

    result = SimpleNamespace(
        dataset=_group_dataset(manifest),
        metrics=metrics,
        reconstructed_tracks=reconstructed,
    )
    config_data = manifest.get("metadata", {}).get("config", {})
    config = SimpleNamespace(**config_data)
    with tempfile.TemporaryDirectory(prefix="bundle-group-") as temp:
        output_dir = Path(temp)
        context = SimpleNamespace(
            analysis="group",
            result=result,
            config=config,
            spec=spec,
            output_dir=output_dir,
        )
        rendered = customize(context) if customize is not None else None
        if rendered is None:
            from behavior_analysis.group.visualization import visualize_group

            rendered = visualize_group(
                result, output_dir, config=config, analysis_type=analysis_type
            )
        source = _pick_artifact(_normalise_artifacts(rendered), output_dir)
        _write_output(source, output)


def render_bundle_chart(
    project: Path, analysis: str, spec_index: int, output: Path, *, customize=None
) -> None:
    """Render one registered Plot Bundle chart into ``output``."""
    project = Path(project).resolve(strict=True)
    bundle_root, manifest, specs = _load_bundle_index(project, analysis)
    plots = specs.get("plots", [])
    if not isinstance(spec_index, int) or not 0 <= spec_index < len(plots):
        raise ValueError("Plot specification index is out of range")
    spec = plots[spec_index]
    if not isinstance(spec, dict):
        raise ValueError("Plot specification must be an object")
    if analysis == "border":
        _render_border(bundle_root, manifest, spec, Path(output), customize=customize)
    elif analysis == "group":
        _render_group(bundle_root, manifest, spec, Path(output), customize=customize)
    else:
        raise ValueError("Unsupported Plot Bundle analysis: {}".format(analysis))
