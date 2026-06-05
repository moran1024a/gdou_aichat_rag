import json
import re
import shutil
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from api_r import APIResponse
from .config import (
    DEEPSEEK_API_BASE,
    EMBEDDING_MODEL,
    MSG_CHAT_SUCCESS,
    MSG_NO_FILE,
    MSG_UPLOAD_ERROR,
    RERANK_MODEL,
    UPLOAD_FIELD_NAME,
)
from .document_parser import parse_document
from .models import RagDatabase, RagDocument, RagRuntimeConfig
from .rag import rag_manager
from .storage import save_upload_file, validate_upload_file

ADMIN_SESSION_KEY = 'rag_admin_logged_in'
SLUG_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


def _get_runtime_config():
    return rag_manager.get_runtime_config()


def _create_default_database():
    return rag_manager._get_or_create_default_database()


def _database_paths(slug: str):
    base_dir = Path(settings.RAG_DATABASE_ROOT) / slug
    return {
        'vector_directory': str(base_dir / 'chroma_db'),
        'bm25_directory': str(base_dir / 'bm25'),
        'upload_directory': str(base_dir / 'uploads'),
        'mineru_output_directory': str(base_dir / 'mineru_output'),
    }


def _ensure_database_directories(database: RagDatabase):
    Path(database.vector_directory).mkdir(parents=True, exist_ok=True)
    Path(database.bm25_directory).mkdir(parents=True, exist_ok=True)
    Path(database.upload_directory).mkdir(parents=True, exist_ok=True)
    Path(database.mineru_output_directory).mkdir(parents=True, exist_ok=True)


def _mask_key(value: str) -> str:
    if not value:
        return '未配置'
    if len(value) <= 8:
        return '已配置'
    return f'{value[:4]}****{value[-4:]}'


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get(ADMIN_SESSION_KEY):
            return redirect('/myapp/console/login/')
        return view_func(request, *args, **kwargs)
    return wrapper


def chat_view(request):
    return render(request, 'chat.html')


@require_POST
@csrf_exempt
def chat(request):
    try:
        body = json.loads(request.body)
        question = body['question']
    except (json.JSONDecodeError, KeyError, TypeError):
        return APIResponse(code=1, msg='问题不能为空')

    result = rag_manager.query_current(question)

    return APIResponse(code=0, msg=MSG_CHAT_SUCCESS, data=result)



@require_GET
def console_login(request):
    if request.session.get(ADMIN_SESSION_KEY):
        return redirect('/myapp/console/')
    return render(request, 'console_login.html')


@require_POST
def console_login_submit(request):
    username = request.POST.get('username', '')
    password = request.POST.get('password', '')

    if not settings.RAG_ADMIN_PASSWORD:
        messages.error(request, '后台密码未配置，请先设置 RAG_ADMIN_PASSWORD')
        return redirect('/myapp/console/login/')

    if username == settings.RAG_ADMIN_USERNAME and password == settings.RAG_ADMIN_PASSWORD:
        request.session[ADMIN_SESSION_KEY] = True
        messages.success(request, '登录成功')
        return redirect('/myapp/console/')

    messages.error(request, '账号或密码错误')
    return redirect('/myapp/console/login/')


@admin_required
def console_logout(request):
    request.session.pop(ADMIN_SESSION_KEY, None)
    messages.success(request, '已退出登录')
    return redirect('/myapp/console/login/')


@admin_required
def console_dashboard(request):
    runtime_config = _get_runtime_config()
    databases = RagDatabase.objects.annotate(document_count=Count('documents'))

    context = {
        'runtime_config': runtime_config,
        'databases': databases,
        'embedding_model': EMBEDDING_MODEL,
        'rerank_model': RERANK_MODEL,
        'llm_api_key_masked': _mask_key(runtime_config.llm_api_key),
        'dashscope_api_key_masked': _mask_key(runtime_config.dashscope_api_key),
    }
    return render(request, 'console_dashboard.html', context)


