import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import llm


class LocalLLMConfigurationTestCase(unittest.TestCase):
    def test_local_service_accepts_url_and_model_without_api_key(self):
        opt = SimpleNamespace(
            llm_provider='local',
            llm_base_url='http://127.0.0.1:8000/v1',
            llm_model='my-qwen-model',
        )
        with patch.dict(os.environ, {'LOCAL_LLM_API_KEY': ''}):
            self.assertIsNone(llm.configuration_error(opt))
            client = llm._llm_client(opt)
        self.assertEqual(str(client.base_url), 'http://127.0.0.1:8000/v1/')
        self.assertEqual(client.api_key, 'EMPTY')
        client.close()

    def test_local_service_requires_url_and_model(self):
        opt = SimpleNamespace(llm_provider='local', llm_base_url='', llm_model='')
        self.assertIn('llm_base_url', llm.configuration_error(opt))
        opt.llm_base_url = 'http://127.0.0.1:8000/v1'
        self.assertIn('llm_model', llm.configuration_error(opt))

    def test_cloud_service_still_requires_its_api_key(self):
        opt = SimpleNamespace(llm_provider='dashscope', llm_model='')
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': ''}):
            self.assertIn('DASHSCOPE_API_KEY', llm.configuration_error(opt))

    def test_local_stream_does_not_send_optional_usage_options(self):
        opt = SimpleNamespace(llm_provider='local', llm_base_url='http://127.0.0.1:8000/v1', llm_model='my-qwen-model')
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='你好。'))])
        create = Mock(return_value=iter([chunk]))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        spoken = []
        avatar = SimpleNamespace(opt=opt, put_msg_txt=lambda text, _: spoken.append(text))
        with patch.object(llm, '_llm_client', return_value=client):
            llm.llm_response('你好', avatar)
        self.assertNotIn('stream_options', create.call_args.kwargs)
        self.assertEqual(spoken, ['你好。'])


if __name__ == '__main__':
    unittest.main()
