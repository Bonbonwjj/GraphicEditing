import unittest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from interactive_style import apply_interactive_style, prepare_conversion_source, read_style


class ConversionRangeTests(unittest.TestCase):
    def test_scatter_bounds_replace_inherited_ranges_only_on_selected_panel(self):
        fig, (axis, other) = plt.subplots(1, 2)
        self.addCleanup(plt.close, fig)
        axis.set_label('A'); other.set_label('B')
        axis.scatter([1, 2], [20, 40])
        axis.set(xlim=(0, 1), ylim=(0, 5))
        other.plot([0, 1], [0, 1]); other.set_ylim(0, 5)
        fig.canvas.draw()
        frames = [a.get_position().bounds for a in fig.axes]
        apply_interactive_style(fig, {'auto_range': {'axis_labels': ['A'],
            'inherited_limits': {'axes_0': {'ylim': [0, 5]}}},
            'component_styles': {'axes_0': {'ylim': [0, 5]}, 'axes_1': {'ylim': [0, 5]}}})
        fig.canvas.draw()
        self.assertLess(axis.get_ylim()[0], 20)
        self.assertGreater(axis.get_ylim()[1], 40)
        self.assertEqual(other.get_ylim(), (0, 5))
        self.assertEqual(frames, [a.get_position().bounds for a in fig.axes])

    def test_later_manual_range_overrides_auto_range(self):
        fig, axis = plt.subplots(); self.addCleanup(plt.close, fig)
        axis.errorbar([1, 2], [20, 40], yerr=10)
        policy = {'axis_labels': None, 'inherited_limits': {'axes_0': {'ylim': [0, 5]}}}
        apply_interactive_style(fig, {'auto_range': policy})
        self.assertGreater(axis.get_ylim()[1], 50)
        apply_interactive_style(fig, {'auto_range': policy,
            'component_styles': {'axes_0': {'ylim': [0, 100]}}})
        self.assertEqual(axis.get_ylim(), (0, 100))

    def test_conversion_policy_is_saved_in_source(self):
        from interactive_style import upsert_style
        source = 'import matplotlib.pyplot as plt\nfig, ax=plt.subplots()\nfig.savefig("test.png")\n'
        baseline = upsert_style(source, {'component_styles': {'axes_0': {'ylim': [0, 5]}}})
        converted = prepare_conversion_source(baseline, baseline, ['A'])
        style = read_style(converted)
        self.assertEqual(style['auto_range']['axis_labels'], ['A'])
        self.assertEqual(style['auto_range']['inherited_limits']['axes_0']['ylim'], [0, 5])

    def test_saved_candidate_worker_reports_new_range(self):
        import tempfile
        from pathlib import Path
        from chat_runner import _one_render
        from interactive_style import upsert_style
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root/'project'
            (project/'charts').mkdir(parents=True)
            source = ('import os\nimport matplotlib.pyplot as plt\n'
                      'fig, ax=plt.subplots()\nax.scatter([1,2], [20,40])\n'
                      'ax.set_ylim(0,5)\nfig.savefig(os.environ["CHART_OUTPUT"])\n')
            baseline = upsert_style(source, {'component_styles': {'axes_0': {'ylim': [0,5]}}})
            candidate = prepare_conversion_source(baseline, baseline)
            (project/'charts/plot.py').write_text(baseline, encoding='utf-8')
            result = _one_render(project, 'charts/plot.py', {'charts/plot.py': candidate}, root/'render')
            self.assertLess(result['axes'][0]['ylim'][0],20)
            self.assertGreater(result['axes'][0]['ylim'][1],40)

    def test_point_conversion_allows_ranges_but_rejects_scale_changes(self):
        from tests.test_scatter_transform import ScatterTransformTests
        from chart_transform import verify_scatter
        fixture = ScatterTransformTests()
        try:
            report = fixture.report()
            report['data_report']['axes_changes'] = [{'axis': 0,
                'before': {'xlim': [0, 1], 'ylim': [0, 5], 'xscale': 'linear', 'yscale': 'linear'},
                'after': {'xlim': [0, 6], 'ylim': [0, 50], 'xscale': 'linear', 'yscale': 'linear'}}]
            context = {'user_message': 'Convert this chart to a scatter plot.'}
            self.assertEqual(verify_scatter(context, report)['status'], 'pass')
            report['data_report']['axes_changes'][0]['after']['yscale'] = 'log'
            self.assertEqual(verify_scatter(context, report)['status'], 'fail')
        finally:
            fixture.doCleanups()

    def test_auto_range_metadata_is_not_a_scientific_input(self):
        from source_data_policy import compare_source_inputs
        before = "INTERACTIVE_STYLE = {'component_styles': {'axes_0': {'ylim': [0, 5]}}}\nvalues = [1, 2, 3]\n"
        after = before.replace("{'component_styles':", "{'auto_range': {'axis_labels': ['h'], 'inherited_limits': {}}, 'component_styles':")
        self.assertNotEqual(compare_source_inputs({'plot.py': before}, {'plot.py': after})['status'], 'fail')
        changed = after.replace('[1, 2, 3]', '[1, 2, 99]')
        self.assertEqual(compare_source_inputs({'plot.py': before}, {'plot.py': changed})['status'], 'fail')

    def test_conversion_keeps_category_labels(self):
        fig, axis = plt.subplots(); self.addCleanup(plt.close, fig)
        axis.violinplot([[1,2,3],[2,4,6]], positions=[.2,.8])
        axis.set_xticks([.2,.8], ['Obs','NObs'])
        apply_interactive_style(fig, {'auto_range': {'axis_labels': None, 'inherited_limits': {}}})
        fig.canvas.draw()
        self.assertEqual([t.get_text() for t in axis.get_xticklabels()], ['Obs','NObs'])
