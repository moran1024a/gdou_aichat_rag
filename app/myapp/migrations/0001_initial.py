from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_default_runtime(apps, schema_editor):
    RagDatabase = apps.get_model('myapp', 'RagDatabase')
    RagRuntimeConfig = apps.get_model('myapp', 'RagRuntimeConfig')

    default_db, _ = RagDatabase.objects.get_or_create(
        slug='default',
        defaults={
            'name': '默认知识库',
            'description': '兼容原始单库版本的默认RAG数据库',
            'vector_directory': settings.RAG_PERSIST_DIRECTORY,
            'bm25_directory': settings.BM25_PERSIST_DIRECTORY,
            'upload_directory': settings.UPLOAD_DIRECTORY,
            'mineru_output_directory': settings.MINERU_OUTPUT_DIRECTORY,
        }
    )

    if not RagRuntimeConfig.objects.exists():
        RagRuntimeConfig.objects.create(
            singleton_key=1,
            current_database=default_db,
            llm_api_base='https://api.deepseek.com',
            llm_api_key=settings.DEEPSEEK_API_KEY,
            dashscope_api_key=settings.DASHSCOPE_API_KEY,
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='RagDatabase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='数据库名称')),
                ('slug', models.SlugField(max_length=100, unique=True, verbose_name='数据库标识')),
                ('description', models.TextField(blank=True, verbose_name='描述')),
                ('vector_directory', models.CharField(max_length=500, verbose_name='向量库目录')),
                ('bm25_directory', models.CharField(max_length=500, verbose_name='BM25目录')),
                ('upload_directory', models.CharField(max_length=500, verbose_name='上传目录')),
                ('mineru_output_directory', models.CharField(max_length=500, verbose_name='MinerU输出目录')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': 'RAG数据库',
                'verbose_name_plural': 'RAG数据库',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='RagRuntimeConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_key', models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ('llm_api_base', models.CharField(blank=True, max_length=500, verbose_name='大语言模型API地址')),
                ('llm_api_key', models.CharField(blank=True, max_length=500, verbose_name='大语言模型API Key')),
                ('dashscope_api_key', models.CharField(blank=True, max_length=500, verbose_name='DashScope API Key')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('current_database', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='myapp.ragdatabase', verbose_name='当前使用数据库')),
            ],
            options={
                'verbose_name': '运行配置',
                'verbose_name_plural': '运行配置',
            },
        ),
        migrations.CreateModel(
            name='RagDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_name', models.CharField(max_length=255, verbose_name='原始文件名')),
                ('file_path', models.CharField(max_length=500, verbose_name='文件路径')),
                ('file_ext', models.CharField(max_length=20, verbose_name='文件扩展名')),
                ('chunk_count', models.PositiveIntegerField(default=0, verbose_name='切片数量')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('database', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='myapp.ragdatabase', verbose_name='所属数据库')),
            ],
            options={
                'verbose_name': 'RAG文档',
                'verbose_name_plural': 'RAG文档',
                'ordering': ['-created_at'],
            },
        ),
        migrations.RunPython(create_default_runtime, migrations.RunPython.noop),
    ]
