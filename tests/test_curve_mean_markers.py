import unittest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
import numpy as np

from component_groups import install_group_tracking, component_groups
from interactive_style import apply_interactive_style
from point_components import targets


class CurveMeanMarkerTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking()
        self.fig,self.ax=plt.subplots()
        self.addCleanup(plt.close,self.fig)
        self.x=np.linspace(0,1,10)
        self.lines=[];self.bands=[]
        for i,(color,marker) in enumerate((('#2465b9','o'),('#d37520','s'))):
            mean=90-self.x*12-i*4
            self.bands.append(self.ax.fill_between(self.x,mean-1,mean+1,color=color,alpha=.2))
            self.lines.append(self.ax.plot(self.x,mean,color=color,marker=marker,markerfacecolor='white',
                markeredgecolor=color,markeredgewidth=.65,label=f'Task {i+1}')[0])
        self.legend=self.ax.legend()
        self.fig.canvas.draw()
        self.key=next(key for key,members in component_groups(self.fig).items() if self.lines[0] in members)

    def test_group_color_links_hollow_mean_edges_band_and_legend_without_recoloring_neighbor(self):
        original=[line.get_xydata().copy() for line in self.lines]
        apply_interactive_style(self.fig,{'component_styles':{self.key:{'color':'#33ee11'}}})
        self.assertEqual(to_rgba(self.lines[0].get_color()),to_rgba('#33ee11'))
        self.assertEqual(to_rgba(self.lines[0].get_markeredgecolor()),to_rgba('#33ee11'))
        self.assertEqual(to_rgba(self.lines[0].get_markerfacecolor()),to_rgba('white'))
        np.testing.assert_allclose(self.bands[0].get_facecolor()[0],to_rgba('#33ee11',.2))
        proxy=self.legend.legend_handles[0]
        self.assertEqual(to_rgba(proxy.get_markeredgecolor()),to_rgba('#33ee11'))
        self.assertEqual(to_rgba(proxy.get_markerfacecolor()),to_rgba('white'))
        self.assertEqual(self.lines[1].get_color(),'#d37520')
        self.assertEqual(self.lines[1].get_marker(),'s')
        for line,raw in zip(self.lines,original):np.testing.assert_array_equal(line.get_xydata(),raw)

    def test_shape_changes_all_means_in_selected_group_and_legend(self):
        apply_interactive_style(self.fig,{'component_styles':{self.key:{'color':'#22cc33','marker_shape':'^','fill_alpha':.4}}})
        self.assertEqual(self.lines[0].get_marker(),'^')
        points=targets(self.fig,[])
        first=next(point for point in points if point['owner_key']=='axes_0.line_0')
        second=next(point for point in points if point['owner_key']=='axes_0.line_1')
        self.assertEqual(first['point_count'],10)
        self.assertEqual(first['style']['marker_shape'],'^')
        np.testing.assert_allclose(first['style']['edge_color'],to_rgba('#22cc33'))
        np.testing.assert_allclose(first['style']['fill_color'],to_rgba('white'))
        self.assertEqual(second['style']['marker_shape'],'s')
        self.assertEqual(self.legend.legend_handles[0].get_marker(),'^')
        self.assertEqual(self.lines[0].get_alpha(),None)
        self.assertAlmostEqual(self.bands[0].get_facecolor()[0,3],.4)

    def test_transparent_hollow_fill_stays_transparent_and_solid_fill_follows_series(self):
        for face in ('none','#2465b9'):
            self.lines[0].set_markerfacecolor(face)
            apply_interactive_style(self.fig,{'component_styles':{self.key:{'color':'#22cc33'}}})
            self.assertEqual(to_rgba(self.lines[0].get_markeredgecolor()),to_rgba('#22cc33'))
            if face=='none':self.assertEqual(to_rgba(self.lines[0].get_markerfacecolor())[3],0)
            else:self.assertEqual(to_rgba(self.lines[0].get_markerfacecolor()),to_rgba('#22cc33'))

    def test_manual_shared_random_legend_does_not_inherit_task_marker_style(self):
        from matplotlib.lines import Line2D
        random=self.fig.legend(handles=[Line2D([],[],color='#888888',linestyle='--',label='Random')])
        shared=self.fig.legend(handles=self.lines,loc='upper right')
        apply_interactive_style(self.fig,{'legend_names':{'Task 1':'New task'},
            'component_styles':{self.key:{'color':'#33ee11','marker_shape':'^'}}})
        self.assertEqual(random.legend_handles[0].get_color(),'#888888')
        self.assertEqual(random.legend_handles[0].get_linestyle(),'--')
        self.assertEqual(shared.legend_handles[0].get_marker(),'^')
        self.assertEqual(to_rgba(shared.legend_handles[0].get_color()),to_rgba('#33ee11'))
        self.assertEqual(shared.get_texts()[0].get_text(),'New task')
