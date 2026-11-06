from app.errors import AppError


class LLMError(AppError):
    """Ошибка обращения к модели. Отдаётся пользователю как 502 в едином формате."""

    def __init__(self, message: str, code: str = "llm_error", status_code: int = 502) -> None:
        super().__init__(message, status_code=status_code, code=code)
