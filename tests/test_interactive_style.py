import ast
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from interactive_style import apply_interactive_style, read_style, upsert_style
from universal_project import adapter_source


class InteractiveStyleTests(unittest.TestCase):
    def test_style_changes_spines_legend_location_and_names(self):
        figure, axis = plt.subplots()
        axis.plot([1,2],[3,4],label='Control')
        axis.legend()
        apply_interactive_style(figure, {'border_width':2.5,'border_color':'#112233',
            'legend_location':'lower left','legend_names':{'Control':'对照组'},
            'line_width':3,'line_color':'#445566','marker_size':7,'font_size':13,
            'grid':True,'legend_visible':True,'title':'结果','xlabel':'时间','ylabel':'分数'})
        self.assertEqual(axis.spines['left'].get_linewidth(),2.5)
        self.assertEqual(axis.get_legend().get_texts()[0].get_text(),'对照组')
        self.assertEqual(axis.get_legend()._loc,3)
        self.assertEqual(axis.lines[0].get_linewidth(),3)
        self.assertEqual(axis.lines[0].get_color(),'#445566')
        self.assertEqual(axis.get_title(),'结果')
        self.assertEqual(axis.get_xlabel(),'时间')
        self.assertTrue(any(line.get_visible() for line in axis.get_xgridlines()))
        plt.close(figure)

    def test_upsert_adapter_preserves_source_and_updates_only_config(self):
        source=adapter_source('figure_1','ax.plot(x, y)','plots.py:42',('data/a.csv',))
        changed=upsert_style(source,{'border_width':3,'border_color':'#abcdef',
            'legend_location':'upper left','legend_names':{'A':'Alpha'}})
        ast.parse(changed)
        self.assertIn("FIGURE_DRAWING_CODE = 'ax.plot(x, y)'",changed)
        self.assertEqual(read_style(changed)['legend_names'],{'A':'Alpha'})
        self.assertEqual(changed.count('PLOT_FORGE_INTERACTIVE_STYLE_START'),1)

    def test_upsert_plain_chart_calls_style_before_output(self):
        source='import os\nimport matplotlib.pyplot as plt\nfig,ax=plt.subplots()\nax.plot([1],[2])\nfig.savefig(os.environ["CHART_OUTPUT"])\n'
        changed=upsert_style(source,{})
        ast.parse(changed)
        self.assertLess(changed.index('apply_interactive_style(plt.gcf()'),changed.index('fig.savefig'))

    def test_upsert_migrates_old_hook_before_finish_figure(self):
        source=('import matplotlib.pyplot as plt\nfig,ax=plt.subplots()\n'
                'finish_figure(fig, "out.png")\n'
                'apply_interactive_style(plt.gcf(), INTERACTIVE_STYLE)\nfig.show()\n'+
                '# --- PLOT_FORGE_INTERACTIVE_STYLE_START ---\n'
                "INTERACTIVE_STYLE = {'border_width': 1}\n"
                '# --- PLOT_FORGE_INTERACTIVE_STYLE_END ---\n')
        changed=upsert_style(source, {})
        ast.parse(changed)
        self.assertEqual(changed.count('apply_interactive_style(plt.gcf(), INTERACTIVE_STYLE)'), 1)
        self.assertLess(changed.index('apply_interactive_style(plt.gcf()'), changed.index('finish_figure'))

    def test_selected_line_and_dragged_legend_are_applied_independently(self):
        figure, axis = plt.subplots()
        first, = axis.plot([0, 1], [0, 1], color='#111111', linewidth=1, label='A')
        second, = axis.plot([0, 1], [1, 0], color='#222222', linewidth=2, label='B')
        axis.legend()
        apply_interactive_style(figure, {
            'series_styles': {'axes_0.line_1': {'color': '#ff0000', 'linewidth': 4}},
            'legend_anchor': [0.3, 0.7],
        })
        self.assertEqual(first.get_color(), '#111111')
        self.assertEqual(second.get_color(), '#ff0000')
        self.assertEqual(second.get_linewidth(), 4)
        self.assertEqual(tuple(axis.get_legend().get_bbox_to_anchor()._bbox.bounds[:2]), (0.3, 0.7))
        plt.close(figure)

    def test_subplot_style_only_changes_selected_axes(self):
        figure, (left, right) = plt.subplots(1, 2)
        left.plot([0, 1], [0, 1])
        right.plot([0, 1], [1, 0])
        apply_interactive_style(figure, {'axes_styles': {'axes_1': {
            'border_width': 4, 'border_color': '#aa0000', 'grid': True,
            'title': '右侧子图', 'font_size': 15,
        }}})
        self.assertNotEqual(left.spines['left'].get_linewidth(), 4)
        self.assertEqual(right.spines['left'].get_linewidth(), 4)
        self.assertEqual(right.spines['left'].get_edgecolor(), (2/3, 0, 0, 1))
        self.assertEqual(right.get_title(), '右侧子图')
        self.assertTrue(any(line.get_visible() for line in right.get_xgridlines()))
        self.assertFalse(any(line.get_visible() for line in left.get_xgridlines()))
        plt.close(figure)


if __name__=='__main__':
    unittest.main()
