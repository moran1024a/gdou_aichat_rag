from django.test import TestCase
from .document_parser import parse_document
from .rag import Document, SchoolRAG
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from .models import RagDatabase, RagRuntimeConfig
from .rag import RAGManager

class TxtParserTests(TestCase):
    def test_txt_only(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'a.txt'; p.write_text('校园流程',encoding='utf-8')
            self.assertEqual(parse_document(p,'.txt'),'校园流程')
            with self.assertRaises(ValueError): parse_document(p,'.pdf')

class RrfTests(TestCase):
    def test_duplicate_chunks_are_collapsed(self):
        rag=SchoolRAG.__new__(SchoolRAG)
        a=Document('same',{'chunk_id':'x'}); b=Document('same',{'chunk_id':'x'}); c=Document('other',{'chunk_id':'y'})
        result=rag._rrf([a],[b,c])
        self.assertEqual([x.metadata['chunk_id'] for x in result],['x','y'])

class MultiDatabaseTests(TestCase):
    def setUp(self):
        self.a = RagDatabase.objects.create(name='A', slug='a', vector_directory='/tmp/a-v', bm25_directory='/tmp/a-b', upload_directory='/tmp/a-u', mineru_output_directory='')
        self.b = RagDatabase.objects.create(name='B', slug='b', vector_directory='/tmp/b-v', bm25_directory='/tmp/b-b', upload_directory='/tmp/b-u', mineru_output_directory='')
        self.config = RagRuntimeConfig.objects.first()
        self.config.current_database = self.a
        self.config.save(update_fields=['current_database'])
        self.manager = RAGManager()

    def test_switch_updates_only_future_current_database(self):
        self.manager.switch_current(self.b)
        self.assertEqual(self.manager.get_runtime_config().current_database_id, self.b.id)
        self.assertNotEqual(self.a.id, self.b.id)

    def test_databases_are_independent_records(self):
        self.assertGreaterEqual(RagDatabase.objects.count(), 2)
        self.assertNotEqual(self.a.vector_directory, self.b.vector_directory)