@require_POST
@admin_required
def console_create_database(request):
    name = request.POST.get('name', '').strip()
    slug = request.POST.get('slug', '').strip()
    description = request.POST.get('description', '').strip()

    if not name or not slug:
        messages.error(request, '数据库名称和标识不能为空')
        return redirect('/myapp/console/')

    if not SLUG_PATTERN.fullmatch(slug):
        messages.error(request, '数据库标识只能包含字母、数字、下划线和短横线')
        return redirect('/myapp/console/')

    if RagDatabase.objects.filter(name=name).exists():
        messages.error(request, '数据库名称已存在')
        return redirect('/myapp/console/')

    if RagDatabase.objects.filter(slug=slug).exists():
        messages.error(request, '数据库标识已存在')
        return redirect('/myapp/console/')

    paths = _database_paths(slug)
    database = RagDatabase.objects.create(
        name=name,
        slug=slug,
        description=description,
        **paths,
    )
    _ensure_database_directories(database)

    runtime_config = _get_runtime_config()
    if runtime_config.current_database is None:
        rag_manager.switch_current(database)

    messages.success(request, '数据库创建成功')
    return redirect('/myapp/console/')


@require_POST
@admin_required
def console_upload_document(request, db_id):
    database = get_object_or_404(RagDatabase, id=db_id)
    result = _upload_to_database(request, database)
    if result is not None:
        return result
    return redirect('/myapp/console/')


def _upload_to_database(request, database: RagDatabase):
    upload = request.FILES.get(UPLOAD_FIELD_NAME)
    if not upload:
        messages.error(request, MSG_NO_FILE)
        return redirect('/myapp/console/')

    is_valid, error_msg, ext = validate_upload_file(upload)
    if not is_valid:
        messages.error(request, error_msg)
        return redirect('/myapp/console/')

    _ensure_database_directories(database)
    file_path = save_upload_file(upload, ext, upload_directory=database.upload_directory)
    try:
        content = parse_document(file_path, ext, mineru_output_directory=database.mineru_output_directory)
        add_result = rag_manager.add_documents(database, content, file_path=str(file_path), file_name=upload.name)
    except Exception as e:
        print(e)
        messages.error(request, MSG_UPLOAD_ERROR)
        return redirect('/myapp/console/')

    if not add_result:
        messages.error(request, MSG_UPLOAD_ERROR)
        return redirect('/myapp/console/')

    RagDocument.objects.create(
        database=database,
        original_name=upload.name,
        file_path=str(file_path),
        file_ext=ext,
        chunk_count=len(add_result),
    )

    messages.success(request, f'上传成功，写入 {len(add_result)} 个片段')
    return None


@require_POST
@admin_required
def console_activate_database(request, db_id):
    database = get_object_or_404(RagDatabase, id=db_id)
    rag_manager.switch_current(database)
    messages.success(request, f'已切换当前数据库：{database.name}')
    return redirect('/myapp/console/')


@require_POST
@admin_required
def console_delete_database(request, db_id):
    database = get_object_or_404(RagDatabase, id=db_id)
    runtime_config = _get_runtime_config()

    if runtime_config.current_database_id == database.id:
        messages.error(request, '不能删除当前正在使用的数据库')
        return redirect('/myapp/console/')

    if RagDatabase.objects.count() <= 1:
        messages.error(request, '不能删除最后一个数据库')
        return redirect('/myapp/console/')

    if database.slug == 'default':
        messages.error(request, '默认兼容数据库不能删除')
        return redirect('/myapp/console/')

    rag_manager.invalidate(database.id)
    _delete_database_files(database)
    database.delete()

    messages.success(request, '数据库已删除')
    return redirect('/myapp/console/')


def _delete_database_files(database: RagDatabase):
    root = Path(settings.RAG_DATABASE_ROOT).resolve()
    for directory in [
        database.vector_directory,
        database.bm25_directory,
        database.upload_directory,
        database.mineru_output_directory,
    ]:
        path = Path(directory).resolve()
        if root in path.parents or path == root:
            shutil.rmtree(path, ignore_errors=True)

    database_root = root / database.slug
    if database_root.exists():
        shutil.rmtree(database_root, ignore_errors=True)


@require_POST
@admin_required
def console_update_runtime_config(request):
    runtime_config = _get_runtime_config()

    llm_api_base = request.POST.get('llm_api_base', '').strip()
    llm_api_key = request.POST.get('llm_api_key', '').strip()
    dashscope_api_key = request.POST.get('dashscope_api_key', '').strip()

    runtime_config.llm_api_base = llm_api_base or DEEPSEEK_API_BASE
    if llm_api_key:
        runtime_config.llm_api_key = llm_api_key
    if dashscope_api_key:
        runtime_config.dashscope_api_key = dashscope_api_key

    runtime_config.save()
    rag_manager.invalidate()

    messages.success(request, '运行配置已保存')
    return redirect('/myapp/console/')
