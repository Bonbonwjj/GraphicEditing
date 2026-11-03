"""Browsing a project may read previews, but must never execute its charts."""
import unittest
from unittest.mock import patch
from urllib.request import urlopen

import server
from tests import test_collaboration_api as api_tests


class OnDemandPreviewTests(unittest.TestCase):
    setUp = api_tests.CollaborationApiTests.setUp

    def test_cached_interaction_metadata_never_requires_a_second_render(self):
        from chart_naming import RenderedImage
        source=self.set_source('one')
        image=RenderedImage(b'cached-png')
        image.render_report={'point_targets':[],'render_size_px':[100,100], 'axes':[{'xlim':[0,1],'ylim':[0,1]}], 'layout_signature': {
            'dpi':100,'axes':[{'bbox_px':[10,10,90,90]}],'texts':[]}}
        server.save_preview(self.project,'one',source,image)
        interaction=self.url('one').replace('/preview','/interaction')
        import json
        with patch.object(server,'render') as render:
            with urlopen(interaction) as response: result=json.load(response)
            self.assertTrue(result['ready'])
            self.assertEqual(result['render_size_px'],[100,100])
            self.assertEqual(len(result['axes']),1)
            self.set_source('one','# changed')
            with urlopen(interaction) as response: result=json.load(response)
            self.assertFalse(result['ready'])
            render.assert_not_called()

    def test_legacy_applied_preview_with_only_labels_is_not_falsely_ready(self):
        import json
        from chart_naming import RenderedImage
        source=self.set_source('one');image=RenderedImage(b'cached-png')
        image.render_report={'render_size_px':[100,100],'layout_signature':{
            'axes':[{'bbox_px':[0,0,100,100]}],'texts':[{'key':'axes_0.xlabel','text':'Group'}]}}
        server.save_preview(self.project,'one',source,image)
        with patch.object(server,'render') as render:
            with urlopen(self.url('one').replace('/preview','/interaction')) as response:result=json.load(response)
            self.assertFalse(result['ready']);render.assert_not_called()

    def test_text_only_chart_with_complete_axis_ranges_is_ready(self):
        import json
        from chart_naming import RenderedImage
        source=self.set_source('one');image=RenderedImage(b'cached-png')
        image.render_report={'point_targets':[],'render_size_px':[100,100],'artists':[],
            'axes':[{'xlim':[0,1],'ylim':[0,1]}],
            'layout_signature':{'axes':[{'bbox_px':[0,0,100,100]}],'texts':[]}}
        server.save_preview(self.project,'one',source,image)
        with urlopen(self.url('one').replace('/preview','/interaction')) as response:result=json.load(response)
        self.assertTrue(result['ready']);self.assertEqual(result['targets'],[])

    def set_source(self, chart, source='pass'):
        path = self.project/'charts'/(chart+'.py')
        path.write_text(source)
        return source

    def url(self, chart, query=''):
        return f'http://127.0.0.1:{self.port}/api/projects/demo/charts/{chart}/preview{query}'

    def test_missing_and_stale_gallery_previews_never_render_even_with_force(self):
        source = self.set_source('one')
        with patch.object(server, 'render') as render:
            for query in ('?cached_only=1', '?cached_only=1&force=1'):
                with urlopen(self.url('one', query)) as response:
                    self.assertEqual(response.status, 204)
                    self.assertEqual(response.read(), b'')
            server.save_preview(self.project, 'one', source, b'old-preview')
            self.set_source('one', '# changed')
            with urlopen(self.url('one', '?cached_only=1')) as response:
                self.assertEqual(response.status, 204)
            self.assertIsNone(server.preview_asset(self.project, 'one', source, cached_only=True))
            render.assert_not_called()

    def test_gallery_serves_valid_cached_image_without_render(self):
        source = self.set_source('one')
        server.save_preview(self.project, 'one', source, b'cached-image')
        with patch.object(server, 'render') as render:
            with urlopen(self.url('one', '?cached_only=1')) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'cached-image')
            render.assert_not_called()

    def test_only_explicit_target_can_trigger_a_render(self):
        self.set_source('one'); self.set_source('two')
        with patch.object(server, 'render', return_value=b'selected-image') as render:
            for name in ('one', 'two'):
                with urlopen(self.url(name, '?cached_only=1')) as response:
                    self.assertEqual(response.status, 204)
            with urlopen(self.url('two')) as response:
                self.assertEqual(response.read(), b'selected-image')
            render.assert_called_once_with(self.project, 'pass')
            self.assertFalse((self.project/'previews/one.png').exists())
            self.assertTrue((self.project/'previews/two.png').exists())

    def test_legacy_warmup_hook_does_not_execute_any_chart(self):
        self.set_source('one'); self.set_source('two')
        with patch.object(server, 'render') as render, patch.object(server, 'preview_asset') as preview:
            server.warm_project_previews('demo')
            render.assert_not_called(); preview.assert_not_called()


if __name__ == '__main__':
    unittest.main()
