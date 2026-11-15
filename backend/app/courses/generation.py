import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.courses import content as C
from app.courses import planning, service, verify
from app.db import SessionLocal
from app.errors import AppError
from app.journal.processing_log import Stage, log_stage, write_log
from app.llm.errors import LLMError
from app.llm.schemas import CourseOutline, SectionContent
from app.llm.service import GenerationResult, LLMService, get_llm_service
from app.models import (
    Author,
    Chunk,
    Course,
    CourseStatus,
    Document,
    DocumentStatus,
    LogLevel,
    Section,
    SectionStatus,
    SectionVersion,
    section_version_chunk,
)

logger = logging.getLogger("app.generation")

PLACEHOLDER = "outline"  # prompt_name «пустой» версии: раздел есть в плане, текста ещё нет
FATAL_CODES = {"llm_no_api_key", "llm_auth", "llm_rate_limit_daily"}  # дальше пробовать бессмысленно
INTERRUPTED_MESSAGE = "Генерация была прервана перезапуском сервера. Создайте курс заново или сгенерируйте разделы по одному"


# данные

def source_of(chunk: Chunk) -> planning.SourceChunk:
    return planning.SourceChunk(chunk.id, chunk.position, chunk.heading, chunk.page_from, chunk.page_to, chunk.text)


def load_sources(session: Session, document_id: int) -> list[planning.SourceChunk]:
    rows = session.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position))
    return [source_of(c) for c in rows]


def is_placeholder(version: SectionVersion | None) -> bool:
    return version is not None and version.prompt_name == PLACEHOLDER


def store_generated(
    session: Session, section: Section, data: dict[str, Any], result: GenerationResult,
    check: dict[str, Any], hint: str = "",
) -> None:
    """Записать сгенерированный раздел. Первая генерация заполняет пустую версию из плана,
    повторная добавляет новую версию (прежние остаются в истории)."""
    current = session.get(SectionVersion, section.current_version_id) if section.current_version_id else None
    if is_placeholder(current):
        content = C.SectionContentIn.model_validate(data).model_dump()
        current.content = content
        current.author = Author.AI
        current.model = result.model
        current.prompt_name = result.prompt_name
        current.user_hint = hint or None
        current.check_result = check
        session.execute(delete(section_version_chunk).where(section_version_chunk.c.section_version_id == current.id))
        valid = session.scalars(
            select(Chunk.id).where(Chunk.id.in_(content["source_chunk_ids"]),
                                   Chunk.document_id == session.get(Course, section.course_id).document_id)
        ).all()
        if valid:
            session.execute(section_version_chunk.insert(), [{"section_version_id": current.id, "chunk_id": c} for c in valid])
        section.title = content["title"]
    else:
        service.add_version(
            session, section, data, Author.AI, model=result.model,
            prompt_name=result.prompt_name, user_hint=hint or None, check_result=check,
        )
    section.status = SectionStatus.READY if check.get("ok", True) else SectionStatus.HAS_ISSUES


def write_section(
    session: Session, section: Section, course: Course, document: Document,
    chunks: list[planning.SourceChunk], llm: LLMService, hint: str = "",
) -> GenerationResult:
    """Один раздел: текст источников -> модель -> проверка -> запись. Общая часть для создания и повтора."""
    text, used = planning.format_chunks(chunks, settings.llm_max_input_chars)
    result = llm.generate(
        "section", SectionContent,
        course_title=course.title, section_title=section.title, user_hint=hint, chunks=text,
    )
    data = result.data.model_dump()  # type: ignore[union-attr]
    # Источники: только те фрагменты, которые мы реально передали модели
    data["source_chunk_ids"] = [i for i in dict.fromkeys(data["source_chunk_ids"]) if i in used] or used
    if document.check_enabled:
        by_id = {c.id: c.text for c in chunks}
        check = verify.check_section(data, "\n".join(by_id[i] for i in used), set(used))
        check["unknown_chunk_ids"] = [i for i in result.data.source_chunk_ids if i not in used]  # type: ignore[union-attr]
        check["ok"] = not check["unsupported"] and not check["unknown_chunk_ids"]
    else:
        check = {"ok": True, "skipped": True}
    store_generated(session, section, data, result, check, hint)
    return result


