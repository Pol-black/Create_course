import json

import httpx
import openai
import pytest

from app.llm.errors import LLMError
from app.llm.prompts import load_prompt
from app.llm.schemas import CourseOutline, SectionContent
from app.llm.service import LLMService, extract_json
from tests.fakes import FakeClient, make_response

OUTLINE = {
    "title": "Работа с кофемолкой",
    "description": "Короткий курс для новых владельцев.",
    "goals": ["Назвать детали", "Молоть кофе по инструкции"],
    "sections": [{"title": "Безопасность", "chunk_ids": [1]}],
}

SECTION = {
    "title": "Безопасность",
    "intro": "Зачем соблюдать правила.",
    "content_md": "1. Не включайте пустую кофемолку.",
    "terms": [],
    "summary": ["Не включать пустой"],
    "questions": [
        {"question": "Что нельзя?", "options": ["А", "Б"], "correct_index": 1, "explanation": "Так в тексте."}
    ],
    "source_chunk_ids": [1],
    "missing_info": [],
}


def service(replies, **kwargs) -> tuple[LLMService, FakeClient]:
    fake = FakeClient(replies)
    kwargs.setdefault("json_mode", False)
    kwargs.setdefault("json_attempts", 2)
    return LLMService(client=fake, model="test/model", **kwargs), fake


def request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


# --- разбор JSON ---

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_in_markdown_fence():
    assert extract_json('Вот ответ:\n```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.parametrize("text", ["", "   ", "просто текст", "{не json"])
def test_extract_json_rejects_garbage(text):
    with pytest.raises(ValueError):
        extract_json(text)


# --- промпты ---

def test_prompt_substitutes_variables_and_keeps_json_braces():
    system, user = load_prompt("course_outline", chunks="[1] Заголовок: текст")
    assert "[1] Заголовок: текст" in user
    assert '"sections"' in system  # фигурные скобки примера JSON не сломались


def test_prompt_missing_variable_is_error():
    with pytest.raises(LLMError) as exc:
        load_prompt("course_outline")
    assert exc.value.code == "llm_prompt_variable"


# --- схемы ---

def test_question_correct_index_must_exist():
    bad = {**SECTION, "questions": [{**SECTION["questions"][0], "correct_index": 5}]}
    with pytest.raises(ValueError):
        SectionContent.model_validate(bad)


def test_outline_requires_sections():
    with pytest.raises(ValueError):
        CourseOutline.model_validate({**OUTLINE, "sections": []})


# --- generate ---

def test_generate_ok():
    llm, fake = service([json.dumps(OUTLINE)])
    result = llm.generate("course_outline", CourseOutline, chunks="[1] текст")
    assert result.data.title == "Работа с кофемолкой"
    assert result.model == "test/model"
    assert result.prompt_name == "course_outline"
    assert result.attempts == 1
    assert fake.calls[0]["temperature"] == llm.temperature


def test_generate_retries_after_broken_json():
    llm, fake = service(["это не json", json.dumps(OUTLINE)])
    result = llm.generate("course_outline", CourseOutline, chunks="x")
    assert result.attempts == 2
    # во втором запросе модели показали её ответ и ошибку
    roles = [m["role"] for m in fake.calls[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_generate_retries_after_schema_violation():
    llm, _ = service([json.dumps({**OUTLINE, "sections": []}), json.dumps(OUTLINE)])
    assert llm.generate("course_outline", CourseOutline, chunks="x").attempts == 2


def test_generate_gives_up_after_attempts():
    llm, fake = service(["плохо", "опять плохо"])
    with pytest.raises(LLMError) as exc:
        llm.generate("course_outline", CourseOutline, chunks="x")
    assert exc.value.code == "llm_bad_json"
    assert len(fake.calls) == 2


def test_generate_section():
    llm, _ = service([json.dumps(SECTION)])
    result = llm.generate(
        "section", SectionContent,
        course_title="К", section_title="С", user_hint="", chunks="[1] текст",
    )
    assert result.data.source_chunk_ids == [1]


def test_json_mode_sets_response_format():
    llm, fake = service([json.dumps(OUTLINE)], json_mode=True)
    llm.generate("course_outline", CourseOutline, chunks="x")
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


# --- ошибки провайдера превращаются в понятные ---

@pytest.mark.parametrize(
    "error, code",
    [
        (openai.APIConnectionError(request=request()), "llm_unavailable"),
        (openai.APITimeoutError(request=request()), "llm_timeout"),
        (openai.AuthenticationError("x", response=httpx.Response(401, request=request()), body=None), "llm_auth"),
        (openai.NotFoundError("x", response=httpx.Response(404, request=request()), body=None), "llm_model_not_found"),
        (openai.RateLimitError("x", response=httpx.Response(429, request=request()), body=None), "llm_rate_limit"),
        (openai.BadRequestError("x", response=httpx.Response(400, request=request()), body=None), "llm_bad_request"),
    ],
)
def test_provider_errors_are_mapped(error, code):
    llm, _ = service([error])
    with pytest.raises(LLMError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert exc.value.code == code


def test_truncated_answer_is_error():
    llm, _ = service([make_response("{", finish_reason="length")])
    with pytest.raises(LLMError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert exc.value.code == "llm_too_long"


def test_missing_api_key_is_clear_error(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(LLMError) as exc:
        LLMService().client
    assert exc.value.code == "llm_no_api_key"


# --- адрес /api/llm/check ---

def test_check_endpoint_ok(client):
    from app.llm.service import get_llm_service
    from app.main import app

    app.dependency_overrides[get_llm_service] = lambda: service(["Я тестовая модель."])[0]
    try:
        response = client.get("/api/llm/check")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["answer"] == "Я тестовая модель."
    assert response.json()["model"] == "test/model"


def test_check_endpoint_error_has_unified_format(client):
    from app.llm.service import get_llm_service
    from app.main import app

    err = openai.APIConnectionError(request=request())
    app.dependency_overrides[get_llm_service] = lambda: service([err])[0]
    try:
        response = client.get("/api/llm/check")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "llm_unavailable"
    assert body["request_id"]


# --- запасная модель ---

def test_fallback_model_used_when_primary_not_found():
    err = openai.NotFoundError("x", response=httpx.Response(404, request=request()), body=None)
    llm, fake = service([err, "ответ"], fallback_model="test/backup")
    assert llm.complete([{"role": "user", "content": "hi"}]) == "ответ"
    assert [c["model"] for c in fake.calls] == ["test/model", "test/backup"]
    assert llm.model == "test/backup"


def test_no_fallback_for_bad_request():
    err = openai.BadRequestError("x", response=httpx.Response(400, request=request()), body=None)
    llm, fake = service([err], fallback_model="test/backup")
    with pytest.raises(LLMError):
        llm.complete([{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1


def test_no_fallback_configured_raises_original_error():
    err = openai.RateLimitError("x", response=httpx.Response(429, request=request()), body=None)
    llm, _ = service([err], fallback_model="")
    with pytest.raises(LLMError) as exc:
        llm.complete([{"role": "user", "content": "hi"}])
    assert exc.value.code == "llm_rate_limit"
