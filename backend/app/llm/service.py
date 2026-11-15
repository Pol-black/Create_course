"""
Сервис LLM: отправляет запрос модели и превращает ответ в проверенный объект.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.llm.errors import LLMError
from app.llm.prompts import load_prompt

logger = logging.getLogger("app.llm")

T = TypeVar("T", bound=BaseModel)

_throttle_lock = threading.Lock()
_last_call = 0.0 

FALLBACK_CODES = {"llm_model_not_found", "llm_rate_limit", "llm_unavailable", "llm_timeout", "llm_empty"}


@dataclass
class GenerationResult:
    """Результат generate(): данные и то, что нужно записать в section_version."""

    data: BaseModel
    model: str
    prompt_name: str
    attempts: int
    duration_ms: int


def retry_after_seconds(exc: Exception) -> float | None:
    """Сколько секунд просит подождать сервис при 429"""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after") if hasattr(headers, "get") else None
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    match = re.search(r"try again in\s+(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)(ms|s))?", str(exc))
    if match and (match.group(1) or match.group(2)):
        seconds = int(match.group(1) or 0) * 60
        if match.group(2):
            seconds += float(match.group(2)) / (1000 if match.group(3) == "ms" else 1)
        return seconds
    return None


def is_daily_limit(exc: Exception) -> bool:
    """Дневной лимит (токенов или запросов)"""
    text = str(exc).lower()
    return "per day" in text or "(tpd)" in text or "(rpd)" in text


def extract_json(text: str) -> Any:
    """Достать JSON из ответа модели.
    """
    if not text or not text.strip():
        raise ValueError("пустой ответ")
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    return json.loads(cleaned[start : end + 1])


def _describe_validation_error(exc: ValidationError) -> str:
    items = []
    for err in exc.errors()[:8]:
        where = ".".join(str(p) for p in err["loc"]) or "ответ"
        items.append(f"{where}: {err['msg']}")
    return "; ".join(items)


class LLMService:
    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
        fallback_model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_attempts: int | None = None,
        json_mode: bool | None = None,
        min_interval_s: float | None = None,
        sleep=time.sleep,
    ) -> None:
        self.model = model or settings.llm_model
        self.fallback_model = settings.llm_fallback_model if fallback_model is None else fallback_model
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.json_attempts = json_attempts or settings.llm_json_attempts
        self.json_mode = settings.llm_json_mode if json_mode is None else json_mode
        self.min_interval_s = settings.llm_min_interval_s if min_interval_s is None else min_interval_s
        self._sleep = sleep  # в тестах подменяется, чтобы не ждать по-настоящему
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            if not settings.llm_api_key:
                raise LLMError(
                    "Не задан ключ LLM_API_KEY. Укажите ключ в файле .env "
                    "и перезапустите backend (docker compose up -d)",
                    code="llm_no_api_key",
                    status_code=503,
                )
            self._client = OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout_s,
                max_retries=0,  
            )
        return self._client

    # Один запрос к модели; если основная недоступна, пробуем запасную
    def complete(self, messages: list[dict[str, str]]) -> str:
        try:
            return self._complete_with(self.model, messages)
        except LLMError as exc:
            if not self.fallback_model or exc.code not in FALLBACK_CODES:
                raise
            logger.warning(
                "Модель %s недоступна (%s), пробуем запасную %s",
                self.model, exc.code, self.fallback_model,
            )
            answer = self._complete_with(self.fallback_model, messages)
            self.model = self.fallback_model  # дальше работаем с рабочей моделью
            return answer

    def _complete_with(self, model: str, messages: list[dict[str, str]]) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if settings.llm_reasoning_effort:
            kwargs["extra_body"] = {"reasoning_effort": settings.llm_reasoning_effort}
        try:
            response = self._create_with_retries(kwargs)
        except LLMError:
            raise
        except openai.APITimeoutError as exc:
            raise LLMError(
                "Модель не ответила вовремя. Повторите запрос или увеличьте LLM_TIMEOUT_S",
                code="llm_timeout", status_code=504,
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMError(
                "Не удалось связаться с сервисом модели. Проверьте интернет и LLM_BASE_URL",
                code="llm_unavailable", status_code=503,
            ) from exc
        except openai.AuthenticationError as exc:
            raise LLMError(
                "Сервис модели не принял ключ. Проверьте LLM_API_KEY (ключ Groq начинается с gsk_)",
                code="llm_auth", status_code=502,
            ) from exc
        except openai.NotFoundError as exc:
            raise LLMError(
                f"Модель «{model}» не найдена. Проверьте LLM_MODEL: список доступных моделей "
                "показывает GET /api/llm/models",
                code="llm_model_not_found",
            ) from exc
        except openai.RateLimitError as exc:
            if is_daily_limit(exc):
                raise LLMError(
                    "Исчерпан дневной лимит бесплатного тарифа. Дождитесь следующих суток, "
                    "смените модель (LLM_MODEL) или подключите платный тариф",
                    code="llm_rate_limit_daily", status_code=429,
                ) from exc
            raise LLMError(
                "Превышен лимит запросов к модели в минуту. Подождите минуту и повторите "
                "или уменьшите LLM_MAX_INPUT_CHARS",
                code="llm_rate_limit", status_code=429,
            ) from exc
        except openai.BadRequestError as exc:
            raise LLMError(
                f"Сервис модели отклонил запрос: {exc}. Если речь про response_format, "
                "поставьте LLM_JSON_MODE=false",
                code="llm_bad_request",
            ) from exc
        except openai.OpenAIError as exc:
            raise LLMError(f"Ошибка сервиса модели: {exc}", code="llm_error") from exc

        if not getattr(response, "choices", None):
            raise LLMError("Модель вернула пустой ответ", code="llm_empty")
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise LLMError(
                "Ответ модели обрезан: не хватило длины. Увеличьте LLM_MAX_TOKENS",
                code="llm_too_long",
            )
        return choice.message.content or ""

    def _throttle(self) -> None:
        """Выдержать паузу между запросами (бесплатные тарифы ограничивают запросы в минуту)."""
        global _last_call
        if self.min_interval_s <= 0:
            return
        with _throttle_lock:
            wait = _last_call + self.min_interval_s - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            _last_call = time.monotonic()

    def _create_with_retries(self, kwargs: dict[str, Any]) -> Any:
        """Запрос к API. При 429 ждём столько, сколько просит сервис, и повторяем (до N раз)."""
        attempt = 0
        while True:
            self._throttle()
            try:
                return self.client.chat.completions.create(**kwargs)
            except openai.RateLimitError as exc:
                wait = retry_after_seconds(exc)
                attempt += 1
                if (
                    is_daily_limit(exc)
                    or attempt > settings.llm_rate_limit_retries
                    or (wait or 0) > settings.llm_rate_limit_max_wait_s
                ):
                    raise
                pause = (wait if wait is not None else 5.0 * attempt) + 0.5
                logger.warning("Лимит запросов (429), ждём %.1f с, повтор %d/%d",
                               pause, attempt, settings.llm_rate_limit_retries)
                self._sleep(pause)

    def list_models(self) -> list[str]:
        """Идентификаторы моделей, доступных по ключу."""
        try:
            return sorted(m.id for m in self.client.models.list().data)
        except openai.AuthenticationError as exc:
            raise LLMError("Сервис модели не принял ключ. Проверьте LLM_API_KEY", code="llm_auth") from exc
        except openai.OpenAIError as exc:
            raise LLMError(f"Не удалось получить список моделей: {exc}", code="llm_error") from exc

    def generate(self, prompt_name: str, schema: type[T], **variables: object) -> GenerationResult:
        system, user = load_prompt(prompt_name, **variables)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        started = time.perf_counter()
        last_error = ""
        for attempt in range(1, self.json_attempts + 1):
            raw = self.complete(messages)
            try:
                data = schema.model_validate(extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_error = (
                    _describe_validation_error(exc) if isinstance(exc, ValidationError) else str(exc)
                )
                logger.warning(
                    "Ответ модели не прошёл проверку (%s, попытка %d/%d): %s",
                    prompt_name, attempt, self.json_attempts, last_error,
                )
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Ответ не прошёл проверку: {last_error}. "
                        "Верни исправленный JSON целиком, без пояснений."
                    ),
                })
                continue

            duration_ms = round((time.perf_counter() - started) * 1000)
            logger.info(
                "LLM %s: модель=%s попыток=%d (%d ms)",
                prompt_name, self.model, attempt, duration_ms,
            )
            return GenerationResult(
                data=data, model=self.model, prompt_name=prompt_name,
                attempts=attempt, duration_ms=duration_ms,
            )

        raise LLMError(
            "Модель не смогла вернуть корректный ответ. Повторите запрос; "
            f"последняя ошибка проверки: {last_error}",
            code="llm_bad_json",
        )

    def ping(self) -> tuple[str, int]:
        """Короткий запрос для проверки связи."""
        system, user = load_prompt("ping")
        started = time.perf_counter()
        saved, self.json_mode = self.json_mode, False
        try:
            answer = self.complete([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ])
        finally:
            self.json_mode = saved
        return answer.strip(), round((time.perf_counter() - started) * 1000)


def get_llm_service() -> LLMService:
    return LLMService()
