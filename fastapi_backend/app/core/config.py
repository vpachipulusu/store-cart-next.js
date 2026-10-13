from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "StoreCart API"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # OpenAPI docs
    OPENAPI_URL: str = "/openapi.json"

    # Database
    DATABASE_URL: str
    EXPIRE_ON_COMMIT: bool = False

    # Rate limiting (ADR-007). Optional: when both are unset, rate limiting is
    # disabled (local dev and tests). Set both in every deployed environment.
    UPSTASH_REDIS_REST_URL: str | None = None
    UPSTASH_REDIS_REST_TOKEN: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Required field (DATABASE_URL) comes from the environment, so the
# app fails at startup when they are missing.
settings = Settings()  # type: ignore[call-arg]
