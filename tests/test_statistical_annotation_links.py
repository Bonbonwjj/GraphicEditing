import unittest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from component_editor import apply_components
from component_groups import install_group_tracking,artist_points,group_report


class StatisticalAnnotationLinkTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking();self.addCleanup(plt.close,'all')

    def example(self,kind='box',horizontal=False):
        fig,ax=plt.subplots(dpi=100)
        if kind=='box':
            ax.boxplot([[1,2,3],[2,3,4]],positions=[1,2],orientation='horizontal' if horizontal else 'vertical')
            keys=['axes_0.box_0','axes_0.box_1']
        elif kind=='violin':
            ax.violinplot([[1,2,3],[2,3,4]],positions=[1,2],orientation='horizontal' if horizontal else 'vertical')
            keys=['axes_0.violin_0','axes_0.violin_1']
        elif kind=='mean':
            for p in (1,2):
                ax.errorbar(p+1 if horizontal else p,p if horizontal else p+1,
                    **({'xerr':.3} if horizontal else {'yerr':.3}),fmt='o',capsize=4)
            keys=['axes_0.mean_error_0','axes_0.mean_error_1']
        else:
            for p in (1,2):
                if horizontal:ax.barh([p],[p+1],xerr=.3,capsize=4)
                else:ax.bar([p],[p+1],yerr=.3,capsize=4)
            keys=['axes_0.bars_0','axes_0.bars_1']
        (ax.set_yticks if horizontal else ax.set_xticks)([1,2],['A','B'])
        transform=ax.get_yaxis_transform() if horizontal else ax.get_xaxis_transform()
        line,=ax.plot([1.03,1.06,1.06,1.03] if horizontal else [1,1,2,2],
            [1,1,2,2] if horizontal else [1.03,1.06,1.06,1.03],transform=transform,clip_on=False)
        text=ax.text(1.09 if horizontal else 1.5,1.5 if horizontal else 1.09,'**',transform=transform,ha='center')
        fig.canvas.draw()
        return fig,ax,keys,line,text

    def test_group_and_comparison_endpoints_labels_and_ticks_follow_across_plot_types(self):
        for kind in ('box','violin','mean','bar'):
            for horizontal in (False,True):
                with self.subTest(kind=kind,horizontal=horizontal):
                    fig,ax,keys,line,text=self.example(kind,horizontal)
                    d=1 if horizontal else 0;q=1-d
                    before=artist_points(line,fig.canvas.get_renderer()).copy()/fig.dpi
                    label=text.get_transform().transform(text.get_position())/fig.dpi
                    tick=(ax.yaxis if horizontal else ax.xaxis).get_major_ticks()[0]
                    tick_before=tick.tick1line.get_transform().transform(tick.tick1line.get_xydata())/fig.dpi
                    raw=line.get_xydata().copy();text_position=text.get_position()
                    move=np.array([9,18] if horizontal else [18,9])/72
                    apply_components(fig,{keys[0]:{'dx':move[0]*72,'dy':move[1]*72}})
                    for dpi in (100,200,72):
                        fig.set_dpi(dpi);fig.canvas.draw()
                        expected=before.copy();expected[:2,d]+=move[d];expected[:,q]+=move[q]
                        np.testing.assert_allclose(artist_points(line,fig.canvas.get_renderer())/dpi,expected)
                        expected_label=label.copy();expected_label[d]+=move[d]/2;expected_label[q]+=move[q]
                        np.testing.assert_allclose(text.get_transform().transform(text.get_position())/dpi,expected_label)
                        expected_tick=tick_before.copy();expected_tick[:,d]+=move[d]
                        np.testing.assert_allclose(tick.tick1line.get_transform().transform(tick.tick1line.get_xydata())/dpi,expected_tick)
                    np.testing.assert_array_equal(line.get_xydata(),raw)
                    self.assertEqual(text.get_position(),text_position)

    def test_both_groups_translate_comparison_once_and_report_preview_links(self):
        fig,ax,keys,line,text=self.example('mean')
        report=group_report(fig,[])
        from component_links import report_links
        report_links(fig,[],report)
        self.assertTrue(next(g for g in report if g['key']==keys[0])['annotation_links'])
        before=artist_points(line,fig.canvas.get_renderer()).copy()
        apply_components(fig,{key:{'dx':12,'dy':-6} for key in keys})
        fig.canvas.draw()
        np.testing.assert_allclose(artist_points(line,fig.canvas.get_renderer()),before+np.array([12,-6])*fig.dpi/72)

    def test_single_group_star_follows_without_moving_unrelated_text(self):
        fig,ax,keys,line,text=self.example('bar')
        star=ax.text(1,1.2,'***',transform=ax.get_xaxis_transform())
        note=ax.text(1,1.3,'unrelated note',transform=ax.get_xaxis_transform())
        fig.canvas.draw()
        before=star.get_transform().transform(star.get_position());other=note.get_transform().transform(note.get_position())
        apply_components(fig,{keys[0]:{'dx':10,'dy':5}})
        np.testing.assert_allclose(star.get_transform().transform(star.get_position()),before+np.array([10,5])*fig.dpi/72)
        np.testing.assert_allclose(note.get_transform().transform(note.get_position()),other)
