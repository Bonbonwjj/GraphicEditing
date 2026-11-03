import unittest
from io import BytesIO
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from interactive_style import apply_interactive_style, read_style, upsert_style
from server import thumbnail_image


class SparseStyleTests(unittest.TestCase):
    def test_component_styles_only_change_selected_text_spine_scatter_and_patch(self):
        from matplotlib.patches import Rectangle
        fig, axis = plt.subplots()
        self.addCleanup(plt.close, fig)
        axis.set(xlabel='X', ylabel='Y')
        original_x_size = axis.xaxis.label.get_fontsize()
        original_bottom_width = axis.spines['bottom'].get_linewidth()
        first = axis.scatter([0], [1], color='red', s=25)
        second = axis.scatter([1], [0], color='blue', s=36)
        patch = Rectangle((.2, .2), .2, .2, facecolor='yellow')
        axis.add_patch(patch)
        apply_interactive_style(fig, {
            'text_styles': {'axes_0.ylabel': {'font_size': 32}},
            'spine_styles': {'axes_0.spine_left': {'border_width': 4}},
            'series_styles': {'axes_0.collection_0': {'color': '#00ff00', 'markersize': 10},
                              'axes_0.patch_0': {'color': '#ff00ff'}},
        })
        self.assertEqual(axis.yaxis.label.get_fontsize(), 32)
        self.assertEqual(axis.xaxis.label.get_fontsize(), original_x_size)
        self.assertEqual(axis.spines['left'].get_linewidth(), 4)
        self.assertEqual(axis.spines['bottom'].get_linewidth(), original_bottom_width)
        self.assertEqual(first.get_sizes().tolist(), [100])
        self.assertEqual(second.get_sizes().tolist(), [36])
        self.assertEqual(first.get_facecolors()[0].tolist(), [0, 1, 0, 1])
        self.assertEqual(second.get_facecolors()[0].tolist(), [0, 0, 1, 1])
        self.assertEqual(patch.get_facecolor(), (1, 0, 1, 1))

    def test_border_change_preserves_labels_grid_legend_and_other_axes(self):
        fig, (left, right) = plt.subplots(1, 2)
        self.addCleanup(plt.close, fig)
        left.plot([0, 1], [1, 2], label='Original')
        left.set(xlabel='Time', ylabel='Score', title='Original title')
        left.grid(True)
        legend = left.legend(loc='lower right')
        right.spines['left'].set_linewidth(3)
        apply_interactive_style(fig, {'axes_styles': {'axes_0': {'border_width': 4}}})
        self.assertEqual((left.get_xlabel(), left.get_ylabel(), left.get_title()),
                         ('Time', 'Score', 'Original title'))
        self.assertTrue(any(line.get_visible() for line in left.get_xgridlines()))
        self.assertIs(left.get_legend(), legend)
        self.assertEqual(right.spines['left'].get_linewidth(), 3)

    def test_explicit_empty_clears_only_requested_label(self):
        fig, axis = plt.subplots()
        self.addCleanup(plt.close, fig)
        axis.set(xlabel='Time', ylabel='Score')
        apply_interactive_style(fig, {'axes_styles': {'axes_0': {'xlabel': '', 'ylabel': None}}})
        self.assertEqual(axis.get_xlabel(), '')
        self.assertEqual(axis.get_ylabel(), 'Score')

    def test_sparse_source_roundtrip_does_not_add_default_overrides(self):
        source = 'import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nfig.savefig("out.png")\n'
        result = upsert_style(source, {'axes_styles': {'axes_0': {'border_width': 4}}})
        self.assertEqual(read_style(result), {'axes_styles': {'axes_0': {'border_width': 4.0}}})

    def test_thumbnail_preserves_aspect_and_bounds(self):
        source = BytesIO()
        Image.new('RGB', (2000, 1000), 'white').save(source, format='PNG')
        with Image.open(BytesIO(thumbnail_image(source.getvalue()))) as image:
            self.assertEqual(image.size, (640, 320))

    def test_export_capture_preserves_outside_labels_and_matches_saved_pixels(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from matplotlib.figure import Figure
        from chart_naming import install_capture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fig, axis = plt.subplots(figsize=(4, 3))
            self.addCleanup(plt.close, fig)
            axis.set_position([.08, .08, .8, .8])
            axis.set(xlabel='Bottom label', ylabel='Outside left label')
            axis.set_xticks([0, 1], ['Group A', 'Group B'])
            output, report = root/'out.png', root/'report.json'
            with patch.object(Figure, 'savefig', Figure.savefig), patch.object(Figure, 'show', Figure.show):
                install_capture(output, root/'names.json', report)
                fig.savefig(output, bbox_inches='tight', dpi=180)
            result = json.loads(report.read_text(encoding='utf-8'))
            with Image.open(output) as image:
                self.assertEqual(result['render_size_px'], list(image.size))
            labels = [t for t in result['layout_signature']['texts']
                      if t['key'] in ('axes_0.xlabel', 'axes_0.ylabel')]
            self.assertEqual(len(labels), 2)
            width, height = result['render_size_px']
            for label in labels:
                x0, y0, x1, y1 = label['bbox']
                self.assertGreaterEqual(min(x0, y0), 0)
                self.assertLessEqual(x1, width)
                self.assertLessEqual(y1, height)
