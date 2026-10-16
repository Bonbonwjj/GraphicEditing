import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bundle_importer import PlotBundleAdapter, import_plot_bundle, inspect_plot_bundle


def _record(root: Path, relative: str):
    path = root / relative
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def make_bundle(root: Path, analysis="border") -> Path:
    bundle = root / "bundle"
    payload_dir = bundle / "payloads" / "counts"
    payload_dir.mkdir(parents=True)
    (payload_dir / "0000.pkl.gz").write_bytes(b"payload-zero")
    (payload_dir / "0001.pkl.gz").write_bytes(b"payload-one")
    specs = {
        "analysis": analysis,
        "plots": [
            {
                "filename": "first.png",
                "theme": "counts",
                "kind": "count_all",
                "payload": "counts/0000",
            },
            {
                "filename": "second.png",
                "theme": "counts",
                "kind": "count_time",
                "payload": "counts/0001",
            },
        ],
    }
    (bundle / "plot_specs.json").write_text(
        json.dumps(specs), encoding="utf-8"
    )
    manifest = {
        "format": "behavior-analysis-plot-bundle",
        "version": 1,
        "analysis": analysis,
        "created_at": "2026-10-14T00:00:00+00:00",
        "metadata": {"label": "fixture"},
        "payloads": {
            "counts/0000": _record(bundle, "payloads/counts/0000.pkl.gz"),
            "counts/0001": _record(bundle, "payloads/counts/0001.pkl.gz"),
        },
        "plot_specs": _record(bundle, "plot_specs.json"),
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return bundle


class PlotBundleInspectionTests(unittest.TestCase):
    def test_adapter_recognises_and_describes_bundle_without_loading_pickle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp))
            adapter = PlotBundleAdapter()

            self.assertTrue(adapter.can_handle(bundle))
            descriptor = adapter.inspect(bundle, mode="server_path", trusted=True)

            self.assertEqual("plot_bundle", descriptor.kind)
            self.assertEqual("border", descriptor.metadata["analysis"])
            self.assertEqual(2, descriptor.metadata["plot_count"])
            self.assertEqual(23, descriptor.metadata["payload_bytes"])
            self.assertTrue(descriptor.trusted)

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp))
            (bundle / "payloads" / "counts" / "0000.pkl.gz").write_bytes(b"payload-zerX")

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                inspect_plot_bundle(bundle)

    def test_payload_path_outside_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp))
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["payloads"]["counts/0000"]["path"] = "../outside.pkl.gz"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Bundle 目录"):
                inspect_plot_bundle(bundle)

    def test_missing_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp))
            (bundle / "payloads" / "counts" / "0001.pkl.gz").unlink()

            with self.assertRaisesRegex(ValueError, "不存在"):
                inspect_plot_bundle(bundle)


class PlotBundleImportTests(unittest.TestCase):
    def test_import_registers_one_editable_chart_per_plot_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "studio"
            root.mkdir()
            bundle = make_bundle(Path(tmp) / "source")

            result = import_plot_bundle(
                root,
                bundle,
                project_id="border_demo",
                name="Border demo",
                mode="server_path",
                trusted=True,
            )

            project = root / "projects" / "border_demo"
            charts = sorted((project / "charts").glob("*.py"))
            self.assertEqual(2, len(charts))
            self.assertEqual(2, result["plot_count"])
            self.assertTrue(all("render_bundle_chart" in p.read_text(encoding="utf-8") for p in charts))
            self.assertTrue(all("def customize(context)" in p.read_text(encoding="utf-8") for p in charts))
            source_meta = json.loads(
                (project / "data_sources.json").read_text(encoding="utf-8")
            )
            self.assertEqual(str(bundle.resolve()), source_meta["sources"][0]["location"])
            self.assertTrue(source_meta["sources"][0]["read_only"])
            self.assertTrue((project / "outputs").is_dir())
            self.assertTrue((project / "history").is_dir())

    def test_failed_import_removes_new_incomplete_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "studio"
            root.mkdir()
            bundle = make_bundle(Path(tmp) / "source")
            (bundle / "payloads" / "counts" / "0000.pkl.gz").unlink()

            with self.assertRaises(ValueError):
                import_plot_bundle(
                    root,
                    bundle,
                    project_id="broken",
                    name="Broken",
                    mode="server_path",
                    trusted=True,
                )

            self.assertFalse((root / "projects" / "broken").exists())

    def test_untrusted_pickle_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "studio"
            root.mkdir()
            bundle = make_bundle(Path(tmp) / "source")

            with self.assertRaisesRegex(ValueError, "受信任"):
                import_plot_bundle(
                    root,
                    bundle,
                    project_id="unsafe",
                    name="Unsafe",
                    mode="server_path",
                    trusted=False,
                )


if __name__ == "__main__":
    unittest.main()
