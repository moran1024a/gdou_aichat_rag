import os
import re
import json
import threading
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction

from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.document_compressors.dashscope_rerank import DashScopeRerank

from chromadb.config import Settings as chromadbSettings
from langchain_chroma import Chroma

from langchain.text_splitter import (
    MarkdownHeaderTextSplitter
)

from langchain_deepseek import ChatDeepSeek

import jieba

from .config import (
    BM25_K,
    CHROMA_COLLECTION_NAME,
    DEEPSEEK_API_BASE,
    DEEPSEEK_MAX_RETRIES,
    DEEPSEEK_MAX_TOKENS,
    DEEPSEEK_MODEL,
    DEEPSEEK_TEMPERATURE,
    DEEPSEEK_TIMEOUT,
    EMBEDDING_MODEL,
    ENSEMBLE_WEIGHTS,
    MSG_SYSTEM_ERROR,
    RAG_PROMPT_TEMPLATE,
    RERANK_MODEL,
    RERANK_TOP_N,
    VECTOR_SEARCH_K,
    VECTOR_SEARCH_TYPE,
)
from .models import RagDatabase, RagRuntimeConfig


class SchoolRAG:
    def __init__(self, database: RagDatabase, runtime_config: RagRuntimeConfig):
        self.database = database
        self.runtime_config = runtime_config
        self.vector_directory = database.vector_directory
        self.bm25_directory = database.bm25_directory
        self.dashscope_api_key = runtime_config.dashscope_api_key or settings.DASHSCOPE_API_KEY
        self.llm_api_base = runtime_config.llm_api_base or DEEPSEEK_API_BASE
        self.llm_api_key = runtime_config.llm_api_key or settings.DEEPSEEK_API_KEY
        self._lock = threading.RLock()

        self.splitter = self._create_splitter()
        self.vectorstore = self._create_vectorstore()

        self.bm25_docs = self._load_bm25()

        self._build_retriever()

        self._prompt = self._create_prompt()
        self.llm = self._create_llm()

    def query(self, question: str):
        with self._lock:
            if self.retriever is None: return MSG_SYSTEM_ERROR

            docs = self.retriever.get_relevant_documents(question)
            # for i, doc in enumerate(docs, 1):
            #     print(doc)
            #     print("*" * 50)

            context = self._format_context(docs)
            prompt = self._prompt.format(context=context, question=question)

            result = self.llm.predict(prompt)

            return result

    def add_documents(self, content: str, file_path: str, file_name: str) -> list[str]:
        with self._lock:
            try:
                chunks = self.splitter.split_text(self._clean_markdown_simple(content))
                if not chunks: return []

                documents = self._build_documents(chunks, file_path, file_name)

                batch_size = 10
                all_ids = []
                for i in range(0, len(documents), batch_size):
                    batch = documents[i:i + batch_size]
                    ids = self.vectorstore.add_documents(batch)
                    all_ids.extend(ids)

                self.bm25_docs.extend(documents)
                self._save_bm25()
                self._build_retriever()

                return all_ids
            except Exception as e:
                print(e)
                print("添加异常了")
                return []
                #raise e

    def _create_splitter(self):
        return MarkdownHeaderTextSplitter(headers_to_split_on=[
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ], strip_headers=True)

    def _create_vectorstore(self):
        Path(self.vector_directory).mkdir(parents=True, exist_ok=True)
        return Chroma(
            persist_directory=self.vector_directory,
            embedding_function=DashScopeEmbeddings(
                dashscope_api_key=self.dashscope_api_key,
                model=EMBEDDING_MODEL
            ),
            collection_name=CHROMA_COLLECTION_NAME,
            client_settings=chromadbSettings(
                is_persistent=True,
                persist_directory=self.vector_directory,
                anonymized_telemetry=False
            )
        )

    def _create_prompt(self):
        return PromptTemplate(
            template=RAG_PROMPT_TEMPLATE,
            input_variables=["context", "question"]
        )

    def _create_llm(self):
        return ChatDeepSeek(
            api_base=self.llm_api_base,
            api_key=self.llm_api_key,
            model=DEEPSEEK_MODEL,
            temperature=DEEPSEEK_TEMPERATURE,
            timeout=DEEPSEEK_TIMEOUT,
            max_retries=DEEPSEEK_MAX_RETRIES,
            max_tokens=DEEPSEEK_MAX_TOKENS
        )

    def _format_context(self, docs):
        context_list = []
        for i, doc in enumerate(docs, 1):
            file_name = doc.metadata.get("file_name", f"未知文档{i}")
            context_list.append(f"文档{i}（{file_name}）内容：\n{doc.page_content}\n")
        return "\n\n".join(context_list)

    def _build_documents(self, chunks, file_path: str, file_name: str):
        documents = []
        for chunk in chunks:
            header_parts = []
            for header_name in ["Header 1", "Header 2", "Header 3"]:
                if header_name in chunk.metadata:
                    header_parts.append(chunk.metadata[header_name])

            header_path = " > ".join(header_parts) if header_parts else ""
            new_content = f"{header_path}\n\n{chunk.page_content}" if header_path else chunk.page_content

            document = Document(
                page_content=new_content,
                metadata={
                    "file_path": file_path,
                    "file_name": file_name
                }
            )
            documents.append(document)

        return documents

    def _bm25_docs_path(self):
        return Path(self.bm25_directory) / "docs.json"

    def _save_bm25(self):
        Path(self.bm25_directory).mkdir(parents=True, exist_ok=True)

        docs_data = [{
            "page_content": d.page_content,
            "metadata": d.metadata
        } for d in self.bm25_docs]

        with open(self._bm25_docs_path(), "w", encoding="utf-8") as f:
            json.dump(docs_data, f, ensure_ascii=False, indent=2)

    def _load_bm25(self):
        Path(self.bm25_directory).mkdir(parents=True, exist_ok=True)

        docs = []
        bm25_docs_path = self._bm25_docs_path()
        if os.path.exists(bm25_docs_path):
            with open(bm25_docs_path, "r", encoding="utf-8") as f:
                docs_data = json.load(f)
            docs = [
                Document(page_content=d["page_content"], metadata=d.get("metadata", {}))
                for d in docs_data
            ]

        return docs

    def _build_retriever(self):
        if self.bm25_docs:
            self.retriever = ContextualCompressionRetriever(
                base_compressor=DashScopeRerank(
                    dashscope_api_key=self.dashscope_api_key,
                    model=RERANK_MODEL,
                    top_n=RERANK_TOP_N
                ),
                base_retriever=EnsembleRetriever(
                    retrievers=[
                        self.vectorstore.as_retriever(
                            search_type=VECTOR_SEARCH_TYPE,
                            search_kwargs={"k": VECTOR_SEARCH_K}
                        ),
                        BM25Retriever.from_documents(
                            documents=self.bm25_docs,
                            preprocess_func=lambda text: list(jieba.cut(text)),
                            k=BM25_K
                        )
                    ],
                    weights=ENSEMBLE_WEIGHTS
                )
            )
        else:
            self.retriever = None

    def _clean_markdown_simple(self, md_text: str) -> str:
        """
        清理 Markdown 文本：
        - 移除图片 (![...](...) 格式)
        - 移除代码块 (``` 包裹的内容)
        - 合并多余空行
        """
        if not md_text:
            return md_text

        # 移除图片链接 (包括 ![alt](url) 和 ![](url) 格式)
        md_text = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', '', md_text)

        # 移除代码块
        lines = md_text.split('\n')
        cleaned_lines = []
        in_code_block = False

        for line in lines:
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            if line.strip() == '':
                if cleaned_lines and cleaned_lines[-1].strip() == '':
                    continue

            cleaned_lines.append(line)
        return '\n'.join(cleaned_lines).strip()


