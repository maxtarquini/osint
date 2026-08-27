"""Behavior checks for application-owned graph-analysis jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep

from raven.models import (
    AnalysisLanguage,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphJobStatus,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
)
from raven.services.graph_jobs import GraphAnalysisQueue


class BlockingGraphRunner:
    def __init__(self) -> None:
        self.first_started = Event()
        self.release_first = Event()
        self.calls: list[str] = []

    def analyze(
        self,
        investigation,
        documents,
        preparation_mode,
        cancelled=None,
        progress=None,
    ) -> GraphAnalysisResult:
        self.calls.append(investigation.investigation_id)
        if progress is not None:
            progress(
                GraphAnalysisProgress(
                    GraphRunStatus.EXTRACTING,
                    0,
                    len(documents),
                    f"Analyzing {documents[0].original_name}",
                )
            )
        if len(self.calls) == 1:
            self.first_started.set()
            assert self.release_first.wait(2)
        now = datetime.now(UTC)
        run = GraphAnalysisRun(
            run_id=f"run-{investigation.investigation_id}",
            investigation_id=investigation.investigation_id,
            status=GraphRunStatus.COMPLETED,
            preparation_mode=preparation_mode,
            analysis_language=investigation.analysis_language.value,
            evidence_total=len(documents),
            evidence_completed=len(documents),
            evidence_failed=0,
            entity_count=0,
            relationship_count=0,
            model_name="test-model",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        graph = InvestigationGraph(
            investigation.investigation_id,
            run.run_id,
            (),
            (),
            now,
        )
        return GraphAnalysisResult(run, graph)


def _investigation(position: int) -> tuple[Investigation, EvidenceDocument]:
    now = datetime.now(UTC)
    investigation_id = f"case-{position}"
    document = EvidenceDocument(
        document_id=f"document-{position}",
        investigation_id=investigation_id,
        original_name=f"report-{position}.pdf",
        storage_key=f"{investigation_id}/report.pdf",
        media_type="application/pdf",
        file_format="PDF",
        size_bytes=100,
        sha256=str(position) * 64,
        page_count=1,
        page_count_estimated=False,
        ingestion_state=EvidenceIngestionState.PENDING,
        created_at=now,
    )
    return (
        Investigation(
            investigation_id=investigation_id,
            name=f"Case {position}",
            description="",
            questions=("Who?",),
            status=InvestigationStatus.DRAFT,
            evidence_documents=(document,),
            created_at=now,
            updated_at=now,
            analysis_language=AnalysisLanguage.ENGLISH,
        ),
        document,
    )


def _wait_for_status(
    queue: GraphAnalysisQueue,
    investigation_id: str,
    expected: GraphJobStatus,
) -> None:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        snapshot = queue.snapshot(investigation_id)
        if snapshot is not None and snapshot.status is expected:
            return
        sleep(0.01)
    snapshot = queue.snapshot(investigation_id)
    raise AssertionError(f"Expected {expected}, received {snapshot}")


def test_graph_jobs_are_queued_and_retained_by_investigation() -> None:
    runner = BlockingGraphRunner()
    queue = GraphAnalysisQueue(runner)
    first, first_document = _investigation(1)
    second, second_document = _investigation(2)
    try:
        queue.enqueue(first, (first_document,), EvidencePreparationMode.COMPRESS)
        assert runner.first_started.wait(1)
        queue.enqueue(second, (second_document,), EvidencePreparationMode.FULL_TEXT)

        assert queue.snapshot(first.investigation_id).status is GraphJobStatus.RUNNING
        assert queue.snapshot(second.investigation_id).status is GraphJobStatus.QUEUED

        runner.release_first.set()
        _wait_for_status(queue, first.investigation_id, GraphJobStatus.COMPLETED)
        _wait_for_status(queue, second.investigation_id, GraphJobStatus.COMPLETED)

        assert runner.calls == [first.investigation_id, second.investigation_id]
        assert queue.snapshot(first.investigation_id).result is not None
        assert queue.snapshot(second.investigation_id).result is not None
    finally:
        runner.release_first.set()
        queue.close()
