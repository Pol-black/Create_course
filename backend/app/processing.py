"""
Обработка документа: извлечение текста -> очистка -> деление на фрагменты.
"""

import logging
from pathlib import Path

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.errors import AppError
from app.files.chunking import split_into_chunks
from app.files.clean import prepare_document, render_text
from app.files.extract import ExtractError, extract_pages
from app.journal.processing_log import Stage, log_stage, write_log
from app.models import Chunk, Document, DocumentStatus, LogLevel

logger = logging.getLogger("app.processing")

INTERRUPTED_MESSAGE = "Обработка была прервана перезапуском сервера. Нажмите «Обработать» ещё раз"


def mark_failed(doc_id: int, message: str) -> None:
    with SessionLocal() as session:
        doc = session.get(Document, doc_id)
        if doc is not None:
            doc.status = DocumentStatus.FAILED
            doc.error_message = message
            session.commit()


def process_document(doc_id: int) -> None:
    """Полный цикл подготовки текста."""
    try:
        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:
                return
            path, file_type = Path(doc.file_path), doc.file_type

        with log_stage(doc_id, Stage.EXTRACT, "Извлечение текста"):
            pages = extract_pages(path, file_type)
        write_log(doc_id, Stage.EXTRACT, f"Найдено страниц с текстом: {len(pages)}")

        with log_stage(doc_id, Stage.CLEAN, "Очистка текста"):
            paras = prepare_document(pages, file_type)
            text = render_text(paras)
            if len(text) < settings.min_text_chars:
                raise ExtractError(
                    "После очистки в документе почти не осталось текста. "
                    "Проверьте, что файл содержит обычный текст, а не оглавление или колонтитулы",
                    "empty_after_clean",
                )
        headings = sum(1 for p in paras if p.level)
        write_log(doc_id, Stage.CLEAN, f"Абзацев: {len(paras) - headings}, заголовков: {headings}, символов: {len(text)}")

        with log_stage(doc_id, Stage.CHUNK, "Деление на фрагменты"):
            chunks = split_into_chunks(
                paras,
                target_words=settings.chunk_target_words,
                max_words=settings.chunk_max_words,
                min_words=settings.chunk_min_words,
            )
            if not chunks:
                raise ExtractError("Не получилось выделить фрагменты текста", "no_chunks")
        write_log(doc_id, Stage.CHUNK, f"Фрагментов: {len(chunks)}, слов: {sum(c.words for c in chunks)}")

        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:  
                return
            session.execute(delete(Chunk).where(Chunk.document_id == doc_id))
            session.add_all(
                Chunk(
                    document_id=doc_id, position=c.position, heading=c.heading,
                    page_from=c.page_from, page_to=c.page_to, text=c.text,
                )
                for c in chunks
            )
            doc.extracted_text = text
            doc.status = DocumentStatus.PROCESSED
            doc.error_message = None
            session.commit()
        write_log(doc_id, "done", "Документ обработан")
    except AppError as exc:
        mark_failed(doc_id, exc.message)
    except Exception as exc:
        logger.exception("Не удалось обработать документ %s", doc_id)
        write_log(doc_id, "error", f"Непредвиденная ошибка: {exc}", LogLevel.ERROR)
        mark_failed(doc_id, f"Внутренняя ошибка при обработке: {exc}")


def recover_interrupted() -> int:
    with SessionLocal() as session:
        stuck = session.scalars(select(Document).where(Document.status == DocumentStatus.PROCESSING)).all()
        for doc in stuck:
            doc.status = DocumentStatus.FAILED
            doc.error_message = INTERRUPTED_MESSAGE
        session.commit()
        return len(stuck)
