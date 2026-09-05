import json
import logging
import re
import shutil
from functools import wraps
from pathlib import Path
from string import Formatter

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
    UPLOAD_FIELD_NAME,
)
from .document_parser import parse_document
from .models import RagDatabase, RagDocument, RagRuntimeConfig
from .rag import rag_manager
from .storage import save_upload_file, validate_upload_file

logger = logging.getLogger(__name__)

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


def _parse_positive_int(value: str):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _prompt_template_is_valid(template: str) -> bool:
    if not template:
        return False
    try:
        fields = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name}
    except ValueError:
        return False
    return fields == {'question', 'context'}


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
    request_id = request.META.get('HTTP_X_REQUEST_ID', '-')
    remote_addr = request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR', '-')

    try:
        body = json.loads(request.body)
        question = body['question']
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning('chat_request_invalid request_id=%s remote=%s body=%r', request_id, remote_addr, request.body[:200])
        return APIResponse(code=1, msg='问题不能为空')

    if not isinstance(question, str) or not question.strip():
        logger.warning('chat_question_empty request_id=%s remote=%s question=%r', request_id, remote_addr, question)
        return APIResponse(code=1, msg='问题不能为空')

    logger.info('chat_request_start request_id=%s remote=%s question=%r', request_id, remote_addr, question[:200])

    try:
        runtime_config = rag_manager.get_runtime_config()
        current_database = runtime_config.current_database
        if current_database is None:
            logger.error('chat_no_current_database request_id=%s runtime_config_id=%s', request_id, runtime_config.id)
            return APIResponse(code=1, msg='未设置当前RAG数据库，请先在后台设置当前数据库')

        logger.info(
            'chat_runtime_config request_id=%s database_id=%s database_slug=%s llm_api_base=%s llm_key_configured=%s dashscope_key_configured=%s',
            request_id,
            current_database.id,
            current_database.slug,
            runtime_config.llm_api_base,
            bool(runtime_config.llm_api_key),
            bool(runtime_config.dashscope_api_key),
        )

        result = rag_manager.query_current(question)
        logger.info('chat_request_success request_id=%s database_id=%s', request_id, current_database.id)
        return APIResponse(code=0, msg=MSG_CHAT_SUCCESS, data=result)
    except Exception as e:
        logger.exception('chat_request_failed request_id=%s remote=%s error=%s', request_id, remote_addr, e)
        error_msg = f'聊天请求处理失败：{e.__class__.__name__}: {e}'
        return APIResponse(code=1, msg=error_msg)



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
        'embedding_model': runtime_config.embedding_model or EMBEDDING_MODEL,
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
        content = parse_document(file_path, ext)
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
    llm_model = request.POST.get('llm_model', '').strip()
    llm_api_key = request.POST.get('llm_api_key', '').strip()
    embedding_api_base = request.POST.get('embedding_api_base', '').strip()
    embedding_api_key = request.POST.get('embedding_api_key', '').strip()
    embedding_model = request.POST.get('embedding_model', '').strip()
    rag_prompt_template = request.POST.get('rag_prompt_template', '').strip()
    max_tokens = _parse_positive_int(request.POST.get('max_tokens', ''))

    if not _prompt_template_is_valid(rag_prompt_template):
        messages.error(request, '回答提示词模板不能为空，并且必须包含 {question} 和 {context}')
        return redirect('/myapp/console/')

    if max_tokens is None:
        messages.error(request, '最大输出Token数必须是正整数')
        return redirect('/myapp/console/')

    runtime_config.llm_api_base = llm_api_base or DEEPSEEK_API_BASE
    runtime_config.llm_model = llm_model
    if llm_api_key:
        runtime_config.llm_api_key = llm_api_key
    if embedding_api_key:
        runtime_config.embedding_api_key = embedding_api_key
    runtime_config.embedding_api_base = embedding_api_base
    runtime_config.embedding_model = embedding_model
    runtime_config.rag_prompt_template = rag_prompt_template
    runtime_config.deepseek_max_tokens = max_tokens
    runtime_config.max_tokens = max_tokens

    runtime_config.save()
    rag_manager.invalidate()

    messages.success(request, '运行配置已保存')
    return redirect('/myapp/console/')
