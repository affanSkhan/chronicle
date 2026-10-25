from functools import lru_cache
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Chronicle API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://chronicle:chronicle-local-only@localhost:5432/chronicle"
    cors_origins: str = "http://localhost:3000"
    max_upload_mb: int = 50
    max_pdf_pages: int = 300
    enable_pdf_ocr: bool = True
    pdf_ocr_max_pages: int = 50
    pdf_ocr_dpi: int = 150
    pdf_ocr_min_text_chars: int = 40
    pdf_ocr_language: str = "eng"
    upload_dir: str = "uploads"
    openalex_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = ""
    jwt_secret_key: SecretStr = SecretStr("development-only-change-this-secret-key")
    jwt_access_token_expire_minutes: int = 480
    enable_scheduled_monitoring: bool = False
    source_monitor_poll_seconds: int = 60
    source_monitor_batch_size: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def ensure_production_jwt_secret(self):
        if self.environment.strip().lower() in {"production", "prod"}:
            if self.jwt_secret_key.get_secret_value() == "development-only-change-this-secret-key":
                raise ValueError("JWT_SECRET_KEY must be replaced with a strong secret in production.")
            if len(self.jwt_secret_key.get_secret_value()) < 32:
                raise ValueError("JWT_SECRET_KEY must contain at least 32 characters in production.")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def openalex_auth_headers() -> dict[str, str]:
    """Return OpenAlex-only auth headers without exposing the key in URLs/logs."""
    key = get_settings().openalex_api_key
    if key is None:
        return {}
    token = key.get_secret_value().strip()
    return {"Authorization": f"Bearer {token}"} if token else {}
