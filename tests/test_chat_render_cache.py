import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import matplotlib
matplotlib.use('Agg')

import chat_render_cache as cache
from chat_runner import render_candidate
from interactive_style import upsert_style
from tests.test_fast_interactive_preview import fixture


class ChatRenderCacheTests(unittest.TestCase):
    def setUp(self):
        with cache._GUARD: cache._CACHE.clear(); cache._LOCKS.clear()
        self.addCleanup(cache._CACHE.clear)

    def test_replay_compatibility_requires_unchanged_construction_and_literal_style(self):
        with tempfile.TemporaryDirectory() as directory:
            project, source = fixture(Path(directory))
            styled = upsert_style(source, {'component_styles': {'axes_0': {'ylim': [0,8]}}})
            self.assertTrue(cache.native_replay_compatible(source, styled))
            self.assertTrue(cache.native_replay_compatible(source, source.replace('    apply_interactive_style(figure, INTERACTIVE_STYLE)',
                '    figure.axes[0].set_title("New")\n    apply_interactive_style(figure, INTERACTIVE_STYLE)')))
            for changed in (source.replace("NATIVE_FIGURE = 'fig1'", "NATIVE_FIGURE = 'fig2'"),
                    source.replace('plot.render()', 'plot.render_other()'),
                    source+'\nprint("extra")', source.replace('INTERACTIVE_STYLE = ', 'INTERACTIVE_STYLE = dict() # ')):
                self.assertFalse(cache.native_replay_compatible(source, changed))
            project_hook = source.replace('    apply_interactive_style(figure, INTERACTIVE_STYLE)',
                '    import project_reader\n    project_reader.restyling(figure)\n    apply_interactive_style(figure, INTERACTIVE_STYLE)')
            self.assertFalse(cache.native_replay_compatible(project_hook,project_hook))

    def test_warm_candidates_reuse_pristine_seed_and_keep_full_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project,source=fixture(root);entry='charts/fig1.py'
            with patch.dict('os.environ', {'PLOT_FORGE_CHAT_PREVIEW_DPI':'100'}):
                first_source=upsert_style(source,{'component_styles':{'axes_0.box_0':{'fill_color':'#ff0000'}}})
                first=render_candidate(project,entry,{entry:first_source},root/'one',baseline_files={entry:source})
                second=render_candidate(project,entry,{entry:upsert_style(first_source,{'component_styles':{'axes_0.box_0':{'fill_color':'#00ff00'}}})},root/'two',baseline_files={entry:first_source})
                self.assertFalse(first['baseline_cache_hit'])
                self.assertTrue(second['baseline_cache_hit']);self.assertTrue(second['candidate_seed_reused'])
                self.assertEqual(second['data_report']['changed'],[])
                self.assertTrue(second['font_audit']);self.assertTrue(second['layout_signature'])
                self.assertEqual(first['candidate_artists'],second['baseline_artists'])
                (project/'data/native/fig1/data/values.json').write_text('[2,3,4,5,6]')
                third=render_candidate(project,entry,{entry:source},root/'three',baseline_files={entry:source})
                self.assertFalse(third['baseline_cache_hit'])
                self.assertFalse(third['candidate_seed_reused'])
                self.assertNotEqual(first['baseline_artists'],third['baseline_artists'])
            self.assertEqual((project/entry).read_text(encoding='utf-8'),source)

    def test_cache_copies_do_not_allow_a_comparison_to_mutate_later_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def renderer(*args,**kwargs): return {'image_bytes':b'png','artists':[{'key':'a'}]}
            with patch.object(cache,'identity',return_value='key'):
                result=cache.baseline(root,'charts/a.py',{},root/'one',100,renderer)
                result['artists'].clear()
                self.assertEqual(cache.peek('key')['artists'],[{'key':'a'}])
                with patch.object(cache,'MAX_ENTRIES',1):
                    with patch.object(cache,'identity',return_value='next'):
                        cache.baseline(root,'charts/a.py',{},root/'two',100,renderer)
                self.assertIsNone(cache.peek('key'))
