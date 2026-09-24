from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or
    backend/.env). See docs/PERSISTENCE.md for what each value controls."""

    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
