"""Run the Alembic migrations from code (startup, the seed command, tests). Same as `alembic upgrade head` in backend/."""

from alembic import command
from alembic.config import Config

from app import config


def alembic_config() -> Config:
    cfg = Config(str(config.BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.MIGRATIONS_DIR))
    return cfg


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")
