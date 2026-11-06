"""Очистка текста и деление на фрагменты: правила без LLM."""

from app.files.chunking import split_into_chunks
from app.files.clean import prepare_document, render_text
from app.files.extract import Page
from app.models import FileType

BODY = (
    "Оператор обязан проверить исправность оборудования перед началом смены и записать результат "
    "проверки в журнал. Если обнаружена неисправность, работа не начинается."
)


def pdf_pages(n=4):
    pages = []
    for i in range(1, n + 1):
        text = f"Инструкция по охране труда\n{BODY} Пункт номер {'один два три четыре'.split()[i - 1]}.\nСтраница {i} из {n}"
        pages.append(Page(i, text, {}))
    return pages


def test_headers_footers_and_page_numbers_removed():
    text = render_text(prepare_document(pdf_pages(), FileType.PDF))
    assert "Инструкция по охране труда" not in text
    assert "Страница 2 из 4" not in text
    assert "Оператор обязан" in text


def test_dehyphenation_and_reflow():
    # Текст, обрезанный по ширине около 60 символов, как в старых TXT
    sentence = "Оператор обязан проверить исправность оборудования перед началом смены и записать результат."
    lines = []
    for _ in range(4):
        lines += ["Оператор обязан проверить исправность обору-", "дования перед началом смены и записать резуль-", "тат проверки в журнал, затем доложить мастеру."]
    text = render_text(prepare_document([Page(1, "\n".join(lines), {})], FileType.TXT))
    assert "оборудования перед началом смены" in text
    assert "результат проверки в журнал" in text
    assert "обору-" not in text


def test_toc_removed():
    toc = "Оглавление\n1. Введение ........ 3\n2. Правила ........ 5\n3. Заключение ........ 9"
    body = "Введение\n" + BODY * 3
    text = render_text(prepare_document([Page(1, toc, {}), Page(2, body, {})], FileType.PDF))
    assert "........" not in text
    assert "Оператор обязан" in text


def test_markdown_headings_in_txt():
    raw = "# Правила\n\n" + BODY + "\n\n## Исключения\n\n" + BODY
    paras = prepare_document([Page(1, raw, {})], FileType.TXT)
    assert [(p.level, p.text) for p in paras if p.level] == [(1, "Правила"), (2, "Исключения")]


def test_chunks_keep_pages_and_headings():
    paras = prepare_document(
        [Page(1, "# Первая тема\n\n" + (BODY + "\n\n") * 6, {}), Page(2, "# Вторая тема\n\n" + (BODY + "\n\n") * 6, {})],
        FileType.DOCX,
    )
    chunks = split_into_chunks(paras, target_words=60, max_words=120, min_words=10)
    assert len(chunks) >= 2
    assert [c.position for c in chunks] == list(range(len(chunks)))
    assert chunks[0].heading == "Первая тема"
    assert chunks[0].page_from == 1
    assert chunks[-1].page_to == 2
    assert all(c.words <= 120 for c in chunks)


def test_no_text_is_lost_in_chunks():
    paras = prepare_document([Page(1, (BODY + "\n\n") * 10, {})], FileType.TXT)
    chunks = split_into_chunks(paras, target_words=40, max_words=80, min_words=10)
    assert sum(c.words for c in chunks) >= sum(len(p.text.split()) for p in paras if not p.level)