# создание курса

def start_course_generation(session: Session, document_id: int, replace: bool = False) -> Course:
    """Проверить условия и создать пустой курс со статусом GENERATING. Саму генерацию запускает API в фоне."""
    document = session.get(Document, document_id)
    if document is None:
        raise AppError("Документ не найден", 404, "not_found")
    if document.status != DocumentStatus.PROCESSED:
        raise AppError("Сначала обработайте документ: нажмите «Обработать»", 409, "not_processed")
    if not settings.llm_api_key:
        raise LLMError(
            "Не задан ключ LLM_API_KEY. Укажите ключ в файле .env и перезапустите backend",
            code="llm_no_api_key", status_code=503,
        )
    existing = list(session.scalars(select(Course).where(Course.document_id == document_id)))
    if any(c.status == CourseStatus.GENERATING for c in existing):
        raise AppError("Курс для этого документа уже создаётся", 409, "already_generating")
    if existing and not replace:
        raise AppError("Для этого документа курс уже создан", 409, "course_exists")
    for course in existing:
        session.delete(course)
    session.flush()
    course = Course(
        document_id=document_id, title=document.file_name, description="", goals=[], status=CourseStatus.GENERATING,
    )
    session.add(course)
    session.commit()
    write_log(document_id, Stage.OUTLINE, "Создание курса запущено пользователем")
    return course


def mark_course_failed(course_id: int, message: str) -> None:
    with SessionLocal() as session:
        course = session.get(Course, course_id)
        if course is not None:
            course.status = CourseStatus.FAILED
            course.error_message = message
            for s in session.scalars(select(Section).where(Section.course_id == course_id, Section.status == SectionStatus.GENERATING)):
                s.status = SectionStatus.FAILED
            session.commit()


def make_outline(llm: LLMService, chunks: list[planning.SourceChunk]) -> CourseOutline:
    outline = llm.generate(
        "course_outline", CourseOutline,
        chunks=planning.outline_overview(chunks, settings.llm_max_input_chars),
    ).data
    try:
        return planning.clean_outline(outline, {c.id for c in chunks})  # type: ignore[arg-type]
    except ValueError as exc:
        raise LLMError(f"Модель составила неверный план курса: {exc}. Повторите создание курса",
                       code="llm_bad_outline") from exc


def run_course_generation(course_id: int, llm: LLMService | None = None) -> None:
    """Фоновая задача: план курса -> разделы по одному. Ход работы виден в БД (статусы) и в журнале."""
    try:
        _run(course_id, llm or get_llm_service())
    except LLMError as exc:
        logger.warning("Курс %s: %s", course_id, exc.message)
        mark_course_failed(course_id, exc.message)
    except Exception:
        logger.exception("Курс %s: неожиданная ошибка генерации", course_id)
        mark_course_failed(course_id, "Не удалось создать курс из-за внутренней ошибки. Подробности в журнале")


