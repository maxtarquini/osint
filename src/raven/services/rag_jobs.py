"""Application-owned FIFO queue for persistent investigation RAG indexing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from queue import Queue
from threading import Event, RLock, Thread
from typing import Protocol
from uuid import uuid4

from raven.exceptions import InvestigationChatCancelledError
from raven.exceptions.graph import CatalogBatchError
from raven.models import BackgroundJob, EvidenceDocument, Investigation, JobKind, JobStatus
from raven.models.chat import RagIndexProgress
from raven.services.job_persistence import BackgroundJobWriter

logger = logging.getLogger(__name__)


class RagIndexRunner(Protocol):
    def index_knowledge_base(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[RagIndexProgress], None] | None = None,
    ) -> int: ...


class JobRecorder(Protocol):
    def save_background_job(self, job: BackgroundJob) -> None: ...


@dataclass(slots=True)
class _RagJobRecord:
    snapshot: BackgroundJob
    investigation: Investigation
    documents: tuple[EvidenceDocument, ...]
    cancellation: Event


class RagIndexQueue:
    """Keep RAG work alive while screens change and expose durable progress."""

    def __init__(
        self,
        runner: RagIndexRunner,
        recorder: JobRecorder | None = None,
        on_change: Callable[[str], None] | None = None,
        *,
        kind: JobKind = JobKind.RAG,
    ) -> None:
        self._runner = runner
        self._kind = kind
        self._label = "Page cataloging" if kind is JobKind.CATALOG else "RAG indexing"
        self._writer = BackgroundJobWriter(recorder)
        self._on_change = on_change
        self._names: dict[str, str] = {}
        self._jobs: dict[str, _RagJobRecord] = {}
        self._latest_progress: dict[str, RagIndexProgress] = {}
        self._chunk_counts: dict[str, dict[str, int]] = {}
        self._queue: Queue[tuple[str, str] | None] = Queue()
        self._lock = RLock()
        self._closed = False
        self._thread = Thread(target=self._consume, name="raven-rag-index-queue", daemon=True)
        self._thread.start()

    def enqueue(
        self, investigation: Investigation, documents: tuple[EvidenceDocument, ...]
    ) -> BackgroundJob:
        with self._lock:
            current = self._jobs.get(investigation.investigation_id)
            if current and current.snapshot.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return current.snapshot
            if self._closed:
                raise RuntimeError("RAG indexing queue is closed")
            self._names[investigation.investigation_id] = investigation.name
            now = datetime.now(UTC)
            snapshot = BackgroundJob(
                job_id=str(uuid4()),
                investigation_id=investigation.investigation_id,
                kind=self._kind,
                investigation_name=investigation.name,
                status=JobStatus.QUEUED,
                stage="queued",
                completed=0,
                total=len(documents),
                message=f"Queued for {self._label}",
                created_at=now,
                updated_at=now,
            )
            self._jobs[investigation.investigation_id] = _RagJobRecord(
                snapshot, investigation, documents, Event()
            )
            self._chunk_counts[investigation.investigation_id] = {}
            self._persist(snapshot)
            self._queue.put((investigation.investigation_id, snapshot.job_id))
            return snapshot

    def snapshot(self, investigation_id: str) -> BackgroundJob | None:
        with self._lock:
            record = self._jobs.get(investigation_id)
            return record.snapshot if record else None

    def snapshots(self) -> tuple[BackgroundJob, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (record.snapshot for record in self._jobs.values()),
                    key=lambda item: item.updated_at,
                    reverse=True,
                )
            )

    def latest_progress(self, investigation_id: str) -> RagIndexProgress | None:
        with self._lock:
            return self._latest_progress.get(investigation_id)

    def cancel(self, investigation_id: str) -> BackgroundJob | None:
        with self._lock:
            record = self._jobs.get(investigation_id)
            if record is None:
                return None
            if record.snapshot.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return record.snapshot
            record.cancellation.set()
            now = datetime.now(UTC)
            if record.snapshot.status is JobStatus.QUEUED:
                record.snapshot = replace(
                    record.snapshot,
                    status=JobStatus.CANCELLED,
                    stage="cancelled",
                    message=f"{self._label} cancelled while queued",
                    updated_at=now,
                )
            else:
                record.snapshot = replace(
                    record.snapshot,
                    message="Cancellation requested after the active model request",
                    updated_at=now,
                )
            self._persist(record.snapshot)
            return record.snapshot

    def remove(self, investigation_id: str) -> None:
        with self._lock:
            record = self._jobs.get(investigation_id)
            if record is not None and record.snapshot.status in {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
            }:
                self._finish(
                    investigation_id,
                    record.snapshot.job_id,
                    JobStatus.CANCELLED,
                    "Indexing cancelled after case change",
                )
            record = self._jobs.pop(investigation_id, None)
            self._latest_progress.pop(investigation_id, None)
            self._chunk_counts.pop(investigation_id, None)
            if record:
                record.cancellation.set()
        if self._on_change is not None:
            self._on_change(investigation_id)

    def flush(self, timeout: float = 10) -> bool:
        return self._writer.flush(timeout)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for record in self._jobs.values():
                record.cancellation.set()
        self._queue.put(None)

    def _consume(self) -> None:
        while True:
            queued = self._queue.get()
            try:
                if queued is None:
                    self._writer.close()
                    return
                investigation_id, job_id = queued
                self._execute(investigation_id, job_id)
            finally:
                self._queue.task_done()

    def _execute(self, investigation_id: str, job_id: str) -> None:
        with self._lock:
            record = self._matching(investigation_id, job_id)
            if record is None or record.snapshot.status is not JobStatus.QUEUED:
                return
            record.snapshot = replace(
                record.snapshot,
                status=JobStatus.RUNNING,
                stage="cataloging" if self._kind is JobKind.CATALOG else "embedding",
                message=f"Preparing documents for {self._label}",
                updated_at=datetime.now(UTC),
            )
            self._persist(record.snapshot)
        try:
            count = self._runner.index_knowledge_base(
                record.investigation,
                record.documents,
                record.cancellation.is_set,
                lambda progress: self._progress(investigation_id, job_id, progress),
            )
        except InvestigationChatCancelledError:
            self._finish(investigation_id, job_id, JobStatus.CANCELLED, f"{self._label} cancelled")
        except Exception as error:
            logger.error(
                "Queued indexing failed. kind=%s investigation_id=%s error_type=%s",
                self._kind.value,
                investigation_id,
                type(error).__name__,
            )
            self._finish(
                investigation_id,
                job_id,
                JobStatus.FAILED,
                str(error)
                if isinstance(error, CatalogBatchError)
                else f"{self._label} failed; check AI and storage, then retry",
                str(error)
                if isinstance(error, CatalogBatchError)
                else f"{self._label} could not finish",
            )
        else:
            if record.cancellation.is_set():
                self._finish(
                    investigation_id, job_id, JobStatus.CANCELLED, f"{self._label} cancelled"
                )
                return
            chunks = sum(self._chunk_counts.get(investigation_id, {}).values())
            noun = "document" if count == 1 else "documents"
            chunk_label = f" · {chunks} chunks" if chunks else ""
            self._finish(
                investigation_id,
                job_id,
                JobStatus.COMPLETED,
                (
                    f"Cataloged {count} {noun} · check page review counts in Evidence"
                    if self._kind is JobKind.CATALOG
                    else f"RAG verified in Qdrant · {count} {noun}{chunk_label}"
                ),
            )

    def _progress(self, investigation_id: str, job_id: str, progress: RagIndexProgress) -> None:
        with self._lock:
            record = self._matching(investigation_id, job_id)
            if record is None or record.snapshot.status is not JobStatus.RUNNING:
                return
            record.snapshot = replace(
                record.snapshot,
                stage=progress.state.value,
                completed=progress.completed,
                total=progress.total,
                message=f"{progress.detail or 'Indexing'} · {progress.document_name}",
                updated_at=datetime.now(UTC),
            )
            self._latest_progress[investigation_id] = progress
            if progress.chunk_count:
                self._chunk_counts.setdefault(investigation_id, {})[progress.document_id] = (
                    progress.chunk_count
                )
            self._persist(record.snapshot)

    def _finish(
        self,
        investigation_id: str,
        job_id: str,
        status: JobStatus,
        message: str,
        error: str | None = None,
    ) -> None:
        with self._lock:
            record = self._matching(investigation_id, job_id)
            if record is None:
                return
            record.snapshot = replace(
                record.snapshot,
                status=status,
                stage=status.value,
                completed=(
                    record.snapshot.total
                    if status is JobStatus.COMPLETED
                    else record.snapshot.completed
                ),
                message=message,
                error=error,
                updated_at=datetime.now(UTC),
            )
            self._persist(record.snapshot)

    def _matching(self, investigation_id: str, job_id: str) -> _RagJobRecord | None:
        record = self._jobs.get(investigation_id)
        return record if record and record.snapshot.job_id == job_id else None

    def _persist(self, snapshot: BackgroundJob) -> None:
        self._writer.submit(snapshot)
        if self._on_change is not None:
            self._on_change(snapshot.investigation_id)
