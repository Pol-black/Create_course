"""
Создание и повторная генерация разделов через языковую модель (слой app.llm).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.courses import service
from app.llm.schemas import SectionContent
from app.llm.service import LLMService, get_llm_service
from app.models import Author, Chunk, Course, Document, Section, SectionStatus


def format_chunks(chunks: list[Chunk]) -> str:
    parts = []
    for c in chunks:
        pages = f", стр. {c.page_from}" + (f"–{c.page_to}" if c.page_to != c.page_from else "") if c.page_from else ""
        parts.append(f"[Фрагмент {c.id}{pages}]\n{c.text}")
    return "\n\n".join(parts)


def source_chunks(session: Session, section: Section) -> list[Chunk]:
    """Фрагменты раздела"""
    course = session.get(Course, section.course_id)
    ids = service.current_content(session, section).get("source_chunk_ids") or []
    query = select(Chunk).where(Chunk.document_id == course.document_id).order_by(Chunk.position)
    if ids:
        query = query.where(Chunk.id.in_(ids))
    return list(session.scalars(query))


def check_sources(content: SectionContent, allowed: set[int]) -> dict[str, Any]:
    """Защита от выдумок на уровне ссылок: модель может ссылаться только на переданные фрагменты."""
    unknown = [c for c in content.source_chunk_ids if c not in allowed]
    return {"unknown_chunk_ids": unknown, "ok": not unknown}


def regenerate_section(session: Session, section_id: int, hint: str = "", llm: LLMService | None = None) -> Section:
    section = service.get_section(session, section_id)
    course = session.get(Course, section.course_id)
    chunks = source_chunks(session, section)
    if not chunks:
        raise service.AppError("У документа нет фрагментов: сначала нажмите «Обработать»", 409, "no_chunks")

    llm = llm or get_llm_service()
    result = llm.generate(
        "section", SectionContent,
        course_title=course.title, section_title=section.title,
        user_hint=hint.strip(), chunks=format_chunks(chunks),
    )
    content: SectionContent = result.data  # type: ignore[assignment]
    check = check_sources(content, {c.id for c in chunks})
    data = content.model_dump()
    data["source_chunk_ids"] = [c for c in data["source_chunk_ids"] if c in {ch.id for ch in chunks}] or [c.id for c in chunks]

    service.add_version(
        session, section, data, Author.AI,
        model=result.model, prompt_name=result.prompt_name, user_hint=hint.strip() or None, check_result=check,
    )
    if not check["ok"]:
        section.status = SectionStatus.HAS_ISSUES
    session.commit()
    return section
