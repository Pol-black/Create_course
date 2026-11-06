from sqlalchemy.exc import OperationalError

from app.db import get_db
from app.main import app


def test_live_does_not_touch_db(client):
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class BrokenSession:
    def execute(self, *_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("db down"))


def test_ready_503_when_db_down(client):
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/api/health/ready")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "unavailable"}


def test_unknown_path_has_unified_error_format(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]


def test_validation_error_format(client):
    response = client.get("/api/documents/abc")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_nonstandard_http_status_does_not_crash_handler(client):
    from fastapi import HTTPException

    @app.get("/api/_teapot_test")
    def _raise():
        raise HTTPException(599, "Странная ошибка")

    response = client.get("/api/_teapot_test")
    assert response.status_code == 599
    assert response.json()["error"]["message"] == "Странная ошибка"
