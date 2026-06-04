import os
import json
import uuid
from pathlib import Path
from typing import Dict, Any

from django.conf import settings
from django.shortcuts import render
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env, read_fn
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.enum_class import MakeMode
from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json


from api_r import APIResponse
from .rag import SchoolRAG

schoolRAG = SchoolRAG()

# MinerU解析PDF
def _parse_with_pipeline(
        pdf_bytes: bytes,
        file_name: str,
        local_image_dir: Path,
        local_md_dir: Path
) -> Dict[str, Any]:
    new_pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(
        pdf_bytes, 0, None
    )

    infer_results, all_image_lists, all_pdf_docs, lang_list_out, ocr_enabled_list = pipeline_doc_analyze(
        [new_pdf_bytes],
        ['ch', 'en'],
        parse_method="auto",
        formula_enable=False,
        table_enable=True
    )

    model_list = infer_results[0]
    images_list = all_image_lists[0]
    pdf_doc = all_pdf_docs[0]
    _lang = lang_list_out[0]
    _ocr_enable = ocr_enabled_list[0]

    # 生成 middle_json
    image_writer = FileBasedDataWriter(local_image_dir)
    middle_json = pipeline_result_to_middle_json(
        model_list, images_list, pdf_doc, image_writer,
        _lang, _ocr_enable, False
    )

    pdf_info = middle_json["pdf_info"]
    image_dir = str(os.path.basename(local_image_dir))

    # 生成 markdown
    md_content = pipeline_union_make(pdf_info, MakeMode.MM_MD, image_dir)

    # 保存 markdown
    md_writer = FileBasedDataWriter(local_md_dir)
    md_writer.write_string(f"{file_name}.md", md_content)
    output_md_file = Path(local_md_dir) / f"{file_name}.md"

    return {
        "md_path": str(output_md_file),
        'md_content': md_content,
    }



def chat_view(request):
    return render(request, 'chat.html')

def upload_view(request):
    return render(request, 'upload.html')


@require_POST
@csrf_exempt
def chat(request):
    body = json.loads(request.body)

    question = body['question']

    result = schoolRAG.query(question)

    return APIResponse(code=0, msg="对话成功", data=result)

@require_POST
@csrf_exempt
def upload(request):
    upload = request.FILES.get('file')
    if not upload:
        return APIResponse(code=1, msg='未提供文件')

    max_size = 10 * 1024 * 1024
    if upload.size > max_size:
        return APIResponse(code=1, msg='文件大小不能超过 10MB')

    allowed_extensions = ['.pdf', '.txt']
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in allowed_extensions:
        return APIResponse(code=1, msg='文件类型不允许')

    Path(settings.UPLOAD_DIRECTORY).mkdir(parents=True, exist_ok=True)
    local_filename = f"{settings.UPLOAD_DIRECTORY}/{uuid.uuid4()}{ext}"
    default_storage.save(local_filename, ContentFile(upload.read()))
    file_path = Path(default_storage.path(local_filename))


    if ext in ['.pdf']:
        # 使用MinerU解析
        os.environ['MINERU_MODEL_SOURCE'] = "local"

        Path(settings.MINERU_OUTPUT_DIRECTORY).mkdir(parents=True, exist_ok=True)

        pdf_bytes = read_fn(file_path)

        file_name = file_path.stem
        local_image_dir, local_md_dir = prepare_env(settings.MINERU_OUTPUT_DIRECTORY, file_name, "auto")

        md_result = _parse_with_pipeline(
            pdf_bytes, file_name,
            local_image_dir, local_md_dir
        )

        content = md_result['md_content']
    elif ext == '.txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

    add_result = schoolRAG.add_documents(content, file_path=str(file_path), file_name=upload.name)
    if not add_result:
        return APIResponse(code=1, msg="上传异常")

    return APIResponse(code=0, msg="上传成功")