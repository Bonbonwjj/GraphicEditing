import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from component_groups import install_group_tracking, component_groups, artist_points, group_report
from component_editor import apply_components


class StatisticalGroupTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking()
        self.figure, self.axis = plt.subplots()
        self.addCleanup(plt.close, self.figure)

    def test_box_width_changes_without_changing_statistical_heights(self):
        result=self.axis.boxplot([[1,2,3,4,5]],patch_artist=True)
        self.figure.canvas.draw()
        box=result['boxes'][0]
        before=artist_points(box,self.figure.canvas.get_renderer())
        apply_components(self.figure,{'axes_0.box_0':{'width_scale':2}})
        after=artist_points(box,self.figure.canvas.get_renderer())
        self.assertAlmostEqual(np.ptp(after[:,0]),2*np.ptp(before[:,0]))
        np.testing.assert_allclose(after[:,1],before[:,1])

    def test_mean_point_size_does_not_change_caps_and_caps_match_color(self):
        error=self.axis.errorbar(.8,2,yerr=.3,fmt='none',capsize=8,ecolor='#9933cc')
        mean=self.axis.scatter([.8],[2],s=400)
        caps=error.lines[1];size=caps[0].get_markersize()
        apply_components(self.figure,{'axes_0.mean_error_0':{'marker_size':12,'color':'#00aa55','linewidth':4}})
        self.assertEqual(mean.get_sizes().tolist(),[144])
        for cap in caps:
            self.assertEqual(cap.get_markersize(),size)
            self.assertEqual(cap.get_markeredgecolor(),'#00aa55')
            self.assertEqual(cap.get_markeredgewidth(),4)

    def test_axis_tick_length_width_and_color_follow_spines(self):
        from interactive_style import apply_interactive_style
        self.axis.set_xticks([0,1,2]);self.axis.set_yticks([0,1,2])
        apply_interactive_style(self.figure,{
            'spine_styles':{'axes_0.spine_left':{'border_color':'#ff0000'},'axes_0.spine_bottom':{'border_color':'#0066ff'}},
            'component_styles':{'axes_0':{'x_tick_length':9,'y_tick_length':13,'x_tick_width':2,'y_tick_width':3},'axes_0.ytick_major_0_1':{'color':'#00aa55'}},
        })
        for tick in self.axis.xaxis.get_major_ticks():
            self.assertEqual(tick.tick1line.get_markersize(),9)
            self.assertEqual(tick.tick1line.get_markeredgewidth(),2)
            self.assertEqual(tick.tick1line.get_markeredgecolor(),self.axis.spines['bottom'].get_edgecolor())
        for tick in self.axis.yaxis.get_major_ticks():
            self.assertEqual(tick.tick1line.get_markersize(),13)
            self.assertEqual(tick.tick1line.get_markeredgewidth(),3)
            self.assertEqual(tick.tick1line.get_markeredgecolor(),self.axis.spines['left'].get_edgecolor())
        self.assertEqual(self.axis.yaxis.get_major_ticks()[0].label1.get_color(),'#00aa55')

    def test_box_contains_whiskers_caps_and_median_and_moves_together(self):
        result = self.axis.boxplot([[1, 2, 3, 4, 5], [2, 3, 4, 5, 6]], patch_artist=True)
        self.figure.canvas.draw()
        members = component_groups(self.figure)['axes_0.box_0']
        self.assertIn(result['medians'][0], members)
        self.assertIn(result['caps'][0], members)
        renderer=self.figure.canvas.get_renderer()
        before=[artist_points(obj, renderer).copy() for obj in members]
        apply_components(self.figure, {'axes_0.box_0': {'dx': 18, 'dy': 9, 'scale': .5, 'edge_color': '#ff0000', 'fill_color': '#00ff00'}})
        self.figure.canvas.draw()
        old=np.concatenate(before);center=(old.min(axis=0)+old.max(axis=0))/2
        for obj, original in zip(members, before):
            np.testing.assert_allclose(artist_points(obj, self.figure.canvas.get_renderer()),
                (original-center)*.5+center+np.array([18,9])*self.figure.dpi/72,atol=1e-8)
        self.assertEqual(result['boxes'][0].get_facecolor(), (0,1,0,1))
        self.assertNotEqual(result['boxes'][1].get_facecolor(), (0,1,0,1))

    def test_mean_and_separate_scatter_are_one_item(self):
        error = self.axis.errorbar(.8, 2, yerr=.3, fmt='none', capsize=6)
        mean = self.axis.scatter([.8], [2])
        groups=component_groups(self.figure)
        self.assertIn(mean, groups['axes_0.mean_error_0'])
        self.assertIn(error.lines[2][0], groups['axes_0.mean_error_0'])
        apply_components(self.figure, {'axes_0.mean_error_0': {'color': '#ff0000', 'linewidth': 4}})
        np.testing.assert_allclose(mean.get_facecolors()[0], [1,0,0,1])
        np.testing.assert_allclose(error.lines[2][0].get_colors()[0], [1,0,0,1])
        self.figure.canvas.draw()
        report=group_report(self.figure, [])
        self.assertEqual(report[0]['key'], 'axes_0.mean_error_0')
        self.assertGreater(len(report[0]['hit_paths_px']), 1)

    def test_axis_color_and_single_tick_override(self):
        self.axis.set(xlabel='X', ylabel='Y')
        self.axis.set_xticks([0,1,2])
        apply_components(self.figure, {'axes_0.xaxis_text': {'color': '#ff0000'},
                                       'axes_0.xtick_major_1_1': {'color': '#0066ff'}})
        self.assertNotEqual(self.axis.xaxis.label.get_color(), '#ff0000')
        self.assertEqual(self.axis.xaxis.get_major_ticks()[0].label1.get_color(), '#ff0000')
        self.assertEqual(self.axis.xaxis.get_major_ticks()[1].label1.get_color(), '#0066ff')
        self.assertNotEqual(self.axis.yaxis.label.get_color(), '#ff0000')
        self.assertEqual(self.axis.xaxis.get_major_ticks()[0].tick1line.get_markeredgecolor(), self.axis.spines['bottom'].get_edgecolor())
        self.assertEqual(self.axis.xaxis.get_major_ticks()[1].tick1line.get_markeredgecolor(), self.axis.spines['bottom'].get_edgecolor())

    def test_new_range_updates_fixed_ticks_and_trimmed_spines(self):
        self.axis.set(xlabel='Keep X', ylabel='Keep Y')
        self.axis.set_yticks([5, 5.25, 5.5, 5.75, 6])
        self.axis.set_xticks([0, 1, 2])
        self.axis.spines['left'].set_bounds(5, 6)
        self.axis.spines['bottom'].set_bounds(0, 2)
        self.axis.set_ylim(5, 6)
        apply_components(self.figure, {
            'axes_0': {'ylim': [4, 8], 'xlim': [-2, 4]},
            'axes_0.yaxis_text': {'color': '#0066ff'},
        })
        self.figure.canvas.draw()
        self.assertEqual(self.axis.get_ylim(), (4, 8))
        self.assertEqual(self.axis.spines['left'].get_bounds(), (4, 8))
        self.assertEqual(self.axis.spines['bottom'].get_bounds(), (-2, 4))
        ticks=self.axis.get_yticks()
        self.assertLessEqual(min(ticks), 4)
        self.assertGreaterEqual(max(ticks), 8)
        self.assertTrue(any(t<5 or t>6 for t in ticks))
        for tick in self.axis.yaxis.get_major_ticks():
            self.assertEqual(tick.label1.get_color(), '#0066ff')
            self.assertEqual(tick.tick1line.get_markeredgecolor(), self.axis.spines['left'].get_edgecolor())
        self.assertNotEqual(self.axis.yaxis.label.get_color(), '#0066ff')
        self.assertEqual(self.axis.get_ylabel(), 'Keep Y')
