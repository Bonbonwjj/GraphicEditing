import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import desktop_launcher as desktop


class DesktopTests(unittest.TestCase):
    def test_packaging_can_seed_projects_from_canonical_repository(self):
        import build_desktop
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';target=Path(folder)/'app'
            for name in ('static','skills','docs','projects/demo/data','projects/demo/code/charts'):
                (source/name).mkdir(parents=True,exist_ok=True)
            for name in ('team_collaboration.json','README.md','requirements.txt','docs/DESKTOP_APP.md','docs/USER_GUIDE.zh-CN.md','docs/CHAT_HARNESS.zh-CN.md'):
                (source/name).write_text('{}')
            (source/'projects/demo/code/project.json').write_text('{}')
            (source/'projects/demo/code/charts/a.py').write_text('pass')
            (source/'projects/demo/data/a.csv').write_text('x\n1\n')
            with patch.object(build_desktop,'ROOT',source):
                projects=build_desktop.stage_application(target)
            self.assertEqual(projects,['demo'])
            self.assertTrue((target/'projects/demo/charts/a.py').is_file())
            self.assertTrue((target/'projects/demo/project.json').is_file())
            self.assertEqual((target/'projects/demo/data/a.csv').read_text(),'x\n1\n')

    def test_startup_page_redirects_to_ready_workspace_without_gui_toolkit(self):
        import threading
        import time
        import urllib.request
        received=[];threads=[]
        def open_page(url):
            with urllib.request.urlopen(url) as response:
                self.assertIn('Plot Forge',response.read().decode())
            def poll():
                for _ in range(30):
                    with urllib.request.urlopen(url+'status') as response:
                        result=json.load(response)
                    if result.get('url'):
                        received.append(result['url']);return
                    time.sleep(.02)
            thread=threading.Thread(target=poll);thread.start();threads.append(thread)
        with patch.object(desktop.webbrowser,'open',side_effect=open_page), \
             patch.object(desktop,'main',return_value='http://127.0.0.1:8766/'):
            desktop.launch_with_progress()
        for thread in threads:thread.join()
        self.assertEqual(received,['http://127.0.0.1:8766/'])

    def test_upgrade_preserves_projects_and_private_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); payload=root/'payload'; home=root/'home'
            app=payload/'app'; (app/'projects/demo/charts').mkdir(parents=True)
            (app/'projects/demo/charts/a.py').write_text('seed')
            (app/'projects/demo/project.json').write_text('{}')
            (app/'server.py').write_text('version1')
            digest='a'*64
            manifest={'runtime_sha256':digest,'release':'first','seed_projects':['demo']}
            (payload/'manifest.json').write_text(json.dumps(manifest))
            runtime=home/'runtimes'/digest[:16];runtime.mkdir(parents=True)
            (runtime/'.ready').write_text('ready')
            _,workspace=desktop.prepare(payload,home)
            self.assertEqual((workspace/'projects/demo/charts/a.py').read_text(),'seed')
            (workspace/'projects/demo/charts/a.py').write_text('user edit')
            (workspace/'.model-api.json').write_text('private settings')
            (app/'server.py').write_text('version2')
            manifest['release']='second';(payload/'manifest.json').write_text(json.dumps(manifest))
            desktop.prepare(payload,home)
            self.assertEqual((workspace/'server.py').read_text(),'version2')
            self.assertEqual((workspace/'projects/demo/charts/a.py').read_text(),'user edit')
            self.assertEqual((workspace/'.model-api.json').read_text(),'private settings')

    def test_runtime_precedes_system_tools_and_clears_frozen_paths(self):
        with patch.dict('os.environ',{'PATH':'system-path','PYTHONHOME':'foreign','PYTHONPATH':'foreign'}):
            env=desktop.runtime_environment(Path('/bundled/runtime'))
        self.assertNotIn('PYTHONHOME',env)
        self.assertNotIn('PYTHONPATH',env)
        self.assertTrue(env['PATH'].startswith(str(Path('/bundled/runtime'))))

    def test_home_override_supports_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'桌面工作区 test'
            with patch.dict('os.environ',{'PLOT_FORGE_HOME':str(target)}):
                self.assertEqual(desktop.user_home(),target.resolve())
