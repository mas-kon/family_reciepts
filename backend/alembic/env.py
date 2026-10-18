from sqlalchemy import create_engine, pool

from alembic import context
from app.config import get_settings
from app.db.migrate import sync_url
from app.db.models import Base

config = context.config
target_metadata = Base.metadata


def url() -> str:
    return config.get_main_option("sqlalchemy.url") or sync_url(get_settings().database_url)


def run_offline() -> None:
    context.configure(url=url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
