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
