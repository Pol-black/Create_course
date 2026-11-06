"""TXT в разных кодировках и понятные ошибки."""

import pytest

from app.files.extract import ExtractError, extract_text
from app.models import FileType

TEXT = "Инструкция для оператора. Перед началом смены проверьте исправность оборудования и запишите результат в журнал."


@pytest.mark.parametrize(
    "encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1251", "cp866", "koi8-r"]
)
def test_encodings(tmp_path, encoding):
    path = tmp_path / "a.txt"
    data = TEXT.encode(encoding)
    if encoding in ("utf-16-le", "utf-16-be"):
        pass  # без BOM
    path.write_bytes(data)
    assert "Перед началом смены" in extract_text(path, FileType.TXT)


def test_short_txt_has_clear_message(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("Привет", encoding="utf-8")
    with pytest.raises(ExtractError) as exc:
        extract_text(path, FileType.TXT)
    assert exc.value.code == "too_short"
    assert "скан" not in str(exc.value)


def test_binary_is_rejected(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(bytes(range(256)) * 20)
    with pytest.raises(ExtractError):
        extract_text(path, FileType.TXT)
