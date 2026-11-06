"""
Очистка и структурирование текста. 
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.files.extract import Page, norm_line
from app.models import FileType


@dataclass
class Para:
    """Абзац или заголовок"""

    text: str
    page_from: int | None
    page_to: int | None
    level: int = 0


# символы

_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
_SPACES = re.compile("[   -   　\t]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE_BULLET = re.compile(r"(?m)^[ ]*[\ue000-\uf8ff]+[ ]*")  
_PRIVATE = re.compile(r"[\ue000-\uf8ff]")
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def normalize_chars(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = _INVISIBLE.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _CONTROL.sub("", text)
    text = _PRIVATE_BULLET.sub("• ", text)
    text = _PRIVATE.sub("", text)
    for ligature, plain in _LIGATURES.items():
        text = text.replace(ligature, plain)
    return text


# колонтитулы

_PAGE_NUMBER = re.compile(
    r"^(?:[-–—\s]*\d{1,4}[-–—\s]*"
    r"|(?:стр\.?|страница|с\.|page|p\.)\s*\d{1,4}(?:\s*(?:из|of|/)\s*\d{1,4})?"
    r"|\d{1,4}\s*(?:из|of|/)\s*\d{1,4})$",
    re.IGNORECASE,
)


def _line_key(line: str) -> str:
    """Строка без номеров"""
    return re.sub(r"\d+", "#", norm_line(line).lower())


def _code_indices(lines: list[str]) -> set[int]:
    """Номера строк внутри блоков кода."""
    inside: set[int] = set()
    opened = False
    for i, line in enumerate(lines):
        if line.strip() == "```":
            inside.add(i)
            opened = not opened
        elif opened:
            inside.add(i)
    return inside


def strip_page_noise(pages: list[tuple[int | None, list[str]]]) -> list[tuple[int | None, list[str]]]:
    """Убрать номера страниц и колонтитулы."""
    count = len(pages)
    edges: list[list[int]] = []
    counter: Counter = Counter()
    for _, lines in pages:
        code = _code_indices(lines)
        nonblank = [i for i, line in enumerate(lines) if line.strip() and i not in code]
        candidates = list(dict.fromkeys(nonblank[:3] + nonblank[-3:]))
        edges.append(candidates)
        counter.update({_line_key(lines[i]) for i in candidates})

    threshold = max(3, math.ceil(0.4 * count))
    repeated = {key for key, n in counter.items() if count >= 3 and n >= threshold and key}

    result = []
    for (number, lines), candidates in zip(pages, edges):
        code = _code_indices(lines)
        nonblank = [i for i, line in enumerate(lines) if line.strip() and i not in code]
        near_edge = set(nonblank[:2] + nonblank[-2:])
        drop = set()
        for i in candidates:
            if _line_key(lines[i]) in repeated:
                drop.add(i)
        for i in near_edge:
            if _PAGE_NUMBER.match(norm_line(lines[i])):
                drop.add(i)
        result.append((number, [line for i, line in enumerate(lines) if i not in drop]))
    return result


# оглавление

_TOC_TITLE = re.compile(r"^(?:содержание|оглавление|contents|table of contents)\.?$", re.IGNORECASE)
_TOC_LEADER = re.compile(r"(?:\.{3,}|…+|(?:\. ){3,}|_{3,})\s*\d{1,4}\s*$")
_TOC_SPACES = re.compile(r"\S\s{4,}\d{1,4}\s*$")


def _is_toc_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 6:
        return False
    return bool(_TOC_LEADER.search(s)) or (bool(_TOC_SPACES.search(s)) and s[0].isalnum())


def remove_toc(items: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    nonblank = [i for i, (_, line) in enumerate(items) if line.strip()]
    matches = [i for i in nonblank if _is_toc_line(items[i][1])]
    if len(matches) < 3:
        return items

    position = {idx: n for n, idx in enumerate(nonblank)}
    groups: list[list[int]] = [[matches[0]]]
    for idx in matches[1:]:
        gap = position[idx] - position[groups[-1][-1]] - 1
        if gap <= 1:
            groups[-1].append(idx)
        else:
            groups.append([idx])

    drop: set[int] = set()
    for group in groups:
        if len(group) < 3:
            continue
        start, end = group[0], group[-1]
        for back in nonblank[max(0, position[start] - 2): position[start]]:
            if _TOC_TITLE.match(norm_line(items[back][1])):
                start = back
                break
        drop.update(range(start, end + 1))
    return [item for i, item in enumerate(items) if i not in drop]


# абзацы и заголовки

_LIST_ITEM = re.compile(
    r"^(?:[•●▪■◦·*\-–—]\s+|\d{1,3}[.)]\s+|[a-zа-я]\)\s+|\(\d{1,3}\)\s+"
    r"|\d{1,3}(?:\.\d{1,3})+\.?\s+|\d{1,3}(?:\.\d{1,3})+\.(?=[A-Za-zА-Яа-яЁё]))",
    re.IGNORECASE,
)
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_KEYWORD_HEADING = re.compile(
    r"^(?:глава|раздел|часть|приложение|chapter|section|appendix)\s+[\dIVXLCА-Я]+[.:)]?(?:\s|$)",
    re.IGNORECASE,
)
_MULTI_NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)\.?\s+([A-ZА-ЯЁ].{1,98})$")
_SINGLE_NUMBERED = re.compile(r"^\d{1,2}[.)]\s+([A-ZА-ЯЁ].{1,78})$")
_TERMINAL = re.compile(r"[.,;:!?…]$")
_SENTENCE_END = re.compile(r"[.!?…»\"”)\]]$")
_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
_KEEP_HYPHEN_AFTER = {"то", "либо", "нибудь", "таки", "кое", "же", "ка", "с"}  # кто-то, что-нибудь


def looks_hard_wrapped(lines: list[str]) -> bool:
    """TXT: строки обрезаны по ширине"""
    lengths = sorted(len(s.strip()) for s in lines if len(s.strip()) >= 15)
    if len(lengths) < 6:
        return False
    p90 = lengths[int(0.9 * (len(lengths) - 1))]
    if p90 < 45 or p90 > 130:  # очень длинные строки — это абзацы, а не перенос по ширине
        return False
    near_width = sum(1 for n in lengths if n >= 0.8 * p90)
    return near_width / len(lengths) >= 0.5


def _line_width(items: list[tuple[int | None, str]]) -> int:
    lengths = sorted(
        len(line.strip())
        for _, line in items
        if len(line.strip()) >= 15 and not _LIST_ITEM.match(line.strip())
    )
    if not lengths:
        return 80
    return max(40, lengths[int(0.9 * (len(lengths) - 1))])


def _unescape(line: str) -> str:
    return line[1:] if line.startswith("\\#") else line


def _join_lines(lines: list[str]) -> str:
    """Склеить строки абзаца."""
    out = lines[0]
    for nxt in lines[1:]:
        hyphenated = re.search(r"[A-Za-zА-Яа-яЁё]-$", out) and not out.endswith(" -")
        first_word = re.match(r"[a-zа-яё]+", nxt)
        if hyphenated and first_word and first_word.group(0) not in _KEEP_HYPHEN_AFTER:
            out = out[:-1] + nxt
        else:
            out = out + " " + nxt
    return re.sub(r" {2,}", " ", out).strip()


def _plausible_heading(text: str) -> bool:
    """Отсеять обрывки таблиц и кода."""
    t = text.strip()
    if len(t) < 2 or t[0].islower() or t.count("(") != t.count(")"):
        return False
    last = re.findall(r"[A-Za-zА-Яа-яЁё]+$", t)
    return not (last and last[0].islower() and len(last[0]) <= 2)  # «… Работа с»


def _heading_level(
    s: str, *, at_start: bool, prev_blank: bool, next_s: str,
    hints: dict[str, int], has_hints: bool, is_pdf: bool, markdown: bool,
    followed_blank: bool = True,
) -> tuple[int, str]:
    if len(s) > 150:
        return 0, s
    if markdown:
        m = _MARKDOWN_HEADING.match(s)
        if m:
            return min(len(m.group(1)), 4), m.group(2).strip()
    key = norm_line(s)
    if key in hints and _plausible_heading(s):
        return hints[key], s
    if len(key) >= 8 and not _LIST_ITEM.match(s):
        squeezed = key.replace(" ", "")
        for hint, level in hints.items():  
            if len(hint) > len(key) and squeezed in hint.replace(" ", "") and _plausible_heading(s):
                return level, s
    if not at_start:
        return 0, s

    if _KEYWORD_HEADING.match(s) and len(s) <= 100:
        return 1, s
    if has_hints:
        return 0, s 
    m = _MULTI_NUMBERED.match(s)
    if m and not re.search(r"[.,;]$", s) and _plausible_heading(s):
        return min(m.group(1).count(".") + 1, 4), s
    if not has_hints:
        m = _SINGLE_NUMBERED.match(s)
        if (
            m and not _TERMINAL.search(s) and len(s.split()) <= 9
            and not (next_s and _LIST_ITEM.match(next_s))
        ):
            return 1, s
    if _LIST_ITEM.match(s):
        return 0, s  
    letters = _LETTER.findall(s)
    if (
        len(letters) >= 3 and s.upper() == s and len(s) <= 80 and len(s.split()) <= 10
        and not _TERMINAL.search(s) and " | " not in s
    ):
        return 1, s
    if (
        not is_pdf and prev_blank and next_s and len(s) <= 60 and len(s.split()) <= 6
        and s[0].isupper() and not _TERMINAL.search(s) and len(next_s) > len(s)
        and not _LIST_ITEM.match(s) and " | " not in s
        and followed_blank and not s.endswith("-")
    ):
        return 2, s
    return 0, s


def build_paragraphs(
    items: list[tuple[int | None, str]], *, hard_wrapped: bool,
    hints: dict[str, int], is_pdf: bool,
) -> list[Para]:
    """Из строк собрать абзацы и заголовки."""
    width = _line_width(items) if hard_wrapped else 0
    explicit = not is_pdf and any(_MARKDOWN_HEADING.match(line.strip()) for _, line in items)
    has_hints = bool(hints) or explicit
    paras: list[Para] = []
    cur: list[str] = []
    pages: list[int | None] = []

    def flush() -> None:
        if cur:
            paras.append(Para(_join_lines(cur), pages[0], pages[-1]))
            cur.clear()
            pages.clear()

    def starts_list() -> bool:
        return bool(cur) and bool(_LIST_ITEM.match(cur[0]))

    prev_blank = True
    last_heading_idx = -1 
    code: list[str] | None = None 
    code_pages: list[int | None] = []
    for idx, (page, line) in enumerate(items):
        s = line.strip()
        if s == "```":
            if code is None:
                flush()
                code, code_pages = [], []
            else:
                paras.append(Para("```\n" + "\n".join(code) + "\n```", code_pages[0] if code_pages else page, page))
                code = None
            prev_blank = True
            continue
        if code is not None:
            code.append(line.rstrip())
            code_pages.append(page)
            continue
        if not s:
            flush()
            prev_blank = True
            continue

        next_s = next((l.strip() for _, l in items[idx + 1: idx + 4] if l.strip()), "")
        level, text = _heading_level(
            s, at_start=not cur, prev_blank=prev_blank, next_s=next_s,
            hints=hints, has_hints=has_hints, is_pdf=is_pdf, markdown=not is_pdf,
            followed_blank=not hard_wrapped or idx + 1 >= len(items) or not items[idx + 1][1].strip(),
        )
        prev_blank = False
        if level:
            flush()
            wrapped = (
                paras and paras[-1].level == level and last_heading_idx >= 0
                and all(not items[k][1].strip() for k in range(last_heading_idx + 1, idx))
                and not _LIST_ITEM.match(s) and not _KEYWORD_HEADING.match(s)
                and not _TERMINAL.search(paras[-1].text) and s[:1].islower()
            )
            if wrapped: 
                paras[-1].text += " " + text
                paras[-1].page_to = page
            else:
                paras.append(Para(text, page, page, level))
            last_heading_idx = idx
            continue

        s = _unescape(s)
        if not hard_wrapped:
            paras.append(Para(s, page, page)) 
            continue

        if _LIST_ITEM.match(s) or " | " in s:
            flush()  
        cur.append(s)
        pages.append(page)

        short = len(s) < 0.55 * width
        semi = len(s) < 0.8 * width and bool(_SENTENCE_END.search(s))
        item_end = starts_list() and bool(re.search(r"[.;!?…]$", s))
        colon_end = s.endswith(":") and len(s) < 0.9 * width
        if short or semi or item_end or colon_end:
            flush()
    if code:
        paras.append(Para("```\n" + "\n".join(code) + "\n```", code_pages[0], code_pages[-1]))
    flush()
    return paras


def render_text(paras: list[Para]) -> str:
    return "\n\n".join(("#" * p.level + " " + p.text) if p.level else p.text for p in paras)


def _group_table_rows(paras: list[Para]) -> list[Para]:
    def is_row(p: Para) -> bool:
        return not p.level and " | " in p.text and "\n" not in p.text and not p.text.startswith("```")

    out: list[Para] = []
    for p in paras:
        if p.text.startswith("```") and out and out[-1].text.startswith("```") and not p.level:
            out[-1] = Para(out[-1].text[:-4] + "\n" + p.text[4:], out[-1].page_from, p.page_to)
            continue
        if is_row(p) and out and is_row(out[-1]) or (is_row(p) and out and out[-1].level == 0 and "\n" in out[-1].text and all(" | " in l for l in out[-1].text.split("\n"))):
            out[-1] = Para(out[-1].text + "\n" + p.text, out[-1].page_from, p.page_to)
        else:
            out.append(p)
    return out


def prepare_document(pages: list[Page], file_type: FileType) -> list[Para]:
    is_pdf = file_type == FileType.PDF

    page_lines = [(p.number, normalize_chars(p.text).split("\n")) for p in pages]
    if is_pdf:
        page_lines = strip_page_noise(page_lines)

    items = [(number, line) for number, lines in page_lines for line in lines]
    items = remove_toc(items)

    hints: dict[str, int] = {}
    for p in pages:
        hints.update(p.headings)

    if is_pdf:
        hard = True
    elif file_type == FileType.TXT:
        hard = looks_hard_wrapped([line for _, line in items])
    else:
        hard = False  

    paras = build_paragraphs(items, hard_wrapped=hard, hints=hints, is_pdf=is_pdf)
    paras = _group_table_rows([p for p in paras if p.text])

    used = sorted({p.level for p in paras if p.level})
    rank = {level: i + 1 for i, level in enumerate(used)}
    for p in paras:
        if p.level:
            p.level = rank[p.level]
    return paras
