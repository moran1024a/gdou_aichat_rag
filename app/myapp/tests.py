import json
from unittest.mock import patch

from django.test import SimpleTestCase
from langchain_core.documents import Document

from .config import RERANK_MODEL, RERANK_TOP_N
from .rag import DASHSCOPE_RERANK_ENDPOINT, SchoolRAG


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
