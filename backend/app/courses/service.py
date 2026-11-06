"""
Работа с курсами в базе: чтение, правки, порядок разделов, версии.
"""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.courses import content as C
from app.errors import AppError
from app.models import (
    Author,
    Chunk,
    Course,
    CourseStatus,
    Document,
    Section,
    SectionStatus,
    SectionVersion,
    section_version_chunk,
)

OFFSET = 1_000_000  


def not_found(what: str) -> AppError:
    return AppError(f"{what} не найден", 404, "not_found")


def get_course(session: Session, course_id: int) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise not_found("Курс")
    return course


def touch_course(session: Session, course_id: int) -> None:
    """Обновить время изменения курса (его ставит триггер на UPDATE)."""
    session.execute(update(Course).where(Course.id == course_id).values(title=Course.title))


def get_section(session: Session, section_id: int) -> Section:
    section = session.get(Section, section_id)
    if section is None:
        raise not_found("Раздел")
    return section


# чтение

def section_view(section: Section, version: SectionVersion | None, versions_count: int) -> dict[str, Any]:
    return {
        "id": section.id,
        "position": section.position,
        "title": section.title,
        "status": section.status.value,
        "version_id": version.id if version else None,
        "version_no": version.version_no if version else None,
        "author": version.author.value if version else None,
        "versions_count": versions_count,
        "updated_at": section.updated_at.isoformat(),
        "content": version.content if version else C.empty_content(section.title),
    }


def course_view(session: Session, course: Course) -> dict[str, Any]:
    sections = session.scalars(
        select(Section).where(Section.course_id == course.id).order_by(Section.position)
    ).all()
    ids = [s.id for s in sections]
    versions = {}
    counts: dict[int, int] = {}
    if ids:
        current_ids = [s.current_version_id for s in sections if s.current_version_id]
        if current_ids:
            versions = {v.id: v for v in session.scalars(select(SectionVersion).where(SectionVersion.id.in_(current_ids)))}
        counts = dict(
            session.execute(
                select(SectionVersion.section_id, func.count()).where(SectionVersion.section_id.in_(ids)).group_by(SectionVersion.section_id)
            ).all()
        )
    document = session.get(Document, course.document_id)
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description or "",
        "goals": list(course.goals or []),
        "status": course.status.value,
        "error_message": course.error_message,
        "document": {"id": document.id, "file_name": document.file_name} if document else None,
        "created_at": course.created_at.isoformat(),
        "updated_at": course.updated_at.isoformat(),
        "sections": [
            section_view(s, versions.get(s.current_version_id), counts.get(s.id, 0)) for s in sections
        ],
    }


def list_courses(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Course, Document.file_name, func.count(Section.id))
        .join(Document, Document.id == Course.document_id)
        .outerjoin(Section, Section.course_id == Course.id)
        .group_by(Course.id, Document.file_name)
        .order_by(Course.id.desc())
    ).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "description": c.description or "",
            "status": c.status.value,
            "document_id": c.document_id,
            "document_name": file_name,
            "sections_count": count,
            "updated_at": c.updated_at.isoformat(),
        }
        for c, file_name, count in rows
    ]


# версии

def add_version(
    session: Session,
    section: Section,
    content: dict[str, Any],
    author: Author,
    *,
    model: str | None = None,
    prompt_name: str | None = None,
    user_hint: str | None = None,
    check_result: dict[str, Any] | None = None,
) -> SectionVersion:
    """Записать новую версию раздела и сделать её текущей."""
    content = C.SectionContentIn.model_validate(content).model_dump()  
    last = session.scalar(select(func.max(SectionVersion.version_no)).where(SectionVersion.section_id == section.id)) or 0
    version = SectionVersion(
        section_id=section.id, version_no=last + 1, content=content, author=author,
        model=model, prompt_name=prompt_name, user_hint=user_hint, check_result=check_result,
    )
    session.add(version)
    session.flush()

    course = session.get(Course, section.course_id)
    wanted = list(dict.fromkeys(content.get("source_chunk_ids") or []))
    if wanted:
        valid = session.scalars(
            select(Chunk.id).where(Chunk.document_id == course.document_id, Chunk.id.in_(wanted))
        ).all()
        if valid:
            session.execute(section_version_chunk.insert(), [{"section_version_id": version.id, "chunk_id": c} for c in valid])

    section.current_version_id = version.id
    section.title = content["title"]
    section.status = SectionStatus.READY
    session.flush()
    touch_course(session, section.course_id)
    return version


