from pathlib import Path
from .config import TXT_ENCODING

def parse_document(file_path: Path, ext: str, mineru_output_directory=None) -> str:
    if ext != '.txt':
        raise ValueError('仅支持 UTF-8 TXT 文件')
    return file_path.read_text(encoding=TXT_ENCODING)
