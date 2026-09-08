"""Case lifecycle orchestration shared by all presentation surfaces."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from raven.exceptions import (
    GraphPersistenceError,
    InvestigationChatError,
    InvestigationPersistenceError,
)
from raven.models import EvidenceDocument, Investigation, InvestigationDraft
from raven.services.operations import InvestigationOperations


class CaseActions:
    def __init__(
        self,
        investigations: Any,
        graph: Any,
        chat: Any,
        graph_jobs: Any,
        rag_jobs: Any,
        operations: InvestigationOperations,
        catalog_jobs: Any = None,
        catalog: Any = None,
    ) -> None:
        self.investigations = investigations
        self.graph = graph
        self.chat = chat
        self.catalog = catalog
        self.queues = tuple(
            queue for queue in (graph_jobs, rag_jobs, catalog_jobs) if queue is not None
        )
        self.operations = operations

    def _cancel(self, investigation_id: str) -> None:
        for queue in self.queues:
            queue.remove(investigation_id)

    def _drain_records(self) -> None:
        if any(not queue.flush() for queue in self.queues):
            raise InvestigationPersistenceError("Job history is still saving; retry the operation")

    def add_evidence(
        self, investigation_id: str, source: Path, cancelled: Callable[[], bool] | None = None
    ) -> EvidenceDocument:
        self._cancel(investigation_id)
        with self.operations.mutation(investigation_id, cancelled):
            self._drain_records()
            return self.investigations.add_evidence(investigation_id, source, cancelled)

    def update(self, current: Investigation, draft: InvestigationDraft) -> Investigation:
        changed = (
            current.analysis_language != draft.analysis_language
            or current.analysis_domain != draft.analysis_domain
        )
        if not changed:
            return self.investigations.update(current, draft)
        self._cancel(current.investigation_id)
        with self.operations.mutation(current.investigation_id):
            self._drain_records()
            # Clear derived stores before changing metadata. On failure the old profile
            # remains authoritative and a retry can complete the cleanup idempotently.
            if self.chat is not None:
                self.chat.remove_investigation(current.investigation_id)
            if self.graph is not None:
                self.graph.remove_investigation(current.investigation_id)
            return self.investigations.update(current, draft)

    def delete(self, investigation: Investigation) -> None:
        investigation_id = investigation.investigation_id
        self._cancel(investigation_id)
        with self.operations.mutation(investigation_id):
            self._drain_records()
            try:
                if self.chat is not None:
                    self.chat.remove_investigation(investigation_id)
            except InvestigationChatError as error:
                raise InvestigationPersistenceError(
                    "RAG cleanup failed; the investigation was not deleted"
                ) from error
            try:
                if self.graph is not None:
                    self.graph.remove_investigation(investigation_id)
            except GraphPersistenceError as error:
                raise InvestigationPersistenceError(
                    "Neo4j graph cleanup failed; the investigation was not deleted"
                ) from error
            self.investigations.delete(investigation)

    def delete_evidence(self, document: EvidenceDocument) -> None:
        self._cancel(document.investigation_id)
        with self.operations.mutation(document.investigation_id):
            self._drain_records()
            if self.graph is not None:
                self.graph.invalidate(document.investigation_id)
            if self.chat is not None:
                self.chat.remove_document(document)
            if self.catalog is not None:
                self.catalog.repository.delete_catalogs(
                    document.investigation_id, document.document_id
                )
            self.investigations.delete_evidence(document)
