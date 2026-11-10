import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from chat_harness import atomic_json


class ChatAtomicWriteTests(unittest.TestCase):
    def test_windows_transient_lock_retries_only_atomic_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.json';path.write_text('{"old":true}')
            original=Path.replace;calls=[]
            def busy(temporary,target):
                calls.append(target)
                if len(calls)<3:
                    error=PermissionError('busy');error.winerror=32;raise error
                return original(temporary,target)
            with patch('chat_harness.os',SimpleNamespace(name='nt')),patch.object(Path,'replace',busy),patch('chat_harness.time.sleep') as sleep:
                atomic_json(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'new':True})
            self.assertEqual(len(calls),3);self.assertEqual(sleep.call_count,2)

    def test_permanent_denial_preserves_live_session_and_does_not_retry_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.json';path.write_text('{"old":true}')
            error=PermissionError('denied');error.winerror=5
            with patch('chat_harness.os',SimpleNamespace(name='nt')),patch.object(Path,'replace',side_effect=error) as replace,patch('chat_harness.time.sleep'):
                with self.assertRaises(PermissionError): atomic_json(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'old':True})
            self.assertEqual(replace.call_count,6)
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])
