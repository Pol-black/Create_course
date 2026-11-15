import tempfile
from pathlib import Path

import docx
from pypdf import PdfWriter

from app.files.extract import ExtractError, extract_text
from app.models import FileType

SAMPLE = "Это проверочный документ для прототипа системы создания курсов."


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)

        # 1. TXT
        txt = folder / "sample.txt"
        txt.write_text(SAMPLE, encoding="utf-8")
        assert SAMPLE in extract_text(txt, FileType.TXT)
        print("TXT: текст извлечён")

        # 2. DOCX 
        docx_path = folder / "sample.docx"
        document = docx.Document()
        document.add_paragraph(SAMPLE)
        document.save(str(docx_path))
        assert SAMPLE in extract_text(docx_path, FileType.DOCX)
        print("DOCX: текст извлечён")

        # 3. PDF без текстового слоя
        pdf_path = folder / "empty.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)  # лист A4
        with pdf_path.open("wb") as out:
            writer.write(out)
        try:
            extract_text(pdf_path, FileType.PDF)
        except ExtractError as exc:
            print(f"PDF без текста: получили ожидаемую ошибку — {exc.message}")
        else:
            raise AssertionError("Пустой PDF должен был вызвать ExtractError")

    print("Проверка пройдена.")


if __name__ == "__main__":
    main()