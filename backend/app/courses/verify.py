"""
Защита от выдуманных сведений: проверка, что числа и латинские термины из текста раздела
есть в исходных фрагментах. Это дешёвая проверка по правилам, без повторного обращения к модели.
Она не доказывает правильность текста, но ловит самые частые выдумки: числа, имена функций, термины.
"""

import re
from typing import Any

NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
LIST_MARK = re.compile(r"^\s*(?:\d+[.)]\s+|[-*•]\s+|#{1,6}\s+)", re.M)

MAX_REPORTED = 12


def _texts(content: dict[str, Any]) -> list[str]:
    parts = [content.get("intro", ""), content.get("content_md", "")]
    parts += content.get("summary", [])
    parts += [f"{t['term']} {t['definition']}" for t in content.get("terms", [])]
    for q in content.get("questions", []):
        parts += [q["question"], q.get("explanation", ""), *q["options"]]
    return [p for p in parts if p]


def _norm_number(value: str) -> str:
    return value.replace(",", ".")


def find_unsupported(content: dict[str, Any], source_text: str) -> list[str]:
    """Числа и латинские слова из раздела, которых нет в источнике (в порядке появления)."""
    source_lower = source_text.lower()
    source_numbers = {_norm_number(n) for n in NUMBER.findall(source_text)}
    seen: set[str] = set()
    missing: list[str] = []

    def add(item: str) -> None:
        if item not in seen:
            seen.add(item)
            missing.append(item)

    for text in _texts(content):
        text = LIST_MARK.sub("", text)  # номера пунктов списка и заголовки числами не считаем
        for n in NUMBER.findall(text):
            if len(n) >= 2 and _norm_number(n) not in source_numbers:  # одиночные цифры слишком шумные
                add(n)
        for word in LATIN.findall(text):
            if word.lower() not in source_lower:
                add(word)
    return missing[:MAX_REPORTED]


def check_section(content: dict[str, Any], source_text: str, allowed_chunk_ids: set[int]) -> dict[str, Any]:
    """Результат проверки раздела: записывается в section_version.check_result."""
    unknown = [c for c in content.get("source_chunk_ids", []) if c not in allowed_chunk_ids]
    unsupported = find_unsupported(content, source_text)
    return {"ok": not unknown and not unsupported, "unknown_chunk_ids": unknown, "unsupported": unsupported}
