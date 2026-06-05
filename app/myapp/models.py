from django.db import models

from .config import DEEPSEEK_MAX_TOKENS, RAG_PROMPT_TEMPLATE


class RagDatabase(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='数据库名称')
    slug = models.SlugField(max_length=100, unique=True, verbose_name='数据库标识')
    description = models.TextField(blank=True, verbose_name='描述')
    vector_directory = models.CharField(max_length=500, verbose_name='向量库目录')
    bm25_directory = models.CharField(max_length=500, verbose_name='BM25目录')
    upload_directory = models.CharField(max_length=500, verbose_name='上传目录')
    mineru_output_directory = models.CharField(max_length=500, verbose_name='MinerU输出目录')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'RAG数据库'
        verbose_name_plural = 'RAG数据库'

    def __str__(self):
        return self.name


class RagRuntimeConfig(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    current_database = models.ForeignKey(
        RagDatabase,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name='当前使用数据库'
    )
    llm_api_base = models.CharField(max_length=500, blank=True, verbose_name='大语言模型API地址')
    llm_api_key = models.CharField(max_length=500, blank=True, verbose_name='大语言模型API Key')
    dashscope_api_key = models.CharField(max_length=500, blank=True, verbose_name='DashScope API Key')
    rag_prompt_template = models.TextField(default=RAG_PROMPT_TEMPLATE, verbose_name='回答提示词模板')
    deepseek_max_tokens = models.PositiveIntegerField(default=DEEPSEEK_MAX_TOKENS, verbose_name='最大输出Token数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '运行配置'
        verbose_name_plural = '运行配置'

    def __str__(self):
        return 'RAG运行配置'


class RagDocument(models.Model):
    database = models.ForeignKey(
        RagDatabase,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name='所属数据库'
    )
    original_name = models.CharField(max_length=255, verbose_name='原始文件名')
    file_path = models.CharField(max_length=500, verbose_name='文件路径')
    file_ext = models.CharField(max_length=20, verbose_name='文件扩展名')
    chunk_count = models.PositiveIntegerField(default=0, verbose_name='切片数量')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'RAG文档'
        verbose_name_plural = 'RAG文档'

    def __str__(self):
        return self.original_name
