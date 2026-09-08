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
    page_groups,
)
from raven.graph.grounding import ground_items
from raven.models import (
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphItemStatus,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
)
from raven.repositories.knowledge_base import KnowledgeBaseStore
from raven.services.operations import InvestigationOperations

logger = logging.getLogger(__name__)


class GraphRunRepository(Protocol):
    def set_evidence_graph_state(
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
        operations: InvestigationOperations | None = None,
    ) -> None:
        self.operations = operations or InvestigationOperations()
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

    def review_item(
        self,
        graph: InvestigationGraph,
        item_id: str,
        status: GraphItemStatus,
    ) -> InvestigationGraph:
        """Reload before review so stale UI snapshots cannot overwrite other decisions."""
        with self.operations.operation(graph.investigation_id) as cancelled:
            if cancelled():
                raise GraphAnalysisValidationError("The investigation is being updated")
            latest = self.latest(graph.investigation_id)
            if latest is None or latest.run_id != graph.run_id:
                raise GraphAnalysisValidationError("Reload the latest graph before reviewing")
            return self._review_item(latest, item_id, status)

    def _review_item(
        self, graph: InvestigationGraph, item_id: str, status: GraphItemStatus
    ) -> InvestigationGraph:
        found = any(entity.entity_id == item_id for entity in graph.entities) or any(
            relationship.relationship_id == item_id for relationship in graph.relationships
        )
        if not found:
            raise GraphAnalysisValidationError("The selected graph item no longer exists")
        entities = tuple(
            replace(entity, status=status) if entity.entity_id == item_id else entity
            for entity in graph.entities
        )
        relationships = tuple(
            replace(relationship, status=status)
            if relationship.relationship_id == item_id
            else relationship
            for relationship in graph.relationships
        )
        previous = next(
            item.status
            for item in (*graph.entities, *graph.relationships)
            if getattr(item, "entity_id", getattr(item, "relationship_id", None)) == item_id
        )
        reviewed = replace(
            graph,
            entities=entities,
            relationships=relationships,
            review_history=(
                *graph.review_history,
                (item_id, previous.value, status.value, datetime.now(UTC).isoformat()),
            ),
        )
        self._repository.save_graph_snapshot(reviewed)
        try:
            self._project(reviewed)
        except GraphPersistenceError:
            logger.warning(
                "Review checkpoint saved; Neo4j projection pending. run_id=%s", graph.run_id
            )
        return reviewed

    def _project(self, graph: InvestigationGraph) -> None:
        self._graph_store.save_graph_snapshot(graph)
        acknowledge = getattr(self._repository, "mark_graph_projected", None)
        if acknowledge is not None:
            acknowledge(graph.investigation_id, graph.run_id)

    def reconcile_projections(self) -> int:
        """Replay the latest authoritative checkpoint after a service reconnect."""
        pending = getattr(self._repository, "pending_graph_investigations", None)
        if pending is None:
            return 0
        recovered = 0
        for investigation_id in pending():
            with self.operations.operation(investigation_id) as cancelled:
                if cancelled():
                    continue
                graph = self.latest(investigation_id)
                if graph is not None:
                    self._project(graph)
                    self._repository.acknowledge_graph_projections(investigation_id)
                    recovered += 1
        return recovered

    def runs(self, investigation_id: str) -> tuple[GraphAnalysisRun, ...]:
        method = getattr(self._repository, "list_graph_runs", None)
        return tuple(method(investigation_id)) if method is not None else ()

    def snapshot(self, investigation_id: str, run_id: str) -> InvestigationGraph | None:
        method = getattr(self._repository, "graph_snapshot", None)
        return method(investigation_id, run_id) if method is not None else None

    def invalidate(self, investigation_id: str) -> None:
        """Remove a graph that no longer matches the investigation analysis profile."""
        invalidate_repository = getattr(self._repository, "invalidate_graph", None)
        if invalidate_repository is not None:
            invalidate_repository(investigation_id)
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
        with self.operations.operation(investigation.investigation_id, cancelled) as stopped:
            return self._analyze(investigation, documents, preparation_mode, stopped, progress)

    def _analyze(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode = EvidencePreparationMode.COMPRESS,
        cancelled: CancelledCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> GraphAnalysisResult:
        if cancelled is not None and cancelled():
            raise GraphAnalysisCancelledError("Graph analysis cancelled")
        if not documents:
            raise GraphAnalysisValidationError("Add at least one Evidence document before analysis")
        if not self._ai_node.available:
            raise GraphAnalysisValidationError(
                "The shared AI node is not connected; test the inference node before analysis"
            )
        try:
            vocabulary = self._extractor.resolve_vocabulary(investigation.analysis_domain)
        except ConfigurationError as error:
            raise GraphAnalysisValidationError(
                f"Investigation analysis domain is unavailable: {investigation.analysis_domain}"
            ) from error
        run = self._new_run(investigation, documents, preparation_mode, vocabulary)
        self._repository.save_graph_run(run)
        try:
            entity_groups: list[tuple] = []
            relationship_groups: list[tuple] = []
            model_names: list[str] = []
            evidence_states: list[tuple[str, EvidenceIngestionState]] = []
            completed = 0
            failed = 0
            failures: list[str] = []
            partial_warnings: list[str] = []
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
                self._repository.set_evidence_graph_state(
                    document.document_id,
                    EvidenceIngestionState.PROCESSING,
                )
                try:
                    pages = self._knowledge_bases.extract_pages(document, cancelled)
                    text = "\n\n".join(page for page in pages if page.strip())
                    if not text:
                        raise GraphAnalysisValidationError(
                            f"No extractable text in {document.original_name}"
                        )
                    grouped_pages = page_groups(pages) if len(pages) > 1 else None
                    if grouped_pages is not None:
                        self._notify(
                            progress,
                            GraphRunStatus.EXTRACTING,
                            index - 1,
                            len(documents),
                            f"{document.original_name} · grouped {len(pages)} pages into "
                            f"{len(grouped_pages)} AI batches",
                        )
                    entities, relationships, model_name = self._extractor.extract(
                        investigation.investigation_id,
                        document.document_id,
                        text,
                        investigation.analysis_language,
                        preparation_mode,
                        investigation.analysis_domain,
                        vocabulary,
                        lambda message, position=index, document_name=document.original_name: (
                            self._notify(
                                progress,
                                GraphRunStatus.EXTRACTING,
                                position - 1,
                                len(documents),
                                f"{document_name} · {message}",
                            )
                        ),
                        cancelled,
                        grouped_pages,
                        lambda message, document_name=document.original_name: (
                            partial_warnings.append(f"{document_name}: {message}")
                        ),
                    )
                    if cancelled is not None and cancelled():
                        raise GraphAnalysisCancelledError("Graph analysis cancelled")
                    entities = ground_items(entities, document.document_id, pages)
                    relationships = ground_items(relationships, document.document_id, pages)
                    missing_support = sum(
                        not any(span.verified_original for span in item.support)
                        for item in (*entities, *relationships)
                    )
                    if missing_support:
                        partial_warnings.append(
                            f"{document.original_name}: {missing_support} candidates "
                            "need original-source review"
                        )
                    existing_entities, _ = consolidate_graph(entity_groups, relationship_groups)
                    entities, relationships = self._extractor.resolve_against(
                        investigation.investigation_id,
                        entities,
                        relationships,
                        existing_entities,
                        cancelled,
                    )
                except (GraphAnalysisCancelledError, InvestigationCancelledError) as error:
                    raise GraphAnalysisCancelledError("Graph analysis cancelled") from error
                except Exception as error:
                    failed += 1
                    failures.append(f"{document.original_name}: {error}")
                    logger.warning(
                        "Evidence graph extraction failed. investigation_id=%s "
                        "document_id=%s error_type=%s",
                        investigation.investigation_id,
                        document.document_id,
                        type(error).__name__,
                    )
                    self._repository.set_evidence_graph_state(
                        document.document_id,
                        EvidenceIngestionState.FAILED,
                    )
                    evidence_states.append((document.document_id, EvidenceIngestionState.FAILED))
                else:
                    completed += 1
                    entity_groups.append(entities)
                    relationship_groups.append(relationships)
                    model_names.append(model_name)
                    self._repository.set_evidence_graph_state(
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
                detail = failures[0] if len(failures) == 1 else "; ".join(failures[:3])
                message = (
                    f"Semantic Evidence analysis failed · {detail}"
                    if detail
                    else "No Evidence document produced an analyzable result"
                )
                failed_run = replace(
                    run,
                    status=GraphRunStatus.FAILED,
                    evidence_failed=failed,
                    last_error=message,
                    updated_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
                self._repository.save_graph_run(failed_run)
                run = failed_run
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
            if cancelled is not None and cancelled():
                raise GraphAnalysisCancelledError("Graph analysis cancelled")
            self._repository.save_graph_snapshot(graph)

            warnings = list(dict.fromkeys(partial_warnings))
            if failures:
                warnings.append(
                    f"{len(failures)} Evidence document(s) failed semantic analysis: "
                    + "; ".join(failures[:3])
                )
            try:
                self._project(graph)
            except GraphPersistenceError as error:
                warnings.append(str(error))
                logger.warning(
                    "Neo4j graph synchronization failed. investigation_id=%s run_id=%s",
                    investigation.investigation_id,
                    run.run_id,
                )
            status = (
                GraphRunStatus.COMPLETED_WITH_WARNINGS
                if failed or warnings
                else GraphRunStatus.COMPLETED
            )
            warning = " · ".join(warnings) or None
            run = replace(
                run,
                status=status,
                evidence_completed=completed,
                evidence_failed=failed,
                entity_count=len(entities),
                relationship_count=len(relationships),
                model_name=",".join(dict.fromkeys(model_names)) or None,
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
        except (GraphAnalysisCancelledError, InvestigationCancelledError):
            for document in documents:
                self._repository.set_evidence_graph_state(
                    document.document_id, EvidenceIngestionState.PENDING
                )
            self._cancel(run, completed, failed)
            raise GraphAnalysisCancelledError("Graph analysis cancelled") from None
        except Exception:
            try:
                self._repository.save_graph_run(
                    replace(
                        run,
                        status=GraphRunStatus.FAILED,
                        updated_at=datetime.now(UTC),
                        completed_at=datetime.now(UTC),
                        last_error=run.last_error or "Analysis failed; check the affected service",
                    )
                )
            except Exception:
                logger.warning("Unable to finalize failed graph run. run_id=%s", run.run_id)
            raise

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
            inference_profile=tuple(
                (key, str(getattr(self._ai_node.settings, key, "")))
                for key in ("provider", "model", "thinking", "random_seed", "context_size", "top_k")
            ),
            evidence_manifest=tuple(
                (document.document_id, document.sha256) for document in documents
            ),
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
