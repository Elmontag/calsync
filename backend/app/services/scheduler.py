"""Background scheduler for periodic sync jobs."""
from __future__ import annotations

import logging
from typing import Callable, Dict

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


class SyncScheduler:
    """Singleton wrapper for APScheduler."""

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._jobs: Dict[str, str] = {}

    def start(self) -> None:
        if not self._scheduler.running:
            logger.info("Starting background scheduler")
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            logger.info("Shutting down background scheduler")
            self._scheduler.shutdown(wait=False)

    def schedule_job(self, job_id: str, func: Callable, minutes: int = 5) -> None:
        if job_id in self._jobs:
            logger.debug("Rescheduling existing job %s", job_id)
            self._scheduler.remove_job(job_id)
        self._scheduler.add_job(func, "interval", minutes=minutes, id=job_id, replace_existing=True)
        self._jobs[job_id] = job_id
        logger.info("Scheduled job %s every %s minutes", job_id, minutes)

    def cancel_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            logger.info("Cancelled job %s", job_id)

    def is_job_active(self, job_id: str) -> bool:
        """Return whether a job is currently scheduled."""
        return job_id in self._jobs


scheduler = SyncScheduler()
