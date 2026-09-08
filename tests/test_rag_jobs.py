"""Persistent application-owned RAG queue behavior."""

from datetime import UTC, datetime
from time import monotonic, sleep

from raven.models import (
    AnalysisLanguage,
    BackgroundJob,
    EvidenceDocument,
    EvidenceIngestionState,
    Investigation,
    InvestigationStatus,
    JobStatus,
    RagIndexProgress,
)
from raven.services.rag_jobs import RagIndexQueue


class Recorder:
    def __init__(self) -> None:
        self.snapshots: list[BackgroundJob] = []

    def save_background_job(self, job: BackgroundJob) -> None:
        self.snapshots.append(job)


class Runner:
    def index_knowledge_base(self, investigation, documents, cancelled=None, progress=None):
        document = documents[0]
        if progress:
            progress(
                RagIndexProgress(
                    document.document_id,
                    document.original_name,
                    EvidenceIngestionState.PROCESSING,
                    0,
                    1,
                    "Embedding chunks",
                )
            )
            progress(
                RagIndexProgress(
                    document.document_id,
                    document.original_name,
                    EvidenceIngestionState.READY,
                    1,
                    1,
                    "Verified in Qdrant",
                    3,
                )
            )
        return 1


def test_rag_queue_retains_and_records_completed_job() -> None:
    now = datetime.now(UTC)
    document = EvidenceDocument(
        "document-id",
        "case-id",
        "report.pdf",
        "case-id/report.pdf",
        "application/pdf",
        "PDF",
        10,
        "0" * 64,
        1,
        False,
        EvidenceIngestionState.READY,
        now,
    )
    investigation = Investigation(
        "case-id",
        "Case",
        "",
        ("Who?",),
        InvestigationStatus.DRAFT,
        (document,),
        now,
        now,
        AnalysisLanguage.ENGLISH,
    )
    recorder = Recorder()
    queue = RagIndexQueue(Runner(), recorder)
    try:
        queued = queue.enqueue(investigation, (document,))
        deadline = monotonic() + 2
        while monotonic() < deadline:
            completed = queue.snapshot(investigation.investigation_id)
            if completed and completed.status is JobStatus.COMPLETED:
                break
            sleep(0.01)
        else:
            raise AssertionError("RAG job did not complete")

        assert queued.status is JobStatus.QUEUED
        assert completed.message.endswith("1 document · 3 chunks")
        assert recorder.snapshots[-1].status is JobStatus.COMPLETED
    finally:
        queue.close()
