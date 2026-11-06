"""
Деление текста на фрагменты (chunk). Без LLM.

Правила:
  * фрагмент заканчивается на границе абзаца, абзац пополам не режем
    (исключение: абзац длиннее максимума, его режем по предложениям);
  * новый заголовок начинает новый фрагмент, если в текущем уже достаточно слов;
  * заголовок никогда не остаётся «висеть» в конце фрагмента без текста;
  * у каждого фрагмента запоминаем заголовок и страницы (page_from, page_to);
  * совсем маленький хвост приклеивается к предыдущему фрагменту.
"""

import re
from dataclasses import dataclass

from app.files.clean import Para


@dataclass
class ChunkData:
    position: int
    heading: str | None
    page_from: int | None
    page_to: int | None
    text: str
    words: int


def count_words(text: str) -> int:
    return len(text.split())


def _split_long(text: str, limit: int) -> list[str]:
    """Режем слишком длинный абзац по предложениям, а если предложение одно — по словам."""
    sentences = re.split(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«\"(\d])", text)
    pieces: list[str] = []
    cur: list[str] = []
    cur_words = 0
    for sentence in sentences:
        n = count_words(sentence)
        if n > limit:  
            if cur:
                pieces.append(" ".join(cur))
                cur, cur_words = [], 0
            words = sentence.split()
            pieces.extend(" ".join(words[i:i + limit]) for i in range(0, len(words), limit))
            continue
        if cur_words + n > limit and cur:
            pieces.append(" ".join(cur))
            cur, cur_words = [], 0
        cur.append(sentence)
        cur_words += n
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def _render(paras: list[Para]) -> str:
    return "\n\n".join(("#" * p.level + " " + p.text) if p.level else p.text for p in paras)


def _pages(paras: list[Para]) -> tuple[int | None, int | None]:
    starts = [p.page_from for p in paras if p.page_from is not None]
    ends = [p.page_to for p in paras if p.page_to is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def split_into_chunks(
    paras: list[Para], *, target_words: int, max_words: int, min_words: int
) -> list[ChunkData]:
    items: list[Para] = []
    for p in paras:
        if not p.level and count_words(p.text) > max_words:
            items.extend(Para(piece, p.page_from, p.page_to) for piece in _split_long(p.text, target_words))
        else:
            items.append(p)

    groups: list[list[Para]] = []
    cur: list[Para] = []
    cur_words = 0

    def flush() -> None:
        """Закрыть фрагмент."""
        nonlocal cur, cur_words
        tail: list[Para] = []
        while cur and cur[-1].level:
            tail.insert(0, cur.pop())
        if cur:
            groups.append(cur)
            cur = tail
        else:
            cur = tail 
        cur_words = sum(count_words(p.text) for p in cur)

    for p in items:
        n = count_words(p.text)
        if p.level:
            body_words = sum(count_words(x.text) for x in cur if not x.level)
            if body_words >= min_words:
                flush()
        elif cur_words >= target_words or (cur_words + n > max_words and any(not x.level for x in cur)):
            flush()
        cur.append(p)
        cur_words += n
    flush()
    if cur:
        if groups:
            groups[-1].extend(cur)
        else:
            groups.append(cur)

    if len(groups) > 1:
        last_words = sum(count_words(p.text) for p in groups[-1] if not p.level)
        prev_words = sum(count_words(p.text) for p in groups[-2])
        if last_words < min_words and prev_words + last_words <= max_words * 1.3:
            groups[-2].extend(groups.pop())

    chunks: list[ChunkData] = []
    last_heading: str | None = None  
    for position, group in enumerate(groups):
        inner = next((p.text for p in group if p.level), None)
        heading = inner if group[0].level else (last_heading or inner)
        for p in group:
            if p.level:
                last_heading = p.text
        page_from, page_to = _pages(group)
        text = _render(group)
        chunks.append(ChunkData(position, heading, page_from, page_to, text, count_words(text)))
    return chunks
