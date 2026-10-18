from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Chronicle API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://chronicle:chronicle-local-only@localhost:5432/chronicle"
    cors_origins: str = "http://localhost:3000"
    max_upload_mb: int = 25
    upload_dir: str = "uploads"
    openai_api_key: SecretStr | None = None
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
