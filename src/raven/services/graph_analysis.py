"""Persistent orchestration of the Hudiny-derived Evidence-to-Graph pipeline."""

from __future__ import annotations

import json
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
    InvestigationChatCancelledError,
)
from raven.graph import (
    EvidenceGraphExtractor,
    NamedEntityVocabularyCatalog,
    ResolvedVocabulary,
    consolidate_graph,
)
from raven.graph.claims import compare_claims, project_claims
from raven.graph.integrity import IntegrityPageAnalyzer
from raven.graph.methods import extraction_profile, graph_method
from raven.graph.pages import PageGraphAnalyzer, plan_pages
from raven.models import (
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphClaim,
    GraphRelationship,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
    PageGraphAnalysis,
)
from raven.models.graph import GraphManifest
from raven.repositories.knowledge_base import KnowledgeBaseStore

logger = logging.getLogger(__name__)


class GraphRunRepository(Protocol):
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
        loader = getattr(self._repository, "active_graph_snapshot", None)
        return (
            loader(investigation_id)
            if callable(loader)
            else self._repository.latest_graph_snapshot(investigation_id)
        )

    def variants(self, investigation_id):
        return self._repository.list_graph_variants(investigation_id)

    def open_variant(self, investigation_id, run_id):
        graph = self._repository.graph_snapshot(investigation_id, run_id)
        if graph is None:
            raise GraphAnalysisValidationError("Variant does not belong to this investigation")
        return graph

    def activate_variant(self, investigation_id, run_id):
        graph = self.open_variant(investigation_id, run_id)
        # MongoDB is authoritative. A Neo4j failure cannot select a different snapshot;
        # retrieval falls back to the exact MongoDB variant.
        self._graph_store.save_graph_snapshot(graph)
        self._repository.activate_graph_variant(investigation_id, run_id)
        return graph

    def compare_variants(self, investigation_id, first_id, second_id):
        from raven.graph.variants import compare_variants

        return compare_variants(
            self.open_variant(investigation_id, first_id),
            self.open_variant(investigation_id, second_id),
        )

    def method_preference(self, investigation_id):
        return self._repository.graph_preferences(investigation_id).get(
            "method_id", "document_claims"
        )

    def set_method_preference(self, investigation_id, method_id):
        self._repository.set_graph_method(investigation_id, method_id)

    def invalidate(self, investigation_id: str) -> None:
        """Remove a graph that no longer matches the investigation analysis profile."""
        try:
            active = self.latest(investigation_id)
            if active is not None and active.manifest is not None:
                return
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
        *,
        method_id: str | None = None,
        variant_name: str = "",
    ) -> GraphAnalysisResult:
        if not documents:
            raise GraphAnalysisValidationError("Add at least one Evidence document before analysis")
        if any(doc.investigation_id != investigation.investigation_id for doc in documents):
            raise GraphAnalysisValidationError("Evidence does not belong to this investigation")
        try:
            vocabulary = self._extractor.resolve_vocabulary(investigation.analysis_domain)
        except ConfigurationError as error:
            raise GraphAnalysisValidationError(
                f"Investigation analysis domain is unavailable: {investigation.analysis_domain}"
            ) from error
        method = graph_method(method_id) if method_id else None
        run = self._new_run(investigation, documents, preparation_mode, vocabulary)
        if method:
            try:
                for document in documents:
                    if not self._knowledge_bases.verify_document_hash(document, cancelled):
                        raise GraphAnalysisValidationError(
                            "Stored Evidence hash differs from its manifest"
                        )
            except InvestigationCancelledError as error:
                raise GraphAnalysisCancelledError("Graph analysis cancelled") from error
            catalog_versions = []
            loader = getattr(self._repository, "load_catalog", None)
            for doc in documents:
                try:
                    catalog = (
                        loader(investigation.investigation_id, doc.document_id)
                        if callable(loader)
                        else None
                    )
                    catalog_versions.append(
                        (doc.document_id, catalog.signature if catalog else "missing")
                    )
                except Exception:
                    catalog_versions.append((doc.document_id, "unavailable"))
            settings = self._ai_node.settings
            configuration = {
                key: getattr(settings, key, None)
                for key in (
                    "provider",
                    "model",
                    "thinking",
                    "top_k",
                    "random_seed",
                    "context_size",
                    "timeout_seconds",
                )
            }
            configuration.update(
                language=investigation.analysis_language.value,
                preparation_requested=preparation_mode.value,
                extraction_basis="original",
                predicates="raven-predicates-v1",
                repair_budget=1,
                effective_thinking="medium",
                max_output_tokens=8192,
                comparisons="raven-comparison-v4",
                semantic_pair_retrieval="raven-source-candidates-v1",
                events="raven-event-records-v1",
                request_timeout=getattr(settings, "timeout_seconds", 120),
            )
            manifest = GraphManifest(
                method_id=method.method_id,
                method_version=method.version,
                prompt_version=method.prompt_version,
                documents=tuple((d.document_id, d.sha256) for d in documents),
                catalogs=tuple(catalog_versions),
                dictionary_hash=vocabulary.sha256,
                dictionary_versions=vocabulary.vocabulary_versions,
                dictionary_snapshot=vocabulary.json,
                model=getattr(settings, "model", "unavailable"),
                configuration=json.dumps(configuration, sort_keys=True),
            )
            run = replace(
                run,
                method_id=method.method_id,
                variant_name=variant_name.strip()[:120]
                or f"{method.name} · {run.created_at:%Y-%m-%d %H:%M}",
                manifest=manifest,
                prompt_version=method.prompt_version,
            )
        self._repository.save_graph_run(run)
        previous = self._repository.latest_graph_snapshot(investigation.investigation_id)
        previous_pages = (
            {(page.evidence_id, page.page_number): page for page in previous.pages}
            if previous is not None and previous.investigation_id == investigation.investigation_id
            else {}
        )
        page_analyzer = (
            IntegrityPageAnalyzer(
                self._extractor,
                method,
                lambda message: self._notify(
                    progress, GraphRunStatus.EXTRACTING, completed, len(documents), message
                ),
            )
            if method
            else PageGraphAnalyzer(self._extractor)
        )
        page_results: list[PageGraphAnalysis] = []
        entity_groups: list[tuple] = []
        claim_groups: list[tuple[GraphClaim, ...]] = []
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
            document_pages = []
            source_loaded = False
            try:
                pages = self._knowledge_bases.extract_pages(document, cancelled)
                source_loaded = True
                if not any(page.strip() for page in pages):
                    document_pages = [
                        PageGraphAnalysis(
                            document.document_id,
                            number,
                            "",
                            "",
                            "failed",
                            datetime.now(UTC),
                            error="no_extractable_text",
                        )
                        for number in range(1, (len(pages) or document.page_count or 1) + 1)
                    ]
                    raise GraphAnalysisValidationError(
                        f"No extractable text in {document.original_name}"
                    )
                catalog, catalog_error = None, False
                loader = getattr(self._repository, "load_catalog", None)
                if callable(loader):
                    try:
                        catalog = loader(investigation.investigation_id, document.document_id)
                    except Exception:
                        catalog_error = True
                plans = plan_pages(
                    investigation,
                    document.document_id,
                    pages,
                    catalog,
                    vocabulary,
                    self._ai_node,
                    preparation_mode,
                    catalog_error=catalog_error,
                    method_profile=extraction_profile(run.manifest) if run.manifest else None,
                )
                for page_index, plan in enumerate(plans, 1):
                    self._notify(
                        progress,
                        GraphRunStatus.EXTRACTING,
                        index - 1,
                        len(documents),
                        f"{document.original_name} · page {plan.number}/{len(pages)} "
                        f"({page_index}/{len(plans)}) · catalog: {plan.catalog_state}",
                    )
                    page_result = page_analyzer.analyze(
                        investigation,
                        document.document_id,
                        pages,
                        plan,
                        vocabulary,
                        preparation_mode,
                        previous_pages.get((document.document_id, plan.number)),
                        cancelled,
                    )
                    if previous is not None and page_result.state == "reused":
                        page_result = replace(page_result, cache_origin=previous.run_id)
                    document_pages.append(page_result)
                document_pages.sort(key=lambda page: page.page_number)
                # Resolve from the raw page cache every time; deleted or changed sources cannot
                # leave behind a previous merge or an old contradiction decision.
                raw_entities = tuple(entity for page in document_pages for entity in page.entities)
                raw_claims = tuple(claim for page in document_pages for claim in page.claims)
                proxies = tuple(
                    GraphRelationship(
                        claim.claim_id,
                        claim.subject_entity_id,
                        claim.object_entity_id or claim.subject_entity_id,
                        claim.predicate,
                    )
                    for claim in raw_claims
                )
                existing_entities, _ = consolidate_graph(entity_groups, ())
                entities, resolved_proxies = self._extractor.resolve_against(
                    investigation.investigation_id,
                    raw_entities,
                    proxies,
                    existing_entities,
                    cancelled=cancelled,
                )
                claims = tuple(
                    replace(
                        claim,
                        subject_entity_id=proxy.source_entity_id,
                        object_entity_id=proxy.target_entity_id if claim.object_entity_id else "",
                    )
                    for claim, proxy in zip(raw_claims, resolved_proxies, strict=True)
                )
            except (
                GraphAnalysisCancelledError,
                InvestigationCancelledError,
                InvestigationChatCancelledError,
            ) as error:
                self._cancel(
                    replace(run, page_outcomes=tuple((*page_results, *document_pages))),
                    completed,
                    failed,
                )
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
                evidence_states.append((document.document_id, EvidenceIngestionState.FAILED))
                # An unreadable source has known missing pages, or one logical unit when its
                # size is unknown. Never reuse the old document's output after a read failure.
                if document_pages:
                    document_pages = [
                        replace(
                            page,
                            state="partial" if page.entities else "failed",
                            error=page.error or "identity_resolution_failed",
                        )
                        for page in document_pages
                    ]
                    page_results.extend(document_pages)
                else:
                    page_results.extend(
                        PageGraphAnalysis(
                            document.document_id,
                            number,
                            "",
                            "",
                            "failed",
                            datetime.now(UTC),
                            error="page_analysis_failed" if source_loaded else "source_read_failed",
                        )
                        for number in range(1, (document.page_count or 1) + 1)
                    )
            else:
                page_results.extend(document_pages)
                incomplete = any(page.state in ("partial", "failed") for page in document_pages)
                failed += int(incomplete)
                completed += int(not incomplete)
                entity_groups.append(entities)
                claim_groups.append(claims)
                model_names.extend(page.model_name for page in document_pages if page.model_name)
                state = (
                    EvidenceIngestionState.FAILED if incomplete else EvidenceIngestionState.READY
                )
                evidence_states.append((document.document_id, state))
            run = replace(
                run,
                status=GraphRunStatus.EXTRACTING,
                evidence_completed=completed,
                evidence_failed=failed,
                page_outcomes=tuple(page_results),
                updated_at=datetime.now(UTC),
            )
            self._repository.save_graph_run(run)

        if completed == 0 and not any(entity_groups):
            failed_run = replace(
                run,
                status=GraphRunStatus.FAILED,
                evidence_failed=failed,
                last_error="No Evidence document produced an analyzable result. "
                + self._page_errors(page_results),
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
        entities, _ = consolidate_graph(entity_groups, ())
        claims = tuple(claim for group in claim_groups for claim in group)
        comparison_diagnostics = []
        try:
            claim_links = compare_claims(claims, entities, cancelled=cancelled)
            if method and method.cross_source_review:
                from raven.agents.source_review import review_comparisons

                self._notify(
                    progress,
                    GraphRunStatus.CONSOLIDATING,
                    completed,
                    len(documents),
                    "CrossSourceReviewAgent · reviewing attributed comparisons",
                )
                claim_links = review_comparisons(
                    self._ai_node,
                    investigation.investigation_id,
                    claim_links,
                    claims,
                    cancelled,
                    entities,
                    diagnostics=comparison_diagnostics,
                    on_stage=lambda stage: self._notify(
                        progress, GraphRunStatus.CONSOLIDATING, completed, len(documents), stage
                    ),
                )
            relationships = project_claims(claims, cancelled=cancelled)
        except (
            GraphAnalysisCancelledError,
            InvestigationChatCancelledError,
            InvestigationCancelledError,
        ) as error:
            self._cancel(run, completed, failed)
            raise GraphAnalysisCancelledError("Graph analysis cancelled") from error
        from raven.graph.events import event_records

        now = datetime.now(UTC)
        graph = InvestigationGraph(
            investigation_id=investigation.investigation_id,
            run_id=run.run_id,
            entities=entities,
            relationships=relationships,
            generated_at=now,
            claims=claims,
            claim_links=claim_links,
            pages=tuple(page_results),
            variant_name=run.variant_name,
            manifest=run.manifest,
            events=event_records(claims, entities) if method else (),
        )
        if cancelled is not None and cancelled():
            self._cancel(run, completed, failed)
            raise GraphAnalysisCancelledError("Graph analysis cancelled")
        self._repository.save_graph_snapshot(graph)

        warnings = list(comparison_diagnostics)
        if method:
            review_count = sum(
                item.semantic_support != "supported" for item in (*entities, *claims)
            )
            if review_count:
                warnings.append(f"{review_count} candidate(s) require semantic review")
        unsupported = sum(
            not item.support or not all(span.verified_original for span in item.support)
            for item in (*entities, *claims)
        )
        if unsupported:
            warnings.append(
                f"{unsupported} graph item(s) have missing or unverified source citations"
            )
        if "deterministic-fallback" in model_names:
            warnings.append("Semantic extraction failed; only deterministic observables retained")
        incomplete_pages = sum(page.state in ("partial", "failed") for page in page_results)
        if incomplete_pages:
            warnings.append(
                f"{incomplete_pages} page(s) require retry; open Claims / coverage for details"
            )
            warnings.append(self._page_errors(page_results))
        observables_only = sum(page.state == "observables_only" for page in page_results)
        if observables_only:
            warnings.append(f"{observables_only} page(s): AI unavailable, observables only")
        warning: str | None = "; ".join(warnings) or None
        try:
            self._graph_store.save_graph_snapshot(graph)
        except GraphPersistenceError as error:
            warning = "; ".join((*warnings, str(error)))
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
            f"Graph ready: {len(entities)} entities, {len(claims)} claims, "
            f"{len(claim_links)} comparisons · "
            f"{sum(page.state == 'reused' for page in page_results)} pages reused",
        )
        return GraphAnalysisResult(
            run=run,
            graph=graph,
            evidence_states=tuple(evidence_states),
        )

    @staticmethod
    def _page_errors(pages: list[PageGraphAnalysis]) -> str:
        failed = [page for page in pages if page.error]
        detail = "; ".join(
            f"{page.evidence_id[:8]} p{page.page_number}: {page.error}" for page in failed[:12]
        )
        return detail + (f"; {len(failed) - 12} more page errors" if len(failed) > 12 else "")

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
