from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    postgres_db: str
    postgres_user: str
    postgres_password: str
    db_host: str = "localhost"
    db_port: int | None = None
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        port = self.db_port or self.postgres_port
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.db_host}:{port}/{self.postgres_db}"
        )


settings = Settings()
