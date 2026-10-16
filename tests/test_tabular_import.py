import json
import io
import tempfile
import unittest
from pathlib import Path

from generic_importer import import_generic
from upload_importer import safe_upload_path, store_bundle_multipart


class _UploadItem:
    def __init__(self, name, content):
        self.name = "bundle_files"
        self.filename = name
        self.file = io.BytesIO(content)


class _UploadFields:
    def __init__(self, items):
        self.list = items


class UploadPathTests(unittest.TestCase):
    def test_safe_relative_upload_path_preserves_folder_structure(self):
        self.assertEqual(
            Path("dataset") / "group-a" / "values.csv",
            safe_upload_path("dataset/group-a/values.csv"),
        )

    def test_parent_traversal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不安全"):
            safe_upload_path("../private/values.csv")

    def test_absolute_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不安全"):
            safe_upload_path("C:/private/values.csv")

    def test_bundle_upload_preserves_bundle_tree_and_returns_manifest_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            fields = _UploadFields(
                [
                    _UploadItem("my_bundle/manifest.json", b"{}"),
                    _UploadItem("my_bundle/plot_specs.json", b"{}"),
                    _UploadItem("my_bundle/payloads/metrics.pkl.gz", b"gzip"),
                ]
            )

            bundle = store_bundle_multipart(Path(tmp), "demo", fields)

            self.assertEqual("my_bundle", bundle.name)
            self.assertTrue((bundle / "payloads" / "metrics.pkl.gz").is_file())


class GenericImportTests(unittest.TestCase):
    @staticmethod
    def write_minimal_data(upload):
        data = upload / "csv"
        data.mkdir(parents=True, exist_ok=True)
        (data / "values.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    def test_explicit_charts_and_lib_folders_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "studio"
            upload = root / "data" / "uploads" / "demo" / "batch"
            charts = upload / "code" / "package" / "charts"
            library = upload / "code" / "package" / "lib" / "plot_helpers"
            charts.mkdir(parents=True)
            library.mkdir(parents=True)
            (charts / "summary.py").write_text(
                "import matplotlib.pyplot as plt\nplt.plot([1], [2])\n",
                encoding="utf-8",
            )
            (library / "theme.py").write_text("COLOR = 'red'\n", encoding="utf-8")
            self.write_minimal_data(upload)

            result = import_generic(root, upload, "demo", "Demo")

            project = root / "projects" / "demo"
            self.assertEqual(["summary"], result["charts"])
            self.assertTrue((project / "charts" / "summary.py").is_file())
            self.assertTrue((project / "lib" / "plot_helpers" / "theme.py").is_file())
            self.assertFalse((project / "charts" / "package_lib_plot_helpers_theme.py").exists())

    def test_legacy_flat_code_folder_still_creates_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "studio"
            upload = root / "data" / "uploads" / "demo" / "batch"
            code = upload / "code"
            code.mkdir(parents=True)
            (code / "plot.py").write_text(
                "import matplotlib.pyplot as plt\nplt.plot([1], [2])\n",
                encoding="utf-8",
            )
            self.write_minimal_data(upload)

            result = import_generic(root, upload, "demo", "Demo")

            self.assertEqual(["plot"], result["charts"])

    def test_csv_tsv_and_json_are_preserved_and_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "studio"
            upload = root / "data" / "uploads" / "demo" / "batch"
            (upload / "code").mkdir(parents=True)
            nested = upload / "csv" / "dataset"
            nested.mkdir(parents=True)
            (upload / "code" / "plot.py").write_text(
                "import matplotlib.pyplot as plt\nplt.plot([1], [2])\n",
                encoding="utf-8",
            )
            (nested / "values.csv").write_text("x,y\n1,2\n", encoding="utf-8")
            (nested / "values.tsv").write_text("x\ty\n1\t2\n", encoding="utf-8")
            (nested / "values.json").write_text('[{"x":1,"y":2}]', encoding="utf-8")

            result = import_generic(root, upload, "demo", "Demo")

            project = root / "projects" / "demo"
            self.assertEqual(3, result["files"])
            self.assertTrue((project / "data" / "dataset" / "values.csv").is_file())
            self.assertTrue((project / "data" / "dataset" / "values.tsv").is_file())
            self.assertTrue((project / "data" / "dataset" / "values.json").is_file())
            metadata = json.loads(
                (project / "data_sources.json").read_text(encoding="utf-8")
            )
            source = metadata["sources"][0]
            self.assertEqual("tabular", source["kind"])
            self.assertTrue(source["read_only"])
            self.assertEqual(
                [
                    "dataset/values.csv",
                    "dataset/values.json",
                    "dataset/values.tsv",
                ],
                source["metadata"]["files"],
            )
            self.assertTrue((project / "lib").is_dir())
            self.assertTrue((project / "outputs").is_dir())


if __name__ == "__main__":
    unittest.main()
