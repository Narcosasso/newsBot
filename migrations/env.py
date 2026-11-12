"""Ambiente Alembic: usa DATABASE_URL (o l'URL passato da codice) e i modelli di cardbot.db."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from cardbot.config import get_settings
from cardbot.db import Base, normalize_url

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return normalize_url(config.attributes.get("url") or get_settings().database_url)


def run_migrations_offline() -> None:
    url = _url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=url.startswith("sqlite"))  # ALTER TABLE su SQLite
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
