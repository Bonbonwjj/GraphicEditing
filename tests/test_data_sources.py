import tempfile
import unittest
from pathlib import Path

from data_sources import (
    DataSourceDescriptor,
    DataSourceRegistry,
    UnsupportedDataSourceError,
    resolve_allowed_path,
)


class _SuffixAdapter:
    kind = "example"

    def can_handle(self, source: Path) -> bool:
        return source.suffix == ".example"

    def inspect(self, source: Path, *, mode: str, trusted: bool):
        return DataSourceDescriptor(
            source_id="source-1",
            kind=self.kind,
            mode=mode,
            location=str(source),
            read_only=True,
            trusted=trusted,
            metadata={"name": source.name},
        )


class DataSourceRegistryTests(unittest.TestCase):
    def test_detect_selects_first_matching_adapter_and_normalises_descriptor(self):
        registry = DataSourceRegistry([_SuffixAdapter()])

        descriptor = registry.inspect(Path("sample.example"), mode="upload", trusted=True)

        self.assertEqual("example", descriptor.kind)
        self.assertEqual("upload", descriptor.mode)
        self.assertTrue(descriptor.read_only)
        self.assertTrue(descriptor.trusted)
        self.assertEqual("sample.example", descriptor.metadata["name"])
        self.assertEqual("source-1", descriptor.as_dict()["id"])

    def test_detect_rejects_unsupported_source(self):
        registry = DataSourceRegistry([_SuffixAdapter()])

        with self.assertRaisesRegex(UnsupportedDataSourceError, "不支持"):
            registry.inspect(Path("sample.csv"), mode="upload", trusted=False)


class AllowedRootTests(unittest.TestCase):
    def test_path_inside_allowed_root_is_returned_as_resolved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared"
            bundle = root / "experiment" / "bundle"
            bundle.mkdir(parents=True)

            resolved = resolve_allowed_path(bundle, [root])

            self.assertEqual(bundle.resolve(), resolved)

    def test_traversal_outside_allowed_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared"
            outside = Path(tmp) / "private"
            root.mkdir()
            outside.mkdir()

            with self.assertRaisesRegex(ValueError, "允许的共享目录"):
                resolve_allowed_path(root / ".." / "private", [root])

    def test_empty_allowed_roots_rejects_server_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "未配置"):
                resolve_allowed_path(Path(tmp), [])


if __name__ == "__main__":
    unittest.main()
