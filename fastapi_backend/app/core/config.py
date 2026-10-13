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

    # CORS
    CORS_ORIGINS: set[str]

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Required fields (DATABASE_URL, CORS_ORIGINS) come from the environment, so the
# app fails at startup when they are missing.
settings = Settings()  # type: ignore[call-arg]
