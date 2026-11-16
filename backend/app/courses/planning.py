"""
Подготовка данных для LLM и разбор её ответа. Без базы данных и без обращений к модели,
поэтому всё здесь проверяется обычными тестами.
"""

from dataclasses import dataclass

from app.llm.schemas import CourseOutline


@dataclass
class SourceChunk:
    id: int
    position: int
    heading: str | None
    page_from: int | None
    page_to: int | None
    text: str


def pages_label(c: SourceChunk) -> str:
    if not c.page_from:
        return ""
    if c.page_to and c.page_to != c.page_from:
        return f", стр. {c.page_from}-{c.page_to}"
    return f", стр. {c.page_from}"


def format_chunks(chunks: list[SourceChunk], max_chars: int) -> tuple[str, list[int]]:
    """Текст фрагментов для промпта раздела, не длиннее max_chars.
    Возвращает (текст, номера фрагментов, которые в него вошли)."""
    parts: list[str] = []
    used: list[int] = []
    left = max_chars
    for c in chunks:
        header = f"[Фрагмент {c.id}{pages_label(c)}]\n"
        room = left - len(header)
        if room < 200 and parts: 
            break
        text = c.text
        if len(text) > room:
            text = text[: max(room, 200)].rsplit(" ", 1)[0] + " […фрагмент обрезан]"
        parts.append(header + text)
        used.append(c.id)
        left -= len(header) + len(text) + 2
        if left <= 0:
            break
    return "\n\n".join(parts), used


def outline_overview(chunks: list[SourceChunk], max_chars: int) -> str:
    """Обзор документа для плана курса: «[номер] заголовок: начало текста»."""
    if not chunks:
        return ""
    heads = [f"[{c.id}] {(c.heading or 'без заголовка').strip()}: " for c in chunks]
    fixed = sum(len(h) + 1 for h in heads)
    excerpt = max(80, (max_chars - fixed) // len(chunks))
    lines = []
    for head, c in zip(heads, chunks):
        text = " ".join(c.text.split())
        if len(text) > excerpt:
            text = text[:excerpt].rsplit(" ", 1)[0] + "…"
        lines.append(head + text)
    return "\n".join(lines)


def clean_outline(outline: CourseOutline, valid_ids: set[int]) -> CourseOutline:
    """Оставить в плане только существующие фрагменты и убрать разделы без источников.
    Модель может выдумать номер фрагмента: такие ссылки отбрасываются."""
    sections = []
    for s in outline.sections:
        ids = [i for i in dict.fromkeys(s.chunk_ids) if i in valid_ids]
        if ids:
            sections.append(s.model_copy(update={"chunk_ids": ids}))
    if not sections:
        raise ValueError("в плане нет разделов с существующими фрагментами документа")
    return outline.model_copy(update={"sections": sections})


def uncovered_chunks(outline: CourseOutline, all_ids: list[int]) -> list[int]:
    covered = {i for s in outline.sections for i in s.chunk_ids}
    return [i for i in all_ids if i not in covered]
