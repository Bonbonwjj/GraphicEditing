import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import project_preparation as prep


class CopyAndHashTests(unittest.TestCase):
    def test_streamed_copy_matches_complete_input_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'input.csv'
            target = Path(directory)/'snapshot.csv'
            content = b'group,value\n' + b'a,123456789\n' * 200000
            source.write_bytes(content)
            digest = prep.copy_and_sha(source, target)
            self.assertEqual(digest, hashlib.sha256(content).hexdigest())
            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(target.stat().st_mtime_ns, source.stat().st_mtime_ns)
            target.write_bytes(b'edited')
            self.assertEqual(source.read_bytes(), content)

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'input'; source.write_bytes(b'input')
            target = Path(directory)/'output'; target.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                prep.copy_and_sha(source, target)
            self.assertEqual(target.read_bytes(), b'existing')

    def test_changed_input_is_rejected_and_partial_copy_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'input'; source.write_bytes(b'input')
            target = Path(directory)/'output'
            original = prep.os.fstat
            calls = 0
            def stat(descriptor):
                nonlocal calls
                calls += 1
                if calls == 2:
                    source.write_bytes(b'changed input')
                return original(descriptor)
            with patch.object(prep.os, 'fstat', side_effect=stat):
                with self.assertRaisesRegex(ValueError, 'Input changed'):
                    prep.copy_and_sha(source, target)
            self.assertFalse(target.exists())
