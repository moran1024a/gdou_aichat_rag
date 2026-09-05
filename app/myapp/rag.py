import hashlib, json, logging, os, threading, urllib.request
from dataclasses import dataclass
from pathlib import Path
import chromadb, jieba
from django.conf import settings
from django.db import IntegrityError, transaction
from rank_bm25 import BM25Okapi
from .config import *
from .models import RagDatabase, RagRuntimeConfig
logger=logging.getLogger(__name__)
@dataclass
class Document:
    page_content:str
    metadata:dict

def _url(base,path): return (base or '').rstrip('/')+path
def _post(url,payload,key,timeout=60):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())
class SchoolRAG:
    def __init__(self,database,config):
        self.database,self.config=database,config; self.lock=threading.RLock()
        self.llm_base=config.llm_api_base or DEEPSEEK_API_BASE; self.llm_key=config.llm_api_key or settings.DEEPSEEK_API_KEY; self.llm_model=getattr(config,'llm_model','') or 'chat-model'
        self.emb_base=config.embedding_api_base or getattr(settings,'EMBEDDING_API_BASE',''); self.emb_key=config.embedding_api_key or getattr(settings,'DASHSCOPE_API_KEY',''); self.emb_model=config.embedding_model or EMBEDDING_MODEL
        if database.index_status == 'ready' and (database.embedding_api_base != self.emb_base or database.embedding_model != self.emb_model): raise RuntimeError('Embedding 配置已变化，请先重建索引')
        Path(database.vector_directory).mkdir(parents=True,exist_ok=True); Path(database.bm25_directory).mkdir(parents=True,exist_ok=True)
        self.client=chromadb.PersistentClient(path=database.vector_directory); self.collection=self.client.get_or_create_collection(CHROMA_COLLECTION_NAME); self.docs=self._load(); self.bm25=BM25Okapi([list(jieba.cut(d.page_content)) for d in self.docs]) if self.docs else None
    def _embed(self,texts):
        if not self.emb_base or not self.emb_key: raise RuntimeError('未配置 Embedding API')
        data=_post(_url(self.emb_base,'/embeddings'),{'model':self.emb_model,'input':texts},self.emb_key,30)
        return [x['embedding'] for x in sorted(data.get('data',[]),key=lambda x:x.get('index',0))]
    def _chat(self,prompt):
        if not self.llm_base or not self.llm_key: raise RuntimeError('未配置 LLM API')
        data=_post(_url(self.llm_base,'/chat/completions'),{'model':self.llm_model,'messages':[{'role':'user','content':prompt}],'temperature':DEEPSEEK_TEMPERATURE,'max_tokens':self.config.max_tokens or DEEPSEEK_MAX_TOKENS},self.llm_key,DEEPSEEK_TIMEOUT or 60)
        return data['choices'][0]['message']['content']
    def query(self,q):
        with self.lock:
            if not self.docs or not self.collection.count(): return '根据现有资料无法确定，当前知识库没有可用依据。'
            vd=self.collection.query(query_embeddings=[self._embed([q])[0]],n_results=VECTOR_SEARCH_K,include=['documents','metadatas'])
            a=[Document(t,m or {}) for t,m in zip(vd['documents'][0],vd['metadatas'][0])]
            b=self.bm25.get_top_n(list(jieba.cut(q)),self.docs,n=BM25_K) if self.bm25 else []
            scores={}; items={}
            for rank,d in enumerate(a+b,1):
                k=d.metadata.get('chunk_id') or hashlib.sha256(d.page_content.encode()).hexdigest(); scores[k]=scores.get(k,0)+1/(60+rank); items[k]=d
            ranked=[items[k] for k,_ in sorted(scores.items(),key=lambda x:x[1],reverse=True)[:4]]
            ctx='\n\n'.join(f"来源：{d.metadata.get('file_name','未知')}#{d.metadata.get('chunk_index','?')}\n{d.page_content}" for d in ranked)
            prompt=(self.config.rag_prompt_template or RAG_PROMPT_TEMPLATE).format(context=ctx,question=q)
            return self._chat(prompt)
    def _rrf(self, a, b):
        scores, items = {}, {}
        for rank, d in enumerate(a + b, 1):
            key = d.metadata.get('chunk_id') or hashlib.sha256(d.page_content.encode()).hexdigest()
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            items[key] = d
        return [items[k] for k, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
    def add_documents(self,content,file_path,file_name):
        text=content.replace('\r\n','\n').strip(); chunks=[]
        for start in range(0,len(text),520):
            piece=text[start:start+600].strip()
            if piece: chunks.append(Document(piece,{'file_name':file_name,'file_path':file_path,'chunk_index':len(chunks)}))
        if not chunks:return []
        for d in chunks:d.metadata['chunk_id']=hashlib.sha256((file_name+str(d.metadata['chunk_index'])+d.page_content).encode()).hexdigest()
        existing=set(self.collection.get(include=[])['ids']); chunks=[d for d in chunks if d.metadata['chunk_id'] not in existing]
        if not chunks:return []
        ids=[d.metadata['chunk_id'] for d in chunks]; self.collection.add(ids=ids,documents=[d.page_content for d in chunks],metadatas=[d.metadata for d in chunks],embeddings=self._embed([d.page_content for d in chunks])); self.docs.extend(chunks); self._save(); self.bm25=BM25Okapi([list(jieba.cut(d.page_content)) for d in self.docs]); self.database.index_status='ready'; self.database.embedding_api_base=self.emb_base; self.database.embedding_model=self.emb_model; self.database.save(update_fields=['index_status','embedding_api_base','embedding_model','updated_at']); return ids
    def _path(self):return Path(self.database.bm25_directory)/'docs.json'
    def _load(self):
        p=self._path()
        if not p.exists():return []
        return [Document(x['page_content'],x.get('metadata',{})) for x in json.loads(p.read_text())]
    def _save(self):
        p=self._path(); t=p.with_suffix('.tmp'); t.write_text(json.dumps([{'page_content':d.page_content,'metadata':d.metadata} for d in self.docs],ensure_ascii=False)); os.replace(t,p)
class RAGManager:
    def __init__(self):self.cache={};self.lock=threading.RLock()
    def get_runtime_config(self):
        c=RagRuntimeConfig.objects.select_related('current_database').first()
        if c:return c
        db=self._get_or_create_default_database()
        try:
            with transaction.atomic():return RagRuntimeConfig.objects.create(singleton_key=1,current_database=db,rag_prompt_template=RAG_PROMPT_TEMPLATE,max_tokens=DEEPSEEK_MAX_TOKENS)
        except IntegrityError:return RagRuntimeConfig.objects.select_related('current_database').first()
    def _get_or_create_default_database(self):
        d=RagDatabase.objects.filter(slug='default').first()
        if d:return d
        return RagDatabase.objects.create(name='默认知识库',slug='default',description='默认知识库',vector_directory=settings.RAG_PERSIST_DIRECTORY,bm25_directory=settings.BM25_PERSIST_DIRECTORY,upload_directory=settings.UPLOAD_DIRECTORY,mineru_output_directory=settings.MINERU_OUTPUT_DIRECTORY)
    def get_rag(self,database,config=None):
        config=config or self.get_runtime_config(); key=(database.id,database.updated_at,config.updated_at)
        with self.lock:
            if key not in self.cache:self.cache={key:SchoolRAG(database,config)}
            return self.cache[key]
    def query_current(self,q):
        c=self.get_runtime_config(); return self.get_rag(c.current_database,c).query(q) if c.current_database else MSG_SYSTEM_ERROR
    def add_documents(self,database,content,file_path,file_name):return self.get_rag(database).add_documents(content,file_path,file_name)
    def invalidate(self,database_id=None):self.cache.clear()
    def switch_current(self,database):
        c=self.get_runtime_config();c.current_database=database;c.save(update_fields=['current_database','updated_at']);self.invalidate()
rag_manager=RAGManager()
