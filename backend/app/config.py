from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

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

    chunk_target_words: int = 600
    chunk_max_words: int = 1000
    chunk_min_words: int = 120

    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-20b"
    llm_fallback_model: str = ""  

    llm_temperature: float = 0.3  
    llm_max_tokens: int = 8192 
    llm_timeout_s: float = 120  
    llm_json_attempts: int = 2  
    llm_json_mode: bool = True  
    llm_reasoning_effort: str = "" 

    # Лимиты бесплатного тарифа
    llm_min_interval_s: float = 2.0
    llm_rate_limit_retries: int = 3
    llm_rate_limit_max_wait_s: float = 60
    llm_max_input_chars: int = 12000  

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
