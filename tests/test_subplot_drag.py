import io
import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from component_editor import apply_components, resolve_component, validate_components
from subplot_layout import panel_text_links


class SubplotDragTests(unittest.TestCase):
    def figure(self):
        fig, axes=plt.subplots(1,2,figsize=(8,4),dpi=100,layout='constrained')
        self.addCleanup(plt.close,fig)
        for i,axis in enumerate(axes):
            axis.plot([0,1,2],[2,4,3],marker='o',label='data')
            axis.set(xlabel='Group',ylabel='Score',title=f'Panel {i+1}')
            axis.text(.3,.8,'***',transform=axis.transAxes)
            axis.legend()
        fig.canvas.draw()
        box=axes[0].get_position()
        fig.text(box.x0-.02,box.y1+.01,'a',fontweight='bold')
        fig.suptitle('Shared title')
        fig.canvas.draw()
        return fig,axes

    def test_entire_subplot_moves_without_resizing_or_moving_neighbor(self):
        fig,axes=self.figure();axis=axes[0]
        before=[a.bbox.extents.copy() for a in axes]
        line=axis.lines[0];data=line.get_xydata().copy()
        points=line.get_transform().transform(data)
        label=fig.texts[0];label_before=label.get_window_extent().extents.copy()
        shared=fig._suptitle.get_window_extent().extents.copy()
        apply_components(fig,{'axes_0':{'dx':18,'dy':-9}});fig.canvas.draw()
        delta=np.array([25,-12.5])
        np.testing.assert_allclose(axis.bbox.extents,before[0]+np.tile(delta,2),atol=1e-6)
        np.testing.assert_allclose(axes[1].bbox.extents,before[1],atol=1e-6)
        np.testing.assert_allclose(line.get_transform().transform(data),points+delta,atol=1e-6)
        np.testing.assert_allclose(label.get_window_extent().extents,label_before+np.tile(delta,2),atol=1e-6)
        np.testing.assert_allclose(fig._suptitle.get_window_extent().extents,shared,atol=1e-6)
        np.testing.assert_array_equal(line.get_xydata(),data)
        self.assertIsNone(fig.get_layout_engine())

    def test_figure_letter_can_move_independently_and_compose_with_subplot(self):
        fig,axes=self.figure();label=fig.texts[0]
        before=label.get_transform().transform(label.get_position())
        bounds=axes[0].bbox.extents.copy()
        apply_components(fig,{'figure.text_0':{'dx':7,'dy':4,'color':'#ff0000'}})
        fig.canvas.draw()
        np.testing.assert_allclose(label.get_transform().transform(label.get_position()),before+np.array([7,4])*100/72)
        np.testing.assert_allclose(axes[0].bbox.extents,bounds,atol=.01)
        self.assertIs(resolve_component(fig,'figure.text_0'),label)
        self.assertIsNone(resolve_component(fig,'figure.text_999'))
        validate_components({'figure.text_0':{'dx':10}})

    def test_own_letter_offset_adds_to_subplot_offset_at_export_dpi(self):
        fig,axes=self.figure();label=fig.texts[0]
        before=label.get_transform().transform(label.get_position())/fig.dpi
        apply_components(fig,{'axes_0':{'dx':18,'dy':9},'figure.text_0':{'dx':3,'dy':-2}})
        for dpi in (100,200,72):
            fig.set_dpi(dpi);fig.canvas.draw()
            np.testing.assert_allclose(label.get_transform().transform(label.get_position())/dpi,before+np.array([21,7])/72,atol=1e-6)
        fig.savefig(io.BytesIO(),format='png',dpi=150)

    def test_report_exposes_figure_letter_association(self):
        from chat_runner import _capture
        fig,axes=self.figure()
        self.assertEqual(panel_text_links(fig),{'figure.text_0':'axes_0'})
        report=_capture(fig,fig.canvas.get_renderer())
        letter=next(t for t in report['layout_signature']['texts'] if t['key']=='figure.text_0')
        self.assertEqual(letter['subplot_key'],'axes_0')

    def test_local_figure_heading_follows_but_source_icon_cannot_steal_letter(self):
        fig,axes=self.figure();box=axes[0].get_position()
        heading=fig.text(box.x0+box.width/2,box.y1+.025,'Task 1',ha='center')
        icon=fig.add_axes([box.x0-.02,box.y1,.02,.02],label='source_icon')
        icon._source_panel='a';fig.canvas.draw()
        self.assertEqual(panel_text_links(fig)['figure.text_0'],'axes_0')
        self.assertEqual(panel_text_links(fig)['figure.text_2'],'axes_0')
        before=heading.get_transform().transform(heading.get_position())
        apply_components(fig,{'axes_0':{'dx':18,'dy':9}});fig.canvas.draw()
        np.testing.assert_allclose(heading.get_transform().transform(heading.get_position()),before+[25,12.5])

    def test_panel_letter_does_not_bind_to_the_previous_panels_right_edge(self):
        fig=plt.figure(figsize=(8,4),dpi=100);self.addCleanup(plt.close,fig)
        fig.add_axes([.1,.2,.4,.6],label='b1')
        fig.add_axes([.6,.2,.3,.6],label='c1')
        fig.text(.51,.82,'c');fig.canvas.draw()
        self.assertEqual(panel_text_links(fig)['figure.text_0'],'axes_1')


if __name__=='__main__':unittest.main()
