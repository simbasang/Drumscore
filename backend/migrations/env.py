from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.persistence.tables import metadata

config = context.config
database_url = config.get_main_option("sqlalchemy.url") or get_settings().database_url.get_secret_value()


def run_migrations_online() -> None:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
