import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_SIZE,
    MSG_FILE_TOO_LARGE,
    MSG_FILE_TYPE_NOT_ALLOWED,
)


def validate_upload_file(upload):
    ext = os.path.splitext(upload.name)[1].lower()

    if upload.size > MAX_UPLOAD_SIZE:
        return False, MSG_FILE_TOO_LARGE, ext

    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return False, MSG_FILE_TYPE_NOT_ALLOWED, ext

    return True, None, ext


def save_upload_file(upload, ext: str, upload_directory=None) -> Path:
    target_directory = upload_directory or settings.UPLOAD_DIRECTORY
    Path(target_directory).mkdir(parents=True, exist_ok=True)
    local_filename = f"{target_directory}/{uuid.uuid4()}{ext}"
    default_storage.save(local_filename, ContentFile(upload.read()))
    return Path(default_storage.path(local_filename))
