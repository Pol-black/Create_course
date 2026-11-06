"""Загрузка только сохраняет файл; обработка запускается отдельным запросом."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api import documents as api
from app.db import get_db
from app.main import app
from app.models import DocumentStatus, FileType


class FakeSession:
    def __init__(self, doc):
        self.doc = doc
        self.added = []

    def get(self, model, doc_id):
        return self.doc if self.doc is not None and self.doc.id == doc_id else None

    def add(self, obj):
        obj.id = 1
        obj.created_at = datetime(2026, 1, 1)
        obj.extracted_text = None
        obj.error_message = None
        self.doc = obj
        self.added.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass

    def scalar(self, *_):
        return 0


def make_doc(status, path):
    return SimpleNamespace(
        id=1, file_name="a.txt", file_type=FileType.TXT, file_size=10, file_path=str(path),
        status=status, error_message=None, extracted_text=None, created_at=datetime(2026, 1, 1),
    )


@pytest.fixture
def session():
    holder = FakeSession(None)
    app.dependency_overrides[get_db] = lambda: holder
    yield holder
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_background(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "process_document", lambda doc_id: calls.append(doc_id))
    monkeypatch.setattr(api, "write_log", lambda *a, **k: None)
    return calls


def test_upload_does_not_process(client, session, tmp_path, monkeypatch, no_background):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    response = client.post("/api/documents", files={"file": ("a.txt", b"x" * 300, "text/plain")})
    assert response.status_code == 201
    assert response.json()["status"] == "UPLOADED"
    assert no_background == []


def test_process_starts_background(client, session, tmp_path, no_background):
    f = tmp_path / "a.txt"
    f.write_text("text")
    session.doc = make_doc(DocumentStatus.UPLOADED, f)
    response = client.post("/api/documents/1/process")
    assert response.status_code == 202
    assert response.json()["status"] == "PROCESSING"
    assert no_background == [1]


def test_process_twice_is_conflict(client, session, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("text")
    session.doc = make_doc(DocumentStatus.PROCESSING, f)
    assert client.post("/api/documents/1/process").status_code == 409


def test_process_missing_file(client, session, tmp_path):
    session.doc = make_doc(DocumentStatus.UPLOADED, tmp_path / "gone.txt")
    response = client.post("/api/documents/1/process")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "file_missing"


def test_process_unknown_document(client, session):
    assert client.post("/api/documents/99/process").status_code == 404


def test_delete_while_processing_is_conflict(client, session, tmp_path):
    session.doc = make_doc(DocumentStatus.PROCESSING, tmp_path / "a.txt")
    assert client.delete("/api/documents/1").status_code == 409
