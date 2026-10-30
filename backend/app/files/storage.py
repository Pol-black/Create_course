import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.errors import AppError
from app.models import FileType

# Какие файлы принимаем
EXTENSIONS: dict[str, FileType] = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".txt": FileType.TXT,
}

HINT_OLD_DOC = (
    "Старый формат .doc не поддерживается. "
    "Откройте файл в Word и сохраните как .docx"
)


class UnsupportedFileType(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400, code="unsupported_file_type")


class FileTooLarge(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=413, code="payload_too_large")


@dataclass
class SavedFile:
    """Куда легло, сколько весит, какого типа"""
    path: Path
    size: int
    file_type: FileType


def detect_file_type(file_name: str) -> FileType:
    """Определить тип по расширению имени файла"""
    suffix = Path(file_name).suffix.lower()
    if suffix == ".doc":
        raise UnsupportedFileType(HINT_OLD_DOC)
    file_type = EXTENSIONS.get(suffix)
    if file_type is None:
        raise UnsupportedFileType(
            f"Формат {suffix or 'без расширения'} не поддерживается. "
            "Принимаем PDF, DOCX и TXT"
        )
    return file_type


def save_upload(upload: UploadFile) -> SavedFile:
    file_name = upload.filename or ""
    file_type = detect_file_type(file_name)

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = settings.upload_dir / f"{uuid.uuid4().hex}{Path(file_name).suffix.lower()}"

    limit = settings.max_upload_bytes
    size = 0
    chunk_size = 1024 * 1024  # 1 МБ

    try:
        with target.open("wb") as out:
            while chunk := upload.file.read(chunk_size):
                size += len(chunk)
                if size > limit:
                    raise FileTooLarge(
                        f"Файл больше {settings.max_upload_mb} МБ. "
                        "Разделите документ на части"
                    )
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    if size == 0:
        target.unlink(missing_ok=True)
        raise UnsupportedFileType("Файл пустой")

    return SavedFile(path=target, size=size, file_type=file_type)


def delete_file(path: str | Path | None) -> None:
    """Удалить файл документа с диска"""
    if path:
        Path(path).unlink(missing_ok=True)


def free_space_mb() -> int:
    """Сколько мегабайт свободно в папке загрузок"""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(settings.upload_dir).free // (1024 * 1024)