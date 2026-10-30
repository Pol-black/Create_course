from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    postgres_db: str
    postgres_user: str
    postgres_password: str
    db_host: str = "localhost"
    db_port: int | None = None
    postgres_port: int = 5432

    log_level: str = "INFO"

    upload_dir: Path = Path("/data/uploads")
    max_upload_mb: int = 25
    min_text_chars: int = 50

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "thinkingmachines/inkling:free"

    llm_temperature: float = 0.3 # 0 — ответы почти одинаковые, 1 — более «творческие». Для курса 0.2–0.4.
    llm_max_tokens: int = 4096 # Максимальная длина ответа модели в токенах 
    llm_timeout_s: float = 300  # Сколько секунд ждать ответа
    llm_json_attempts: int = 2 # Сколько раз просить модель, если она вернула неправильный JSON
    llm_json_mode: bool = True # Просить у API режим «только JSON» 

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
    
    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.db_host,
            port=self.db_port or self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
