from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.courses import content as C
from app.courses import generation, service
from app.courses.example import create_example_course
from app.courses.from_document import create_draft_course
from app.db import get_db

router = APIRouter(tags=["courses"])


class CoursePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    goals: list[str] | None = None


class OrderIn(BaseModel):
    section_ids: list[int]


class NewSection(BaseModel):
    title: str = Field(min_length=1)


class RegenerateIn(BaseModel):
    hint: str = Field(default="", max_length=2000)


# курсы

@router.get("/courses")
def list_courses(session: Session = Depends(get_db)) -> list[dict]:
    return service.list_courses(session)


@router.get("/courses/{course_id}")
def get_course(course_id: int, session: Session = Depends(get_db)) -> dict:
    return service.course_view(session, service.get_course(session, course_id))


@router.patch("/courses/{course_id}")
def edit_course(course_id: int, body: CoursePatch, session: Session = Depends(get_db)) -> dict:
    course = service.edit_course(session, course_id, body.title, body.description, body.goals)
    return service.course_view(session, course)


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: int, session: Session = Depends(get_db)) -> None:
    session.delete(service.get_course(session, course_id))
    session.commit()


@router.put("/courses/{course_id}/order")
def reorder(course_id: int, body: OrderIn, session: Session = Depends(get_db)) -> dict:
    service.reorder_sections(session, course_id, body.section_ids)
    return service.course_view(session, service.get_course(session, course_id))


@router.post("/courses/{course_id}/sections", status_code=201)
def add_section(course_id: int, body: NewSection, session: Session = Depends(get_db)) -> dict:
    service.add_section(session, course_id, body.title.strip())
    return service.course_view(session, service.get_course(session, course_id))


@router.get("/courses/{course_id}/export.md")
def export_course(course_id: int, session: Session = Depends(get_db)) -> Response:
    course = service.course_view(session, service.get_course(session, course_id))
    filename = quote(f"{course['title']}.md")
    return Response(
        C.export_markdown(course),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# создание курса без LLM

@router.post("/courses/example", status_code=201)
def create_example(session: Session = Depends(get_db)) -> dict:
    """Готовый пример курса (MPI) вместе с документом и фрагментами."""
    return service.course_view(session, create_example_course(session))


@router.post("/documents/{document_id}/course/draft", status_code=201)
def create_draft(
    document_id: int,
    replace: bool = Query(False, description="Заменить уже созданный курс"),
    session: Session = Depends(get_db),
) -> dict:
    """Черновик курса из фрагментов документа по правилам, без языковой модели."""
    return service.course_view(session, create_draft_course(session, document_id, replace))


# разделы

class SectionPatch(C.ContentPatch):
    pass


@router.patch("/sections/{section_id}")
def edit_section(section_id: int, body: SectionPatch, session: Session = Depends(get_db)) -> dict:
    section = service.edit_section(session, section_id, body)
    return _section(session, section.id)


@router.delete("/sections/{section_id}", status_code=204)
def delete_section(section_id: int, session: Session = Depends(get_db)) -> None:
    service.delete_section(session, section_id)


@router.get("/sections/{section_id}/versions")
def versions(section_id: int, session: Session = Depends(get_db)) -> list[dict]:
    return service.list_versions(session, section_id)


@router.post("/sections/{section_id}/versions/{version_id}/restore")
def restore(section_id: int, version_id: int, session: Session = Depends(get_db)) -> dict:
    service.restore_version(session, section_id, version_id)
    return _section(session, section_id)


@router.post("/sections/{section_id}/regenerate")
def regenerate(section_id: int, body: RegenerateIn, session: Session = Depends(get_db)) -> dict:
    """Заново написать выбранный раздел через LLM. Остальной курс не меняется."""
    generation.regenerate_section(session, section_id, body.hint)
    return _section(session, section_id)


def _section(session: Session, section_id: int) -> dict:
    section = service.get_section(session, section_id)
    session.refresh(section)
    course = service.course_view(session, service.get_course(session, section.course_id))
    return next(s for s in course["sections"] if s["id"] == section_id)
