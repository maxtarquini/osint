"""Application-level commands kept outside the Textual bootstrap."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from raven.config import AiNodeSettings, RavenSettings
from raven.exceptions import (
    ConfigurationError,
    GraphPersistenceError,
    InvestigationChatError,
    InvestigationPersistenceError,
    InvestigationValidationError,
)
from raven.graph import NamedEntityVocabularyCatalog
from raven.models import (
    ChatMessage,
    ChatStreamEvent,
    EvidenceDocument,
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    Investigation,
    InvestigationDomain,
    InvestigationDraft,
    InvestigationGraph,
    RagIndexProgress,
    ServiceStatus,
)
from raven.services import GraphAnalysisService, PageCatalogService
from raven.services.capabilities import CapabilityRegistry
from raven.tui.screens.investigation import InvestigationCreateScreen
from raven.tui.screens.investigation_catalog import InvestigationCatalogScreen
from raven.tui.screens.investigation_workspace import InvestigationWorkspaceScreen


class RavenApplicationActions:
    """Use-case façade consumed by screens while RavenApp remains lifecycle-focused."""

    def save_configuration(self, settings: RavenSettings) -> None:
        """Persist public settings, reload adapters, and return to the home screen."""
        previous_root = self._knowledge_bases.root if self._knowledge_bases is not None else None
        previous_dictionary_root = self.settings.with_environment().dictionaries.path
        try:
            if self._knowledge_bases is not None:
                self._knowledge_bases.configure_root(settings.with_environment().storage.path)
            if isinstance(self.graph_analysis, GraphAnalysisService):
                self.graph_analysis.configure_dictionary_root(
                    settings.with_environment().dictionaries.path
                )
            if isinstance(self.page_catalog, PageCatalogService):
                self.page_catalog.dictionary_root = settings.with_environment().dictionaries.path
            self.configuration_store.save(settings)
        except (ConfigurationError, InvestigationPersistenceError) as error:
            if self._knowledge_bases is not None and previous_root is not None:
                self._knowledge_bases.configure_root(previous_root)
            if isinstance(self.graph_analysis, GraphAnalysisService):
                self.graph_analysis.configure_dictionary_root(previous_dictionary_root)
            if isinstance(self.page_catalog, PageCatalogService):
                self.page_catalog.dictionary_root = previous_dictionary_root
            if isinstance(error, ConfigurationError):
                raise
            raise ConfigurationError(str(error)) from error
        self.settings = settings
        self.capabilities = CapabilityRegistry(
            settings.with_environment().skills.path,
            getattr(self.infrastructure, "ai_node", None),
            profile_settings=settings.with_environment().ai,
        )
        self.infrastructure.configure(settings)
        self.navigate("home")
        message = "Application configuration saved."
        if settings.neo4j.password:
            message += " Neo4j password stored in the system credential vault."
        self.notify(message, title="Configuration")
        self.refresh_infrastructure()

    def test_ai_node(self, settings: AiNodeSettings) -> ServiceStatus:
        """Delegate a draft AI-node probe to the infrastructure boundary."""
        return self.infrastructure.test_ai_node(settings)

    def create_investigation(
        self,
        draft: InvestigationDraft,
    ) -> Investigation:
        """Create an investigation through the injected use-case service."""
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        available_domains = {domain.code for domain in self.analysis_domains()}
        if draft.analysis_domain not in available_domains:
            raise InvestigationValidationError(
                f"Analysis domain is not available: {draft.analysis_domain}"
            )
        return self.investigations.create(draft)

    def update_investigation(
        self,
        current: Investigation,
        draft: InvestigationDraft,
    ) -> Investigation:
        """Persist mutable case configuration and invalidate derived profile artifacts."""
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        available_domains = {domain.code for domain in self.analysis_domains()}
        if draft.analysis_domain not in available_domains:
            raise InvestigationValidationError(
                f"Analysis domain is not available: {draft.analysis_domain}"
            )
        profile_changed = (
            current.analysis_language != draft.analysis_language
            or current.analysis_domain != draft.analysis_domain
        )
        updated = self.investigations.update(current, draft)
        if profile_changed:
            if self.graph_jobs is not None:
                self.graph_jobs.cancel(current.investigation_id)
            if self.investigation_chat is not None:
                self.investigation_chat.remove_investigation(current.investigation_id)
            if self.graph_analysis is not None:
                self.graph_analysis.invalidate(current.investigation_id)
        return updated

    def delete_investigation(self, investigation: Investigation) -> None:
        """Delete every case-owned artifact using an idempotent retry-safe order."""
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        investigation_id = investigation.investigation_id
        if self.graph_jobs is not None:
            self.graph_jobs.remove(investigation_id)
        if self.investigation_chat is not None:
            try:
                self.investigation_chat.remove_investigation(investigation_id)
            except InvestigationChatError as error:
                raise InvestigationPersistenceError(
                    "RAG cleanup failed; the investigation was not deleted"
                ) from error
        if self.graph_analysis is not None:
            try:
                self.graph_analysis.remove_investigation(investigation_id)
            except GraphPersistenceError as error:
                raise InvestigationPersistenceError(
                    "Neo4j graph cleanup failed; the investigation was not deleted"
                ) from error
        self.investigations.delete(investigation)

    def analysis_domains(self) -> tuple[InvestigationDomain, ...]:
        """Return selectable domains from the currently configured dictionary folder."""
        catalog = NamedEntityVocabularyCatalog(self.settings.with_environment().dictionaries.path)
        return tuple(
            InvestigationDomain(item.code, item.name, item.description)
            for item in catalog.list_domains()
        )

    def add_evidence(
        self,
        investigation_id: str,
        source: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> EvidenceDocument:
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        return self.investigations.add_evidence(investigation_id, source, cancelled)

    def evidence_directory(self, investigation_id: str) -> Path:
        """Return the configured local directory for one investigation's Evidence."""
        if self._knowledge_bases is not None:
            return self._knowledge_bases.investigation_directory(investigation_id)
        return self.settings.with_environment().storage.path / investigation_id

    def delete_evidence(self, document: EvidenceDocument) -> None:
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        self.investigations.delete_evidence(document)
        if self.investigation_chat is not None:
            self.investigation_chat.remove_document(document)

    def list_investigations(self) -> tuple[Investigation, ...]:
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        return self.investigations.list_investigations()

    def open_investigation(self, investigation: Investigation) -> None:
        """Replace the catalog with the selected investigation workspace."""
        self.switch_screen(InvestigationWorkspaceScreen(investigation))

    def edit_investigation(self, investigation: Investigation) -> None:
        """Open the case form prefilled with the persisted investigation profile."""
        self.push_screen(
            InvestigationCreateScreen(
                self.analysis_domains(),
                investigation=investigation,
            )
        )

    def latest_graph(self, investigation_id: str) -> InvestigationGraph | None:
        if self.graph_analysis is None:
            return None
        return self.graph_analysis.latest(investigation_id)

    def evidence_index_states(self, investigation, documents):
        if self.investigation_chat is None:
            raise InvestigationPersistenceError("Investigation chat is not available")
        return self.investigation_chat.index_states(investigation, documents)

    def index_investigation_knowledge_base(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[RagIndexProgress], None] | None = None,
    ) -> int:
        if self.investigation_chat is None:
            raise InvestigationPersistenceError("Investigation chat is not available")
        return self.investigation_chat.index_knowledge_base(
            investigation, documents, cancelled, progress
        )

    def reindex_evidence_document(self, investigation, document, cancelled=None, progress=None):
        if self.investigation_chat is None:
            raise InvestigationPersistenceError("Investigation chat is not available")
        return self.investigation_chat.reindex_document(
            investigation, document, cancelled, progress
        )

    def load_evidence_catalog(self, investigation, document, *, with_pages: bool = True):
        if document.investigation_id != investigation.investigation_id:
            raise InvestigationValidationError("Evidence does not belong to this investigation")
        if self.page_catalog is not None:
            return self.page_catalog.load(investigation, document, with_pages=with_pages)
        repository = getattr(self.infrastructure, "mongo_repository", None)
        if repository is None:
            raise InvestigationPersistenceError("Catalog storage is not available")
        return repository.load_catalog(
            investigation.investigation_id,
            document.document_id,
            with_pages=with_pages,
        )

    def catalog_evidence_document(
        self,
        investigation,
        document,
        cancelled=None,
        progress=None,
        *,
        force: bool = False,
    ):
        if self.page_catalog is None:
            raise InvestigationPersistenceError("Page cataloging is not available")
        return self.page_catalog.catalog_document(
            investigation,
            document,
            cancelled,
            progress,
            force=force,
        )

    def stream_investigation_chat(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        graph: InvestigationGraph | None,
        question: str,
        cancelled: Callable[[], bool] | None = None,
        index_progress: Callable[[RagIndexProgress], None] | None = None,
    ) -> Iterator[ChatStreamEvent]:
        if self.investigation_chat is None:
            raise InvestigationPersistenceError("Investigation chat is not available")
        if self.graph_analysis is not None:
            graph = self.graph_analysis.latest(investigation.investigation_id)
        return self.investigation_chat.stream_answer(
            investigation,
            documents,
            graph,
            question,
            cancelled,
            index_progress,
        )

    def load_investigation_chat(self, investigation_id: str) -> tuple[ChatMessage, ...]:
        if self.investigation_chat is None:
            return ()
        return self.investigation_chat.load_history(investigation_id)

    def clear_investigation_chat(self, investigation_id: str) -> None:
        if self.investigation_chat is None:
            raise InvestigationPersistenceError("Investigation chat is not available")
        self.investigation_chat.clear_history(investigation_id)

    def export_investigation_chat_response(
        self,
        investigation: Investigation,
        response: str,
        sources: tuple[str, ...],
        destination: Path,
    ) -> Path:
        """Create an analyst-requested Markdown export through the filesystem boundary."""
        return self.chat_exports.save(investigation, response, sources, destination)

    def suggested_chat_export_filename(self, investigation: Investigation) -> str:
        """Return a filesystem-safe default name for the latest response."""
        return self.chat_exports.suggested_filename(investigation)

    def analyze_graph(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[GraphAnalysisProgress], None] | None = None,
    ) -> GraphAnalysisResult:
        if self.graph_analysis is None:
            raise InvestigationPersistenceError("Graph analysis is not available")
        return self.graph_analysis.analyze(
            investigation,
            documents,
            preparation_mode,
            cancelled,
            progress,
        )

    def enqueue_graph_analysis(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
        *,
        method_id: str = "document_claims",
        variant_name: str = "",
    ) -> GraphAnalysisJob:
        """Queue graph work independently from the currently mounted screen."""
        if self.graph_jobs is None:
            raise InvestigationPersistenceError("Graph analysis is not available")
        return self.graph_jobs.enqueue(
            investigation,
            documents,
            preparation_mode,
            method_id=method_id,
            variant_name=variant_name,
        )

    def graph_analysis_job(self, investigation_id: str) -> GraphAnalysisJob | None:
        """Return the latest queue snapshot for one investigation."""
        if self.graph_jobs is None:
            return None
        return self.graph_jobs.snapshot(investigation_id)

    def cancel_graph_analysis(self, investigation_id: str) -> GraphAnalysisJob | None:
        """Cancel queued work or request cancellation of a running graph job."""
        if self.graph_jobs is None:
            return None
        return self.graph_jobs.cancel(investigation_id)

    def investigation_created(self, investigation: Investigation) -> None:
        """Open the workspace immediately after investigation creation."""
        self.switch_screen(InvestigationWorkspaceScreen(investigation))
        self.notify(
            f"{investigation.name} created. The investigation workspace is now open.",
            title="Investigation created",
        )

    def investigation_updated(self, investigation: Investigation) -> None:
        """Return from the edit form to a workspace using the new persisted profile."""
        self.switch_screen(InvestigationWorkspaceScreen(investigation))
        self.notify(
            f"{investigation.name} configuration saved.",
            title="Investigation updated",
        )

    def investigation_deleted(self, investigation: Investigation) -> None:
        """Return to the catalog after confirmed case deletion."""
        self.switch_screen(InvestigationCatalogScreen())
        self.notify(
            f"{investigation.name}, its Evidence, RAG vectors, graph, chat and cache were deleted.",
            title="Investigation deleted",
        )
