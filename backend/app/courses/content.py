from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.llm.schemas import Question, Term


class SectionContentIn(BaseModel):
    """Содержимое раздела."""

    title: str = Field(min_length=1)
    intro: str = ""
    content_md: str = ""
    terms: list[Term] = []
    summary: list[str] = []
    questions: list[Question] = []
    source_chunk_ids: list[int] = []
    missing_info: list[str] = []

    @field_validator("title", "intro", "content_md")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("summary", "missing_info")
    @classmethod
    def drop_blank(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class ContentPatch(BaseModel):
    """Что пользователь меняет в разделе."""

    title: str | None = Field(default=None, min_length=1)
    intro: str | None = None
    content_md: str | None = None
    terms: list[Term] | None = None
    summary: list[str] | None = None
    questions: list[Question] | None = None
    missing_info: list[str] | None = None


def merge_content(current: dict[str, Any], patch: ContentPatch) -> dict[str, Any]:
    """Новое содержимое"""
    data = dict(current)
    for field, value in patch.model_dump(exclude_unset=True).items():
        if value is not None:
            data[field] = value
    return SectionContentIn.model_validate(data).model_dump()


def empty_content(title: str) -> dict[str, Any]:
    return SectionContentIn(title=title).model_dump()


def content_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return SectionContentIn.model_validate(a).model_dump() == SectionContentIn.model_validate(b).model_dump()


def check_permutation(requested: list[int], existing: list[int]) -> None:
    """Каждый раздел курса ровно один раз."""
    if sorted(requested) != sorted(existing):
        raise ValueError("Список разделов должен содержать каждый раздел курса ровно один раз")


def export_markdown(course: dict[str, Any]) -> str:
    """Весь курс одним Markdown-файлом: для сохранения и передачи."""
    out = [f"# {course['title']}", ""]
    if course.get("description"):
        out += [course["description"], ""]
    if course.get("goals"):
        out += ["## Цели изучения", ""] + [f"- {g}" for g in course["goals"]] + [""]
    for number, section in enumerate(course["sections"], start=1):
        c = section["content"]
        out += [f"## {number}. {section['title']}", ""]
        if c.get("intro"):
            out += [f"*{c['intro']}*", ""]
        if c.get("content_md"):
            out += [c["content_md"].strip(), ""]
        if c.get("terms"):
            out += ["### Термины", ""] + [f"- **{t['term']}** — {t['definition']}" for t in c["terms"]] + [""]
        if c.get("summary"):
            out += ["### Выводы", ""] + [f"- {item}" for item in c["summary"]] + [""]
        if c.get("questions"):
            out += ["### Вопросы для самопроверки", ""]
            for i, q in enumerate(c["questions"], start=1):
                out.append(f"{i}. {q['question']}")
                out += [f"   - {'[x]' if j == q['correct_index'] else '[ ]'} {opt}" for j, opt in enumerate(q["options"])]
                if q.get("explanation"):
                    out.append(f"   - Пояснение: {q['explanation']}")
            out.append("")
        if c.get("missing_info"):
            out += ["### Чего не хватает в документе", ""] + [f"- {item}" for item in c["missing_info"]] + [""]
    return "\n".join(out).rstrip() + "\n"
