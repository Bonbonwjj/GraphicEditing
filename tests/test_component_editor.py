import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from component_editor import validate_components
from interactive_style import apply_interactive_style, upsert_style, read_style


class ComponentEditorTests(unittest.TestCase):
    def test_isolated_snapshot_contains_transitive_component_modules(self):
        import tempfile
        from pathlib import Path
        from chat_runner import _one_render
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';(project/'charts').mkdir(parents=True)
            source="""import os
import matplotlib.pyplot as plt
from interactive_style import apply_interactive_style
from component_groups import install_group_tracking
install_group_tracking()
fig,ax=plt.subplots()
ax.errorbar([0,1],[1,2],yerr=.1,capsize=5)
ax.set(xlabel='X',ylabel='Y')
apply_interactive_style(fig,{'component_styles':{'axes_0.ylabel':{'color':'#ff0000'}}})
fig.savefig(os.environ['CHART_OUTPUT'])
"""
            (project/'charts/plot.py').write_text(source,encoding='utf-8')
            result=_one_render(project,'charts/plot.py',{},root/'render')
            self.assertTrue(result['image_bytes'].startswith(b'\x89PNG'))
            self.assertTrue((root/'render/packages/component_editor.py').is_file())
            self.assertTrue((root/'render/packages/component_groups.py').is_file())

    def test_axis_scale_moves_data_and_ticks_together_without_changing_values(self):
        fig, axis=plt.subplots()
        self.addCleanup(plt.close,fig)
        line,=axis.plot([0,1],[0,1])
        axis.set_xticks([0,.5,1]);axis.set_yticks([0,.5,1])
        axis.set_xlim(0,1);axis.set_ylim(0,1);fig.canvas.draw()
        before=line.get_transform().transform(line.get_xydata())
        apply_interactive_style(fig,{'component_styles':{'axes_0.spine_left':{'scale':.5}}})
        fig.canvas.draw()
        after=line.get_transform().transform(line.get_xydata())
        self.assertAlmostEqual(after[1,1]-after[0,1],.5*(before[1,1]-before[0,1]))
        self.assertAlmostEqual(after[1,0]-after[0,0],before[1,0]-before[0,0])
        np.testing.assert_array_equal(axis.get_yticks(),[0,.5,1])
        for tick in axis.yaxis.get_major_ticks():
            self.assertAlmostEqual(tick.tick1line.get_transform().transform(tick.tick1line.get_xydata())[0,1],axis.transData.transform((0,tick.get_loc()))[1])
        np.testing.assert_array_equal(line.get_ydata(),[0,1])

    def test_axis_scale_survives_tight_layout_and_export_without_accumulating(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import json
        from matplotlib.figure import Figure
        from chart_naming import install_capture
        fig,axis=plt.subplots(figsize=(6,4))
        self.addCleanup(plt.close,fig)
        axis.plot([0,1],[0,1]);axis.set(xlabel='X',ylabel='Y')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'out.png';report=root/'report.json'
            with patch.object(Figure,'savefig',Figure.savefig),patch.object(Figure,'show',Figure.show):
                install_capture(output,root/'names.json',report)
                fig.tight_layout();fig.savefig(output,bbox_inches='tight')
                original=json.loads(report.read_text())['layout_signature']['axes'][0]['spines']
                apply_interactive_style(fig,{'component_styles':{'axes_0':{'x_scale':.6,'y_scale':.5}}})
                fig.tight_layout();fig.savefig(output,bbox_inches='tight')
                current=json.loads(report.read_text())['layout_signature']['axes'][0]['spines']
                self.assertAlmostEqual((current['bottom'][2]-current['bottom'][0])/(original['bottom'][2]-original['bottom'][0]),.6,places=5)
                self.assertAlmostEqual((current['left'][3]-current['left'][1])/(original['left'][3]-original['left'][1]),.5,places=5)
                size=tuple(axis.get_position().bounds)
                fig.savefig(output,bbox_inches='tight')
                np.testing.assert_allclose(axis.get_position().bounds,size)

    def test_properties_ranges_and_transforms_preserve_source_values(self):
        fig, axis = plt.subplots()
        self.addCleanup(plt.close, fig)
        line, = axis.plot([0, 1], [1, 2])
        other, = axis.plot([0, 1], [2, 1])
        axis.set(xlabel='X', ylabel='Y')
        patch = Rectangle((.2, .3), .4, .2)
        axis.add_patch(patch)
        fig.canvas.draw()
        original = line.get_transform().transform([[0, 1], [1, 2]])
        style = {'component_styles': {
            'axes_0': {'xlim': [-1, 3], 'ylim': [0, 4]},
            'axes_0.ylabel': {'color': '#ff0000', 'font_size': 24, 'font_family': 'DejaVu Sans', 'text': 'New Y', 'dx': 12},
            'axes_0.line_0': {'linewidth': 5, 'dx': 10, 'dy': 20, 'scale': .5},
            'axes_0.patch_0': {'fill_color': '#00ff00', 'edge_color': '#ff0000', 'linewidth': 3, 'scale': 2},
        }}
        apply_interactive_style(fig, style)
        self.assertEqual(axis.get_xlim(), (-1, 3))
        self.assertEqual(axis.get_ylim(), (0, 4))
        self.assertEqual(axis.get_ylabel(), 'New Y')
        self.assertEqual(axis.yaxis.label.get_color(), '#ff0000')
        self.assertEqual(axis.xaxis.label.get_text(), 'X')
        self.assertEqual(line.get_linewidth(), 5)
        self.assertNotEqual(other.get_linewidth(), 5)
        np.testing.assert_array_equal(line.get_ydata(), [1, 2])
        self.assertFalse(np.array_equal(original, line.get_transform().transform([[0, 1], [1, 2]])))
        self.assertEqual(patch.get_facecolor(), (0, 1, 0, 1))
        self.assertEqual(patch.get_edgecolor(), (1, 0, 0, 1))
        self.assertEqual(patch.get_linewidth(), 3)
        # Rectangle's own patch transform must be applied exactly once.
        fig.canvas.draw()
        self.assertAlmostEqual(patch.get_window_extent().width / axis.bbox.width, .2)
        source = 'import matplotlib.pyplot as plt\nfig, ax=plt.subplots()\nfig.savefig("x.png")\n'
        self.assertEqual(read_style(upsert_style(source, style))['component_styles'], style['component_styles'])

    def test_multiple_items_share_the_same_numeric_scale(self):
        fig, axis = plt.subplots()
        self.addCleanup(plt.close, fig)
        first, = axis.plot([0, 1], [1, 2])
        second, = axis.plot([0, 1], [2, 1])
        fig.canvas.draw()
        before = [line.get_transform().transform(line.get_xydata()) for line in (first, second)]
        apply_interactive_style(fig, {'component_styles': {key: {'scale': .5, 'dx': 12} for key in ('axes_0.line_0', 'axes_0.line_1')}})
        for line, points in zip((first, second), before):
            after = line.get_transform().transform(line.get_xydata())
            np.testing.assert_allclose(after[1]-after[0], (points[1]-points[0])*.5)

    def test_range_edit_keeps_frames_and_remaps_data_on_draw_and_export(self):
        import io
        for layout in (None, 'constrained'):
            with self.subTest(layout=layout):
                fig, axes = plt.subplots(1, 2, figsize=(8, 4), layout=layout)
                try:
                    axis, neighbor = axes
                    line, = axis.plot([0, 1], [0, 1])
                    axis.set(xlim=(0, 1), ylim=(0, 1))
                    axis.set_aspect('equal')
                    neighbor.plot([0, 1], [1, 0])
                    fig.canvas.draw()
                    frames = [a.bbox.bounds for a in axes]
                    before = axis.transData.transform((1, 1))
                    apply_interactive_style(fig, {'component_styles': {
                        'axes_0': {'xlim': [0, 2], 'ylim': [0, 4]}}})
                    fig.tight_layout()
                    fig.canvas.draw()
                    for a, frame in zip(axes, frames):
                        np.testing.assert_allclose(a.bbox.bounds, frame)
                    after = axis.transData.transform((1, 1))
                    self.assertLess(after[0], before[0])
                    self.assertLess(after[1], before[1])
                    np.testing.assert_array_equal(line.get_xydata(), [[0, 0], [1, 1]])
                    self.assertEqual(axis.get_xlim(), (0, 2))
                    self.assertEqual(axis.get_ylim(), (0, 4))
                    fig.savefig(io.BytesIO(), format='png')
                    for a, frame in zip(axes, frames):
                        np.testing.assert_allclose(a.bbox.bounds, frame)
                finally:
                    plt.close(fig)

    def test_invalid_properties_and_log_ranges_are_rejected(self):
        for spec in ({'scale': 0}, {'xlim': [1, 1]}, {'dy': float('nan')}, {'font_family': 1}, {'color': 'red'}):
            with self.assertRaises(ValueError): validate_components({'axes_0': spec})
        fig, axis = plt.subplots()
        self.addCleanup(plt.close, fig)
        axis.set_xscale('log')
        with self.assertRaises(ValueError): apply_interactive_style(fig, {'component_styles': {'axes_0': {'xlim': [-1, 2]}}})


class RangeEndpointTests(unittest.TestCase):
    def test_both_endpoints_are_labeled_without_changing_frame(self):
        import io
        from matplotlib.ticker import FixedFormatter, FixedLocator
        for scale, limits in (('linear', (.13, 3.87)), ('linear', (3.87, .13)),
                              ('linear', (-1.23, 8.76)), ('log', (.3, 73))):
            with self.subTest(scale=scale, limits=limits):
                fig, axis = plt.subplots()
                try:
                    axis.plot([1, 2], [1, 2]); axis.set_yscale(scale)
                    if scale == 'linear':
                        axis.yaxis.set_major_locator(FixedLocator([0, 1, 2]))
                        axis.yaxis.set_major_formatter(FixedFormatter(['0', '1', '2']))
                    fig.canvas.draw(); frame = axis.bbox.bounds
                    for pair in (limits, (limits[0], limits[1]*1.1)):
                        apply_interactive_style(fig, {'component_styles': {'axes_0': {'ylim': list(pair)}}})
                        fig.tight_layout(); fig.canvas.draw()
                        np.testing.assert_allclose(axis.bbox.bounds, frame)
                        ticks = axis.get_yticks(); labels = axis.get_yticklabels()
                        for endpoint in pair:
                            index = np.flatnonzero(np.isclose(ticks, endpoint))[0]
                            self.assertTrue(labels[index].get_visible())
                            self.assertTrue(labels[index].get_text().strip())
                        if scale == 'linear':
                            np.testing.assert_allclose(np.diff(ticks), np.diff(ticks)[0])
                        self.assertEqual(axis.get_ylim(), pair)
                        fig.savefig(io.BytesIO(), format='png')
                        np.testing.assert_allclose(axis.bbox.bounds, frame)
                finally:
                    plt.close(fig)
