import gzip
import hashlib
import json
import pickle
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bundle_runtime import load_verified_pickle, render_bundle_chart


def _record(root: Path, relative: str):
    path = root / relative
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as stream:
        pickle.dump(value, stream, protocol=5)


def _write_project(project: Path, bundle: Path, manifest, specs):
    (bundle / "plot_specs.json").write_text(json.dumps(specs), encoding="utf-8")
    manifest["plot_specs"] = _record(bundle, "plot_specs.json")
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    project.mkdir(parents=True)
    (project / "data_sources.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": [
                    {
                        "id": "bundle",
                        "kind": "plot_bundle",
                        "mode": "server_path",
                        "location": str(bundle),
                        "read_only": True,
                        "trusted": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class VerifiedPayloadTests(unittest.TestCase):
    def test_loading_one_payload_does_not_open_other_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            _dump(bundle / "payloads" / "first.pkl.gz", {"value": 1})
            (bundle / "payloads" / "other.pkl.gz").write_bytes(b"not-a-pickle")
            manifest = {
                "payloads": {
                    "first": _record(bundle, "payloads/first.pkl.gz"),
                    "other": _record(bundle, "payloads/other.pkl.gz"),
                }
            }

            loaded = load_verified_pickle(bundle, manifest, "first")

            self.assertEqual({"value": 1}, loaded)


class BorderRuntimeTests(unittest.TestCase):
    def test_border_chart_loads_selected_payload_and_calls_theme_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            bundle = base / "bundle"
            selected = types.SimpleNamespace(
                theme="counts", filename="selected.png", marker="chosen"
            )
            _dump(bundle / "payloads" / "counts" / "0000.pkl.gz", selected)
            (bundle / "payloads" / "counts" / "0001.pkl.gz").write_bytes(b"invalid")
            manifest = {
                "format": "behavior-analysis-plot-bundle",
                "version": 1,
                "analysis": "border",
                "metadata": {},
                "payloads": {
                    "counts/0000": _record(bundle, "payloads/counts/0000.pkl.gz"),
                    "counts/0001": _record(bundle, "payloads/counts/0001.pkl.gz"),
                },
            }
            specs = {
                "analysis": "border",
                "plots": [
                    {
                        "theme": "counts",
                        "kind": "count_all",
                        "filename": "selected.png",
                        "payload": "counts/0000",
                    },
                    {
                        "theme": "counts",
                        "kind": "other",
                        "filename": "other.png",
                        "payload": "counts/0001",
                    },
                ],
            }
            _write_project(project, bundle, manifest, specs)

            captured = []

            def renderer(artifact, output_dir):
                captured.append(artifact.marker)
                path = Path(output_dir) / artifact.filename
                path.write_bytes(b"rendered-border")
                return [path]

            visualization = types.ModuleType("behavior_analysis.border.visualization")
            visualization.render_count_artifact = renderer
            visualization.render_eta_artifact = renderer
            visualization.render_fate_artifact = renderer
            visualization.render_roaming_dwell_artifact = renderer
            modules = {
                "behavior_analysis": types.ModuleType("behavior_analysis"),
                "behavior_analysis.border": types.ModuleType("behavior_analysis.border"),
                "behavior_analysis.border.visualization": visualization,
            }
            output = base / "chart.png"
            with patch.dict(sys.modules, modules):
                render_bundle_chart(project, "border", 0, output)

            self.assertEqual(["chosen"], captured)
            self.assertEqual(b"rendered-border", output.read_bytes())

    def test_chart_customize_hook_can_replace_one_border_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            bundle = base / "bundle"
            selected = types.SimpleNamespace(
                theme="counts", filename="selected.png", marker="chosen"
            )
            _dump(bundle / "payloads" / "counts" / "0000.pkl.gz", selected)
            manifest = {
                "format": "behavior-analysis-plot-bundle",
                "version": 1,
                "analysis": "border",
                "metadata": {},
                "payloads": {
                    "counts/0000": _record(bundle, "payloads/counts/0000.pkl.gz")
                },
            }
            specs = {
                "analysis": "border",
                "plots": [
                    {
                        "theme": "counts",
                        "kind": "count_all",
                        "filename": "selected.png",
                        "payload": "counts/0000",
                    }
                ],
            }
            _write_project(project, bundle, manifest, specs)
            observed = []

            def customize(context):
                observed.append((context.analysis, context.artifact.marker))
                path = context.output_dir / "custom.png"
                path.write_bytes(b"custom-border")
                return path

            output = base / "chart.png"
            render_bundle_chart(project, "border", 0, output, customize=customize)

            self.assertEqual([("border", "chosen")], observed)
            self.assertEqual(b"custom-border", output.read_bytes())


class GroupRuntimeTests(unittest.TestCase):
    def test_group_chart_dispatches_only_selected_metric_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            bundle = base / "bundle"
            metrics = {
                "figure_description": "demo",
                "rrate_each_hour": {0: [1]},
                "lv_time": {0: [2]},
            }
            _dump(bundle / "payloads" / "metrics.pkl.gz", metrics)
            (bundle / "payloads" / "reconstructed.pkl.gz").write_bytes(b"invalid")
            manifest = {
                "format": "behavior-analysis-plot-bundle",
                "version": 1,
                "analysis": "group",
                "metadata": {
                    "dataset": {
                        "group_names": ["g1"],
                        "data_names": {"0": {"0": "file"}},
                        "data_type_name": "group-demo",
                    },
                    "config": {"fps": 10, "in_patch": 1},
                },
                "payloads": {
                    "metrics": _record(bundle, "payloads/metrics.pkl.gz"),
                    "reconstructed_tracks": _record(bundle, "payloads/reconstructed.pkl.gz"),
                },
            }
            specs = {
                "analysis": "group",
                "plots": [
                    {"kind": "roaming_rate", "data_keys": ["rrate_each_hour"]}
                ],
            }
            _write_project(project, bundle, manifest, specs)

            captured = []

            def visualize(result, output_dir, config=None, **kwargs):
                captured.append(sorted(result.metrics))
                path = Path(output_dir) / "group.png"
                path.write_bytes(b"rendered-group")
                return [path]

            visualization = types.ModuleType("behavior_analysis.group.visualization")
            visualization.visualize_group = visualize
            modules = {
                "behavior_analysis": types.ModuleType("behavior_analysis"),
                "behavior_analysis.group": types.ModuleType("behavior_analysis.group"),
                "behavior_analysis.group.visualization": visualization,
            }
            output = base / "chart.png"
            with patch.dict(sys.modules, modules):
                render_bundle_chart(project, "group", 0, output)

            self.assertIn("rrate_each_hour", captured[0])
            self.assertNotIn("lv_time", captured[0])
            self.assertEqual(b"rendered-group", output.read_bytes())


if __name__ == "__main__":
    unittest.main()
