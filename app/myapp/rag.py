import os
import re
import json
import threading
from pathlib import Path

from django.conf import settings

from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
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


class SchoolRAG:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ], strip_headers=True)

        self.vectorstore = Chroma(
            persist_directory=settings.RAG_PERSIST_DIRECTORY,
            embedding_function=DashScopeEmbeddings(
                dashscope_api_key=settings.DASHSCOPE_API_KEY,
                model="text-embedding-v4"
            ),
            collection_name="school-rag",
            client_settings=chromadbSettings(
                is_persistent=True,
                persist_directory=settings.RAG_PERSIST_DIRECTORY,
                anonymized_telemetry=False
            )
        )

        self.bm25_docs = self._load_bm25()

        self._build_retriever()

        self._prompt = PromptTemplate(
            template="""你叫零一，是广东海洋大学数学与计算机学院研发的智能机器人，同时也是广东海洋大学智慧海豚团队的科普小助手，专注于中华白海豚及相关海洋知识的科普。

        ## 核心要求  
        **字数限制**：回答必须严格控制在150字以内，优先提供最关键的信息。

        ## 回答规则  
        1. **检索文档有相关内容时**：  
        - 优先依据文档中的准确信息回答  
        - 若用户问题中的名称与文档不一致，以文档为准并自然纠正  
        - 保留文档中的HTTP/HTTPS链接  

        2. **检索文档为空或无关时**：  
        - 使用自身知识简要回答，优先白海豚及海洋科普内容  
        - 无法确定时如实说明  

        ## 表达规范  
        - 直接作答，不提及检索或文档来源  
        - 语言自然简洁，符合科普风格  
        - 中文问答用中文，英文用英文  
        - 内容超限时优先保留：核心科普事实 > 关键数据 > 链接  
        
        ## 问题相关性优先：
        - 仅回答与用户问题直接相关的内容
        - 禁止扩展无关科普
        - 若问题为简单计算/常识题，仅给出答案，可附简短引导后续提问

        ---  
        用户问题: {question}  

        检索文档:  
        {context}  

        请在150字内回答:""",
            input_variables=["context", "question"]
        )

        self.llm = ChatDeepSeek(
            api_base="https://api.deepseek.com",
            api_key=settings.DEEPSEEK_API_KEY,
            model="deepseek-chat",
            temperature=0.8,
            timeout=None,
            max_retries=2,
            max_tokens=1024
        )

    def query(self, question: str):
        if self.retriever is None: return "系统异常"

        docs = self.retriever.get_relevant_documents(question)
        # for i, doc in enumerate(docs, 1):
        #     print(doc)
        #     print("*" * 50)

        context_list = []
        for i, doc in enumerate(docs, 1):
            file_name = doc.metadata.get("file_name", f"未知文档{i}")
            context_list.append(f"文档{i}（{file_name}）内容：\n{doc.page_content}\n")
        context = "\n\n".join(context_list)

        prompt = self._prompt.format(context=context, question=question)

        result = self.llm.predict(prompt)

        return result

    def add_documents(self, content: str, file_path: str, file_name: str) -> list[str]:
        try:
            chunks = self.splitter.split_text(self._clean_markdown_simple(content))
            if not chunks: return []
            # 白海豚语料库没有标题分割，所以修改一点代码让他先能跑
            # if not chunks:
                # chunks = [Document(page_content=content, metadata={})]
                
            #cleaned = self._clean_markdown_simple(content)
            #chunks = self.splitter.split_text(cleaned)
            #if not chunks:
            #    chunks = [Document(page_content=cleaned, metadata={})]

            documents = []
            for chunk in chunks:
                header_parts = []
                if "Header 1" in chunk.metadata:
                    header_parts.append(chunk.metadata["Header 1"])
                if "Header 2" in chunk.metadata:
                    header_parts.append(chunk.metadata["Header 2"])
                if "Header 3" in chunk.metadata:
                    header_parts.append(chunk.metadata["Header 3"])

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

    def _save_bm25(self):
        Path(settings.BM25_PERSIST_DIRECTORY).mkdir(parents=True, exist_ok=True)

        docs_data = [{
            "page_content": d.page_content,
            "metadata": d.metadata
        } for d in self.bm25_docs]

        with open(f"{settings.BM25_PERSIST_DIRECTORY}/docs.json", "w", encoding="utf-8") as f:
            json.dump(docs_data, f, ensure_ascii=False, indent=2)

    def _load_bm25(self):
        Path(settings.BM25_PERSIST_DIRECTORY).mkdir(parents=True, exist_ok=True)

        docs = []
        if os.path.exists(f"{settings.BM25_PERSIST_DIRECTORY}/docs.json"):
            with open(f"{settings.BM25_PERSIST_DIRECTORY}/docs.json", "r", encoding="utf-8") as f:
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
                    dashscope_api_key=settings.DASHSCOPE_API_KEY,
                    model="qwen3-rerank",
                    top_n=3
                ),
                base_retriever=EnsembleRetriever(
                    retrievers=[
                        self.vectorstore.as_retriever(
                            search_type="similarity",
                            search_kwargs={"k": 10}
                        ),
                        BM25Retriever.from_documents(
                            documents=self.bm25_docs,
                            preprocess_func=lambda text: list(jieba.cut(text)),
                            k=10
                        )
                    ],
                    weights=[0.5, 0.5]
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