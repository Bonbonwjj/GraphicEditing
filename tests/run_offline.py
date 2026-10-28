"""Run regressions without reading user credentials or contacting model services."""
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import model_config
import chatgpt_auth
from tests.test_model_config import FakeKeyring


def main():
    with ExitStack() as stack:
        directory=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='plot-offline-tests-')))
        stack.enter_context(patch.object(model_config,'CONFIG_PATH',directory/'settings.json'))
        stack.enter_context(patch.object(model_config,'keyring',FakeKeyring()))
        stack.enter_context(patch.object(model_config,'_session_secret',None))
        stack.enter_context(patch.object(chatgpt_auth,'keyring',FakeKeyring()))
        stack.enter_context(patch.object(chatgpt_auth,'_vault',return_value=FakeKeyring()))
        stack.enter_context(patch.object(chatgpt_auth,'_record',{}))
        stack.enter_context(patch.dict(os.environ,{key:'' for key in ('OPENAI_API_KEY','LLM_API_KEY','LLM_API_URL','LLM_MODEL','CHAT_AGENT_URL','NORMALIZER_AGENT_URL')}))
        original=socket.socket.connect
        def local_only(sock,address):
            if sock.family in (socket.AF_INET,socket.AF_INET6) and address[0] not in ('127.0.0.1','::1','localhost'):
                raise RuntimeError('Offline test blocked external network access')
            return original(sock,address)
        stack.enter_context(patch.object(socket.socket,'connect',local_only))
        suite=(unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:]) if sys.argv[1:] else
               unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py'))
        # Preserve and run the two pre-existing pytest-style standardizer tests
        # without adding a pytest runtime dependency to the application.
        import tests.test_project_standardizer as standardizer
        for name in ([] if sys.argv[1:] else dir(standardizer)):
            if name.startswith('test_'):
                def invoke(function=getattr(standardizer,name)):
                    with tempfile.TemporaryDirectory(prefix='plot-legacy-test-') as temp:
                        function(Path(temp))
                suite.addTest(unittest.FunctionTestCase(invoke,description=name))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
