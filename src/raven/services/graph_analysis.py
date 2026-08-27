"""Persistent orchestration of the Hudiny-derived Evidence-to-Graph pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from raven.ai import SharedAiNode
from raven.exceptions import (
    ConfigurationError,
    GraphAnalysisCancelledError,
    GraphAnalysisError,
    GraphAnalysisValidationError,
    GraphPersistenceError,
    InvestigationCancelledError,
)
from raven.graph import (
    EvidenceGraphExtractor,
    NamedEntityVocabularyCatalog,
    ResolvedVocabulary,
    consolidate_graph,
)
from raven.models import (
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
)
from raven.repositories.knowledge_base import KnowledgeBaseStore

logger = logging.getLogger(__name__)


class GraphRunRepository(Protocol):
    def set_evidence_ingestion_state(
        self,
        document_id: str,
        state: EvidenceIngestionState,
    ) -> None: ...

    def save_graph_run(self, run: GraphAnalysisRun) -> None: ...

    def save_graph_snapshot(self, graph: InvestigationGraph) -> None: ...

    def latest_graph_snapshot(self, investigation_id: str) -> InvestigationGraph | None: ...


class GraphStore(Protocol):
    def save_graph_snapshot(self, graph: InvestigationGraph) -> None: ...

    def delete_investigation(self, investigation_id: str) -> None: ...


ProgressCallback = Callable[[GraphAnalysisProgress], None]
CancelledCallback = Callable[[], bool]


class GraphAnalysisService:
    """Create a proposed, Evidence-grounded graph and preserve every run state."""

    def __init__(
        self,
        repository: GraphRunRepository,
        graph_store: GraphStore,
        ai_node: SharedAiNode,
        knowledge_bases: KnowledgeBaseStore,
        dictionary_root: Path | None = None,
    ) -> None:
        self._repository = repository
        self._graph_store = graph_store
        self._ai_node = ai_node
        catalog = (
            NamedEntityVocabularyCatalog(dictionary_root) if dictionary_root is not None else None
        )
        self._extractor = EvidenceGraphExtractor(ai_node, catalog)
        self._knowledge_bases = knowledge_bases

    def configure_dictionary_root(self, root: Path) -> None:
        """Validate and activate a dictionary folder for subsequent graph runs."""
        self._extractor = EvidenceGraphExtractor(
            self._ai_node,
            NamedEntityVocabularyCatalog(root),
        )

    def latest(self, investigation_id: str) -> InvestigationGraph | None:
        return self._repository.latest_graph_snapshot(investigation_id)

    def invalidate(self, investigation_id: str) -> None:
        """Remove a graph that no longer matches the investigation analysis profile."""
        try:
            self._graph_store.delete_investigation(investigation_id)
        except GraphPersistenceError:
            logger.warning(
                "Unable to invalidate Neo4j graph. investigation_id=%s",
                investigation_id,
            )

    def remove_investigation(self, investigation_id: str) -> None:
        """Remove the external graph, failing when cleanup cannot be confirmed."""
        self._graph_store.delete_investigation(investigation_id)

    def analyze(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode = EvidencePreparationMode.COMPRESS,
        cancelled: CancelledCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> GraphAnalysisResult:
        if not documents:
            raise GraphAnalysisValidationError("Add at least one Evidence document before analysis")
        try:
            vocabulary = self._extractor.resolve_vocabulary(investigation.analysis_domain)
        except ConfigurationError as error:
            raise GraphAnalysisValidationError(
                f"Investigation analysis domain is unavailable: {investigation.analysis_domain}"
            ) from error
        run = self._new_run(investigation, documents, preparation_mode, vocabulary)
        self._repository.save_graph_run(run)
        entity_groups: list[tuple] = []
        relationship_groups: list[tuple] = []
        model_names: list[str] = []
        evidence_states: list[tuple[str, EvidenceIngestionState]] = []
        completed = 0
        failed = 0
        self._notify(
            progress, GraphRunStatus.EXTRACTING, 0, len(documents), "Starting Evidence analysis"
        )

        for index, document in enumerate(documents, 1):
            if cancelled is not None and cancelled():
                self._cancel(run, completed, failed)
                raise GraphAnalysisCancelledError("Graph analysis cancelled")
            self._notify(
                progress,
                GraphRunStatus.EXTRACTING,
                index - 1,
                len(documents),
                f"Analyzing {document.original_name}",
            )
            self._repository.set_evidence_ingestion_state(
                document.document_id,
                EvidenceIngestionState.PROCESSING,
            )
            try:
                text = self._knowledge_bases.extract_text(document, cancelled)
                if not text:
                    raise GraphAnalysisValidationError(
                        f"No extractable text in {document.original_name}"
                    )
                entities, relationships, model_name = self._extractor.extract(
                    investigation.investigation_id,
                    document.document_id,
                    text,
                    investigation.analysis_language,
                    preparation_mode,
                    investigation.analysis_domain,
                    vocabulary,
                )
                existing_entities, _ = consolidate_graph(entity_groups, relationship_groups)
                entities, relationships = self._extractor.resolve_against(
                    investigation.investigation_id,
                    entities,
                    relationships,
                    existing_entities,
                )
            except (GraphAnalysisCancelledError, InvestigationCancelledError) as error:
                self._cancel(run, completed, failed)
                raise GraphAnalysisCancelledError("Graph analysis cancelled") from error
            except Exception as error:
                failed += 1
                logger.warning(
                    "Evidence graph extraction failed. investigation_id=%s "
                    "document_id=%s error_type=%s",
                    investigation.investigation_id,
                    document.document_id,
                    type(error).__name__,
                )
                self._repository.set_evidence_ingestion_state(
                    document.document_id,
                    EvidenceIngestionState.FAILED,
                )
                evidence_states.append((document.document_id, EvidenceIngestionState.FAILED))
            else:
                completed += 1
                entity_groups.append(entities)
                relationship_groups.append(relationships)
                model_names.append(model_name)
                self._repository.set_evidence_ingestion_state(
                    document.document_id,
                    EvidenceIngestionState.READY,
                )
                evidence_states.append((document.document_id, EvidenceIngestionState.READY))
            run = replace(
                run,
                status=GraphRunStatus.EXTRACTING,
                evidence_completed=completed,
                evidence_failed=failed,
                updated_at=datetime.now(UTC),
            )
            self._repository.save_graph_run(run)

        if completed == 0:
            failed_run = replace(
                run,
                status=GraphRunStatus.FAILED,
                evidence_failed=failed,
                last_error="No Evidence document produced an analyzable result",
                updated_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            self._repository.save_graph_run(failed_run)
            raise GraphAnalysisError(failed_run.last_error)

        self._notify(
            progress,
            GraphRunStatus.CONSOLIDATING,
            completed,
            len(documents),
            "Consolidating entity and relationship candidates",
        )
        run = replace(run, status=GraphRunStatus.CONSOLIDATING, updated_at=datetime.now(UTC))
        self._repository.save_graph_run(run)
        entities, relationships = consolidate_graph(entity_groups, relationship_groups)
        now = datetime.now(UTC)
        graph = InvestigationGraph(
            investigation_id=investigation.investigation_id,
            run_id=run.run_id,
            entities=entities,
            relationships=relationships,
            generated_at=now,
        )
        self._repository.save_graph_snapshot(graph)

        warning: str | None = None
        try:
            self._graph_store.save_graph_snapshot(graph)
        except GraphPersistenceError as error:
            warning = str(error)
            logger.warning(
                "Neo4j graph synchronization failed. investigation_id=%s run_id=%s",
                investigation.investigation_id,
                run.run_id,
            )
        status = (
            GraphRunStatus.COMPLETED_WITH_WARNINGS
            if failed or warning
            else GraphRunStatus.COMPLETED
        )
        run = replace(
            run,
            status=status,
            evidence_completed=completed,
            evidence_failed=failed,
            entity_count=len(entities),
            relationship_count=len(relationships),
            model_name=",".join(dict.fromkeys(model_names)) or "deterministic",
            updated_at=now,
            completed_at=now,
            last_error=warning,
        )
        self._repository.save_graph_run(run)
        self._notify(
            progress,
            status,
            completed,
            len(documents),
            f"Graph ready: {len(entities)} entities, {len(relationships)} relationships",
        )
        return GraphAnalysisResult(
            run=run,
            graph=graph,
            evidence_states=tuple(evidence_states),
        )

    def _new_run(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
        vocabulary: ResolvedVocabulary,
    ) -> GraphAnalysisRun:
        now = datetime.now(UTC)
        return GraphAnalysisRun(
            run_id=str(uuid4()),
            investigation_id=investigation.investigation_id,
            status=GraphRunStatus.QUEUED,
            preparation_mode=preparation_mode,
            analysis_language=investigation.analysis_language.value,
            evidence_total=len(documents),
            evidence_completed=0,
            evidence_failed=0,
            entity_count=0,
            relationship_count=0,
            model_name=None,
            created_at=now,
            updated_at=now,
            dictionary_domain=vocabulary.domain_code,
            dictionary_hash=vocabulary.sha256,
            dictionary_versions=vocabulary.vocabulary_versions,
        )

    def _cancel(
        self,
        run: GraphAnalysisRun,
        completed: int,
        failed: int,
    ) -> GraphAnalysisRun:
        now = datetime.now(UTC)
        cancelled = replace(
            run,
            status=GraphRunStatus.CANCELLED,
            evidence_completed=completed,
            evidence_failed=failed,
            updated_at=now,
            completed_at=now,
        )
        self._repository.save_graph_run(cancelled)
        return cancelled

    @staticmethod
    def _notify(
        callback: ProgressCallback | None,
        stage: GraphRunStatus,
        completed: int,
        total: int,
        message: str,
    ) -> None:
        if callback is not None:
            callback(GraphAnalysisProgress(stage, completed, total, message))
