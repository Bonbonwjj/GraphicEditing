import unittest

import matplotlib.pyplot as plt

from interactive_style import apply_interactive_style
from server import interactive_style_note
from component_editor import apply_components


class InteractiveStyleSynchronizationTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_subplot_axis_names_change_only_the_selected_subplot(self):
        figure, (left, right) = plt.subplots(1, 2)
        left.set(xlabel='Left X', ylabel='Left Y')
        right.set(xlabel='Right X', ylabel='Right Y')

        apply_interactive_style(figure, {'axes_styles': {
            'axes_1': {'xlabel': 'Elapsed time\n(seconds)', 'ylabel': 'Response rate'}
        }})

        self.assertEqual(left.get_xlabel(), 'Left X')
        self.assertEqual(left.get_ylabel(), 'Left Y')
        self.assertEqual(right.get_xlabel(), 'Elapsed time\n(seconds)')
        self.assertEqual(right.get_ylabel(), 'Response rate')

    def test_line_style_updates_existing_legend_proxy(self):
        figure, axis = plt.subplots()
        line, = axis.plot([0, 1], [1, 2], label='Measured', color='#112233',
                          linewidth=1, marker='o', markersize=4)
        legend = axis.legend()

        apply_interactive_style(figure, {'series_styles': {
            'axes_0.line_0': {'color': '#ff0000', 'linewidth': 4, 'markersize': 9}
        }})

        proxy = list(legend.legend_handles if hasattr(legend, 'legend_handles')
                     else legend.legendHandles)[0]
        self.assertEqual(line.get_color(), '#ff0000')
        self.assertEqual(proxy.get_color(), '#ff0000')
        self.assertEqual(proxy.get_linewidth(), 4)
        self.assertEqual(proxy.get_markersize(), 9)

    def test_duplicate_labels_keep_legend_entry_order(self):
        figure, axis = plt.subplots()
        axis.plot([0, 1], [1, 2], label='Repeated', color='blue')
        axis.plot([0, 1], [2, 1], label='Repeated', color='green')
        legend = axis.legend()
        apply_interactive_style(figure, {'series_styles': {
            'axes_0.line_1': {'color': '#ff0000', 'linewidth': 5}}})
        proxies=list(legend.legend_handles if hasattr(legend,'legend_handles') else legend.legendHandles)
        self.assertEqual([item.get_color() for item in proxies], ['blue', '#ff0000'])
        self.assertEqual([item.get_linewidth() for item in proxies], [1.5, 5])

    def test_component_style_color_and_width_update_legend_proxy(self):
        figure,axis=plt.subplots()
        line,=axis.plot([0,1],[1,2],label='Measured',color='#112233',linewidth=1)
        legend=axis.legend()
        apply_interactive_style(figure,{'component_styles':{
            'axes_0.line_0':{'color':'#00aa55','linewidth':4}}})
        proxy=list(legend.legend_handles if hasattr(legend,'legend_handles') else legend.legendHandles)[0]
        self.assertEqual(line.get_color(),'#00aa55')
        self.assertEqual(proxy.get_color(),'#00aa55')
        self.assertEqual(proxy.get_linewidth(),4)

    def test_linked_curve_band_color_updates_line_legend_only_once(self):
        from component_groups import install_group_tracking,component_groups
        install_group_tracking();figure,axis=plt.subplots();x=[0,1,2];mean=[2,3,2.5]
        axis.fill_between(x,[1.8,2.7,2.4],[2.2,3.3,2.6],color='#336699',alpha=.2)
        line,=axis.plot(x,mean,color='#336699',label='Mean');legend=axis.legend()
        key=next(key for key in component_groups(figure) if '.group_' in key)
        apply_interactive_style(figure,{'component_styles':{key:{'color':'#ff0000'}}})
        proxy=list(legend.legend_handles if hasattr(legend,'legend_handles') else legend.legendHandles)[0]
        self.assertEqual(line.get_color(),'#ff0000')
        self.assertEqual(proxy.get_color(),'#ff0000')
        self.assertEqual(len(legend.get_texts()),1)

    def test_figure_legend_supports_names_styles_and_visibility(self):
        figure, (left, right) = plt.subplots(1, 2)
        first, = left.plot([0, 1], [1, 2], label='First', color='blue')
        second, = right.plot([0, 1], [2, 1], label='Second', color='green')
        legend = figure.legend([first, second], ['Control', 'Treatment'])
        apply_interactive_style(figure, {
            'series_styles': {'axes_1.line_0': {'color': '#ff0000', 'linewidth': 4}},
            'legend_names': {'Control': '对照组', 'Treatment': '处理组'}})
        proxies=list(legend.legend_handles if hasattr(legend,'legend_handles') else legend.legendHandles)
        self.assertEqual([text.get_text() for text in legend.get_texts()], ['对照组', '处理组'])
        self.assertEqual([item.get_color() for item in proxies], ['blue', '#ff0000'])
        apply_interactive_style(figure, {'legend_visible': False})
        self.assertEqual(figure.legends, [])

    def test_figure_legend_best_preserves_its_explicit_original_location(self):
        figure,axis=plt.subplots();line,=axis.plot([0,1],[1,2],label='Series')
        legend=figure.legend([line],['Series'],loc='upper left')
        original=legend._loc
        apply_interactive_style(figure,{'legend_location':'best'})
        self.assertEqual(legend._loc,original)

    def test_history_note_describes_actual_style_delta(self):
        before={'axes_styles':{'axes_1':{'xlabel':'Old'}},'series_styles':{}}
        after={'axes_styles':{'axes_1':{'xlabel':'New'}},
               'series_styles':{'axes_1.line_0':{'color':'#ff0000'}}}
        self.assertEqual(interactive_style_note(before,after),'交互样式：坐标轴名称/标题、数据系列')

    def test_missing_font_is_rejected_instead_of_silent_fallback(self):
        figure,axis=plt.subplots();axis.set_xlabel('Result')
        with self.assertRaisesRegex(ValueError,'字体不可用'):
            apply_components(figure,{'axes_0.xlabel':{'font_family':'Definitely Missing Research Font'}})
        apply_components(figure,{'axes_0.xlabel':{'font_family':'DejaVu Sans'}})
        self.assertEqual(axis.xaxis.label.get_fontfamily(),['DejaVu Sans'])


if __name__ == '__main__':
    unittest.main()
