from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="development", alias="ENV")
    debug: bool = Field(default=False, alias="DEBUG")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_access_ttl_minutes: int = Field(default=15, alias="JWT_ACCESS_TTL_MINUTES")
    jwt_refresh_ttl_days: int = Field(default=30, alias="JWT_REFRESH_TTL_DAYS")

    provider_key_encryption_key: str = Field(alias="PROVIDER_KEY_ENCRYPTION_KEY")

    whatsapp_app_secret: str = Field(default="", alias="WHATSAPP_APP_SECRET")
    whatsapp_access_token: str = Field(default="", alias="WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_number_id: str = Field(default="", alias="WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_verify_token: str = Field(default="", alias="WHATSAPP_VERIFY_TOKEN")
    whatsapp_graph_url: str = Field(default="https://graph.facebook.com/v20.0", alias="WHATSAPP_GRAPH_URL")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:2000"], alias="CORS_ORIGINS")

    default_timezone: str = Field(default="Asia/Kolkata", alias="DEFAULT_TIMEZONE")

    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