def _run(course_id: int, llm: LLMService) -> None:
    with SessionLocal() as session:
        course = session.get(Course, course_id)
        document = session.get(Document, course.document_id)
        doc_id = document.id
        chunks = load_sources(session, doc_id)
        if not chunks:
            raise LLMError("У документа нет фрагментов: сначала нажмите «Обработать»", code="no_chunks", status_code=409)

        # 1. План курса
        with log_stage(doc_id, Stage.OUTLINE, "План курса"):
            outline = make_outline(llm, chunks)
        course.title = outline.title.strip()
        course.description = outline.description.strip()
        course.goals = outline.goals
        for old in session.scalars(select(Section).where(Section.course_id == course_id)):
            session.delete(old)
        session.flush()

        # Разделы появляются сразу (статус GENERATING): страница курса показывает ход работы.
        # В каждом уже лежат фрагменты-источники из плана, чтобы раздел можно было сгенерировать повторно.
        sections: list[tuple[int, list[int]]] = []
        for position, item in enumerate(outline.sections):
            section = Section(course_id=course_id, position=position, title=item.title.strip(), status=SectionStatus.GENERATING)
            session.add(section)
            session.flush()
            placeholder = C.empty_content(section.title)
            placeholder["source_chunk_ids"] = item.chunk_ids
            service.add_version(session, section, placeholder, Author.AI, prompt_name=PLACEHOLDER)
            section.status = SectionStatus.GENERATING
            sections.append((section.id, item.chunk_ids))
        session.commit()
        uncovered = planning.uncovered_chunks(outline, [c.id for c in chunks])
        if uncovered:
            write_log(doc_id, Stage.OUTLINE, f"В плане нет фрагментов: {len(uncovered)} из {len(chunks)}", LogLevel.WARN)

    # 2. Разделы по одному; ошибка одного раздела не останавливает остальные
    by_id = {c.id: c for c in chunks}
    errors: list[str] = []
    fatal = False
    for number, (section_id, chunk_ids) in enumerate(sections, start=1):
        with SessionLocal() as session:
            section = session.get(Section, section_id)
            if fatal:
                section.status = SectionStatus.FAILED
                session.commit()
                continue
            course = session.get(Course, course_id)
            document = session.get(Document, doc_id)
            title = section.title
            try:
                with log_stage(doc_id, Stage.SECTION, f"Раздел {number}/{len(sections)} «{title}»"):
                    write_section(session, section, course, document, [by_id[i] for i in chunk_ids], llm)
                session.commit()
            except LLMError as exc:
                session.rollback()
                section = session.get(Section, section_id)
                section.status = SectionStatus.FAILED
                session.commit()
                errors.append(f"«{title}»: {exc.message}")
                fatal = exc.code in FATAL_CODES

    # 3. Итог
    with SessionLocal() as session:
        course = session.get(Course, course_id)
        statuses = [s.status for s in session.scalars(select(Section).where(Section.course_id == course_id))]
        done = sum(1 for s in statuses if s != SectionStatus.FAILED)
        course.status = CourseStatus.READY if done else CourseStatus.FAILED
        course.error_message = (
            f"Не удалось сгенерировать разделов: {len(statuses) - done}. " + errors[0] if errors else None
        )
        session.commit()
    write_log(doc_id, Stage.SECTION, f"Курс готов: разделов {done} из {len(statuses)}",
              LogLevel.INFO if not errors else LogLevel.WARN)


def recover_interrupted_courses() -> int:
    """При запуске сервера: курсы, которые генерировались в момент перезапуска, помечаем ошибкой."""
    with SessionLocal() as session:
        stuck = list(session.scalars(select(Course).where(Course.status == CourseStatus.GENERATING)))
        for course in stuck:
            course.status = CourseStatus.FAILED
            course.error_message = INTERRUPTED_MESSAGE
            for s in session.scalars(select(Section).where(Section.course_id == course.id, Section.status == SectionStatus.GENERATING)):
                s.status = SectionStatus.FAILED
        session.commit()
        return len(stuck)


# повторная генерация раздела

def source_chunks(session: Session, section: Section) -> list[planning.SourceChunk]:
    """Фрагменты раздела: те, на которые он ссылается; если ссылок нет — весь документ."""
    course = session.get(Course, section.course_id)
    ids = service.current_content(session, section).get("source_chunk_ids") or []
    chunks = load_sources(session, course.document_id)
    return [c for c in chunks if c.id in ids] if ids else chunks


def regenerate_section(session: Session, section_id: int, hint: str = "", llm: LLMService | None = None) -> Section:
    """Заново написать один раздел. Остальной курс не меняется, прежний текст остаётся в истории версий."""
    section = service.get_section(session, section_id)
    course = session.get(Course, section.course_id)
    document = session.get(Document, course.document_id)
    chunks = source_chunks(session, section)
    if not chunks:
        raise AppError("У документа нет фрагментов: сначала нажмите «Обработать»", 409, "no_chunks")
    write_section(session, section, course, document, chunks, llm or get_llm_service(), hint.strip())
    if course.status == CourseStatus.FAILED and section.status != SectionStatus.FAILED:
        course.status = CourseStatus.READY  # курс снова пригоден: хотя бы раздел получился
        course.error_message = None
    session.commit()
    write_log(document.id, Stage.SECTION, f"Раздел «{section.title}» сгенерирован заново")
    return section
