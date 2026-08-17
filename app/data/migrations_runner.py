"""
Runs Alembic migrations programmatically so a user never has to
remember to run `alembic upgrade head` by hand before starting the app —
main.py calls this once at startup. Uses the exact same alembic.ini /
env.py as the CLI would, just invoked in-process.
"""

from __future__ import annotations

from alembic.config import Config

from alembic import command
from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)


def run_migrations() -> None:
    settings = get_settings()
    alembic_ini_path = settings.project_root / "alembic.ini"
    if not alembic_ini_path.exists():
        log.warning("No alembic.ini found at {}; skipping migrations.", alembic_ini_path)
        return

    cfg = Config(str(alembic_ini_path))
    cfg.set_main_option("script_location", str(settings.project_root / "alembic"))

    log.info("Running database migrations...")
    command.upgrade(cfg, "head")
    log.info("Database is up to date.")
