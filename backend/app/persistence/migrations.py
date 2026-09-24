from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _config(database_url: str) -> Config:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    # configparser interpolation treats '%' specially (e.g. url-encoded passwords).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(_config(database_url), "head")


def downgrade_to_base(database_url: str) -> None:
    command.downgrade(_config(database_url), "base")
