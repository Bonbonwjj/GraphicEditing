import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from component_editor import apply_components
from component_groups import install_group_tracking,artist_key,artist_points
from chat_runner import _capture


class SummaryItemMoveTests(unittest.TestCase):
    def setUp(self):install_group_tracking();self.addCleanup(plt.close,'all')

    def example(self,horizontal=False,separate=False,mean=False,asymmetric=False):
        fig,ax=plt.subplots(dpi=100)
        positions=[1,2,3];values=[3,4,5]
        error_values=np.array([[.2,.3,.4],[.7,.8,.9]]) if asymmetric else .4
        if mean:
            bars=None;error=ax.errorbar(values if horizontal else positions,positions if horizontal else values,**({'xerr':error_values} if horizontal else {'yerr':error_values}),fmt='o-',capsize=4)
        else:
            bars=(ax.barh if horizontal else ax.bar)(positions,values,**({} if separate else {'xerr' if horizontal else 'yerr':error_values,'capsize':4}))
            error=ax.errorbar(values if horizontal else positions,positions if horizontal else values,**({'xerr':error_values} if horizontal else {'yerr':error_values}),fmt='none',capsize=4) if separate else bars.errorbar
        (ax.set_yticks if horizontal else ax.set_xticks)(positions,['A','B','C'])
        transform=ax.get_yaxis_transform() if horizontal else ax.get_xaxis_transform()
        bracket,=ax.plot([1.02,1.08,1.08,1.02] if horizontal else [1,1,2,2],[1,1,2,2] if horizontal else [1.02,1.08,1.08,1.02],transform=transform,clip_on=False)
        star=ax.text(1.1 if horizontal else 1.5,1.5 if horizontal else 1.1,'***',transform=transform)
        fig.canvas.draw();return fig,ax,bars,error,bracket,star

    def verify(self,horizontal=False,separate=False,mean=False,asymmetric=False):
        fig,ax,bars,error,bracket,star=self.example(horizontal,separate,mean,asymmetric)
        before_segments=[np.array([c.get_transform().transform(s) for s in c.get_segments()])/100 for c in error.lines[2]]
        caps=[c.get_transform().transform(c.get_xydata())/100 for c in error.lines[1]]
        raw=[c.get_xydata().copy() for c in error.lines[1]]
        bracket_before=artist_points(bracket,fig.canvas.get_renderer())/100
        star_before=star.get_transform().transform(star.get_position())/100
        ticks=(ax.yaxis if horizontal else ax.xaxis).get_major_ticks()
        tick_before=[t.tick1line.get_transform().transform(t.tick1line.get_xydata())/100 for t in ticks]
        if mean:
            report=_capture(fig,fig.canvas.get_renderer());point=next(p for p in report['point_targets'] if p['point_role']=='mean' and p['point_group']=='axes_0.category_0');key=point['key']
            center_before=error.lines[0].get_transform().transform(error.lines[0].get_xydata())/100
        else:
            key=artist_key(fig,bars.patches[0]);body=[artist_points(p,fig.canvas.get_renderer())/100 for p in bars.patches]
        apply_components(fig,{key:{'dx':18,'dy':9}})
        d=1 if horizontal else 0;q=1-d;delta=np.array([18,9])/72
        for dpi in (100,200,72):
            fig.set_dpi(dpi);fig.canvas.draw()
            for collection,original in zip(error.lines[2],before_segments):
                actual=np.array([collection.get_transform().transform(s) for s in collection.get_segments()])
                # LineCollection per-segment transforms are applied before its master transform.
                from component_groups import CollectionSegment
                actual=np.array([artist_points(CollectionSegment(collection,i),fig.canvas.get_renderer())/dpi for i in range(len(collection.get_segments()))])
                expected=original.copy();expected[0]+=delta;np.testing.assert_allclose(actual,expected,atol=1e-8)
            for cap,original,data in zip(error.lines[1],caps,raw):
                expected=original.copy();expected[0]+=delta
                np.testing.assert_allclose(cap.get_transform().transform(cap.get_xydata())/dpi,expected)
                np.testing.assert_array_equal(cap.get_xydata(),data)
            for i,tick in enumerate(ticks):
                expected=tick_before[i].copy()
                if i==0:expected[:,d]+=delta[d]
                np.testing.assert_allclose(tick.tick1line.get_transform().transform(tick.tick1line.get_xydata())/dpi,expected)
            expected=bracket_before.copy();expected[:2,d]+=delta[d];expected[:,q]+=delta[q]
            np.testing.assert_allclose(artist_points(bracket,fig.canvas.get_renderer())/dpi,expected)
            expected=star_before.copy();expected[d]+=delta[d]/2;expected[q]+=delta[q]
            np.testing.assert_allclose(star.get_transform().transform(star.get_position())/dpi,expected)
            if mean:
                expected=center_before.copy();expected[0]+=delta
                np.testing.assert_allclose(error.lines[0].get_transform().transform(error.lines[0].get_xydata())/dpi,expected)
            else:
                for i,patch in enumerate(bars.patches):np.testing.assert_allclose(artist_points(patch,fig.canvas.get_renderer())/dpi,body[i]+(delta if i==0 else 0))

    def test_individual_bar_and_mean_item_in_shared_containers(self):
        for horizontal in (False,True):
            for separate in (False,True):
                with self.subTest(horizontal=horizontal,separate=separate):self.verify(horizontal,separate)
            with self.subTest(horizontal=horizontal,mean=True):self.verify(horizontal,mean=True)

    def test_legacy_container_offsets_compose_with_new_item_offsets_and_keep_color(self):
        fig,ax,bars,error,*_=self.example()
        before=[artist_points(p,fig.canvas.get_renderer()).copy() for p in bars.patches]
        apply_components(fig,{'axes_0.bars_0':{'dx':12,'fill_color':'#ff0000'},'axes_0.bar_item_0':{'dx':3}})
        for i,patch in enumerate(bars.patches):
            np.testing.assert_allclose(artist_points(patch,fig.canvas.get_renderer()),before[i]+[fig.dpi*(15 if i==0 else 12)/72,0])
            np.testing.assert_allclose(patch.get_facecolor()[:3],[1,0,0])

    def test_asymmetric_error_bars_use_authored_means_not_interval_midpoints(self):
        for horizontal in (False,True):
            for separate in (False,True):
                with self.subTest(horizontal=horizontal,separate=separate):self.verify(horizontal,separate,asymmetric=True)

    def test_separate_comparison_strokes_and_figure_star_follow(self):
        from component_groups import CollectionSegment
        for collection_bracket in (False,True):
            with self.subTest(collection=collection_bracket):
                fig,ax,bars,error,old,oldstar=self.example()
                old.remove();oldstar.remove();ax.set_ylim(0,7)
                if collection_bracket:
                    bridge=ax.hlines(6,1,2);ticks=ax.vlines([1,2],5.8,6)
                    artists=[CollectionSegment(bridge,0),CollectionSegment(ticks,0),CollectionSegment(ticks,1)]
                else:
                    bridge,=ax.plot([1,2],[6,6]);left,=ax.plot([1,1],[5.8,6]);right,=ax.plot([2,2],[5.8,6]);artists=[bridge,left,right]
                pos=fig.transFigure.inverted().transform(ax.transData.transform((1.5,6.1)))
                star=fig.text(*pos,'***',ha='center');fig.canvas.draw()
                before=[artist_points(a,fig.canvas.get_renderer())/100 for a in artists]
                label=star.get_transform().transform(star.get_position())/100
                apply_components(fig,{artist_key(fig,bars.patches[0]):{'dx':18,'dy':9}})
                for dpi in (100,200,72):
                    fig.set_dpi(dpi);fig.canvas.draw()
                    for i,artist in enumerate(artists):
                        expected=before[i].copy();expected[:,1]+=9/72
                        if i==0:expected[0,0]+=18/72
                        elif i==1:expected[:,0]+=18/72
                        np.testing.assert_allclose(artist_points(artist,fig.canvas.get_renderer())/dpi,expected,atol=1e-8)
                    np.testing.assert_allclose(star.get_transform().transform(star.get_position())/dpi,label+np.array([9,9])/72)
                report=_capture(fig,fig.canvas.get_renderer())
                group=next(g for g in report['component_groups'] if g['key']=='axes_0.bar_item_0')
                self.assertGreaterEqual(len(group['annotation_links']),4)

    def test_annotation_text_offsets_and_arrow_survive_redraw_and_export_dpi(self):
        for offset in (False,True):
            with self.subTest(offset=offset):
                fig,ax,bars,error,bracket,oldstar=self.example();oldstar.remove()
                star=ax.annotate('***',xy=(1.5,1.1),xycoords=ax.get_xaxis_transform(),
                    **({'xytext':(0,5),'textcoords':'offset points','arrowprops':{'arrowstyle':'-','shrinkA':0,'shrinkB':0}} if offset else {}))
                fig.canvas.draw();before=star.get_transform().transform(star.get_position())/100
                raw=star.xy,star.get_position()
                apply_components(fig,{artist_key(fig,bars.patches[0]):{'dx':18,'dy':9}})
                for dpi in (100,200,72):
                    fig.set_dpi(dpi);fig.canvas.draw()
                    np.testing.assert_allclose(star.get_transform().transform(star.get_position())/dpi,before+np.array([9,9])/72)
                self.assertEqual((star.xy,star.get_position()),raw)

    def test_stem_group_moves_category_ticks_and_comparison_like_other_statistics(self):
        for horizontal in (False,True):
            fig,ax=plt.subplots(dpi=100);stem=ax.stem([1,2],[3,4],orientation='horizontal' if horizontal else 'vertical')
            (ax.set_yticks if horizontal else ax.set_xticks)([1,2],['A','B'])
            transform=ax.get_yaxis_transform() if horizontal else ax.get_xaxis_transform()
            bracket,=ax.plot([1.02,1.08,1.08,1.02] if horizontal else [1,1,2,2],[1,1,2,2] if horizontal else [1.02,1.08,1.08,1.02],transform=transform,clip_on=False)
            ax.text(1.1 if horizontal else 1.5,1.5 if horizontal else 1.1,'*',transform=transform)
            fig.canvas.draw();before=artist_points(bracket,fig.canvas.get_renderer()).copy()
            tick=(ax.yaxis if horizontal else ax.xaxis).get_major_ticks()[0]
            tick_before=tick.tick1line.get_transform().transform(tick.tick1line.get_xydata())
            apply_components(fig,{'axes_0.stem_0':{'dx':18,'dy':9}});fig.canvas.draw()
            np.testing.assert_allclose(artist_points(bracket,fig.canvas.get_renderer()),before+np.array([18,9])*100/72)
            np.testing.assert_allclose(tick.tick1line.get_transform().transform(tick.tick1line.get_xydata()),tick_before+np.array([0,9] if horizontal else [18,0])*100/72)

    def test_limit_caps_with_different_vertex_counts_follow_only_their_bar(self):
        fig,ax=plt.subplots(dpi=100);bars=ax.bar([1,2,3],[3,4,5])
        error=ax.errorbar([1,2,3],[3,4,5],yerr=.4,fmt='none',capsize=4,lolims=[True,False,False])
        fig.canvas.draw();before=[cap.get_transform().transform(cap.get_xydata()).copy() for cap in error.lines[1]]
        apply_components(fig,{artist_key(fig,bars.patches[0]):{'dx':18,'dy':9}});fig.canvas.draw()
        for cap,old in zip(error.lines[1],before):
            expected=old.copy();expected[np.isclose(cap.get_xdata(),1)]+=np.array([18,9])*100/72
            np.testing.assert_allclose(cap.get_transform().transform(cap.get_xydata()),expected)

    def test_old_duplicate_part_offsets_do_not_move_group_twice(self):
        fig,ax,bars,error,*_=self.example()
        before=artist_points(bars.patches[0],fig.canvas.get_renderer()).copy()
        apply_components(fig,{'axes_0.patch_0':{'dx':12},artist_key(fig,error.lines[1][0])+'.vertex_0':{'dx':12}})
        np.testing.assert_allclose(artist_points(bars.patches[0],fig.canvas.get_renderer()),before+[100*12/72,0])

    def test_dragging_shared_mean_line_moves_all_means_errorbars_and_caps(self):
        fig,ax,bars,error,*_=self.example(mean=True)
        before=[cap.get_transform().transform(cap.get_xydata()).copy() for cap in error.lines[1]]
        apply_components(fig,{artist_key(fig,error.lines[0]):{'dx':12,'dy':6}})
        for cap,original in zip(error.lines[1],before):
            np.testing.assert_allclose(cap.get_transform().transform(cap.get_xydata()),original+np.array([12,6])*100/72)

    def test_saved_code_and_isolated_render_keep_bar_caps_comparison_and_data_linked(self):
        import tempfile
        from pathlib import Path
        from chat_runner import _one_render
        from interactive_style import upsert_style
        source="""import os
import matplotlib.pyplot as plt
fig,ax=plt.subplots(figsize=(4,3),dpi=100)
ax.bar([1,2,3],[3,4,5],yerr=[[.2,.3,.4],[.7,.8,.9]],capsize=4)
ax.set_xticks([1,2,3],['A','B','C'])
ax.plot([1,2],[6,6],color='black')
ax.vlines([1,2],5.8,6,color='black')
ax.annotate('***',xy=(1.5,6),xytext=(0,5),textcoords='offset points',ha='center')
fig.savefig(os.environ['CHART_OUTPUT'])
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';(project/'charts').mkdir(parents=True)
            (project/'charts/plot.py').write_text(source,encoding='utf-8')
            before=_one_render(project,'charts/plot.py',{},root/'before')
            code=upsert_style(source,{'component_styles':{'axes_0.patch_0':{'dx':12,'dy':6}}})
            after=_one_render(project,'charts/plot.py',{'charts/plot.py':code},root/'after')
            group0=next(g for g in before['component_groups'] if g['key']=='axes_0.bar_item_0')
            group1=next(g for g in after['component_groups'] if g['key']=='axes_0.bar_item_0')
            old={p['key']:np.array(p['hit_path_px']) for p in group0['part_targets']}
            for part in group1['part_targets']:
                np.testing.assert_allclose(np.array(part['hit_path_px'])-old[part['key']],np.tile(np.array([12,6])*100/72,(len(old[part['key']]),1)),atol=1e-5)
            self.assertEqual([(a['key'],a['data_hash']) for a in before['artists']],[(a['key'],a['data_hash']) for a in after['artists']])
            from server import interaction_payload
            payload=interaction_payload(after)
            selected=next(p for p in payload['targets'] if p['key']=='axes_0.patch_0')
            self.assertEqual(selected['movement_group'],'axes_0.bar_item_0')
            self.assertEqual(len(payload['targets']),len({p['key'] for p in payload['targets']}))
            self.assertTrue(group1['annotation_targets'])


if __name__=='__main__':unittest.main()
