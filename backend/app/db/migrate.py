from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings

BACKEND = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "")


def upgrade() -> None:
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(), "head")
