import io
import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.collections import PathCollection
import numpy as np

from chat_runner import _capture, _install_stat_capture, _one_render
from component_groups import install_group_tracking, component_groups
from interactive_style import apply_interactive_style, upsert_style, read_style
from plot_modes import apply_modes, capabilities, validate_modes, CATEGORY_MODES


class PlotModeTests(unittest.TestCase):
    def setUp(self):
        original = {name: getattr(Axes, name) for name in ('boxplot', 'violinplot', 'bxp', 'violin')}
        self.addCleanup(lambda: [setattr(Axes, name, method) for name, method in original.items()])
        self.addCleanup(plt.close, 'all')
        _install_stat_capture(Axes)
        install_group_tracking()

    def example(self, horizontal=False):
        figure, (axis, other) = plt.subplots(1, 2)
        values = [np.array([1., 2, 4, 8]), np.array([2., 3, 5, 9])]
        axis.boxplot(values, positions=[0, 1], patch_artist=True,
                     orientation='horizontal' if horizontal else 'vertical')
        (axis.set_yticks if horizontal else axis.set_xticks)([0, 1], ['A', 'B'])
        axis.set(xlabel='Group', ylabel='Score')
        other.plot([0, 1], [2, 3], label='Other')
        figure.canvas.draw()
        return figure, axis, other, values

    def test_box_and_scatter_keep_all_samples_categories_and_neighbor(self):
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                figure, axis, other, values = self.example(horizontal)
                frames = [a.bbox.bounds for a in figure.axes]
                neighbor = other.lines[0].get_xydata().copy()
                apply_interactive_style(figure, {'plot_modes': {'axes_0': ['scatter', 'boxplot']}})
                figure.canvas.draw()
                points = [a for a in axis.collections if isinstance(a, PathCollection)]
                self.assertEqual(len(points), 2)
                for scatter, original in zip(points, values):
                    np.testing.assert_array_equal(scatter.get_offsets()[:, 0 if horizontal else 1], original)
                self.assertEqual(sum('.box_' in key for key in component_groups(figure)), 2)
                labels = axis.get_yticklabels() if horizontal else axis.get_xticklabels()
                self.assertEqual([label.get_text() for label in labels], ['A', 'B'])
                for a, frame in zip(figure.axes, frames):
                    np.testing.assert_allclose(a.bbox.bounds, frame)
                np.testing.assert_array_equal(other.lines[0].get_xydata(), neighbor)
                figure.savefig(io.BytesIO(), format='png', dpi=150)

    def test_all_layers_and_repeated_switches_do_not_duplicate_samples(self):
        figure, axis, _, values = self.example()
        apply_modes(figure, {'axes_0': list(CATEGORY_MODES)})
        scatter = [a for a in axis.collections if isinstance(a, PathCollection) and getattr(a, '_plot_mode_layer', '') == 'scatter']
        self.assertEqual(sum(len(a.get_offsets()) for a in scatter), sum(map(len, values)))
        self.assertEqual(len(axis._plot_mode_samples), 1)
        for _ in range(3):
            apply_modes(figure, {'axes_0': ['scatter']})
            self.assertEqual(len(axis.collections), 2)
            self.assertEqual(len(axis.patches), 0)
            self.assertEqual(len(axis.containers), 0)
        self.assertEqual(len(axis._plot_mode_samples), 1)

    def test_violin_constant_group_is_rejected_before_mutating_figure(self):
        figure, axis = plt.subplots()
        axis.boxplot([[2, 2, 2]], patch_artist=True)
        before = list(axis.patches)
        with self.assertRaisesRegex(ValueError, '常量'):
            apply_modes(figure, {'axes_0': ['violinplot', 'scatter']})
        self.assertEqual(list(axis.patches), before)

    def test_summary_layers_use_means_and_sem_from_full_groups(self):
        figure, axis, _, values = self.example()
        apply_modes(figure, {'axes_0': ['mean_bar']})
        np.testing.assert_allclose([patch.get_height() for patch in axis.patches], [np.mean(v) for v in values])
        bars = axis.containers[-1]
        segments = bars.errorbar.lines[2][0].get_segments()
        for segment, original in zip(segments, values):
            self.assertAlmostEqual(np.ptp(segment[:, 1]), 2*np.std(original, ddof=1)/np.sqrt(len(original)))

    def test_xy_overlay_keeps_exact_order_and_unnamed_annotation(self):
        figure, axis = plt.subplots()
        line, = axis.plot([2, 0, 1], [4, 3, 6], label='A')
        bracket, = axis.plot([0, 0, 1, 1], [6, 7, 7, 6])
        original = line.get_xydata().copy()
        for modes in (['scatter', 'line'], ['scatter'], ['line', 'scatter']):
            apply_modes(figure, {'axes_0': modes})
            self.assertIn(bracket, axis.lines)
            self.assertEqual(len(axis.collections), 1)
            np.testing.assert_array_equal(axis.collections[0].get_offsets(), original)
            self.assertEqual(len(axis.lines), 2 if 'line' in modes else 1)

    def test_paired_lines_and_significance_are_preserved(self):
        figure, axis, _, _ = self.example()
        pair, = axis.plot([0, 1], [2, 3], alpha=.3)
        text = axis.text(.5, 10, '***')
        apply_modes(figure, {'axes_0': ['violinplot', 'scatter']})
        self.assertIn(pair, axis.lines)
        self.assertIn(text, axis.texts)

    def test_unsupported_types_and_missing_samples_do_not_invent_data(self):
        for value in ({'axes_0': []}, {'axes_0': ['scatter', 'scatter']}, {'axes_0': ['unknown']}):
            with self.assertRaises(ValueError):
                validate_modes(value)
        figure, axis = plt.subplots()
        axis.bar([0, 1], [3, 4])
        self.assertFalse(capabilities(figure)[0]['supported'])
        with self.assertRaises(ValueError):
            apply_modes(figure, {'axes_0': ['boxplot']})

    def test_histogram_and_density_overlay_uses_observation_axis(self):
        figure, axis, other, values = self.example()
        frame = other.bbox.bounds
        apply_modes(figure, {'axes_0': ['histogram', 'density']})
        figure.canvas.draw()
        self.assertEqual(axis.get_xlabel(), 'Score')
        self.assertEqual(axis.get_ylabel(), 'Probability density')
        self.assertEqual(len(axis.lines), 2)
        self.assertGreater(len(axis.patches), 0)
        np.testing.assert_allclose(other.bbox.bounds, frame)
        self.assertEqual(len(axis._plot_mode_samples), 1)
        for mode in ('density', 'histogram'):
            apply_modes(figure, {'axes_0': [mode]})
            self.assertEqual(axis._plot_modes_selected, [mode])
            self.assertEqual(axis.get_xlabel(), 'Score')
        apply_modes(figure, {'axes_0':['boxplot','scatter']})
        self.assertEqual(axis.get_xlabel(), 'Group')
        self.assertEqual(axis.get_ylabel(), 'Score')
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], ['A','B'])

    def test_incompatible_coordinate_types_are_rejected_before_change(self):
        figure, axis, _, _ = self.example()
        patches = list(axis.patches)
        with self.assertRaisesRegex(ValueError, '不能'):
            apply_modes(figure, {'axes_0': ['histogram', 'boxplot']})
        self.assertEqual(list(axis.patches), patches)

    def test_count_histogram_uses_original_metric_and_exact_bin_counts(self):
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                figure, axis, other, values = self.example(horizontal)
                frames = [a.bbox.bounds for a in figure.axes]
                self.assertIn('histogram_count', capabilities(figure)[0]['supported'])
                apply_modes(figure, {'axes_0': ['histogram_count']})
                figure.canvas.draw()
                self.assertEqual(axis.get_xlabel(), 'Group' if horizontal else 'Score')
                self.assertEqual(axis.get_ylabel(), 'Count')
                edges = np.histogram_bin_edges(np.concatenate(values), bins='auto')
                for bars, observations in zip(axis.containers, values):
                    np.testing.assert_array_equal([p.get_height() for p in bars], np.histogram(observations, edges)[0])
                    self.assertEqual(sum(p.get_height() for p in bars), len(observations))
                    np.testing.assert_allclose([p.get_x() for p in bars], edges[:-1])
                for a, frame in zip(figure.axes, frames):
                    np.testing.assert_allclose(a.bbox.bounds, frame)
                ticks = axis.get_yticks()
                np.testing.assert_allclose(ticks, np.round(ticks))
                apply_modes(figure, {'axes_0': ['histogram', 'density']})
                self.assertEqual(axis.get_ylabel(), 'Probability density')
                apply_modes(figure, {'axes_0': ['boxplot']})
                self.assertEqual(axis.get_xlabel(), 'Group')
                self.assertEqual(axis.get_ylabel(), 'Score')

    def test_count_and_density_cannot_mix_units_or_modify_original(self):
        figure, axis, _, _ = self.example()
        patches = list(axis.patches)
        for modes in (['histogram_count', 'histogram'], ['histogram_count', 'density'], ['histogram_count', 'boxplot'],
                      ['density_count', 'density'], ['density_count', 'histogram'], ['density_count', 'boxplot']):
            with self.assertRaisesRegex(ValueError, '不能'):
                apply_modes(figure, {'axes_0': modes})
            self.assertEqual(list(axis.patches), patches)

    def test_count_density_scales_each_group_by_its_sample_size_and_shared_bin_width(self):
        from scipy.stats import gaussian_kde
        figure, axis = plt.subplots()
        values = [np.array([1., 2, 4, 8]), np.array([2., 3, 5, 9, 10, 12])]
        axis.boxplot(values, patch_artist=True)
        axis.set(xlabel='Group', ylabel='Score')
        figure.canvas.draw()
        frame = axis.bbox.bounds
        edges = np.histogram_bin_edges(np.concatenate(values), bins='auto')
        width = edges[1]-edges[0]
        for modes in (['density_count'], ['histogram_count', 'density_count']):
            apply_modes(figure, {'axes_0': modes})
            figure.canvas.draw()
            self.assertEqual(axis.get_xlabel(), 'Score')
            self.assertIn(f'width={width:g}', axis.get_ylabel())
            self.assertEqual(len(axis.lines), 2)
            self.assertEqual(bool(axis.patches), 'histogram_count' in modes)
            for line, observations in zip(axis.lines, values):
                np.testing.assert_allclose(line.get_ydata(), gaussian_kde(observations)(line.get_xdata())*len(observations)*width)
            np.testing.assert_allclose(axis.bbox.bounds, frame)
        apply_modes(figure, {'axes_0': ['boxplot']})
        self.assertEqual(axis.get_ylabel(), 'Score')

    def test_count_density_cannot_estimate_constant_samples(self):
        figure, axis = plt.subplots()
        axis.boxplot([[1, 1, 1]], patch_artist=True)
        self.assertIn('density_count', capabilities(figure)[0]['unavailable'])
        with self.assertRaisesRegex(ValueError, '常量'):
            apply_modes(figure, {'axes_0': ['density_count']})

    def test_count_histogram_fast_preview_matches_full_render(self):
        from tests.test_fast_interactive_preview import fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, source = fixture(root)
            code = project/'lib/native/fig1/code/plot.py'
            code.write_text(code.read_text(encoding='utf-8').replace('    ax.plot([0,1],[1,3])\n', ''), encoding='utf-8')
            baseline = _one_render(project, 'charts/fig1.py', {}, root/'baseline', capture_interactive_seed=True)
            candidate = upsert_style(source, {**read_style(source), 'plot_modes': {'axes_0': ['histogram_count', 'density_count']}})
            fast = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'fast',
                               interactive_seed=baseline['interactive_seed_bytes'])
            full = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'full')
            self.assertEqual(fast['image_bytes'], full['image_bytes'])
            self.assertEqual(fast['plot_mode_axes'][0]['selected'], ['histogram_count', 'density_count'])

    def test_unnamed_xy_series_can_be_switched_without_inventing_points(self):
        figure, axis = plt.subplots()
        axis.plot([0,1,2], [2,4,3])
        self.assertIn('line', capabilities(figure)[0]['supported'])
        apply_modes(figure, {'axes_0': ['line','scatter']})
        np.testing.assert_array_equal(axis.collections[0].get_offsets(), [[0,2],[1,4],[2,3]])

    def test_worker_seed_preview_and_saved_source_keep_selected_modes(self):
        from tests.test_fast_interactive_preview import fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, source = fixture(root)
            baseline = _one_render(project, 'charts/fig1.py', {}, root/'baseline', capture_interactive_seed=True)
            self.assertIn('boxplot', baseline['plot_mode_axes'][0]['supported'])
            style = {**read_style(source), 'plot_modes': {'axes_0': ['boxplot', 'scatter']}}
            candidate = upsert_style(source, style)
            self.assertEqual(read_style(candidate)['plot_modes'], style['plot_modes'])
            before = (project/'charts/fig1.py').read_bytes()
            fast = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'fast',
                               interactive_seed=baseline['interactive_seed_bytes'])
            full = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'full')
            self.assertEqual(fast['image_bytes'], full['image_bytes'])
            self.assertEqual(fast['plot_mode_axes'][0]['selected'], ['boxplot', 'scatter'])
            self.assertEqual((project/'charts/fig1.py').read_bytes(), before)
            from source_data_policy import compare_source_inputs
            self.assertNotEqual(compare_source_inputs({'chart.py': source}, {'chart.py': candidate})['status'], 'fail')
