import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
import numpy as np

import tests.test_plot_modes as mode_tests
from plot_modes import apply_modes, capabilities, validate_palettes
from interactive_style import apply_interactive_style, read_style, upsert_style
from chat_runner import _one_render


class PaletteTests(unittest.TestCase):
    setUp = mode_tests.PlotModeTests.setUp
    example = mode_tests.PlotModeTests.example
    colors = ['#24d668', '#2c88dd']

    def paint(self, axis):
        for patch, color in zip(axis.patches, self.colors):
            patch.set_facecolor(color)

    def palette(self, figure):
        return next(axis['palette'] for axis in capabilities(figure) if axis['key'] == 'axes_0')

    def assert_palette(self, figure, colors=None):
        self.assertEqual([row['color'] for row in self.palette(figure)], colors or self.colors)

    def test_colors_survive_violin_density_and_repeated_switches(self):
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                figure, axis, _, _ = self.example(horizontal)
                self.paint(axis)
                for modes in (['violinplot', 'scatter'], ['histogram', 'density'], ['mean_bar'],
                              ['boxplot', 'scatter'], ['mean_line'], ['violinplot']):
                    apply_modes(figure, {'axes_0': modes})
                    figure.canvas.draw()
                    self.assert_palette(figure)

    def test_palette_captured_after_manual_color_edit_survives_fresh_source(self):
        original, axis, _, _ = self.example()
        apply_interactive_style(original, {'component_styles': {
            f'axes_0.box_{i}': {'fill_color': color} for i, color in enumerate(self.colors)}})
        palette = self.palette(original)
        target, new_axis, _, _ = self.example()
        apply_interactive_style(target, {'plot_modes': {'axes_0': ['violinplot', 'scatter']},
                                        'plot_mode_palettes': {'axes_0': palette}})
        self.assert_palette(target)
        for artist in new_axis.collections:
            if getattr(artist, '_plot_mode_group_position', None) is not None:
                position = artist._plot_mode_group_position
                self.assertEqual(to_hex(artist.get_facecolor()[0]), self.colors[int(position)])
        body = new_axis.collections[0]
        self.assertLess(body.get_facecolor()[0][3], 1)

    def test_palette_entries_match_group_identity_not_list_order(self):
        figure, axis, _, _ = self.example()
        self.paint(axis)
        palette = list(reversed(self.palette(figure)))
        target, _, _, _ = self.example()
        apply_modes(target, {'axes_0': ['scatter']}, {'axes_0': palette})
        self.assert_palette(target)

    def test_recolored_violin_is_the_palette_for_the_next_conversion(self):
        figure, axis, _, _ = self.example()
        self.paint(axis)
        apply_modes(figure, {'axes_0': ['violinplot']})
        apply_interactive_style(figure, {'component_styles': {'axes_0.violin_0': {'fill_color': '#b244a9'}}})
        palette = self.palette(figure)
        target, _, _, _ = self.example()
        apply_modes(target, {'axes_0': ['boxplot', 'scatter']}, {'axes_0': palette})
        self.assert_palette(target, ['#b244a9', self.colors[1]])

    def test_dragged_group_retains_original_color_identity(self):
        from component_editor import apply_components
        figure, axis, _, _ = self.example()
        self.paint(axis)
        apply_components(figure, {'axes_0.box_0': {'dx': 35, 'dy': 10}})
        palette = self.palette(figure)
        self.assertEqual([entry['color'] for entry in palette], self.colors)
        target, _, _, _ = self.example()
        apply_modes(target, {'axes_0': ['violinplot']}, {'axes_0': palette})
        self.assert_palette(target)

    def test_statistical_line_colors_opacity_and_values_survive_conversions(self):
        figure, axis, _, values = self.example()
        self.paint(axis)
        statistics = {name: [] for name in ('medians', 'whiskers', 'caps')}
        for line in axis.lines:
            role = getattr(line, '_plot_mode_stat_role', '')
            if role in statistics:
                line.set_color('#111111' if role == 'medians' else '#454545')
                line.set_alpha(.75 if role == 'medians' else .9)
                statistics[role].append(line)
        palette = self.palette(figure)
        for entry in palette:
            self.assertEqual(entry['median_color'], '#111111')
            self.assertEqual(entry['median_alpha'], .75)
        for modes in (['boxplot','scatter'], ['violinplot','scatter'], ['boxplot']):
            target, other, _, _ = self.example()
            apply_modes(target, {'axes_0': modes}, {'axes_0': palette})
            current = self.palette(target)
            for entry in current:
                self.assertEqual(entry['median_color'], '#111111')
                self.assertAlmostEqual(entry['median_alpha'], .75)
                self.assertEqual(entry['edge_color'], palette[0]['edge_color'])
            if 'boxplot' in modes:
                medians = [line for line in other.lines if getattr(line, '_plot_mode_stat_role', '') == 'medians']
                self.assertEqual(len(medians), len(values))
                for line, observations in zip(medians, values):
                    np.testing.assert_allclose(line.get_ydata(), [np.median(observations)]*2)
                    self.assertEqual(to_hex(line.get_color()), '#111111')

    def test_group_fill_color_does_not_recolor_median_or_change_opacity(self):
        figure, axis, _, _ = self.example()
        for line in axis.lines:
            if getattr(line, '_plot_mode_stat_role', '') == 'medians': line.set_color('#000000')
        apply_modes(figure, {'axes_0':['boxplot','scatter']})
        opacity = axis.patches[0].get_facecolor()[3]
        apply_interactive_style(figure, {'component_styles': {'axes_0.box_0': {'color':'#aabbcc'}}})
        self.assertEqual(to_hex(axis.patches[0].get_facecolor()), '#aabbcc')
        self.assertAlmostEqual(axis.patches[0].get_facecolor()[3], opacity)
        for line in axis.lines:
            if getattr(line, '_plot_mode_stat_role', '') == 'medians':
                self.assertEqual(to_hex(line.get_color()), '#000000')

    def test_named_xy_series_keep_custom_palette(self):
        figure, axis = plt.subplots()
        for index, color in enumerate(self.colors):
            axis.plot([0, 1, 2], [index, index+2, index+1], color=color, label=f'Group {index}')
        palette = self.palette(figure)
        target, other = plt.subplots()
        for index in range(2):
            other.plot([0, 1, 2], [index, index+2, index+1], label=f'Group {index}')
        apply_modes(target, {'axes_0': ['line', 'scatter']}, {'axes_0': palette})
        self.assertEqual([to_hex(line.get_color()) for line in other.lines], self.colors)
        self.assertEqual([to_hex(points.get_facecolor()[0]) for points in other.collections], self.colors)

    def test_palette_metadata_does_not_waive_scientific_data_changes(self):
        from source_data_policy import compare_source_inputs
        before = 'INTERACTIVE_STYLE = {}\nvalues = [1, 2, 3]\n'
        palette = {'axes_0': [{'position': 0, 'label': 'A', 'color': '#24d668'}]}
        after = before.replace('INTERACTIVE_STYLE = {}', f'INTERACTIVE_STYLE = '+repr({'plot_mode_palettes': palette}))
        self.assertNotEqual(compare_source_inputs({'a.py': before}, {'a.py': after})['status'], 'fail')
        self.assertEqual(compare_source_inputs({'a.py': before}, {'a.py': after.replace('[1, 2, 3]', '[1, 2, 99]')})['status'], 'fail')
        for invalid in ({'axes_0': [{'position': 0, 'color': 'red'}]},
                        {'axes_0': [{'position': float('nan'), 'color': '#ffffff'}]},
                        {'axes_0': [{'position': 0, 'series_index': 0, 'color': '#ffffff'}]}):
            with self.assertRaises(ValueError): validate_palettes(invalid)

    def test_lightweight_color_preview_reports_fresh_palette(self):
        from tests.test_fast_interactive_preview import fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project, source = fixture(root)
            baseline = _one_render(project, 'charts/fig1.py', {}, root/'baseline', capture_interactive_seed=True)
            candidate = upsert_style(source, {**read_style(source),
                'component_styles': {'axes_0.box_0': {'fill_color': '#b244a9'}}})
            report = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'fast',
                                 interactive_seed=baseline['interactive_seed_bytes'], lightweight_preview=True)
            self.assertEqual(report['plot_mode_axes'][0]['palette'][0]['color'], '#b244a9')