class RAGManager:
    def __init__(self):
        self._cache = {}
        self._lock = threading.RLock()

    def query_current(self, question: str) -> str:
        runtime_config = self.get_runtime_config()
        if runtime_config.current_database is None:
            return MSG_SYSTEM_ERROR
        return self.get_rag(runtime_config.current_database, runtime_config).query(question)

    def add_documents(self, database: RagDatabase, content: str, file_path: str, file_name: str) -> list[str]:
        runtime_config = self.get_runtime_config()
        return self.get_rag(database, runtime_config).add_documents(content, file_path, file_name)

    def get_rag(self, database: RagDatabase, runtime_config: RagRuntimeConfig = None) -> SchoolRAG:
        runtime_config = runtime_config or self.get_runtime_config()
        cache_key = database.id
        cache_version = (database.updated_at, runtime_config.updated_at)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached_version, rag = cached
                if cached_version == cache_version:
                    return rag

            rag = SchoolRAG(database, runtime_config)
            self._cache[cache_key] = (cache_version, rag)
            return rag

    def invalidate(self, database_id=None):
        with self._lock:
            if database_id is None:
                self._cache.clear()
            else:
                self._cache.pop(database_id, None)

    def switch_current(self, database: RagDatabase):
        runtime_config = self.get_runtime_config()
        runtime_config.current_database = database
        runtime_config.save(update_fields=['current_database', 'updated_at'])
        self.invalidate()

    def get_runtime_config(self):
        runtime_config = RagRuntimeConfig.objects.select_related('current_database').order_by('id').first()
        if runtime_config is not None:
            return runtime_config

        with self._lock:
            runtime_config = RagRuntimeConfig.objects.select_related('current_database').order_by('id').first()
            if runtime_config is not None:
                return runtime_config

            default_database = self._get_or_create_default_database()
            try:
                with transaction.atomic():
                    return RagRuntimeConfig.objects.create(
                        singleton_key=1,
                        current_database=default_database,
                        llm_api_base=DEEPSEEK_API_BASE,
                        llm_api_key=settings.DEEPSEEK_API_KEY,
                        dashscope_api_key=settings.DASHSCOPE_API_KEY,
                    )
            except IntegrityError:
                return RagRuntimeConfig.objects.select_related('current_database').order_by('id').first()

    def _get_or_create_default_database(self):
        database = RagDatabase.objects.filter(slug='default').first()
        if database is not None:
            return database

        try:
            with transaction.atomic():
                return RagDatabase.objects.create(
                    name='默认知识库',
                    slug='default',
                    description='兼容原始单库版本的默认RAG数据库',
                    vector_directory=settings.RAG_PERSIST_DIRECTORY,
                    bm25_directory=settings.BM25_PERSIST_DIRECTORY,
                    upload_directory=settings.UPLOAD_DIRECTORY,
                    mineru_output_directory=settings.MINERU_OUTPUT_DIRECTORY,
                )
        except IntegrityError:
            return RagDatabase.objects.get(slug='default')


rag_manager = RAGManager()
