"""
Проверка настройки LLM из консоли (без запуска сайта):

    docker compose exec backend python -m app.scripts.check_llm
"""

import sys

from app.config import settings
from app.llm.errors import LLMError
from app.llm.service import LLMService


def main() -> int:
    key = settings.llm_api_key
    print(f"LLM_BASE_URL   = {settings.llm_base_url}")
    print(f"LLM_MODEL      = {settings.llm_model}")
    print(f"LLM_JSON_MODE  = {settings.llm_json_mode}")
    print(f"LLM_API_KEY    = {key[:4] + '...' + key[-3:] if len(key) > 8 else ('(не задан)' if not key else '(слишком короткий)')}")
    if "groq" in settings.llm_base_url and key and not key.startswith("gsk_"):
        print("ВНИМАНИЕ: ключи Groq начинаются с gsk_. Проверьте LLM_API_KEY в .env")

    llm = LLMService()
    try:
        models = llm.list_models()
        print(f"\nДоступно моделей: {len(models)}")
        print("LLM_MODEL найдена в списке" if llm.model in models else
              f"ВНИМАНИЕ: модели «{llm.model}» нет в списке. Выберите одну из:\n  " + "\n  ".join(models))
        answer, ms = llm.ping()
    except LLMError as exc:
        print(f"\nОШИБКА [{exc.code}]: {exc.message}")
        return 1
    print(f"\nОтвет модели: {answer!r} ({ms} мс)\nВсё работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
