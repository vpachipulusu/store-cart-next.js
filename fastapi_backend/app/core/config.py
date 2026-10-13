from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ENVIRONMENTS = frozenset({"local", "test"})
VERCEL_NON_PRODUCTION = frozenset({"preview", "development"})


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
    # Set by Vercel itself (production, preview or development). When present it
    # wins: preview and development relax the rate limit guard, production is strict.
    VERCEL_ENV: str | None = None

    # Rate limiting (ADR-007). Optional only when ENVIRONMENT is local or test, where
    # unset means rate limiting is disabled. Any other environment must set both.
    UPSTASH_REDIS_REST_URL: str | None = None
    UPSTASH_REDIS_REST_TOKEN: SecretStr | None = None

    # Error reporting (KAN-35). Sentry is initialised only when SENTRY_DSN is set;
    # leave it unset locally and in tests. The release comes from Vercel.
    SENTRY_DSN: SecretStr | None = None
    VERCEL_GIT_COMMIT_SHA: str | None = None

    # ADR-003: separate server-only keys per environment; never NEXT_PUBLIC_*.
    BACKEND_INTERNAL_KEY: SecretStr | None = None
    BACKEND_INTERNAL_KEY_NEXT: SecretStr | None = None
    RATE_LIMIT_EMAIL_KEY: SecretStr | None = None
    FIREBASE_ADMIN_PROJECT_ID: str | None = None
    FIREBASE_ADMIN_CLIENT_EMAIL: str | None = None
    FIREBASE_ADMIN_PRIVATE_KEY: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def require_rate_limit_config_outside_local(self) -> "Settings":
        configured = bool(self.UPSTASH_REDIS_REST_URL and self.UPSTASH_REDIS_REST_TOKEN)
        if self.VERCEL_ENV:
            relaxed = self.VERCEL_ENV in VERCEL_NON_PRODUCTION
        else:
            relaxed = self.ENVIRONMENT in LOCAL_ENVIRONMENTS
        if not configured and not relaxed:
            raise ValueError(
                "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set "
                f"in production (ENVIRONMENT='{self.ENVIRONMENT}', "
                f"VERCEL_ENV='{self.VERCEL_ENV}'); rate limiting can only be disabled "
                "for local, test, Vercel preview and Vercel development"
            )
        return self

    @model_validator(mode="after")
    def validate_auth_config(self) -> "Settings":
        for name in (
            "BACKEND_INTERNAL_KEY",
            "BACKEND_INTERNAL_KEY_NEXT",
            "RATE_LIMIT_EMAIL_KEY",
        ):
            key = getattr(self, name)
            if key is not None and len(key.get_secret_value()) < 32:
                raise ValueError(f"{name} must have at least 32 characters")
        relaxed = (
            self.VERCEL_ENV in VERCEL_NON_PRODUCTION
            if self.VERCEL_ENV
            else self.ENVIRONMENT in LOCAL_ENVIRONMENTS
        )
        required = (
            "BACKEND_INTERNAL_KEY",
            "RATE_LIMIT_EMAIL_KEY",
            "FIREBASE_ADMIN_PROJECT_ID",
            "FIREBASE_ADMIN_CLIENT_EMAIL",
            "FIREBASE_ADMIN_PRIVATE_KEY",
        )
        if not relaxed and any(not getattr(self, name) for name in required):
            raise ValueError(
                "Production authentication requires internal key, email HMAC key and Firebase Admin credentials"
            )
        return self


# Required field (DATABASE_URL) comes from the environment, so the
# app fails at startup when they are missing.
settings = Settings()  # type: ignore[call-arg]
