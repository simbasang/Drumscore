from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def migration_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    # configparser interpolation treats '%' specially (e.g. url-encoded passwords).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(migration_config(database_url), "head")


def downgrade_to_base(database_url: str) -> None:
    command.downgrade(migration_config(database_url), "base")


if __name__ == "__main__":  # pragma: no cover - process entrypoint (the deployment's one-shot migrate step)
    from app.config import get_settings

    upgrade_to_head(get_settings().database_url.get_secret_value())
