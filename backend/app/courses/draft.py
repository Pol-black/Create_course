"""
Черновик курса из фрагментов документа БЕЗ языковой модели.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePath

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\"(])")
_LIST_ITEM = re.compile(r"^(?:[-•*]|\d+[.)])\s+")
_TERM = re.compile(
    r"^(?:[-•*]\s+)?([A-ZА-ЯЁa-zа-яё][A-Za-zА-Яа-яЁё0-9_ ()\-]{1,40}?)\s*(?::|—|–)\s+(\S.{15,400})$"
)

MIN_SECTION_WORDS = 15
THIN_SECTION_WORDS = 40


@dataclass
class Block:
    chunk_id: int
    text: str
    level: int = 0  # 0 — обычный абзац


@dataclass
class DraftSection:
    title: str
    content: dict
    chunk_ids: list[int]


@dataclass
class DraftCourse:
    title: str
    description: str
    goals: list[str]
    sections: list[DraftSection] = field(default_factory=list)


@dataclass
class ChunkInput:
    id: int
    text: str


def words(text: str) -> int:
    return len(text.split())


def sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s.strip() for s in _SENTENCE.split(flat) if s.strip()]


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:—-")
    return cut + "…"


def to_blocks(chunks: list[ChunkInput]) -> list[Block]:
    blocks: list[Block] = []
    for chunk in chunks:
        for raw in re.split(r"\n{2,}", chunk.text):
            raw = raw.strip()
            if not raw:
                continue
            m = _HEADING.match(raw)
            if m and "\n" not in raw:
                blocks.append(Block(chunk.id, m.group(2).strip(), len(m.group(1))))
            else:
                blocks.append(Block(chunk.id, raw))
    return blocks


def _pick_levels(blocks: list[Block]) -> tuple[str | None, int]:
    """Название документа и уровень заголовков разделов."""
    levels = sorted({b.level for b in blocks if b.level})
    if not levels:
        return None, 0
    top = levels[0]
    top_blocks = [b for b in blocks if b.level == top]
    first_heading = next(b for b in blocks if b.level)
    if len(top_blocks) == 1 and len(levels) > 1 and first_heading is top_blocks[0]:
        return top_blocks[0].text, levels[1]
    return None, top


def _body_text(blocks: list[Block], section_level: int) -> str:
    """Markdown раздела: вложенные заголовки получают уровень"""
    out = []
    for b in blocks:
        if b.level:
            depth = min(max(b.level - section_level + 2, 3), 6)
            out.append("#" * depth + " " + b.text)
        else:
            out.append(b.text)
    return "\n\n".join(out)


def find_terms(blocks: list[Block], limit: int = 8) -> list[dict]:
    terms: list[dict] = []
    seen: set[str] = set()
    for b in blocks:
        if b.level:
            continue
        for line in b.text.split("\n"):
            m = _TERM.match(line.strip())
            if not m:
                continue
            term, definition = m.group(1).strip(), m.group(2).strip()
            if len(term.split()) > 5 or term.lower() in seen or definition[0].islower() is False and definition[0].isdigit():
                continue
            seen.add(term.lower())
            terms.append({"term": term, "definition": shorten(definition, 300)})
            if len(terms) >= limit:
                return terms
    return terms


def make_summary(blocks: list[Block], limit: int = 5) -> list[str]:
    """Выводы: первое предложение каждого из первых абзацев"""
    summary: list[str] = []
    for b in blocks:
        if b.level or b.text.lstrip().startswith(("```", "#include")) or "{" in b.text[:80]:
            continue
        first = sentences(b.text.split("\n")[0])
        if first and words(first[0]) >= 5:
            item = shorten(_LIST_ITEM.sub("", first[0]), 220)
            if item not in summary:
                summary.append(item)
        if len(summary) >= limit:
            break
    return summary


def make_section(title: str, blocks: list[Block], section_level: int) -> DraftSection:
    body_blocks = blocks
    text_blocks = [b for b in blocks if not b.level]
    paragraphs = [b for b in text_blocks if not _LIST_ITEM.match(b.text) and not b.text.startswith("```")]
    intro_src = (paragraphs or text_blocks or [Block(0, title)])[0].text
    intro = shorten(" ".join(sentences(intro_src)[:2]) or intro_src, 320)
    summary = make_summary(body_blocks) or [intro]
    body_words = sum(words(b.text) for b in text_blocks)
    missing = []
    if body_words < THIN_SECTION_WORDS:
        missing.append("В документе мало материала по этой теме: раздел стоит дополнить")
    chunk_ids = list(dict.fromkeys(b.chunk_id for b in blocks if b.chunk_id)) 
    content = {
        "title": title,
        "intro": intro,
        "content_md": _body_text(body_blocks, section_level) or intro,
        "terms": find_terms(body_blocks),
        "summary": summary,
        "questions": [],
        "source_chunk_ids": chunk_ids,
        "missing_info": missing,
    }
    return DraftSection(title, content, chunk_ids)


def split_sections(blocks: list[Block], section_level: int) -> list[tuple[str, list[Block]]]:
    """Список (название, абзацы)."""
    groups: list[tuple[str, list[Block]]] = []
    pending: list[Block] = []  # текст до первого заголовка
    cur_title: str | None = None
    cur: list[Block] = []
    for b in blocks:
        if b.level and b.level <= section_level:
            if cur_title is not None:
                groups.append((cur_title, cur))
            elif pending:
                groups.append(("Введение", pending))
            pending = []
            cur_title, cur = b.text, []
        elif cur_title is None:
            pending.append(b)
        else:
            cur.append(b)
    if cur_title is not None:
        groups.append((cur_title, cur))
    elif pending:
        groups.append(("Введение", pending))

    merged: list[tuple[str, list[Block]]] = []
    carry: list[Block] = []
    for title, body in groups:
        if sum(words(b.text) for b in body if not b.level) < MIN_SECTION_WORDS:
            carry.extend([Block(0, title, section_level + 1)] + body)  # название становится подзаголовком
            continue
        merged.append((title, carry + body))
        carry = []
    if carry:
        if merged:
            merged[-1] = (merged[-1][0], merged[-1][1] + carry)
        else:
            merged.append((groups[0][0], carry[1:]))
    return merged


def split_without_headings(blocks: list[Block], target_words: int = 450) -> list[tuple[str, list[Block]]]:
    groups: list[list[Block]] = []
    cur: list[Block] = []
    count = 0
    for b in blocks:
        cur.append(b)
        count += words(b.text)
        if count >= target_words:
            groups.append(cur)
            cur, count = [], 0
    if cur:
        if groups and count < target_words // 3:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    result = []
    for i, g in enumerate(groups, 1):
        first = sentences(g[0].text)
        label = shorten(first[0], 60) if first else ""
        result.append((f"Часть {i}. {label}" if label else f"Часть {i}", g))
    return result


def title_from_file(file_name: str) -> str:
    stem = PurePath(file_name).stem
    return re.sub(r"[_]+", " ", stem).strip() or "Учебный курс"


def build_draft_course(file_name: str, chunks: list[ChunkInput]) -> DraftCourse:
    blocks = to_blocks(chunks)
    doc_title, section_level = _pick_levels(blocks)
    if doc_title:
        blocks = [b for b in blocks if not (b.level and b.text == doc_title and b.level < section_level)]

    if section_level:
        groups = split_sections(blocks, section_level)
    else:
        groups = split_without_headings(blocks)
    sections = [make_section(t, bs, section_level or 1) for t, bs in groups if bs or t]

    title = doc_title or title_from_file(file_name)
    first_text = next((b for b in blocks if not b.level and words(b.text) >= 8), None)
    description = shorten(" ".join(sentences(first_text.text)[:3]), 400) if first_text else ""
    description = description or f"Учебный курс по документу «{file_name}»"
    goals = [f"Разобраться в теме: {s.title}" for s in sections[:8]] or ["Изучить материал документа"]
    return DraftCourse(title, description, goals, sections)