def current_content(session: Session, section: Section) -> dict[str, Any]:
    if section.current_version_id:
        version = session.get(SectionVersion, section.current_version_id)
        if version:
            return dict(version.content)
    return C.empty_content(section.title)


def edit_section(session: Session, section_id: int, patch: C.ContentPatch) -> Section:
    section = get_section(session, section_id)
    current = current_content(session, section)
    try:
        new = C.merge_content(current, patch)
    except ValueError as exc:
        raise AppError(f"Некорректное содержимое раздела: {exc}", 422, "invalid_section") from exc
    if section.current_version_id and C.content_equal(current, new):
        return section  
    add_version(session, section, new, Author.USER)
    session.commit()
    return section


def list_versions(session: Session, section_id: int) -> list[dict[str, Any]]:
    section = get_section(session, section_id)
    versions = session.scalars(
        select(SectionVersion).where(SectionVersion.section_id == section_id).order_by(SectionVersion.version_no.desc())
    ).all()
    return [
        {
            "id": v.id,
            "version_no": v.version_no,
            "author": v.author.value,
            "model": v.model,
            "user_hint": v.user_hint,
            "check_result": v.check_result,
            "created_at": v.created_at.isoformat(),
            "is_current": v.id == section.current_version_id,
            "content": v.content,
        }
        for v in versions
    ]


def restore_version(session: Session, section_id: int, version_id: int) -> Section:
    """Вернуться к прошлой версии."""
    section = get_section(session, section_id)
    old = session.get(SectionVersion, version_id)
    if old is None or old.section_id != section.id:
        raise not_found("Версия")
    add_version(session, section, dict(old.content), Author.USER, prompt_name=f"restore:v{old.version_no}")
    session.commit()
    return section


# структура

def renumber(session: Session, course_id: int, ordered_ids: list[int]) -> None:
    """Расставить позиции 0..n-1 в заданном порядке."""
    session.execute(update(Section).where(Section.course_id == course_id).values(position=Section.position + OFFSET))
    for position, section_id in enumerate(ordered_ids):
        session.execute(update(Section).where(Section.id == section_id).values(position=position))
    session.expire_all()


def reorder_sections(session: Session, course_id: int, section_ids: list[int]) -> None:
    get_course(session, course_id)
    existing = list(session.scalars(select(Section.id).where(Section.course_id == course_id)))
    try:
        C.check_permutation(section_ids, existing)
    except ValueError as exc:
        raise AppError(str(exc), 422, "invalid_order") from exc
    renumber(session, course_id, section_ids)
    touch_course(session, course_id)
    session.commit()


def add_section(session: Session, course_id: int, title: str) -> Section:
    get_course(session, course_id)
    position = (session.scalar(select(func.max(Section.position)).where(Section.course_id == course_id)) or -1) + 1
    section = Section(course_id=course_id, position=position, title=title, status=SectionStatus.READY)
    session.add(section)
    session.flush()
    add_version(session, section, C.empty_content(title), Author.USER)
    session.commit()
    return section


def delete_section(session: Session, section_id: int) -> None:
    section = get_section(session, section_id)
    course_id = section.course_id
    count = session.scalar(select(func.count()).select_from(Section).where(Section.course_id == course_id))
    if count <= 1:
        raise AppError("Нельзя удалить единственный раздел курса", 409, "last_section")
    session.delete(section)
    session.flush()
    rest = list(session.scalars(select(Section.id).where(Section.course_id == course_id).order_by(Section.position)))
    renumber(session, course_id, rest)
    touch_course(session, course_id)
    session.commit()


def edit_course(session: Session, course_id: int, title: str | None, description: str | None, goals: list[str] | None) -> Course:
    course = get_course(session, course_id)
    if title is not None:
        course.title = title.strip()
    if description is not None:
        course.description = description.strip()
    if goals is not None:
        course.goals = [g.strip() for g in goals if g and g.strip()]
    session.commit()
    return course


# создание курса

def create_course(
    session: Session,
    document_id: int,
    title: str,
    description: str,
    goals: list[str],
    sections: list[tuple[str, dict[str, Any]]],
    *,
    author: Author = Author.AI,
    model: str | None = None,
    prompt_name: str | None = None,
) -> Course:
    """Сохранить курс целиком."""
    course = Course(
        document_id=document_id, title=title, description=description,
        goals=goals, status=CourseStatus.READY,
    )
    session.add(course)
    session.flush()
    for position, (section_title, content) in enumerate(sections):
        section = Section(course_id=course.id, position=position, title=section_title, status=SectionStatus.READY)
        session.add(section)
        session.flush()
        add_version(session, section, content, author, model=model, prompt_name=prompt_name)
    session.commit()
    return course
