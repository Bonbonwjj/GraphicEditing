import copy
import unittest

from layout_preservation import check_layout,unchanged_spacing_issues


class LayoutPreservationTests(unittest.TestCase):
    def setUp(self):
        self.signature={'size_inches':[7,4], 'dpi':200,'axes':[
            {'axis_label':'a','position':[.1,.2,.3,.5]},
            {'axis_label':'d','position':[.55,.2,.3,.5]}]}
        self.report={'baseline_layout_signature':copy.deepcopy(self.signature),
            'layout_signature':copy.deepcopy(self.signature)}
        self.context={'user_message':'把fig5的d图的箱型图改为小提琴图'}

    def test_local_conversion_rejects_canvas_resize_panel_move_and_panel_shrink(self):
        for mutation in ('canvas','move','shrink'):
            report=copy.deepcopy(self.report)
            if mutation=='canvas':report['layout_signature']['size_inches'][0]*=1.6
            elif mutation=='move':report['layout_signature']['axes'][0]['position'][0]+=.05
            else:report['layout_signature']['axes'][1]['position'][2]/=1.6
            with self.subTest(mutation=mutation):self.assertEqual(check_layout(self.context,report)['status'],'fail')

    def test_dpi_and_text_bounds_are_not_panel_geometry(self):
        self.report['layout_signature']['dpi']=600
        self.report['layout_signature']['axes'][0]['bbox_px']=[0,0,10,10]
        self.assertEqual(check_layout(self.context,self.report)['status'],'pass')

    def test_explicit_layout_edit_allowed_but_preserve_requirement_and_mark_width_are_not(self):
        self.report['layout_signature']['size_inches'][0]*=1.6
        for message,status in [('把整图画布加宽60%','authorized'),('调整子图间距','authorized'),
                               ('保持原布局，只把d图改为小提琴图','fail'),('不要调整布局，只换图型','fail'),
                               ('把箱型加宽一些','fail')]:
            with self.subTest(message=message):self.assertEqual(check_layout({'user_message':message},self.report)['status'],status)

    def test_verified_original_layout_reference_can_restore_bad_applied_resize(self):
        self.report['baseline_layout_signature']['size_inches'][0]*=1.6
        context={**self.context,'_layout_reference':{'signature':self.signature,'layout':{}}}
        self.assertEqual(check_layout(context,self.report)['status'],'pass')

    def test_only_unchanged_original_spacing_is_inherited(self):
        issue={'id':'old','kind':'panel_spacing','elements':['panel_1','panel_2'],'message':'existing gap'}
        new={**issue,'id':'new','message':'worse gap'}
        self.report.update(baseline_layout={'issues':[issue]},layout={'issues':[issue,new]})
        self.assertEqual(unchanged_spacing_issues(self.context,self.report),[issue])

    def test_normalization_can_relayout(self):
        self.report['layout_signature']['size_inches'][0]*=1.6
        self.assertEqual(check_layout(self.context,self.report,normalizing=True)['status'],'not_applicable')


if __name__=='__main__':unittest.main()
