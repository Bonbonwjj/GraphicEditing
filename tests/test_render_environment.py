import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import render_environment as env


class RenderEnvironmentTests(unittest.TestCase):
    def test_default_uses_application_python_and_warns_without_native_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'native-project.json').write_text(json.dumps({'required_versions':{'numpy':'0.0'}}))
            with patch.object(env,'ROOT',root):result=env.describe(root)
            self.assertEqual(result['executable'],sys.executable)
            self.assertEqual(result['mode'],'default')
            self.assertTrue(any('numpy' in w for w in result['warnings']))
            self.assertFalse((root/'.native-venv').exists())

    def test_strict_missing_environment_never_silently_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'native-project.json').write_text('{"environment_mode":"strict"}')
            with patch.object(env,'ROOT',root),patch.object(env.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'严格复现.*不存在'):env.describe(root)
                run.assert_not_called()

    def test_strict_checks_versions_and_selects_independent_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            python=root/('.native-venv/Scripts/python.exe' if env.os.name=='nt' else '.native-venv/bin/python')
            python.parent.mkdir(parents=True);python.touch()
            (root/'native-project.json').write_text(json.dumps({'environment_mode':'strict','required_versions':{'numpy':'1.24.3'}}))
            with patch.object(env,'ROOT',root),patch.object(env.subprocess,'run') as run:
                run.return_value.returncode=0
                run.return_value.stdout=json.dumps({'python':'3.11','versions':{'numpy':'2.0'},'prefix':temp,'base_prefix':temp})
                with self.assertRaisesRegex(ValueError,'版本不符合'):env.describe(root)
                run.return_value.stdout=json.dumps({'python':'3.11','versions':{'numpy':'1.24.3'},'prefix':temp,'base_prefix':temp})
                result=env.describe(root)
                self.assertEqual(result['executable'],str(python))
                self.assertEqual(result['warnings'],[])

    def test_package_changes_invalidate_environment_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(env,'ROOT',root),patch.object(env.subprocess,'run') as run:
                run.return_value.returncode=0
                run.return_value.stdout=json.dumps({'python':'3.11','versions':{'numpy':'1'},'prefix':temp,'base_prefix':temp})
                first=env.describe(root)['fingerprint']
                run.return_value.stdout=json.dumps({'python':'3.11','versions':{'numpy':'2'},'prefix':temp,'base_prefix':temp})
                self.assertNotEqual(first,env.describe(root)['fingerprint'])

    def test_strict_container_mode_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'native-project.json').write_text('{"environment_mode":"strict"}')
            with self.assertRaisesRegex(ValueError,'容器'):env.describe(root,'docker')
