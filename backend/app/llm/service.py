"""
Сервис LLM: отправляет запрос модели и превращает ответ в проверенный объект.
"""

import json
import logging
import re
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

FALLBACK_CODES = {"llm_model_not_found", "llm_rate_limit", "llm_unavailable", "llm_timeout", "llm_empty"}


@dataclass
class GenerationResult:
    """Результат generate(): данные и то, что нужно записать в section_version."""

    data: BaseModel
    model: str
    prompt_name: str
    attempts: int
    duration_ms: int


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
    ) -> None:
        self.model = model or settings.llm_model
        self.fallback_model = settings.llm_fallback_model if fallback_model is None else fallback_model
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.json_attempts = json_attempts or settings.llm_json_attempts
        self.json_mode = settings.llm_json_mode if json_mode is None else json_mode
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            if not settings.llm_api_key:
                raise LLMError(
                    "Не задан ключ LLM_API_KEY. Укажите ключ OpenRouter в файле .env "
                    "и перезапустите backend",
                    code="llm_no_api_key",
                    status_code=503,
                )
            self._client = OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout_s,
                max_retries=0,  # повторы делаем сами, чтобы писать их в журнал
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
        try:
            response = self.client.chat.completions.create(**kwargs)
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
                "Сервис модели не принял ключ. Проверьте LLM_API_KEY",
                code="llm_auth", status_code=502,
            ) from exc
        except openai.NotFoundError as exc:
            raise LLMError(
                f"Модель «{model}» не найдена. Проверьте LLM_MODEL: у бесплатных "
                "моделей OpenRouter имя может измениться или модель может быть убрана",
                code="llm_model_not_found",
            ) from exc
        except openai.RateLimitError as exc:
            raise LLMError(
                "Превышен лимит запросов к модели (у бесплатных моделей он небольшой). "
                "Подождите минуту и повторите или смените модель",
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
        """Короткий запрос для проверки связи. Возвращает в мс."""
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
