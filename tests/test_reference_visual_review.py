import unittest
from reference_visual_review import validate,cache_key,visual_request


class ReferenceVisualReviewTests(unittest.TestCase):
    def setUp(self):
        self.context={'_reference_visual_task':'extract','reference_images':[{'reference_id':'r','revision_id':'v1'}],
                      'image_order':['r'],'_images':['data:image/png;base64,test']}
        self.feature={'feature_id':'f','reference_id':'r','name':'半小提琴','expected':'左侧半小提琴',
                      'evidence':'参考图可见半侧密度形状','transfer':'style'}

    def test_source_coverage_identifiers_and_evidence_are_required(self):
        self.assertEqual(validate(self.context,{'features':[self.feature]})['status'],'extracted')
        for patch in ({'reference_id':'unknown'},{'evidence':''},{'transfer':'invent_data'}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                validate(self.context,{'features':[{**self.feature,**patch}]})
        with self.assertRaises(ValueError):validate(self.context,{'features':[self.feature,self.feature]})

    def test_all_features_must_be_compared_with_pixel_observation(self):
        context={**self.context,'_reference_visual_task':'compare','reference_features':[self.feature]}
        item={'feature_id':'f','status':'different','observed':'候选没有密度形状','reason':'参考有半小提琴，候选仅有散点'}
        self.assertEqual(validate(context,{'items':[item]})['status'],'different')
        for patch in ({'feature_id':'other'},{'status':'pass'},{'observed':''},{'reason':''}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate(context,{'items':[{**item,**patch}]})
        with self.assertRaises(ValueError):validate(context,{'items':[]})

    def test_pinned_cache_and_actual_images(self):
        self.assertNotEqual(cache_key(self.context),cache_key({**self.context,'reference_images':[{'reference_id':'r','revision_id':'v2'}]}))
        self.assertEqual(visual_request(self.context,'extract')['image_order'],['r'])
        with self.assertRaises(ValueError):visual_request({**self.context,'_images':[]},'extract')
