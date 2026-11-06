import docx
import pytest

from app.config import settings
from app.files.extract import ExtractError, clean_text, extract_text
from app.models import FileType

TEXT = "Первый абзац инструкции.\n\nВторой абзац инструкции с достаточным количеством текста."


def test_clean_text_normalizes_whitespace():
    raw = "строка   \r\n\r\n\r\n\r\nещё строка\r\n"
    assert clean_text(raw) == "строка\n\nещё строка"


def test_txt_utf8(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(TEXT, encoding="utf-8")
    assert "Второй абзац" in extract_text(path, FileType.TXT)


def test_txt_cp1251(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(TEXT.encode("cp1251"))
    assert "Первый абзац" in extract_text(path, FileType.TXT)


def test_docx_paragraphs_and_tables(tmp_path):
    path = tmp_path / "a.docx"
    document = docx.Document()
    document.add_paragraph(TEXT)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Ячейка А"
    table.rows[0].cells[1].text = "Ячейка Б"
    document.save(path)
    text = extract_text(path, FileType.DOCX)
    assert "Первый абзац" in text
    assert "Ячейка А | Ячейка Б" in text


def test_too_short_txt_is_clear_error(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("коротко", encoding="utf-8")
    with pytest.raises(ExtractError) as exc:
        extract_text(path, FileType.TXT)
    assert exc.value.code == "too_short"


def test_broken_docx_is_clear_error(tmp_path):
    path = tmp_path / "a.docx"
    path.write_bytes(b"not a docx")
    with pytest.raises(ExtractError) as exc:
        extract_text(path, FileType.DOCX)
    assert exc.value.code == "bad_docx"


def test_broken_pdf_is_clear_error(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ExtractError) as exc:
        extract_text(path, FileType.PDF)
    assert exc.value.code == "bad_pdf"


def test_min_text_chars_comes_from_settings():
    assert settings.min_text_chars == 50


# --- страницы PDF ---

from pypdf import PdfWriter  # noqa: E402

from app.files.extract import extract_pages  # noqa: E402
from tests.pdfmaker import make_pdf  # noqa: E402


def test_pdf_keeps_page_numbers(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf(["First page of the instruction manual", "Second page of the instruction manual"]))
    pages = extract_pages(path, FileType.PDF)
    assert [p.number for p in pages] == [1, 2]
    assert "Second page" in pages[1].text


def test_pdf_empty_pages_are_dropped_but_numbers_kept(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf(["Page one has enough text to pass the minimum check", "", "Page three also has text"]))
    assert [p.number for p in extract_pages(path, FileType.PDF)] == [1, 3]


def test_docx_and_txt_pages_have_no_numbers(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(TEXT, encoding="utf-8")
    pages = extract_pages(path, FileType.TXT)
    assert len(pages) == 1 and pages[0].number is None


def test_password_protected_pdf_gives_password_error(tmp_path):
    path = tmp_path / "locked.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    with path.open("wb") as out:
        writer.write(out)
    with pytest.raises(ExtractError) as exc:
        extract_text(path, FileType.PDF)
    assert exc.value.code == "encrypted_pdf"
