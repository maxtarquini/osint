"""Application-owned FIFO queue for graph-analysis jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from queue import Queue
from threading import Event, RLock, Thread
from typing import Protocol
from uuid import uuid4

from raven.exceptions import GraphAnalysisCancelledError, GraphAnalysisError
from raven.models import (
    BackgroundJob,
    EvidenceDocument,
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphJobStatus,
    GraphRunStatus,
    Investigation,
    JobKind,
    JobStatus,
)
from raven.services.job_persistence import BackgroundJobWriter

logger = logging.getLogger(__name__)


class GraphAnalysisRunner(Protocol):
    """Execution seam implemented by the persistent graph-analysis service."""

    def analyze(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[GraphAnalysisProgress], None] | None = None,
    ) -> GraphAnalysisResult: ...


class JobRecorder(Protocol):
    def save_background_job(self, job: BackgroundJob) -> None: ...


@dataclass(slots=True)
class _GraphJobRecord:
    snapshot: GraphAnalysisJob
    investigation: Investigation
    documents: tuple[EvidenceDocument, ...]
    cancellation: Event


class GraphAnalysisQueue:
    """Run graph jobs independently from any mounted Textual screen."""

    def __init__(
        self,
        runner: GraphAnalysisRunner,
        recorder: JobRecorder | None = None,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        self._runner = runner
        self._writer = BackgroundJobWriter(recorder)
        self._on_change = on_change
        self._names: dict[str, str] = {}
        self._jobs: dict[str, _GraphJobRecord] = {}
        self._queue: Queue[tuple[str, str] | None] = Queue()
        self._lock = RLock()
        self._closed = False
        self._thread = Thread(
            target=self._consume,
            name="raven-graph-analysis-queue",
            daemon=True,
        )
        self._thread.start()

    def enqueue(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
    ) -> GraphAnalysisJob:
        """Append one job, returning an existing active job for duplicate submissions."""
        with self._lock:
            if self._closed:
                raise GraphAnalysisError("Graph analysis queue is closed")
            current = self._jobs.get(investigation.investigation_id)
            if current is not None and current.snapshot.status in {
                GraphJobStatus.QUEUED,
                GraphJobStatus.RUNNING,
            }:
                return current.snapshot
            self._names[investigation.investigation_id] = investigation.name
            now = datetime.now(UTC)
            job_id = str(uuid4())
            snapshot = GraphAnalysisJob(
                job_id=job_id,
                investigation_id=investigation.investigation_id,
                status=GraphJobStatus.QUEUED,
                preparation_mode=preparation_mode,
                submitted_at=now,
                updated_at=now,
                progress=GraphAnalysisProgress(
                    GraphRunStatus.QUEUED,
                    0,
                    len(documents),
                    "Queued for graph analysis",
                ),
            )
            self._jobs[investigation.investigation_id] = _GraphJobRecord(
                snapshot,
                investigation,
                documents,
                Event(),
            )
            self._persist(snapshot)
            self._queue.put((investigation.investigation_id, job_id))
            return snapshot

    def snapshot(self, investigation_id: str) -> GraphAnalysisJob | None:
        """Return the latest immutable job state for one investigation."""
        with self._lock:
            record = self._jobs.get(investigation_id)
            return record.snapshot if record is not None else None

    def investigation_name(self, investigation_id: str) -> str:
        with self._lock:
            return self._names.get(investigation_id, "")

    def snapshots(self) -> tuple[GraphAnalysisJob, ...]:
        """Return newest in-memory snapshots for immediate UI refreshes."""
        with self._lock:
            return tuple(
                sorted(
                    (record.snapshot for record in self._jobs.values()),
                    key=lambda item: item.updated_at,
                    reverse=True,
                )
            )

    def cancel(self, investigation_id: str) -> GraphAnalysisJob | None:
        """Cancel queued work immediately or request cancellation for active work."""
        with self._lock:
            record = self._jobs.get(investigation_id)
            if record is None or record.snapshot.status not in {
                GraphJobStatus.QUEUED,
                GraphJobStatus.RUNNING,
            }:
                return record.snapshot if record is not None else None
            record.cancellation.set()
            now = datetime.now(UTC)
            if record.snapshot.status is GraphJobStatus.QUEUED:
                record.snapshot = replace(
                    record.snapshot,
                    status=GraphJobStatus.CANCELLED,
                    updated_at=now,
                    progress=GraphAnalysisProgress(
                        GraphRunStatus.CANCELLED,
                        record.snapshot.progress.completed,
                        record.snapshot.progress.total,
                        "Analysis cancelled while queued",
                    ),
                )
            else:
                record.snapshot = replace(
                    record.snapshot,
                    updated_at=now,
                    progress=replace(
                        record.snapshot.progress,
                        message="Cancellation requested after the active model call",
                    ),
                )
            self._persist(record.snapshot)
            return record.snapshot

    def remove(self, investigation_id: str) -> None:
        """Forget a case-owned job after requesting cancellation."""
        with self._lock:
            record = self._jobs.get(investigation_id)
            if record is not None and record.snapshot.status in {
                GraphJobStatus.QUEUED,
                GraphJobStatus.RUNNING,
            }:
                self._finish_cancelled(investigation_id, record.snapshot.job_id)
            record = self._jobs.pop(investigation_id, None)
            if record is not None:
                record.cancellation.set()
        if self._on_change is not None:
            self._on_change(investigation_id)

    def flush(self, timeout: float = 10) -> bool:
        return self._writer.flush(timeout)

    def close(self) -> None:
        """Stop accepting work and request cancellation of remaining jobs."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for record in self._jobs.values():
                if record.snapshot.status in {GraphJobStatus.QUEUED, GraphJobStatus.RUNNING}:
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
                record = self._begin(investigation_id, job_id)
                if record is not None:
                    self._execute(investigation_id, job_id, record)
            finally:
                self._queue.task_done()

    def _begin(self, investigation_id: str, job_id: str) -> _GraphJobRecord | None:
        with self._lock:
            record = self._jobs.get(investigation_id)
            if (
                record is None
                or record.snapshot.job_id != job_id
                or record.snapshot.status is not GraphJobStatus.QUEUED
            ):
                return None
            now = datetime.now(UTC)
            record.snapshot = replace(
                record.snapshot,
                status=GraphJobStatus.RUNNING,
                updated_at=now,
                progress=replace(
                    record.snapshot.progress,
                    stage=GraphRunStatus.EXTRACTING,
                    message="Starting persistent graph analysis",
                ),
            )
            self._persist(record.snapshot)
            return record

    def _execute(
        self,
        investigation_id: str,
        job_id: str,
        record: _GraphJobRecord,
    ) -> None:
        try:
            result = self._runner.analyze(
                record.investigation,
                record.documents,
                record.snapshot.preparation_mode,
                record.cancellation.is_set,
                lambda progress: self._progress(investigation_id, job_id, progress),
            )
        except GraphAnalysisCancelledError:
            self._finish_cancelled(investigation_id, job_id)
        except GraphAnalysisError as error:
            self._finish_failed(investigation_id, job_id, str(error))
        except Exception as error:
            logger.error(
                "Unexpected queued graph analysis failure. investigation_id=%s "
                "job_id=%s error_type=%s",
                investigation_id,
                job_id,
                type(error).__name__,
            )
            self._finish_failed(
                investigation_id,
                job_id,
                "Unable to analyze Evidence; check the Raven log",
            )
        else:
            # The service checks cancellation before its commit point. A completed
            # publication must remain completed if a late cancellation arrives.
            self._finish_completed(investigation_id, job_id, result)

    def _progress(
        self,
        investigation_id: str,
        job_id: str,
        progress: GraphAnalysisProgress,
    ) -> None:
        with self._lock:
            record = self._matching_record(investigation_id, job_id)
            if record is not None and record.snapshot.status is GraphJobStatus.RUNNING:
                record.snapshot = replace(
                    record.snapshot,
                    updated_at=datetime.now(UTC),
                    progress=progress,
                )
                self._persist(record.snapshot)

    def _finish_completed(
        self,
        investigation_id: str,
        job_id: str,
        result: GraphAnalysisResult,
    ) -> None:
        with self._lock:
            record = self._matching_record(investigation_id, job_id)
            if record is None:
                return
            record.snapshot = replace(
                record.snapshot,
                status=GraphJobStatus.COMPLETED,
                updated_at=datetime.now(UTC),
                progress=GraphAnalysisProgress(
                    result.run.status,
                    result.run.evidence_completed,
                    result.run.evidence_total,
                    "Graph analysis completed",
                ),
                result=result,
                error=result.run.last_error,
            )
            self._persist(record.snapshot)

    def _finish_cancelled(self, investigation_id: str, job_id: str) -> None:
        with self._lock:
            record = self._matching_record(investigation_id, job_id)
            if record is None:
                return
            record.snapshot = replace(
                record.snapshot,
                status=GraphJobStatus.CANCELLED,
                updated_at=datetime.now(UTC),
                progress=replace(
                    record.snapshot.progress,
                    stage=GraphRunStatus.CANCELLED,
                    message="Graph analysis cancelled",
                ),
            )
            self._persist(record.snapshot)

    def _finish_failed(self, investigation_id: str, job_id: str, detail: str) -> None:
        with self._lock:
            record = self._matching_record(investigation_id, job_id)
            if record is None:
                return
            record.snapshot = replace(
                record.snapshot,
                status=GraphJobStatus.FAILED,
                updated_at=datetime.now(UTC),
                progress=replace(
                    record.snapshot.progress,
                    stage=GraphRunStatus.FAILED,
                    message="Graph analysis failed",
                ),
                error=detail,
            )
            self._persist(record.snapshot)

    def _persist(self, snapshot: GraphAnalysisJob) -> None:
        self._writer.submit(
            BackgroundJob(
                job_id=snapshot.job_id,
                investigation_id=snapshot.investigation_id,
                investigation_name=self._names.get(snapshot.investigation_id, ""),
                kind=JobKind.GRAPH,
                status=JobStatus(snapshot.status.value),
                stage=snapshot.progress.stage.value,
                completed=snapshot.progress.completed,
                total=snapshot.progress.total,
                message=snapshot.progress.message,
                created_at=snapshot.submitted_at,
                updated_at=snapshot.updated_at,
                error=snapshot.error,
            )
        )
        if self._on_change is not None:
            self._on_change(snapshot.investigation_id)

    def _matching_record(
        self,
        investigation_id: str,
        job_id: str,
    ) -> _GraphJobRecord | None:
        record = self._jobs.get(investigation_id)
        if record is None or record.snapshot.job_id != job_id:
            return None
        return record
