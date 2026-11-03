import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import project_preparation as prep
from preparation_cleanup import cleanup_completed_cache, release_verified_live_workspaces


class PreparationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.project=self.root/'p'
        (self.project/'charts').mkdir(parents=True)
        (self.project/'charts/a.py').write_text('pass')
        prep.write_json(self.project/'project.json',{'name':'p'})
        for name in ('universal-cache','native-cache','source'):
            folder=self.project/'.preparation'/name
            folder.mkdir(parents=True)
            (folder/'keep.dat').write_bytes(b'original')
        (self.project/'previews').mkdir()
        (self.project/'previews/a.png').write_bytes(b'preview')

    def test_only_installed_ready_projects_drop_caches_and_keep_outputs(self):
        for status in ('working','needs_context','ready'):
            prep.save_state(self.project,{'status':status})
            self.assertEqual(cleanup_completed_cache(self.project)['removed'],[])
            self.assertTrue((self.project/'.preparation/universal-cache').exists())
        prep.save_state(self.project,{'status':'ready','validation':{'state':'passed'}})
        self.assertFalse((self.project/'.preparation/universal-cache').exists())
        self.assertFalse((self.project/'.preparation/native-cache').exists())
        self.assertEqual((self.project/'.preparation/source/keep.dat').read_bytes(),b'original')
        self.assertEqual((self.project/'previews/a.png').read_bytes(),b'preview')
        self.assertEqual((self.project/'charts/a.py').read_text(),'pass')

    def test_symlinked_cache_cannot_remove_external_files(self):
        target=self.project/'.preparation/universal-cache'
        (target/'keep.dat').unlink();target.rmdir()
        external=self.root/'external';external.mkdir()
        (external/'value').write_text('keep')
        target.symlink_to(external,target_is_directory=True)
        prep.save_state(self.project,{'status':'ready','validation':{'state':'passed'}})
        self.assertTrue(target.is_symlink())
        self.assertEqual((external/'value').read_text(),'keep')

    def test_live_cleanup_releases_verified_pair_only(self):
        work=self.root/'plot-universal-prepare-test'
        staged=work/'project'
        prep.write_json(staged/'project.json',{'name':'p'})
        registry={'schema':'plot-forge-universal/1','figures':{}}
        for index in (1,2):
            ident='draw_'+str(index)
            registry['figures'][ident]={'entry_path':'draw.py','entry_symbol':None,'output_index':index}
            for prefix in ('render_','repeat_'):
                folder=work/(prefix+ident);folder.mkdir(parents=True)
                (folder/'data.csv').write_text('input copy')
        prep.write_json(staged/'universal-project.json',registry)
        image=b'verified-png'
        (staged/'previews').mkdir()
        (staged/'previews/draw_1.png').write_bytes(image)
        cache=self.project/'.preparation/universal-cache'
        (cache/'key.png').write_bytes(image)
        prep.write_json(cache/'key.json',{'key':'key','image_sha256':hashlib.sha256(image).hexdigest(),
            'report':{'output_count':1,'output_provenance':{'entry_path':'draw.py','entry_symbol':None,'output_index':1}}})
        result=release_verified_live_workspaces(self.project,work)
        self.assertEqual(result['released'],['draw_1'])
        self.assertFalse((work/'render_draw_1').exists())
        self.assertFalse((work/'repeat_draw_1').exists())
        self.assertTrue((work/'render_draw_2/data.csv').exists())
        self.assertTrue((work/'repeat_draw_2/data.csv').exists())
        self.assertTrue((staged/'previews/draw_1.png').exists())
        self.assertTrue((cache/'key.json').exists())
