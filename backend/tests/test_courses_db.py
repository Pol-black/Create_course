"""
Курсы через API на настоящей базе: создание примера, правка, версии, порядок, удаление, экспорт.
Тесты пропускаются, если база недоступна (запускайте в Docker: docker compose exec backend pytest).
"""

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Document


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.execute(text("select 1 from course limit 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="нет доступной базы данных с миграциями")


@pytest.fixture
def course(client, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    response = client.post("/api/courses/example")
    assert response.status_code == 201, response.text
    data = response.json()
    yield data
    with SessionLocal() as s:  # курс и всё его содержимое удаляются каскадом
        for doc in s.query(Document).filter(Document.id == data["document"]["id"]):
            s.delete(doc)
        s.commit()


def test_example_is_created_once(client, course):
    again = client.post("/api/courses/example")
    assert again.json()["id"] == course["id"]
    assert len(course["sections"]) >= 8
    assert [s["position"] for s in course["sections"]] == list(range(len(course["sections"])))


def test_course_survives_reload(client, course):
    loaded = client.get(f"/api/courses/{course['id']}").json()
    assert loaded["title"] == course["title"]
    assert loaded["sections"][0]["content"]["content_md"]
    assert any(c["id"] == course["id"] for c in client.get("/api/courses").json())


def test_edit_creates_new_version_and_keeps_old(client, course):
    section = course["sections"][0]
    assert section["versions_count"] == 1
    edited = client.patch(f"/api/sections/{section['id']}", json={"title": "Новое название", "content_md": "Мой текст"})
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["title"] == "Новое название" and body["content"]["content_md"] == "Мой текст"
    assert body["version_no"] == 2 and body["author"] == "USER"
    assert body["content"]["source_chunk_ids"] == section["content"]["source_chunk_ids"]

    versions = client.get(f"/api/sections/{section['id']}/versions").json()
    assert [v["version_no"] for v in versions] == [2, 1]
    assert versions[1]["content"]["content_md"] == section["content"]["content_md"]


def test_unchanged_save_does_not_create_version(client, course):
    section = course["sections"][0]
    client.patch(f"/api/sections/{section['id']}", json={"intro": section["content"]["intro"]})
    assert client.get(f"/api/sections/{section['id']}/versions").json().__len__() == 1


def test_invalid_edit_is_rejected(client, course):
    section = course["sections"][0]
    bad = {"questions": [{"question": "?", "options": ["а", "б"], "correct_index": 9, "explanation": "п"}]}
    assert client.patch(f"/api/sections/{section['id']}", json=bad).status_code == 422
    assert client.patch(f"/api/sections/{section['id']}", json={"title": ""}).status_code == 422


def test_restore_old_version(client, course):
    section = course["sections"][0]
    original = section["content"]["content_md"]
    client.patch(f"/api/sections/{section['id']}", json={"content_md": "Другое"})
    first = [v for v in client.get(f"/api/sections/{section['id']}/versions").json() if v["version_no"] == 1][0]
    restored = client.post(f"/api/sections/{section['id']}/versions/{first['id']}/restore").json()
    assert restored["content"]["content_md"] == original
    assert restored["version_no"] == 3  # история не стирается


def test_reorder_sections(client, course):
    ids = [s["id"] for s in course["sections"]]
    new = [ids[1], ids[0]] + ids[2:]
    result = client.put(f"/api/courses/{course['id']}/order", json={"section_ids": new})
    assert result.status_code == 200, result.text
    assert [s["id"] for s in result.json()["sections"]] == new
    assert [s["position"] for s in result.json()["sections"]] == list(range(len(new)))
    # порядок сохранён в базе
    assert [s["id"] for s in client.get(f"/api/courses/{course['id']}").json()["sections"]] == new


def test_reorder_rejects_wrong_list(client, course):
    ids = [s["id"] for s in course["sections"]]
    assert client.put(f"/api/courses/{course['id']}/order", json={"section_ids": ids[:-1]}).status_code == 422


def test_add_and_delete_section(client, course):
    count = len(course["sections"])
    added = client.post(f"/api/courses/{course['id']}/sections", json={"title": "Свой раздел"}).json()
    assert len(added["sections"]) == count + 1
    new = added["sections"][-1]
    assert new["title"] == "Свой раздел" and new["content"]["content_md"] == ""

    assert client.delete(f"/api/sections/{course['sections'][0]['id']}").status_code == 204
    after = client.get(f"/api/courses/{course['id']}").json()
    assert len(after["sections"]) == count
    assert [s["position"] for s in after["sections"]] == list(range(count))


def test_edit_course_description(client, course):
    result = client.patch(f"/api/courses/{course['id']}", json={"title": "Мой курс", "goals": ["а", " ", "б"]}).json()
    assert result["title"] == "Мой курс" and result["goals"] == ["а", "б"]


def test_export_markdown(client, course):
    response = client.get(f"/api/courses/{course['id']}/export.md")
    assert response.status_code == 200
    assert response.text.startswith("# ")
    assert course["sections"][0]["title"] in response.text


def test_regenerate_without_llm_key_gives_clear_error(client, course, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")
    response = client.post(f"/api/sections/{course['sections'][0]['id']}/regenerate", json={"hint": ""})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_no_api_key"


def test_unknown_ids_give_404(client, course):
    assert client.get("/api/courses/999999").status_code == 404
    assert client.patch("/api/sections/999999", json={"title": "x"}).status_code == 404
