"""Application settings loaded from environment variables.

Uses pydantic-settings for type-safe configuration with fail-fast
validation — the app crashes immediately if required env vars are missing.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    DEFAULT_JWT_ALGORITHM,
    INSECURE_JWT_SECRET_PLACEHOLDERS,
    JWT_SECRET_KEY_MIN_LENGTH,
    REDIS_SOCKET_CONNECT_TIMEOUT,
    REDIS_SOCKET_TIMEOUT,
)
from app.core.messages import ERROR_INSECURE_JWT_SECRET


class Settings(BaseSettings):
    """Global application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    APP_NAME: str = "TaskHub"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str
    DB_NAME: str = "taskhub"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_SOCKET_TIMEOUT: float = REDIS_SOCKET_TIMEOUT
    REDIS_SOCKET_CONNECT_TIMEOUT: float = REDIS_SOCKET_CONNECT_TIMEOUT

    JWT_SECRET_KEY: str = Field(..., min_length=JWT_SECRET_KEY_MIN_LENGTH)
    JWT_ALGORITHM: str = DEFAULT_JWT_ALGORITHM
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def reject_placeholder_secret(cls, value: str) -> str:
        """Prevent startup with documented example or CHANGE_ME secret keys."""
        if value in INSECURE_JWT_SECRET_PLACEHOLDERS or value.upper().startswith("CHANGE_ME"):
            raise ValueError(ERROR_INSECURE_JWT_SECRET)
        return value

    @property
    def DATABASE_URL(self) -> str:
        """Build async MySQL connection string."""
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"mysql+asyncmy://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Build sync MySQL connection string (for Alembic)."""
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"mysql+pymysql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def REDIS_URL(self) -> str:
        """Build Redis connection string."""
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — reads .env once."""
    return Settings()
