import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.markers import MarkerStyle

from component_groups import install_group_tracking,artist_key
from component_editor import apply_components,validate_components
from point_components import layers,targets
from chat_runner import _capture


class PointComponentTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking();self.fig,self.ax=plt.subplots();self.addCleanup(plt.close,self.fig)

    def plot(self):
        values=[1,2,2,3,3,4,20]
        box=self.ax.boxplot([values],positions=[1],patch_artist=True,showmeans=True)
        points=self.ax.scatter(np.linspace(.94,1.06,len(values)),values,c='purple',alpha=.4,s=36)
        self.fig.canvas.draw();return box,points

    def test_samples_means_and_fliers_have_independent_selectable_layers(self):
        box,points=self.plot();found=layers(self.fig)
        self.assertEqual(sum(p['point_role']=='mean' for p in found),1)
        owner=artist_key(self.fig,points)
        ordinary=next(p for p in found if p['owner_key']==owner and p['point_role']=='regular')
        outliers=next(p for p in found if p['owner_key']==owner and p['point_role']=='outliers')
        self.assertEqual(ordinary['indices'].tolist(),list(range(6)));self.assertEqual(outliers['indices'].tolist(),[6])
        self.assertTrue(any(p['owner'] is box['fliers'][0] and p['point_role']=='outliers' for p in found))

    def test_subsets_change_shape_color_size_without_leaking_to_other_points_or_data(self):
        box,points=self.plot();before=np.asarray(points.get_offsets()).copy();old_box=box['boxes'][0].get_facecolor()
        owner=artist_key(self.fig,points)
        apply_components(self.fig,{owner+'.points_regular':{'marker_shape':'s','marker_size':12,'fill_color':'#ff0000'},
            owner+'.points_outliers':{'marker_shape':'^','marker_size':7,'fill_color':'#00ff00'}})
        np.testing.assert_array_equal(points.get_offsets(),before)
        np.testing.assert_allclose(points.get_sizes(),[144]*6+[49])
        np.testing.assert_allclose(points.get_facecolors()[:6,:3],np.tile([1,0,0],(6,1)))
        np.testing.assert_allclose(points.get_facecolors()[:,3],[.4]*7)
        np.testing.assert_allclose(points.get_facecolors()[6,:3],[0,1,0])
        square=MarkerStyle('s');triangle=MarkerStyle('^')
        np.testing.assert_allclose(points.get_paths()[0].vertices,square.get_path().transformed(square.get_transform()).vertices)
        np.testing.assert_allclose(points.get_paths()[6].vertices,triangle.get_path().transformed(triangle.get_transform()).vertices)
        self.assertEqual(box['boxes'][0].get_facecolor(),old_box)

    def test_one_mean_on_connecting_line_changes_without_altering_connector_or_neighbor(self):
        self.ax.boxplot([[1,2,3],[3,4,5]],patch_artist=True,showmeans=False)
        line,=self.ax.plot([1,2],[2,4],marker='D',color='black',alpha=.6)
        self.fig.canvas.draw();key=artist_key(self.fig,line);before=np.column_stack(line.get_data()).copy()
        means=[p for p in layers(self.fig) if p['owner'] is line]
        self.assertEqual([p['point_role'] for p in means],['mean','mean'])
        apply_components(self.fig,{key+'.points_mean_0':{'marker_shape':'*','marker_size':15,'fill_color':'#ff0000','dx':12}})
        self.fig.canvas.draw();report=_capture(self.fig,self.fig.canvas.get_renderer())
        np.testing.assert_array_equal(np.column_stack(line.get_data()),before)
        self.assertEqual(line.get_color(),'black');self.assertEqual(line.get_marker(),'D')
        self.assertEqual(line.get_markevery(),[1])
        point=next(p for p in report['point_targets'] if p['key']==key+'.points_mean_0')
        self.assertEqual(point['style']['marker_shape'],'*');self.assertEqual(point['style']['marker_size'],15)
        self.assertEqual(len([a for a in report['artists'] if a['key'].startswith('axes_0.line_')]),len(self.ax.lines)-1)

    def test_violin_uses_original_box_definition_after_conversion_and_can_use_display_iqr(self):
        box,points=self.plot()
        for artists in box.values():
            for obj in artists:obj.remove()
        self.ax.violinplot([[1,2,2,3,3,4,20]],positions=[1])
        selected=[p for p in layers(self.fig) if p['owner'] is points and p['point_role']=='outliers']
        self.assertEqual(selected[0]['indices'].tolist(),[6]);self.assertEqual(selected[0]['rule'],'original_whiskers')
        fig,ax=plt.subplots();self.addCleanup(plt.close,fig)
        ax.violinplot([[1,2,2,3,3,4,20]],positions=[1]);scatter=ax.scatter([1]*7,[1,2,2,3,3,4,20])
        self.assertEqual(next(p for p in layers(fig) if p['owner'] is scatter and p['point_role']=='outliers')['indices'].tolist(),[6])

    def test_scatter_motion_follows_same_group_outliers_without_rewriting_offsets(self):
        _,points=self.plot();self.fig.canvas.draw();before=np.asarray(points.get_offsets()).copy();key=artist_key(self.fig,points)
        old=targets(self.fig,[]);original=next(p for p in old if p['key']==key+'.points_outliers')['hit_path_px']
        apply_components(self.fig,{key+'.points_regular':{'dx':9,'dy':-3,'marker_shape':'s'}})
        self.fig.canvas.draw();new=targets(self.fig,[])
        np.testing.assert_array_equal(points.get_offsets(),before)
        np.testing.assert_allclose(next(p for p in new if p['key']==key+'.points_outliers')['hit_path_px'],np.array(original)+np.array([9,-3])*self.fig.dpi/72)

    def test_invalid_marker_is_rejected(self):
        with self.assertRaises(ValueError):validate_components({'axes_0.collection_0.points_regular':{'marker_shape':'eval'}})

    def test_violin_editing_classification_does_not_count_mean_markers_as_samples(self):
        values=np.array([0,0,1,2,3,4,8.])
        self.ax.violinplot([values,values+2],positions=[1,2])
        first=self.ax.scatter(np.full(len(values),1),values)
        self.ax.scatter(np.full(len(values),2),values+2)
        self.ax.plot([1,2],[values.mean(),values.mean()+2],marker='D')
        q1,q3=np.percentile(values,[25,75]);expected=np.where((values<q1-1.5*(q3-q1))|(values>q3+1.5*(q3-q1)))[0]
        found=[p for p in layers(self.fig) if p['owner'] is first and p['point_role']=='outliers']
        self.assertEqual(found[0]['indices'].tolist() if found else [],expected.tolist())

    def test_separate_scatter_means_are_independent_but_singleton_samples_remain_samples(self):
        values=[1,2,3,4,5]
        self.ax.violinplot([values],positions=[1]);self.ax.scatter([1]*5,values)
        mean=self.ax.scatter([1],[3],marker='D',s=80)
        key=next(p['key'] for p in layers(self.fig) if p['owner'] is mean)
        self.assertTrue(key.endswith('points_mean_0'))
        apply_components(self.fig,{key:{'marker_shape':'*','fill_color':'#ff0000'}})
        self.assertEqual(next(p['key'] for p in layers(self.fig) if p['owner'] is mean),key)
        fig,ax=plt.subplots();self.addCleanup(plt.close,fig);ax.boxplot([values])
        samples=[ax.scatter([1],[v]) for v in values]
        self.assertTrue(all(p['point_role']=='regular' for p in layers(fig) if p['owner'] in samples))

    def two_groups(self,kind='box',horizontal=False):
        values=[1,2,2,3,3,4,20]
        if kind=='box':self.ax.boxplot([values,values],positions=[1,2],patch_artist=True,orientation='horizontal' if horizontal else 'vertical')
        else:self.ax.violinplot([values,values],positions=[1,2])
        category=np.repeat([1,2],len(values));data=np.tile(values,2)
        points=self.ax.scatter(data,category,c='purple') if horizontal else self.ax.scatter(category,data,c='purple')
        self.fig.canvas.draw();return points

    def test_mixed_collection_is_split_by_category_in_box_and_violin(self):
        for kind,horizontal in [('box',False),('violin',False),('box',True)]:
            with self.subTest(kind=kind,horizontal=horizontal):
                self.ax.clear()
                # clear() intentionally does not clear application-owned attrs.
                for attr in ('_component_point_regions','_component_violin_point_regions','_component_boxes','_component_violins'):
                    if hasattr(self.ax,attr):delattr(self.ax,attr)
                points=self.two_groups(kind,horizontal);before=np.asarray(points.get_offsets()).copy()
                found=[p for p in layers(self.fig) if p['owner'] is points]
                first=next(p for p in found if p['indices'][0]==0)
                selected=[p for p in found if p['point_group']==first['point_group']]
                self.assertEqual(len({p['point_group'] for p in found}),2)
                self.assertEqual(sorted(np.concatenate([p['indices'] for p in selected]).tolist()),list(range(7)))
                apply_components(self.fig,{p['key']:{'fill_color':'#ff0000','marker_shape':'s'} for p in selected})
                np.testing.assert_allclose(points.get_facecolors()[:7,:3],np.tile([1,0,0],(7,1)))
                np.testing.assert_allclose(points.get_facecolors()[7:,:3],np.tile([.5019607843137255,0,.5019607843137255],(7,1)))
                np.testing.assert_array_equal(points.get_offsets(),before)

    def test_outlier_and_sample_artists_share_only_their_own_category(self):
        values=[1,2,2,3,3,4,20]
        self.ax.boxplot([values,values],positions=[1,2])
        sample_artists=[self.ax.scatter([position],[value],c='purple') for position in [1,2] for value in values]
        found=layers(self.fig);left=next(p['point_group'] for p in found if p['owner'] is sample_artists[0])
        left_layers=[p for p in found if p['point_group']==left and p['point_role'] in ('regular','outliers')]
        self.assertEqual(len(left_layers),8) # Seven observed dots plus the boxplot flier.
        self.assertTrue(any(p['point_role']=='outliers' for p in left_layers))
        apply_components(self.fig,{p['key']:{'fill_color':'#00ff00'} for p in left_layers})
        np.testing.assert_allclose(sample_artists[0].get_facecolors()[0,:3],[0,1,0])
        np.testing.assert_allclose(sample_artists[7].get_facecolors()[0,:3],[.5019607843137255,0,.5019607843137255])

    def test_saved_broad_styles_remain_baseline_under_new_group_override(self):
        points=self.two_groups();owner=artist_key(self.fig,points)
        first=next(p for p in layers(self.fig) if p['owner'] is points and p['point_role']=='regular')
        apply_components(self.fig,{first['key']:{'fill_color':'#0000ff'},owner+'.points_regular':{'fill_color':'#ff0000'}})
        np.testing.assert_allclose(points.get_facecolors()[0,:3],[0,0,1])
        np.testing.assert_allclose(points.get_facecolors()[7,:3],[1,0,0])


if __name__=='__main__':unittest.main()
