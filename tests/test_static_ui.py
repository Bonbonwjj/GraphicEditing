import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DataSourceUiContractTests(unittest.TestCase):
    def test_import_dialog_exposes_bundle_type_and_both_source_modes(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        for element_id in (
            "importBundleButton",
            "uploadPackage",
            "bundleSourceMode",
            "bundleFolder",
            "bundleServerPath",
            "bundleTrusted",
        ):
            self.assertIn('id="{}"'.format(element_id), html)

    def test_browser_code_calls_both_bundle_import_endpoints(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8") + (ROOT / "static" / "ly_features.js").read_text(encoding="utf-8")

        self.assertIn("/api/data-sources/import-upload", javascript)
        self.assertIn("/api/data-sources/import", javascript)
        self.assertIn("share_mode:'embedded'", javascript)

    def test_shared_module_ui_has_validation_chart_selector(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="validationControls"', html)
        self.assertIn('id="validationChart"', html)

    def test_browser_supports_shared_module_resources(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8") + (ROOT / "static" / "ly_features.js").read_text(encoding="utf-8")

        self.assertIn("/modules/", javascript)
        self.assertIn("共享绘图模块", javascript)
        self.assertIn("validationChart", javascript)


if __name__ == "__main__":
    unittest.main()
