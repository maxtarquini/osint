"""Graph actions and selection presentation for the investigation workspace."""

from __future__ import annotations

import logging
from dataclasses import replace

from textual import work
from textual.containers import VerticalScroll
from textual.widgets import Button, Input, Static

from raven.exceptions import GraphAnalysisError, InvestigationError
from raven.models import (
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisResult,
    GraphEntity,
    GraphJobStatus,
    GraphRelationship,
    GraphRunStatus,
    InvestigationGraph,
)
from raven.models.graph import EvidenceSpan
from raven.tui.widgets import GraphCanvas
from raven.tui.widgets.claim_details import ClaimDetails
from raven.tui.widgets.graph_activity import GraphBuildActivity

logger = logging.getLogger(__name__)


class WorkspaceGraphActions:
    """Handle graph jobs, selection, and detail rendering outside the screen shell."""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "graph-entity-search":
            return
        selected = self.query_one("#graph-canvas", GraphCanvas).select_matching(event.value)
        if selected is None:
            self.notify(
                f'No graph entity matches "{event.value.strip()}".',
                title="Entity not found",
                severity="warning",
            )

    def on_graph_canvas_view_changed(self, event: GraphCanvas.ViewChanged) -> None:
        self.query_one("#graph-zoom-label", Static).update(event.label)

    def on_graph_canvas_selection_changed(self, event: GraphCanvas.SelectionChanged) -> None:
        selection = event.selection
        if isinstance(selection, GraphEntity):
            self.query_one("#graph-selection-detail", Static).update(self._entity_detail(selection))
        elif isinstance(selection, tuple) and selection:
            self.query_one("#graph-selection-detail", Static).update(
                self._relationship_detail(selection)
            )
        else:
            self.query_one("#graph-selection-detail", Static).update(
                "SELECTED ITEM\nClick a node or edge, or focus the graph and use J/K."
            )
        self.query_one("#graph-details-panel", VerticalScroll).scroll_home(animate=False)

    @work(thread=True, exclusive=True, group="graph-load", exit_on_error=False)
    def _load_latest_graph(self) -> None:
        try:
            graph = self._raven_app.latest_graph(self.investigation.investigation_id)
        except Exception as error:
            logger.warning(
                "Unable to load latest graph. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
        else:
            if graph is not None:
                self.app.call_from_thread(self._show_graph, graph)

    def _open_variants(self):
        from raven.tui.screens.graph_variants import GraphVariantsScreen

        service = self._raven_app.graph_analysis
        if service is None:
            self.notify("Servizio grafo non disponibile", severity="error")
            return
        self.app.push_screen(
            GraphVariantsScreen(
                self.investigation,
                service,
                busy=self._graph_busy,
                model=self._raven_app.settings.with_environment().ai.model,
            ),
            self._variant_selected,
        )

    def _variant_selected(self, result):
        if result is None:
            return
        if result[0] == "generate":
            self._start_graph_analysis(method_id=result[1], variant_name=result[2])
        else:
            self._show_graph(result[1])
            self.notify(
                "Variante attiva selezionata"
                if result[0] == "active"
                else "Variante aperta per consultazione; chat usa quella attiva"
            )

    def _start_graph_analysis(self, *, method_id=None, variant_name="") -> None:
        if self._graph_busy:
            return
        if not self.documents:
            self.notify(
                "Add at least one Evidence document before graph analysis.",
                title="No Evidence",
                severity="warning",
            )
            return
        if method_id is None:
            self._open_variants()
            return
        try:
            job = self._raven_app.enqueue_graph_analysis(
                self.investigation,
                tuple(self.documents),
                EvidencePreparationMode.FULL_TEXT,
                method_id=method_id,
                variant_name=variant_name,
            )
        except (GraphAnalysisError, InvestigationError) as error:
            self._graph_failed(str(error))
        else:
            self._apply_graph_analysis_job(job)

    def _sync_graph_analysis_job(self) -> None:
        if not self.is_mounted:
            return
        job = self._raven_app.graph_analysis_job(self.investigation.investigation_id)
        if job is not None:
            self._apply_graph_analysis_job(job)

    def _apply_graph_analysis_job(self, job: GraphAnalysisJob) -> None:
        if not self.is_mounted:
            return
        active = job.status in {GraphJobStatus.QUEUED, GraphJobStatus.RUNNING}
        self._graph_busy = active
        self.query_one("#analyze-evidence", Button).disabled = active
        cancel = self.query_one("#cancel-graph-analysis", Button)
        cancel.set_class(not active, "hidden")
        panel = self.query_one("#graph-build-panel")
        activity = self.query_one("#graph-build-activity", GraphBuildActivity)
        panel.set_class(not active, "hidden")
        if active:
            activity.start(job.submitted_at)
            stage = {
                GraphRunStatus.QUEUED: "Waiting for the analysis slot",
                GraphRunStatus.EXTRACTING: "Reading pages · extracting entities and claims",
                GraphRunStatus.CONSOLIDATING: "Connecting entities · comparing sources",
            }.get(job.progress.stage, "Preparing the investigation graph")
            self.query_one("#graph-build-stage", Static).update(stage)
            queue_label = "Queued" if job.status is GraphJobStatus.QUEUED else "Running"
            progress = job.progress
            self._set_graph_status(
                f"● {queue_label} · {progress.message} ({progress.completed}/{progress.total})",
                "running",
            )
            return
        activity.stop()
        if self._applied_graph_job_id == job.job_id:
            return
        self._applied_graph_job_id = job.job_id
        if job.status is GraphJobStatus.COMPLETED and job.result is not None:
            self._graph_succeeded(job.result)
        elif job.status is GraphJobStatus.CANCELLED:
            self._graph_cancelled()
        elif job.status is GraphJobStatus.FAILED:
            self._graph_failed(job.error or "Graph analysis failed")

    def _graph_succeeded(self, result: GraphAnalysisResult) -> None:
        if not self.is_mounted:
            return
        self._show_graph(result.graph)
        state = "warning" if result.run.evidence_failed or result.run.last_error else "success"
        label = (
            f"● {result.run.status.value.replace('_', ' ').title()} · "
            f"model: {result.run.model_name}"
        )
        self._finish_graph_operation(label, state)

    def _graph_cancelled(self) -> None:
        if self.is_mounted:
            self._finish_graph_operation("● Analysis cancelled", "cancelled")

    def _graph_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._finish_graph_operation("● Analysis failed", "error")
        status = self.query_one("#graph-analysis-status", Static)
        status.tooltip = detail
        self.notify(detail, title="Graph analysis failed", severity="error")

    def _show_graph(self, graph: InvestigationGraph) -> None:
        if not self.is_mounted:
            return
        self.graph = graph
        displayed = (
            replace(
                graph,
                entities=tuple(e for e in graph.entities if e.semantic_support == "supported"),
            )
            if graph.manifest
            else graph
        )
        self.query_one("#graph-canvas", GraphCanvas).set_graph(displayed)
        self.query_one("#graph-statistics", Static).update(
            self._graph_statistics_label(graph, self.size.width)
        )
        self.query_one("#workspace-graph-metric", Static).update(
            f"GRAPH\n{len(graph.entities)}N · {len(graph.relationships)}E"
        )
        type_counts: dict[str, int] = {}
        for entity in graph.entities:
            type_counts[entity.entity_type] = type_counts.get(entity.entity_type, 0) + 1
        breakdown = "\n".join(
            f"{entity_type.title()}  {count}"
            for entity_type, count in sorted(
                type_counts.items(), key=lambda item: (-item[1], item[0])
            )
        )
        generated_at = graph.generated_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self.query_one("#graph-breakdown", Static).update(
            "Entity types\n" + (breakdown or "No entities") + f"\n\nGenerated\n{generated_at}"
        )
        self.query_one("#chat-context-summary", Static).update(self._chat_context_label())

    @staticmethod
    def _graph_statistics_label(graph: InvestigationGraph, width: int) -> str:
        counts = f"{len(graph.entities)} entities · {len(graph.relationships)} relationships"
        return counts if width < 100 else counts + f" · run {graph.run_id[:8]}"

    def _entity_detail(self, entity: GraphEntity) -> str:
        classification = entity.entity_type
        if entity.subtype:
            classification += " / " + entity.subtype
        aliases = ", ".join(entity.aliases[:4]) or "—"
        identifiers = (
            ", ".join(f"{key}: {value}" for key, value in entity.external_identifiers[:4]) or "—"
        )
        rationale = entity.rationale.strip() or "No rationale supplied"
        return (
            "SELECTED ENTITY\n"
            + entity.canonical_name
            + "\n\nTYPE\n"
            + classification
            + "\n\nSTATUS / CONFIDENCE\n"
            + f"{entity.status.value.upper()} · {entity.confidence:.0%}"
            + "\n\nALIASES\n"
            + aliases
            + "\n\nIDENTIFIERS\n"
            + identifiers
            + "\n\nEVIDENCE\n"
            + f"{len(entity.evidence_ids)} supporting document(s)"
            + "\n\nFONTI / CITAZIONI\n"
            + self._support_detail(entity.support)
            + (
                "\n\nNOTE DI IDENTITÀ\n" + "\n".join(entity.resolution_notes)
                if entity.resolution_notes
                else ""
            )
            + "\n\nRATIONALE\n"
            + rationale
        )

    def _relationship_detail(
        self,
        relationships: tuple[GraphRelationship, ...],
    ) -> str:
        by_id = (
            {entity.entity_id: entity.canonical_name for entity in self.graph.entities}
            if self.graph is not None
            else {}
        )
        first = relationships[0]
        source = by_id.get(first.source_entity_id, first.source_entity_id)
        target = by_id.get(first.target_entity_id, first.target_entity_id)
        types = ", ".join(dict.fromkeys(item.relationship_type for item in relationships))
        evidence_ids = {evidence_id for item in relationships for evidence_id in item.evidence_ids}
        confidence = max(item.confidence for item in relationships)
        rationale = next(
            (item.rationale.strip() for item in relationships if item.rationale.strip()),
            "No rationale supplied",
        )
        support = "\n\n".join(
            (
                f"{item.relationship_type} · {item.status.value.upper()}\n"
                if len(relationships) > 1
                else ""
            )
            + self._support_detail(item.support)
            + (
                "\nNOTE SULLA RELAZIONE\n" + "\n".join(item.resolution_notes)
                if item.resolution_notes
                else ""
            )
            for item in relationships
        )
        return (
            "SELECTED RELATIONSHIP\n"
            + source
            + "\n  → "
            + target
            + "\n\nTYPE\n"
            + types
            + "\n\nSTATUS / CONFIDENCE\n"
            + f"{first.status.value.upper()} · {confidence:.0%}"
            + "\n\nEVIDENCE\n"
            + f"{len(evidence_ids)} supporting document(s)"
            + "\n\nFONTI / CITAZIONI\n"
            + support
            + "\n\nAFFERMAZIONI E CONFRONTI\n"
            + self._relationship_claim_details(relationships)
            + "\n\nRATIONALE\n"
            + rationale
        )

    def _relationship_claim_details(self, relationships: tuple[GraphRelationship, ...]) -> str:
        claim_ids = tuple(
            dict.fromkeys(claim_id for item in relationships for claim_id in item.claim_ids)
        )
        if not claim_ids or self.graph is None:
            return (
                "Nessuna affermazione strutturata collegata; "
                "i grafi precedenti non la registravano."
            )
        details = ClaimDetails(self.graph, tuple(self.documents))
        return "\n\n".join(
            details.claim_text(details.claims[claim_id])
            if claim_id in details.claims
            else f"Affermazione collegata non disponibile: {claim_id}"
            for claim_id in claim_ids
        )

    def _support_detail(self, support: tuple[EvidenceSpan, ...]) -> str:
        if not support:
            return (
                "Nessuna citazione puntuale salvata. I grafi precedenti possono avere solo "
                "riferimenti al documento: rigenera l'analisi per verificare pagine e citazioni."
            )
        documents = {item.document_id: item for item in self.documents}
        excerpts = []
        for span in dict.fromkeys(support):
            document = documents.get(span.evidence_id)
            source = (
                document.original_name
                if document
                else f"Documento non presente nell'indagine · {span.evidence_id}"
            )
            position = (
                f"Pagina {span.page_number}"
                if type(span.page_number) is int and span.page_number > 0
                else "Pagina non disponibile · posizione non verificata"
            )
            if document and document.file_format.upper() != "PDF" and span.page_number == 1:
                position = "Unità di testo 1 · formato senza paginazione stabile"
            verification = (
                "Citazione verificata nel testo originale"
                if span.verified_original
                else "Citazione non verificata nel testo originale"
            )
            excerpts.append(f"{source}\n{position}\n{verification}\n“{span.quote}”")
        return "\n\n".join(excerpts) + (
            "\n\nLa verifica della citazione conferma la presenza nel testo, "
            "non la verità dell'affermazione."
        )

    def _finish_graph_operation(self, label: str, state: str) -> None:
        self._graph_busy = False
        self.query_one("#graph-build-activity", GraphBuildActivity).stop()
        self.query_one("#graph-build-panel").add_class("hidden")
        self.query_one("#analyze-evidence", Button).disabled = False
        self.query_one("#cancel-graph-analysis", Button).add_class("hidden")
        self._set_graph_status(label, state)

    def _set_graph_status(self, label: str, state: str) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#graph-analysis-status", Static)
        status.set_classes(state)
        status.update(label)
        status.tooltip = None
