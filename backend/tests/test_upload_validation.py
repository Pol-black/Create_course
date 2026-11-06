"""Проверки загрузки, которым не нужна база: формат, пустой файл, размер."""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    return tmp_path


def post(client, name: str, data: bytes):
    return client.post("/api/documents", files={"file": (name, data, "application/octet-stream")})


def test_unsupported_extension(client, upload_dir):
    response = post(client, "a.exe", b"data")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert list(upload_dir.iterdir()) == []


def test_old_doc_format_has_hint(client):
    response = post(client, "a.doc", b"data")
    assert response.status_code == 400
    assert "docx" in response.json()["error"]["message"].lower()


def test_empty_file(client, upload_dir):
    response = post(client, "a.txt", b"")
    assert response.status_code == 400
    assert list(upload_dir.iterdir()) == []


def test_too_large_file_is_removed(client, upload_dir, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    response = post(client, "a.txt", b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert list(upload_dir.iterdir()) == []
