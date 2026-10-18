"""Migrations must produce the schema the models describe (tests elsewhere use create_all)."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from alembic import command
from app.db.migrate import alembic_config
from app.db.models import Base


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), Base.metadata)
    assert diff == []


def test_migrations_downgrade_to_base(tmp_path):
    url = f"sqlite:///{tmp_path / 'd.db'}"
    cfg = alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")


def test_generated_api_types_are_current():
    """frontend/openapi.json (the source of the web app's types) matches the API in the code.
    After changing a response: `npm run gen:api` in frontend/."""
    import json
    from pathlib import Path

    from app.web import create_app

    saved = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "openapi.json").read_text())
    assert saved == json.loads(json.dumps(create_app().openapi())), "run `npm run gen:api` in frontend/"
