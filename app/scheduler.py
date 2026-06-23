"""In-process scheduled ingestion using APScheduler.

Disabled by default (ENABLE_SCHEDULER=false) so the demo stays static and safe.
When enabled, a background job periodically refreshes the bundled JSON from
GNews/Reddit and re-seeds the database. Any failure is logged and swallowed so
the web process never goes down.

Why APScheduler and not Celery: Celery needs an external broker (Redis/RabbitMQ)
and a separate worker process. For a single instance refreshing a handful of
topics every few hours, an in-process scheduler is simpler and sufficient.
Celery is the scale-out path documented for V2.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .ingest import seed_from_json

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
_scheduler: BackgroundScheduler | None = None


def _run_script(name: str) -> None:
    script = ROOT / "scripts" / name
    try:
        subprocess.run([sys.executable, str(script)], check=False, timeout=300)
    except Exception:  # noqa: BLE001
        logger.exception("Refresh script failed: %s", name)


def refresh_job() -> None:
    logger.info("Scheduled ingestion starting...")
    try:
        _run_script("refresh_all.py")
        logger.info("Scheduled ingestion complete.")
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled ingestion failed (web process unaffected).")


def start_scheduler() -> None:
    global _scheduler
    if not settings.enable_scheduler:
        logger.info("Scheduler disabled (ENABLE_SCHEDULER=false).")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        refresh_job,
        "interval",
        hours=max(1, settings.ingest_interval_hours),
        id="refresh_job",
    )
    _scheduler.start()
    logger.info("Scheduler started: every %s hour(s).", settings.ingest_interval_hours)
