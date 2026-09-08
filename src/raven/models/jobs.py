"""Persistent application job snapshots shared by every long-running pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobKind(StrEnum):
    RAG = "rag"
    CATALOG = "catalog"
    GRAPH = "graph"
    OCR = "ocr"
    EXPORT = "export"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class BackgroundJob:
    """Immutable, MongoDB-persisted progress record for the Jobs workspace."""

    job_id: str
    investigation_id: str
    kind: JobKind
    status: JobStatus
    stage: str
    completed: int
    total: int
    message: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    investigation_name: str = ""

    @property
    def progress_percent(self) -> int:
        if self.total <= 0:
            return 0
        return max(0, min(100, round(self.completed / self.total * 100)))
