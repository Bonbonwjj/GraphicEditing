import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import project_preparation as prep


class WorkspaceReadyTests(unittest.TestCase):
    def test_install_rolls_back_on_project_volume_even_when_staging_is_elsewhere(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=root/'project';staged=root/'other-volume/staged'
            for folder in ('charts','lib'):
                (project/folder).mkdir(parents=True)
                (staged/folder).mkdir(parents=True)
                (project/folder/'old.py').write_text('original '+folder)
                (staged/folder/'new.py').write_text('replacement '+folder)
            rename=Path.rename
            copytree=prep.shutil.copytree
            def same_volume(source,destination):
                if not Path(destination).is_relative_to(project):
                    raise OSError(18,'Cross-device rename')
                return rename(source,destination)
            def fail_second(source,destination,*args,**kwargs):
                if Path(source)==staged/'lib':raise OSError('disk full')
                return copytree(source,destination,*args,**kwargs)
            with patch.object(Path,'rename',same_volume),patch.object(prep.shutil,'copytree',side_effect=fail_second):
                with self.assertRaisesRegex(OSError,'disk full'):
                    prep.install_verified(project,staged,('charts','lib'),root/'other-volume/rollback')
            for folder in ('charts','lib'):
                self.assertEqual((project/folder/'old.py').read_text(),'original '+folder)
                self.assertFalse((project/folder/'new.py').exists())

    def test_only_validated_nonempty_projects_are_openable(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p/'charts').mkdir()
            (p/'charts/a.py').write_text('pass')
            self.assertTrue(prep.can_open(p))  # Legacy split chart, no new state file.
            prep.save_state(p, {'status':'ready'})
            self.assertFalse(prep.can_open(p))  # Explicit new state still needs evidence.
            prep.save_state(p, {'status': 'needs_analysis'})
            self.assertFalse(prep.can_open(p))
            prep.save_state(p, {'status': 'ready', 'validation': {'state': 'passed'}})
            self.assertTrue(prep.can_open(p))
            (p/'charts/a.py').unlink()
            self.assertFalse(prep.can_open(p))

    def test_restored_validation_and_incomplete_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p/'charts').mkdir(); (p/'charts/a.py').write_text('pass')
            (p/'validation').mkdir()
            (p/'validation/direct.json').write_text(json.dumps({'state': 'passed'}))
            self.assertTrue(prep.can_open(p))
            prep.save_state(p, {'status': 'ready', 'mode': 'batch'})
            prep.write_json(p/'.preparation/batch.json', {'installed': False, 'jobs': [{'status': 'ready'}]})
            self.assertFalse(prep.can_open(p))
