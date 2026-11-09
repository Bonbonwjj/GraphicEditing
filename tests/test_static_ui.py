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

    def test_interactive_style_lives_in_preview_and_uses_transient_endpoint(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        figure = html.split('id="figurePane"', 1)[1].split('id="codePane"', 1)[0]
        code = html.split('id="codePane"', 1)[1].split('id="dataPane"', 1)[0]
        self.assertIn('id="interactiveStyle"', figure)
        self.assertNotIn('id="interactiveStyle"', code)
        self.assertIn("'style-preview'", javascript)
        self.assertIn('确定并同步更改代码', html)
        self.assertIn('id="clearSelectedLine"', html)
        self.assertIn('hit_path_px', javascript)
        self.assertIn('onpointerdown', javascript)
        self.assertIn('legend_anchor', javascript)
        self.assertIn('series_styles', javascript)
        self.assertIn('result.texts', javascript)
        self.assertIn('result.axes', javascript)
        self.assertIn('highlightInteractiveControls', javascript)
        self.assertIn('interactionActive', (ROOT / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn('openComponentInspector', javascript)
        self.assertIn('selectSubplot', javascript)
        self.assertIn('axes_styles', javascript)
        self.assertIn('componentInspector', (ROOT / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn('.previewStylePanel{display:none!important}', (ROOT / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn('.chartCard.active{grid-column:1/-1', (ROOT / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn('data-inspector-apply', javascript)
        self.assertIn('data-inspector-cancel', javascript)
        self.assertIn('showStyleComparison', javascript)
        self.assertIn('commitInteractiveStyle', javascript)
        self.assertIn('data-compare-confirm', javascript)
        self.assertIn('修改前 · 当前版本', javascript)
        self.assertIn('本次修改 · 候选版本', javascript)
        self.assertIn('styleCompareDialog', (ROOT / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn('将此格式更新为当前版本', javascript)
        self.assertIn('stylePreviewQueued', javascript)
        self.assertIn('const pendingLatest=stylePreviewQueued', javascript)
        self.assertIn('stylePreviewData._dirty=true', javascript)
        self.assertIn('已显示上一轮修改，正在追赶最新修改', javascript)
        self.assertIn("original.type==='color'", javascript)
        self.assertIn("if(id==='lineColor')$('useLineColor').checked=true", javascript)
        self.assertIn('cssColorToHex', javascript)
        self.assertIn('chartLoadingOverlay', javascript)
        self.assertIn('stylePreviewData?._project', javascript)
        self.assertIn("const delay=lightweight?($('subplotZoomDialog')?700:280):100", javascript)
        self.assertIn("zoomed=!!$('subplotZoomDialog')",javascript)
        self.assertIn('style,lightweight,zoomed',javascript)
        component_editor=(ROOT / "static" / "component_editor.js").read_text(encoding="utf-8")
        self.assertIn('offlineComponentPreview',component_editor)
        self.assertIn('已在本地即时预览',component_editor)
        self.assertIn("['color','fill_color','edge_color','linewidth','alpha','fill_alpha','edge_alpha']",component_editor)
        self.assertIn("const geometric=new Set(['dx','dy','scale','x_scale','y_scale','width_scale','xlim','ylim'])",component_editor)
        self.assertIn('#subplotZoomDialog .subplotZoomFrame img',component_editor)
        subplot=(ROOT / "static" / "subplot_zoom.js").read_text(encoding="utf-8")
        self.assertIn('requestAnimationFrame',subplot)
        self.assertIn('正在后台生成 360 DPI 高清版本',subplot)
        self.assertIn('currentDpi<360',subplot)
        self.assertIn("key?'axis':'global'", javascript)
        self.assertIn('整图共享图例属性', javascript)
        self.assertIn('id="png"', html)
        self.assertIn("endpoint('png')", javascript)
        self.assertIn("location.port",javascript)
        workspace=(ROOT / "static" / "workspace.js").read_text(encoding="utf-8")
        self.assertIn("some(project=>project.can_open)",workspace)
        self.assertNotIn("setTimeout(openWorkspace,100)",workspace)
        self.assertIn('原图 DPI', html)
        self.assertIn("$('png').hidden=!formats.includes('png')", (ROOT / "static" / "workspace.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
