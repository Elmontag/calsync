"""In-memory tracking for long-running synchronization jobs."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from ..schemas import SyncJobStatus


@dataclass
class JobState:
    """Represents the progress of a single job."""

    job_id: str
    status: str = "queued"
    processed: int = 0
    total: Optional[int] = None
    detail: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None

    def to_status(self) -> SyncJobStatus:
        """Convert the job state into an API response model."""
        return SyncJobStatus(
            job_id=self.job_id,
            status=self.status,
            processed=self.processed,
            total=self.total,
            detail=self.detail,
            message=self.message,
        )


class JobTracker:
    """Thread-safe registry for currently running jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobState] = {}

    def create(self, prefix: str = "job", total: Optional[int] = None) -> JobState:
        """Create a new job entry and return its state."""
        job_id = f"{prefix}-{uuid.uuid4().hex}"
        state = JobState(job_id=job_id, total=total)
        with self._lock:
            self._jobs[job_id] = state
        return state

    def get(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        processed: Optional[int] = None,
        total: Optional[int] = None,
        message: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Optional[JobState]:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return None
            if status is not None:
                state.status = status
            if processed is not None:
                state.processed = processed
            if total is not None:
                state.total = total
            if message is not None:
                state.message = message
            if detail is not None:
                state.detail = detail
            if status in {"completed", "failed"} and state.finished_at is None:
                state.finished_at = datetime.utcnow()
            return state

    def increment(
        self,
        job_id: str,
        *,
        processed_delta: int = 0,
        total_delta: int = 0,
    ) -> Optional[JobState]:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return None
            if processed_delta:
                state.processed += processed_delta
            if total_delta:
                state.total = (state.total or 0) + total_delta
            return state

    def finish(self, job_id: str, detail: Optional[Dict[str, Any]] = None) -> Optional[JobState]:
        return self.update(job_id, status="completed", detail=detail)

    def fail(self, job_id: str, message: str) -> Optional[JobState]:
        return self.update(job_id, status="failed", message=message)


job_tracker = JobTracker()
