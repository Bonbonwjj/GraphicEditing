"""Deterministic checks of normalization helpers, never modifies project data.

Run: MPLCONFIGDIR=/tmp/plot-forge-mpl python3 docs/acceptance/verify_style.py
Images/reports are synthetic candidate artifacts, not deployed-model outputs.
"""
from pathlib import Path
import copy
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator
import numpy as np
from PIL import Image
import studio_style as style

ARTIFACTS = Path(__file__).resolve().parent / 'verified-style'
ARTIFACTS.mkdir(exist_ok=True)


def line_figure():
    fig, ax = plt.subplots(figsize=(7.2, 4.8), dpi=120)
    ax.plot([0, 1, 2, 3], [1, 1.3, 1.1, 1.7], 'o-', label='A')
    ax.set(xlabel='Time (s)', ylabel='Response', ylim=(0.9, 1.9), xlim=(-.1, 3.1))
    return fig, ax


class NormalizationTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_x_axis_translation_is_12pt_and_y_data_stationary(self):
        original = style._normalization_profile()
        baseline = copy.deepcopy(original)
        baseline['global']['x_axis_down_offset_pt'] = 0
        fig0, ax0 = line_figure()
        with patch.object(style, '_normalization_profile', return_value=baseline):
            style.normalize_figure_geometry(fig0, 'line')
        fig1, ax1 = line_figure()
        style.normalize_figure_geometry(fig1, 'line')
        px = fig1.dpi / 72
        def center_y(artist, fig):
            box = artist.get_window_extent(fig.canvas.get_renderer())
            return (box.y0 + box.y1) / 2
        for get in (lambda ax: ax.spines['bottom'], lambda ax: ax.get_xticklabels()[0], lambda ax: ax.xaxis.label):
            self.assertAlmostEqual(center_y(get(ax0), fig0) - center_y(get(ax1), fig1), 12 * px, places=5)
        np.testing.assert_allclose(ax0.transData.transform([[0, 1], [3, 1.7]]), ax1.transData.transform([[0, 1], [3, 1.7]]))
        np.testing.assert_allclose(ax0.spines['left'].get_window_extent().bounds, ax1.spines['left'].get_window_extent().bounds)

    def test_visible_spines_stop_at_ticks_without_changing_limits(self):
        fig, ax = line_figure()
        limits = (ax.get_xlim(), ax.get_ylim())
        style.normalize_figure_geometry(fig, 'line')
        for axis, side in ((ax.xaxis, 'bottom'), (ax.yaxis, 'left')):
            lo, hi = sorted(axis.get_view_interval())
            ticks = [tick for tick in axis.get_majorticklocs() if lo <= tick <= hi]
            self.assertEqual(ax.spines[side].get_bounds(), (ticks[0], ticks[-1]))
        self.assertLessEqual(len([t for t in ax.get_yticks() if .9 <= t <= 1.9]), 5)
        self.assertEqual(limits, (ax.get_xlim(), ax.get_ylim()))

    def test_bar_baseline_remains_full(self):
        fig, ax = plt.subplots()
        ax.bar([.82, 1.18], [2, 3])
        ax.set_xticks([.82, 1.18], ['A', 'B'])
        ax.spines['bottom'].set_bounds(.82, 1.18)
        style.normalize_figure_geometry(fig, 'two_group_bar')
        self.assertEqual(ax.spines['bottom'].get_bounds(), tuple(sorted(ax.get_xlim())))

    def test_category_y_labels_preserved(self):
        fig, ax = plt.subplots()
        ax.scatter([1, 2, 3], [0, 1, 2])
        ax.set_yticks([0, 1, 2], ['Group A', 'Group B', 'Group C'])
        style.normalize_figure_geometry(fig, 'scatter')
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ['Group A', 'Group B', 'Group C'])

    def test_multiple_axes_not_collapsed_or_repositioned(self):
        fig, axes = plt.subplots(1, 2)
        positions = [ax.get_position().bounds for ax in axes]
        size = fig.get_size_inches().copy()
        result = style.normalize_figure_geometry(fig, 'line')
        self.assertIsNone(result['matched_template'])
        self.assertTrue(result['warnings'])
        np.testing.assert_allclose([ax.get_position().bounds for ax in axes], positions)
        np.testing.assert_allclose(fig.get_size_inches(), size)

    def test_twin_axes_not_collapsed(self):
        fig, ax = line_figure()
        twin = ax.twinx()
        positions = [a.get_position().bounds for a in fig.axes]
        result = style.normalize_figure_geometry(fig, 'line')
        self.assertIsNone(result['matched_template'])
        np.testing.assert_allclose([a.get_position().bounds for a in fig.axes], positions)
        self.assertTrue(twin.spines['right'].get_visible())

    def test_polar_geometry_preserved(self):
        fig, ax = plt.subplots(subplot_kw={'projection': 'polar'})
        ax.plot([0, 1, 2], [1, 3, 2])
        position = ax.get_position().bounds
        style.normalize_figure_geometry(fig, 'line')
        self.assertEqual(ax.name, 'polar')
        np.testing.assert_allclose(position, ax.get_position().bounds)

    def test_heatmap_frame_colorbar_colormap(self):
        fig, ax = plt.subplots()
        data = np.arange(28).reshape(4, 7)
        image = ax.imshow(data, cmap='viridis', vmin=0, vmax=30)
        bar = fig.colorbar(image, ax=ax)
        ax.set_xticks(range(7), [f'C{i}' for i in range(7)])
        ax.set_yticks(range(4), [f'R{i}' for i in range(4)])
        ax.set(xlabel='Column', ylabel='Row')
        ax.spines['left'].set_position(('outward', 12))
        ax.spines['left'].set_bounds(0, 3)
        style.normalize_figure_geometry(fig, 'heatmap')
        for side in ('left', 'bottom', 'right', 'top'):
            self.assertTrue(ax.spines[side].get_visible())
            self.assertEqual(ax.spines[side].get_position(), ('outward', 0))
        self.assertEqual(ax.spines['left'].get_bounds(), tuple(sorted(ax.get_ylim())))
        self.assertEqual(ax.spines['bottom'].get_bounds(), tuple(sorted(ax.get_xlim())))
        np.testing.assert_allclose([ax.get_position().y0, ax.get_position().y1], [bar.ax.get_position().y0, bar.ax.get_position().y1])
        self.assertEqual(image.get_cmap().name, 'viridis')
        self.assertEqual(image.get_clim(), (0, 30))
        np.testing.assert_equal(image.get_array(), data)
        style.finish_normalized_figure(fig, ARTIFACTS / 'heatmap_7x4.png', 'heatmap')
        self.assertEqual(Image.open(ARTIFACTS / 'heatmap_7x4.png').size, (2520, 2340))

    def test_fixed_canvas_even_with_rc_tight_bbox(self):
        for name, expected in [('line', (2160, 1440)), ('two_group_box', (1620, 1440))]:
            if name == 'two_group_box':
                fig, ax = plt.subplots()
                ax.bxp([{'label': 'A', 'med': 2, 'q1': 1.5, 'q3': 2.5, 'whislo': 1, 'whishi': 3, 'fliers': []},
                        {'label': 'B', 'med': 3, 'q1': 2.5, 'q3': 3.5, 'whislo': 2, 'whishi': 4, 'fliers': []}],
                       positions=[.82, 1.18], widths=.1333333333,
                       boxprops={'linewidth': 3.2}, whiskerprops={'linewidth': 3.2}, capprops={'linewidth': 3.2}, medianprops={'linewidth': 3.1})
                ax.set_ylabel('Response')
            else:
                fig, ax = line_figure()
                ax.lines[0].set_linewidth(3.2)
                ax.lines[0].set_markersize(20)
            ax.set_title('Original title', loc='left')
            with matplotlib.rc_context({'savefig.bbox': 'tight'}):
                report = style.finish_normalized_figure(fig, ARTIFACTS / f'{name}.png', name)
            self.assertEqual(Image.open(ARTIFACTS / f'{name}.png').size, expected)
            self.assertIn('Original title', report['removed_titles'])

    def test_missing_heavy_font_uses_profile_fallback_with_report(self):
        fig, ax = line_figure()
        result = style.normalize_figure_geometry(fig, 'line')
        for substitution in result['font_substitutions']:
            if 'CJK' not in substitution['reason']:
                self.assertEqual(substitution['selected_family'], style._normalization_profile()['global']['font_fallback'])
        self.assertEqual(ax.xaxis.label.get_fontweight(), 'black')

    def test_explicit_sem(self):
        result = style.plotting_error_values([{'sem': '0.2'}, {'sem': '.3'}], {'kind': 'SEM', 'column': 'sem'})
        self.assertEqual(result['values'], [.2, .3])
        self.assertEqual(result['columns'], ['sem'])

    def test_aggregate_sd_n_to_explicit_sem(self):
        result = style.plotting_error_values([{'sd': '.6', 'n': '9'}, {'sd': '.8', 'n': '16'}],
                                             {'kind': 'SEM', 'sd_column': 'sd', 'n_column': 'n', 'sample_sd': True})
        np.testing.assert_allclose(result['values'], [.2, .2])
        self.assertIn('supplied', result['formula'])

    def test_no_default_sem_or_raw_replicates(self):
        rows = [{'value': '1'}, {'value': '2'}, {'value': '3'}]
        for spec in ({}, {'kind': 'SEM'}, {'kind': 'SEM', 'sd_column': 'sd', 'n_column': 'n'}):
            self.assertEqual(style.plotting_error_values(rows, spec)['status'], 'unavailable')

    def test_invalid_summaries_report_instead_of_fabrication(self):
        for n in ('1', '2.5', 'NaN', '0'):
            result = style.plotting_error_values([{'sd': '.6', 'n': n}], {'kind': 'SEM', 'sd_column': 'sd', 'n_column': 'n', 'sample_sd': True})
            self.assertEqual(result['status'], 'unavailable')
            self.assertIsNone(result['values'])
        self.assertEqual(style.plotting_error_values([{'sem': '-.2'}], {'kind': 'SEM', 'column': 'sem'})['status'], 'unavailable')

    def test_existing_ci_bounds_preserved(self):
        rows = [{'mean': '2', 'lower': '1.7', 'upper': '2.5'}]
        result = style.plotting_error_values(rows, {'kind': 'CI', 'mean_column': 'mean', 'lower_column': 'lower', 'upper_column': 'upper', 'definition': 'stored 95% CI'})
        np.testing.assert_allclose(result['values'], [[.3], [.5]])

    def test_no_missing_fit_added(self):
        fig, ax = plt.subplots()
        ax.scatter([1, 2], [3, 4])
        style.normalize_figure_geometry(fig, 'scatter')
        self.assertEqual(len(ax.lines), 0)

    def test_violin_prepared_quartiles_half_ratio(self):
        fig, ax = plt.subplots()
        pos = [.82, 1.18]
        values = [np.array([1, 1.2, 1.4, 1.5, 1.8, 2, 2.2]), np.array([1.5, 1.6, 1.8, 2, 2.1, 2.3, 2.6])]
        bodies = ax.violinplot(values, positions=pos, widths=.1333333333)['bodies']
        # These stored quartiles represent the supplied plot summaries.
        quartiles = [[1.3, 1.5, 1.9], [1.7, 2, 2.2]]
        before = [body.get_paths()[0].vertices.copy() for body in bodies]
        marks = style.add_normalized_violin_quartiles(ax, bodies, pos, quartiles)
        for group in range(2):
            lines = [marks[group * 4 + i].get_segments()[0] for i in range(4)]
            lengths = [segment[1, 0] - segment[0, 0] for segment in lines[:3]]
            np.testing.assert_allclose([lengths[0] / lengths[1], lengths[2] / lengths[1]], [.5, .5])
            np.testing.assert_allclose(lines[3], [[pos[group], quartiles[group][0]], [pos[group], quartiles[group][2]]])
            np.testing.assert_allclose(bodies[group].get_paths()[0].vertices, before[group])
        ax.set_xticks(pos, ['A', 'B'])
        ax.set_ylabel('Response')
        style.finish_normalized_figure(fig, ARTIFACTS / 'violin_quartiles.png', 'two_group_violin')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NormalizationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (ARTIFACTS / 'results.json').write_text(json.dumps({
        'profile_version': style._normalization_profile()['version'], 'tests_run': result.testsRun,
        'failures': [name.id() + ': ' + detail for name, detail in result.failures],
        'errors': [name.id() + ': ' + detail for name, detail in result.errors],
        'scope': 'deterministic runtime helper checks; no deployed model call and no general all-rule verdict'
    }, ensure_ascii=False, indent=2) + '\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
