import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase, TestCase
from langchain_core.documents import Document

from .config import DEEPSEEK_MAX_TOKENS, RERANK_MODEL, RERANK_TOP_N
from .models import RagDatabase, RagRuntimeConfig
from .rag import DASHSCOPE_RERANK_ENDPOINT, SchoolRAG
from .views import ADMIN_SESSION_KEY, console_update_runtime_config


class _Database:
    id = 123


class _DashScopeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class DirectDashScopeRerankTests(SimpleTestCase):
    def _rag(self, api_key='test-key'):
        rag = SchoolRAG.__new__(SchoolRAG)
        rag.database = _Database()
        rag.dashscope_api_key = api_key
        rag.llm_api_base = 'https://api.deepseek.com'
        rag.llm_api_key = 'test-key'
        rag.runtime_config = SimpleNamespace(
            rag_prompt_template='Context: {context}\nQuestion: {question}',
            deepseek_max_tokens=256,
        )
        return rag

    @patch('myapp.rag.urllib.request.urlopen')
    def test_rerank_posts_to_dashscope_and_returns_ranked_documents(self, urlopen):
        urlopen.return_value = _DashScopeResponse({
            'output': {
                'results': [
                    {'index': 2, 'relevance_score': 0.91},
                    {'index': 0, 'relevance_score': 0.73},
                ]
            }
        })
        docs = [
            Document(page_content='first'),
            Document(page_content='second'),
            Document(page_content='third'),
        ]

        result = self._rag()._rerank_documents('query text', docs)

        self.assertEqual([doc.page_content for doc in result], ['third', 'first'])
        self.assertEqual(result[0].metadata['rerank_score'], 0.91)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, DASHSCOPE_RERANK_ENDPOINT)
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(payload['model'], RERANK_MODEL)
        self.assertEqual(payload['input']['query'], 'query text')
        self.assertEqual(payload['input']['documents'], ['first', 'second', 'third'])
        self.assertEqual(payload['parameters']['top_n'], min(RERANK_TOP_N, len(docs)))
        self.assertFalse(payload['parameters']['return_documents'])

    @patch('myapp.rag.urllib.request.urlopen')
    def test_rerank_without_api_key_falls_back_without_http_call(self, urlopen):
        docs = [Document(page_content=str(i)) for i in range(RERANK_TOP_N + 2)]

        result = self._rag(api_key='')._rerank_documents('query text', docs)

        self.assertEqual(result, docs[:RERANK_TOP_N])
        urlopen.assert_not_called()

    @patch('myapp.rag.ChatDeepSeek')
    def test_create_llm_uses_runtime_max_tokens(self, chat_deepseek):
        self._rag()._create_llm()

        self.assertEqual(chat_deepseek.call_args.kwargs['max_tokens'], 256)

    def test_create_prompt_uses_runtime_template(self):
        prompt = self._rag()._create_prompt()

        self.assertEqual(prompt.template, 'Context: {context}\nQuestion: {question}')


class RuntimeConfigConsoleTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.database = RagDatabase.objects.get(slug='default')
        self.runtime_config = RagRuntimeConfig.objects.get(singleton_key=1)
        self.runtime_config.current_database = self.database
        self.runtime_config.llm_api_base = 'https://api.deepseek.com'
        self.runtime_config.rag_prompt_template = 'old {context} {question}'
        self.runtime_config.deepseek_max_tokens = DEEPSEEK_MAX_TOKENS
        self.runtime_config.save()

    def _request(self, data):
        request = self.factory.post('/myapp/console/settings/', data=data)
        SessionMiddleware(lambda req: None).process_request(request)
        request.session[ADMIN_SESSION_KEY] = True
        request.session.save()
        request._messages = FallbackStorage(request)
        return request

    @patch('myapp.views.rag_manager.invalidate')
    def test_update_runtime_config_saves_prompt_and_max_tokens(self, invalidate):
        response = console_update_runtime_config(self._request({
            'llm_api_base': 'https://example.test',
            'llm_api_key': '',
            'dashscope_api_key': '',
            'rag_prompt_template': 'new prompt {context} {question}',
            'deepseek_max_tokens': '2048',
        }))

        self.assertEqual(response.status_code, 302)
        self.runtime_config.refresh_from_db()
        self.assertEqual(self.runtime_config.llm_api_base, 'https://example.test')
        self.assertEqual(self.runtime_config.rag_prompt_template, 'new prompt {context} {question}')
        self.assertEqual(self.runtime_config.deepseek_max_tokens, 2048)
        invalidate.assert_called_once()

    @patch('myapp.views.rag_manager.invalidate')
    def test_update_runtime_config_rejects_prompt_without_required_variables(self, invalidate):
        response = console_update_runtime_config(self._request({
            'llm_api_base': 'https://example.test',
            'llm_api_key': '',
            'dashscope_api_key': '',
            'rag_prompt_template': 'missing variables',
            'deepseek_max_tokens': '2048',
        }))

        self.assertEqual(response.status_code, 302)
        self.runtime_config.refresh_from_db()
        self.assertEqual(self.runtime_config.rag_prompt_template, 'old {context} {question}')
        self.assertEqual(self.runtime_config.deepseek_max_tokens, DEEPSEEK_MAX_TOKENS)
        invalidate.assert_not_called()
