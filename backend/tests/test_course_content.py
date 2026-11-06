"""Содержимое раздела: правки, порядок, экспорт, пример курса. Без базы данных."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.courses import content as C

EXAMPLE = Path(__file__).parent.parent / "app" / "courses" / "example"

CURRENT = {
    "title": "Тема", "intro": "Кратко", "content_md": "Текст", "terms": [], "summary": ["вывод"],
    "questions": [], "source_chunk_ids": [1, 2], "missing_info": [],
}


def test_merge_changes_only_given_fields():
    new = C.merge_content(CURRENT, C.ContentPatch(content_md="Новый текст"))
    assert new["content_md"] == "Новый текст"
    assert new["title"] == "Тема" and new["summary"] == ["вывод"]


def test_merge_keeps_sources():
    new = C.merge_content(CURRENT, C.ContentPatch(title="Другое название"))
    assert new["source_chunk_ids"] == [1, 2]


def test_blank_title_is_rejected():
    with pytest.raises(ValidationError):
        C.ContentPatch(title="")


def test_blank_summary_items_are_dropped():
    new = C.merge_content(CURRENT, C.ContentPatch(summary=["один", "  ", "", "два"]))
    assert new["summary"] == ["один", "два"]


def test_question_with_wrong_correct_index_is_rejected():
    with pytest.raises(ValidationError):
        C.ContentPatch(questions=[{"question": "?", "options": ["а", "б"], "correct_index": 5, "explanation": "п"}])


def test_valid_question_is_saved():
    patch = C.ContentPatch(questions=[{"question": "?", "options": ["а", "б"], "correct_index": 1, "explanation": "п"}])
    assert C.merge_content(CURRENT, patch)["questions"][0]["correct_index"] == 1


def test_content_equal_ignores_whitespace():
    changed = C.merge_content(CURRENT, C.ContentPatch(content_md="  Текст  "))
    assert C.content_equal(CURRENT, changed)


def test_empty_content_for_new_section():
    content = C.empty_content("Новый")
    assert content["title"] == "Новый" and content["content_md"] == "" and content["source_chunk_ids"] == []


def test_permutation_check():
    C.check_permutation([3, 1, 2], [1, 2, 3])
    for bad in ([1, 2], [1, 2, 2], [1, 2, 4], [1, 2, 3, 3]):
        with pytest.raises(ValueError):
            C.check_permutation(bad, [1, 2, 3])


def test_export_markdown_contains_everything():
    course = {
        "title": "Курс", "description": "Описание", "goals": ["цель"],
        "sections": [{"title": "Раздел", "content": {
            **CURRENT, "terms": [{"term": "Т", "definition": "О"}],
            "questions": [{"question": "В?", "options": ["а", "б"], "correct_index": 0, "explanation": "п"}],
            "missing_info": ["нет данных"],
        }}],
    }
    md = C.export_markdown(course)
    for part in ("# Курс", "- цель", "## 1. Раздел", "**Т** — О", "- вывод", "- [x] а", "- [ ] б", "нет данных"):
        assert part in md


def test_example_course_is_valid_and_complete():
    data = json.loads((EXAMPLE / "course.json").read_text(encoding="utf-8"))
    chunks = json.loads((EXAMPLE / "chunks.json").read_text(encoding="utf-8"))
    positions = {c["position"] for c in chunks}
    assert len(data["sections"]) >= 8
    for section in data["sections"]:
        content = C.SectionContentIn.model_validate(section["content"])
        assert len(content.content_md.split()) > 40  # есть содержательный текст, а не только заголовок
        assert content.summary and content.questions
        assert section["chunk_positions"] and set(section["chunk_positions"]) <= positions


def test_example_pdf_is_shipped():
    assert (EXAMPLE / "MPI.pdf").stat().st_size > 1000
