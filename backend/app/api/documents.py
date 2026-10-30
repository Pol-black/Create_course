import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.files import extract_text, save_upload
from app.files.storage import delete_file
from app.journal.processing_log import log_stage, write_log
from app.models import Document, DocumentStatus

logger = logging.getLogger("app.documents")

router = APIRouter(tags=["documents"], prefix="/documents")

class DocumentOut(BaseModel):
    id: int
    file_name: str
    file_type: str | None
    file_size: int | None
    status: str
    error_message: str | None
    text_length: int
    created_at: str

    @classmethod
    def of(cls, doc: Document) -> "DocumentOut":
        return cls(
            id=doc.id,
            file_name=doc.file_name,
            file_type=doc.file_type.value if doc.file_type else None,
            file_size=doc.file_size,
            status=doc.status.value,
            error_message=doc.error_message,
            text_length=len(doc.extracted_text or ""),
            created_at=doc.created_at.isoformat(),
        )


class DocumentTextOut(BaseModel):
    id: int
    text: str
    text_length: int


# Загрузка

@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile = File(..., description="PDF, DOCX или TXT"),
    check_enabled: bool = Query(True, description="Проверять курс на соответствие документу"),
    session: Session = Depends(get_db),
) -> DocumentOut:
    # Сохраняем файл на диск. Здесь же проверяются формат и размер
    saved = save_upload(file)

    # Запись в БД
    doc = Document(
        file_name=Path(file.filename or "без имени").name,
        file_type=saved.file_type,
        file_size=saved.size,
        file_path=str(saved.path),
        status=DocumentStatus.UPLOADED,
        check_enabled=check_enabled,
    )
    session.add(doc)
    session.commit()

    doc_id = doc.id

    write_log(doc_id, "upload", f"Файл загружен: {doc.file_name} ({saved.size} байт)")

    # Извлечение текста
    doc.status = DocumentStatus.PROCESSING
    session.commit()

    try:
        with log_stage(doc_id, "extract", "Извлечение текста"):
            text = extract_text(saved.path, saved.file_type)
    except AppError as exc:
        # Ошибка понятная пользователю (не тот формат, скан, битый файл).
        doc.status = DocumentStatus.FAILED
        doc.error_message = exc.message
        session.commit()
        return DocumentOut.of(doc)
    except Exception as exc:
        # Непредвиденная ошибка
        logger.exception("Не удалось извлечь текст из документа %s", doc_id)
        doc.status = DocumentStatus.FAILED
        doc.error_message = f"Внутренняя ошибка при извлечении текста: {exc}"
        session.commit()
        return DocumentOut.of(doc)

    doc.extracted_text = text
    doc.status = DocumentStatus.PROCESSED
    doc.error_message = None
    session.commit()
    return DocumentOut.of(doc)


# Чтение
@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[DocumentOut]:
    docs = session.scalars(
        select(Document).order_by(Document.id.desc()).limit(limit)
    ).all()
    return [DocumentOut.of(doc) for doc in docs]


def get_document_or_404(doc_id: int, session: Session) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    return doc


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, session: Session = Depends(get_db)) -> DocumentOut:
    return DocumentOut.of(get_document_or_404(doc_id, session))


@router.get("/{doc_id}/text", response_model=DocumentTextOut)
def get_document_text(
    doc_id: int, session: Session = Depends(get_db)
) -> DocumentTextOut:
    doc = get_document_or_404(doc_id, session)
    text = doc.extracted_text or ""
    if not text:
        raise HTTPException(404, "У документа ещё нет извлечённого текста")
    return DocumentTextOut(id=doc.id, text=text, text_length=len(text))


# Удаление
@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, session: Session = Depends(get_db)) -> None:
    doc = get_document_or_404(doc_id, session)
    path = doc.file_path
    session.delete(doc)
    session.commit()
    delete_file(path)