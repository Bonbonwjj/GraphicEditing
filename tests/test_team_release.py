import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from app_version import APP_VERSION


class TeamReleaseTests(unittest.TestCase):
    def test_default_package_contains_platform_only_with_consistent_version(self):
        script=Path(__file__).resolve().parents[1]/'tools/package_team_release.py'
        spec=importlib.util.spec_from_file_location('team_package_test',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'app';root.mkdir();(root/'docs').mkdir()
            (root/'docs/团队共享文件夹与打包.md').write_text('Guide',encoding='utf-8')
            (root/'server.py').write_text('# platform')
            (root/'team_collaboration.json').write_text('{"mode":"direct","path":"X:\\\\figure_DATA_code"}')
            (root/'.model-api.json').write_text('private settings')
            project=root/'projects/private';project.mkdir(parents=True);(project/'secret.csv').write_text('research data')
            with patch.object(module,'ROOT',root):
                result=module.package(Path(directory)/'release',[])
            self.assertEqual(len(result),1)
            archive=Path(result[0]['path']);self.assertEqual(archive.name,f'Plot-Forge-v{APP_VERSION}-team.zip')
            with zipfile.ZipFile(archive) as z:
                prefix=f'Plot-Forge-v{APP_VERSION}-team/'
                self.assertIn(prefix+'server.py',z.namelist())
                self.assertFalse(any('/projects/' in path or '.model-api' in path for path in z.namelist()))
                manifest=json.loads(z.read(prefix+'PACKAGE_MANIFEST.json'))
                self.assertEqual(manifest['version'],APP_VERSION);self.assertEqual(manifest['projects'],[])
            self.assertTrue((archive.parent/'SHA256SUMS.txt').is_file())


if __name__=='__main__':unittest.main()
