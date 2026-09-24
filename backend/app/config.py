from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or
    backend/.env). docs/OPERATIONS.md documents every value and which ones
    are secret; docs/PERSISTENCE.md explains the queue/storage ones."""

    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore")

    database_url: SecretStr = SecretStr("postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore")
    storage_root: Path = _BACKEND_DIR / "data"
    worker_concurrency: int = 2
    lease_seconds: int = 300
    heartbeat_seconds: float = 60
    poll_interval_seconds: float = 2.0
    max_attempts: int = 3
    retry_base_seconds: int = 30
    failed_job_retention_days: int = 7
    prune_interval_seconds: int = 3600
    storage_warn_bytes: int = 50 * 1024**3
    run_migrations_on_startup: bool = True
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    max_source_duration_seconds: PositiveInt = 900
    max_download_bytes: PositiveInt = 200 * 1024**2
    max_request_bytes: PositiveInt = 5 * 1024**2
    max_active_jobs: PositiveInt = 20
    storage_max_bytes: PositiveInt = 100 * 1024**3

    @field_validator("storage_root")
    @classmethod
    def _resolve_relative_storage_root(cls, value: Path) -> Path:
        # A relative STORAGE_ROOT means the same directory for the API and
        # the workers whatever directory they were started from.
        return value if value.is_absolute() else _BACKEND_DIR / value

    @model_validator(mode="after")
    def _heartbeat_shorter_than_lease(self) -> "Settings":
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError(
                f"HEARTBEAT_SECONDS must be less than LEASE_SECONDS "
                f"(got {self.heartbeat_seconds} >= {self.lease_seconds}); otherwise the lease expires between heartbeats"
            )
        return self

    @model_validator(mode="after")
    def _warning_below_storage_limit(self) -> "Settings":
        if self.storage_warn_bytes > self.storage_max_bytes:
            raise ValueError(
                f"STORAGE_WARN_BYTES must not exceed STORAGE_MAX_BYTES "
                f"(got {self.storage_warn_bytes} > {self.storage_max_bytes})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
