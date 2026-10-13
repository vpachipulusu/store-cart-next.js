from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ENVIRONMENTS = frozenset({"local", "test"})


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

    # Deployment environment. Defaults to "production" so a deployment that forgets
    # to set it gets the strict checks. Only "local" and "test" are relaxed.
    ENVIRONMENT: str = "production"

    # Rate limiting (ADR-007). Optional only when ENVIRONMENT is local or test, where
    # unset means rate limiting is disabled. Any other environment must set both.
    UPSTASH_REDIS_REST_URL: str | None = None
    UPSTASH_REDIS_REST_TOKEN: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def require_rate_limit_config_outside_local(self) -> "Settings":
        configured = bool(self.UPSTASH_REDIS_REST_URL and self.UPSTASH_REDIS_REST_TOKEN)
        if not configured and self.ENVIRONMENT not in LOCAL_ENVIRONMENTS:
            raise ValueError(
                "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set "
                f"when ENVIRONMENT is '{self.ENVIRONMENT}' (rate limiting cannot be "
                "disabled outside local and test; set ENVIRONMENT=local for development)"
            )
        return self


# Required field (DATABASE_URL) comes from the environment, so the
# app fails at startup when they are missing.
settings = Settings()  # type: ignore[call-arg]
