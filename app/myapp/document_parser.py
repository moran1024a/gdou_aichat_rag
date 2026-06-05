import os
from pathlib import Path
from typing import Any, Dict

from django.conf import settings

from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json
from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env, read_fn
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.enum_class import MakeMode

from .config import (
    MINERU_FORMULA_ENABLE,
    MINERU_LANGUAGES,
    MINERU_MODEL_SOURCE,
    MINERU_PARSE_METHOD,
    MINERU_TABLE_ENABLE,
    TXT_ENCODING,
)


def parse_document(file_path: Path, ext: str, mineru_output_directory=None) -> str:
    if ext == '.pdf':
        return _parse_pdf(file_path, mineru_output_directory=mineru_output_directory)
    if ext == '.txt':
        return _parse_txt(file_path)
    return ''


def _parse_pdf(file_path: Path, mineru_output_directory=None) -> str:
    os.environ['MINERU_MODEL_SOURCE'] = MINERU_MODEL_SOURCE

    output_directory = mineru_output_directory or settings.MINERU_OUTPUT_DIRECTORY
    Path(output_directory).mkdir(parents=True, exist_ok=True)

    pdf_bytes = read_fn(file_path)
    file_name = file_path.stem
    local_image_dir, local_md_dir = prepare_env(output_directory, file_name, MINERU_PARSE_METHOD)

    md_result = _parse_with_pipeline(
        pdf_bytes, file_name,
        local_image_dir, local_md_dir
    )

    return md_result['md_content']


def _parse_txt(file_path: Path) -> str:
    with open(file_path, 'r', encoding=TXT_ENCODING) as f:
        return f.read()


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
        MINERU_LANGUAGES,
        parse_method=MINERU_PARSE_METHOD,
        formula_enable=MINERU_FORMULA_ENABLE,
        table_enable=MINERU_TABLE_ENABLE
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
