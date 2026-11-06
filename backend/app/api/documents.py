import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.files import save_upload
from app.files.chunking import count_words
from app.files.storage import delete_file
from app.journal.processing_log import Stage, write_log
from app.models import Chunk, Document, DocumentStatus, ProcessingLog
from app.processing import process_document

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
    chunks_count: int
    created_at: str

    @classmethod
    def of(cls, doc: Document, chunks_count: int = 0) -> "DocumentOut":
        return cls(
            id=doc.id,
            file_name=doc.file_name,
            file_type=doc.file_type.value if doc.file_type else None,
            file_size=doc.file_size,
            status=doc.status.value,
            error_message=doc.error_message,
            text_length=len(doc.extracted_text or ""),
            chunks_count=chunks_count,
            created_at=doc.created_at.isoformat(),
        )


class DocumentTextOut(BaseModel):
    id: int
    text: str
    text_length: int


class ChunkOut(BaseModel):
    id: int
    position: int
    heading: str | None
    page_from: int | None
    page_to: int | None
    words: int
    text: str


class LogOut(BaseModel):
    id: int
    stage: str
    level: str
    message: str
    duration_ms: int | None
    created_at: str


def get_document_or_404(doc_id: int, session: Session) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    return doc


def chunks_count_of(session: Session, doc_id: int) -> int:
    return session.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)) or 0


# Загрузка: только сохраняем файл. Текст извлекается по кнопке «Обработать».

@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile = File(..., description="PDF, DOCX или TXT"),
    check_enabled: bool = Query(True, description="Проверять курс на соответствие документу"),
    session: Session = Depends(get_db),
) -> DocumentOut:
    saved = save_upload(file)

    # Запись в БД
    try:
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
    except Exception:
        session.rollback()
        delete_file(saved.path)
        raise

    doc_id = doc.id
    write_log(doc_id, Stage.UPLOAD, f"Файл загружен: {doc.file_name} ({saved.size} байт)")
    return DocumentOut.of(doc)


# Обработка по кнопке

@router.post("/{doc_id}/process", response_model=DocumentOut, status_code=202)
def start_processing(
    doc_id: int,
    background: BackgroundTasks,
    session: Session = Depends(get_db),
) -> DocumentOut:
    doc = get_document_or_404(doc_id, session)
    if doc.status == DocumentStatus.PROCESSING:
        raise AppError("Документ уже обрабатывается", 409, "already_processing")
    if not doc.file_path or not Path(doc.file_path).is_file():
        raise AppError(
            "Файл документа не найден на сервере. Удалите документ и загрузите его заново",
            410, "file_missing",
        )

    doc.status = DocumentStatus.PROCESSING
    doc.error_message = None
    session.commit()
    write_log(doc_id, Stage.UPLOAD, "Обработка запущена пользователем")
    background.add_task(process_document, doc_id)
    return DocumentOut.of(doc, chunks_count_of(session, doc_id))


# Чтение

@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[DocumentOut]:
    docs = session.scalars(select(Document).order_by(Document.id.desc()).limit(limit)).all()
    counts = dict(
        session.execute(
            select(Chunk.document_id, func.count())
            .where(Chunk.document_id.in_([d.id for d in docs]))
            .group_by(Chunk.document_id)
        ).all()
    ) if docs else {}
    return [DocumentOut.of(doc, counts.get(doc.id, 0)) for doc in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, session: Session = Depends(get_db)) -> DocumentOut:
    doc = get_document_or_404(doc_id, session)
    return DocumentOut.of(doc, chunks_count_of(session, doc_id))


@router.get("/{doc_id}/text", response_model=DocumentTextOut)
def get_document_text(doc_id: int, session: Session = Depends(get_db)) -> DocumentTextOut:
    doc = get_document_or_404(doc_id, session)
    text = doc.extracted_text or ""
    if not text:
        raise HTTPException(404, "Текст ещё не извлечён: нажмите «Обработать»")
    return DocumentTextOut(id=doc.id, text=text, text_length=len(text))


@router.get("/{doc_id}/chunks", response_model=list[ChunkOut])
def get_document_chunks(doc_id: int, session: Session = Depends(get_db)) -> list[ChunkOut]:
    get_document_or_404(doc_id, session)
    chunks = session.scalars(
        select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.position)
    ).all()
    return [
        ChunkOut(
            id=c.id, position=c.position, heading=c.heading, page_from=c.page_from,
            page_to=c.page_to, words=count_words(c.text), text=c.text,
        )
        for c in chunks
    ]


@router.get("/{doc_id}/log", response_model=list[LogOut])
def get_document_log(doc_id: int, session: Session = Depends(get_db)) -> list[LogOut]:
    get_document_or_404(doc_id, session)
    rows = session.scalars(
        select(ProcessingLog).where(ProcessingLog.document_id == doc_id).order_by(ProcessingLog.id)
    ).all()
    return [
        LogOut(
            id=r.id, stage=r.stage, level=r.level.value, message=r.message,
            duration_ms=r.duration_ms, created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


# Удаление

@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, session: Session = Depends(get_db)) -> None:
    doc = get_document_or_404(doc_id, session)
    if doc.status == DocumentStatus.PROCESSING:
        raise AppError("Документ обрабатывается: дождитесь окончания и удалите его снова", 409, "already_processing")
    path = doc.file_path
    session.delete(doc)
    session.commit()
    delete_file(path)
