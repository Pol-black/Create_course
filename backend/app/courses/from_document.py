"""Черновик курса из фрагментов документа без LLM (правила из draft.py)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.courses import service
from app.courses.draft import ChunkInput, build_draft_course
from app.errors import AppError
from app.models import Author, Chunk, Course, Document, DocumentStatus


def create_draft_course(session: Session, document_id: int, replace: bool = False) -> Course:
    document = session.get(Document, document_id)
    if document is None:
        raise AppError("Документ не найден", 404, "not_found")
    if document.status != DocumentStatus.PROCESSED:
        raise AppError("Сначала обработайте документ: нажмите «Обработать»", 409, "not_processed")

    existing = list(session.scalars(select(Course).where(Course.document_id == document_id)))
    if existing and not replace:
        raise AppError("Для этого документа курс уже создан", 409, "course_exists")
    for course in existing:
        session.delete(course)
    session.flush()

    chunks = list(session.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position)))
    draft = build_draft_course(document.file_name, [ChunkInput(c.id, c.text) for c in chunks])
    return service.create_course(
        session, document_id, draft.title, draft.description, draft.goals,
        [(s.title, s.content) for s in draft.sections],
        author=Author.AI, model="draft", prompt_name="draft",
    )
