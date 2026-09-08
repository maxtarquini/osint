"""Use cases for investigations and their evidence knowledge bases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from raven.exceptions import InvestigationError, InvestigationPersistenceError
from raven.models import (
    EvidenceDocument,
    EvidenceIngestionState,
    Investigation,
    InvestigationDraft,
    InvestigationStatus,
)
from raven.repositories.knowledge_base import KnowledgeBaseStore

logger = logging.getLogger(__name__)


class InvestigationRepository(Protocol):
    def create_investigation(self, investigation: Investigation) -> None: ...

    def update_investigation(self, investigation: Investigation) -> None: ...

    def delete_investigation(self, investigation_id: str) -> None: ...

    def clear_graph_data(self, investigation_id: str) -> None: ...

    def reset_evidence_ingestion_states(self, investigation_id: str) -> None: ...

    def add_evidence(self, document: EvidenceDocument) -> None: ...

    def delete_evidence(self, document: EvidenceDocument) -> None: ...

    def list_investigations(self) -> tuple[Investigation, ...]: ...


class InvestigationService:
    """Manage investigation metadata separately from evidence document operations."""

    def __init__(
        self,
        repository: InvestigationRepository,
        knowledge_bases: KnowledgeBaseStore | None = None,
    ) -> None:
        self._repository = repository
        self._knowledge_bases = knowledge_bases or KnowledgeBaseStore()

    def create(self, draft: InvestigationDraft) -> Investigation:
        draft = draft.validated()
        investigation_id = str(uuid4())
        now = datetime.now(UTC)
        investigation = Investigation(
            investigation_id=investigation_id,
            name=draft.name,
            description=draft.description,
            questions=draft.questions,
            status=InvestigationStatus.DRAFT,
            evidence_documents=(),
            created_at=now,
            updated_at=now,
            analysis_language=draft.analysis_language,
            analysis_domain=draft.analysis_domain,
        )
        self._knowledge_bases.investigation_directory(
            investigation_id,
            create=True,
        )
        logger.info(
            "Creating investigation. investigation_id=%s question_count=%d",
            investigation_id,
            len(draft.questions),
        )
        try:
            self._repository.create_investigation(investigation)
        except InvestigationError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError("Unable to save the investigation") from error
        logger.info("Investigation created. investigation_id=%s", investigation_id)
        return investigation

    def list_investigations(self) -> tuple[Investigation, ...]:
        """Return persisted investigations with their evidence manifests."""
        try:
            return self._repository.list_investigations()
        except InvestigationError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load investigations") from error

    def update(self, current: Investigation, draft: InvestigationDraft) -> Investigation:
        """Update mutable metadata and invalidate analysis when its profile changes."""
        draft = draft.validated()
        profile_changed = (
            current.analysis_language != draft.analysis_language
            or current.analysis_domain != draft.analysis_domain
        )
        updated = replace(
            current,
            name=draft.name,
            description=draft.description,
            questions=draft.questions,
            analysis_language=draft.analysis_language,
            analysis_domain=draft.analysis_domain,
            updated_at=datetime.now(UTC),
        )
        logger.info(
            "Updating investigation. investigation_id=%s profile_changed=%s",
            current.investigation_id,
            profile_changed,
        )
        try:
            self._repository.update_investigation(updated)
            if profile_changed:
                self._repository.reset_evidence_ingestion_states(current.investigation_id)
                self._repository.clear_graph_data(current.investigation_id)
        except InvestigationError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError("Unable to update the investigation") from error
        if profile_changed:
            updated = replace(
                updated,
                evidence_documents=tuple(
                    replace(
                        document,
                        rag_state=EvidenceIngestionState.PENDING,
                        graph_state=EvidenceIngestionState.PENDING,
                    )
                    for document in updated.evidence_documents
                ),
            )
        return updated

    def delete(self, investigation: Investigation) -> None:
        """Delete one investigation and its isolated local Evidence directory."""
        logger.info(
            "Deleting investigation. investigation_id=%s",
            investigation.investigation_id,
        )
        roots = {self._knowledge_bases.root}
        roots.update(
            self._knowledge_bases.document_path(document).parent.parent
            for document in investigation.evidence_documents
        )
        staged: list[tuple[KnowledgeBaseStore, Path | None]] = []
        try:
            for root in sorted(roots):
                store = KnowledgeBaseStore(root)
                staged.append(
                    (store, store.stage_investigation_delete(investigation.investigation_id))
                )
            self._repository.delete_investigation(investigation.investigation_id)
        except Exception as error:
            for store, directory in reversed(staged):
                store.restore_investigation_delete(investigation.investigation_id, directory)
            if isinstance(error, InvestigationError):
                raise
            raise InvestigationPersistenceError("Unable to delete the investigation") from error
        for store, directory in staged:
            store.commit_investigation_delete(directory)
        logger.info(
            "Investigation deleted. investigation_id=%s",
            investigation.investigation_id,
        )

    def add_evidence(
        self,
        investigation_id: str,
        source: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> EvidenceDocument:
        logger.info("Adding evidence. investigation_id=%s", investigation_id)
        document = self._knowledge_bases.add(investigation_id, source, cancelled)
        try:
            self._repository.add_evidence(document)
        except InvestigationError:
            self._knowledge_bases.discard_document(document)
            raise
        except Exception as error:
            self._knowledge_bases.discard_document(document)
            raise InvestigationPersistenceError("Unable to register evidence document") from error
        logger.info(
            "Evidence added. investigation_id=%s document_id=%s",
            investigation_id,
            document.document_id,
        )
        return document

    def delete_evidence(self, document: EvidenceDocument) -> None:
        logger.info(
            "Deleting evidence. investigation_id=%s document_id=%s",
            document.investigation_id,
            document.document_id,
        )
        staged = self._knowledge_bases.stage_delete(document)
        try:
            self._repository.delete_evidence(document)
        except InvestigationError:
            self._knowledge_bases.restore_delete(document, staged)
            raise
        except Exception as error:
            self._knowledge_bases.restore_delete(document, staged)
            raise InvestigationPersistenceError("Unable to delete evidence metadata") from error
        self._knowledge_bases.commit_delete(staged)
        self._knowledge_bases.remove_ocr_cache(document)
