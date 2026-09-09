"""Application bootstrap and infrastructure lifecycle for the Raven TUI."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

from textual import work
from textual.app import App
from textual.dom import DOMNode

from raven.config import AiNodeSettings, ConfigurationStore, RavenSettings
from raven.config.logging import configure_logging
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
    ServiceName,
    ServiceStatus,
)
from raven.repositories import KnowledgeBaseStore
from raven.services import (
    ChatExportService,
    GraphAnalysisQueue,
    GraphAnalysisService,
    InfrastructureService,
    InvestigationChatService,
    InvestigationService,
)
from raven.services.capabilities import CapabilityRegistry
from raven.tui.screens.capabilities import CapabilitiesScreen
from raven.tui.screens.configuration import ConfigurationScreen
from raven.tui.screens.home import HomeScreen
from raven.tui.screens.investigation import InvestigationCreateScreen
from raven.tui.screens.investigation_catalog import InvestigationCatalogScreen
from raven.tui.screens.investigation_workspace import InvestigationWorkspaceScreen
from raven.tui.widgets import ServiceStatusIndicator, TopNavigation


class InfrastructureLifecycle(Protocol):
    """Small seam used by the app and deterministic TUI tests."""

    def configure(self, settings: RavenSettings) -> None: ...

    def initialize(self, service: ServiceName) -> ServiceStatus: ...

    def test_ai_node(self, settings: AiNodeSettings) -> ServiceStatus: ...

    def close(self) -> None: ...


class InvestigationLifecycle(Protocol):
    """Use-case seam for deterministic investigation-screen tests."""

    def create(
        self,
        draft: InvestigationDraft,
    ) -> Investigation: ...

    def update(
        self,
        current: Investigation,
        draft: InvestigationDraft,
    ) -> Investigation: ...

    def delete(self, investigation: Investigation) -> None: ...

    def add_evidence(
        self,
        investigation_id: str,
        source: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> EvidenceDocument: ...

    def delete_evidence(self, document: EvidenceDocument) -> None: ...

    def list_investigations(self) -> tuple[Investigation, ...]: ...


class GraphAnalysisLifecycle(Protocol):
    def latest(self, investigation_id: str) -> InvestigationGraph | None: ...

    def invalidate(self, investigation_id: str) -> None: ...

    def remove_investigation(self, investigation_id: str) -> None: ...

    def analyze(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[GraphAnalysisProgress], None] | None = None,
    ) -> GraphAnalysisResult: ...


class InvestigationChatLifecycle(Protocol):
    def index_knowledge_base(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[RagIndexProgress], None] | None = None,
    ) -> int: ...

    def reindex_document(
        self,
        investigation: Investigation,
        document: EvidenceDocument,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[RagIndexProgress], None] | None = None,
    ) -> int: ...

    def stream_answer(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        graph: InvestigationGraph | None,
        question: str,
        cancelled: Callable[[], bool] | None = None,
        index_progress: Callable[[RagIndexProgress], None] | None = None,
    ) -> Iterator[ChatStreamEvent]: ...

    def load_history(self, investigation_id: str) -> tuple[ChatMessage, ...]: ...

    def clear_history(self, investigation_id: str) -> None: ...

    def remove_document(self, document: EvidenceDocument) -> None: ...

    def remove_investigation(self, investigation_id: str) -> None: ...


class RavenApp(App[None]):
    """Keyboard-first shell for Raven's OSINT graph workflows."""

    TITLE = "Raven"
    SUB_TITLE = "OSINT Graph Intelligence"
    CSS_PATH = "tui/raven.tcss"

    def __init__(
        self,
        *,
        configuration_store: ConfigurationStore | None = None,
        infrastructure: InfrastructureLifecycle | None = None,
        investigations: InvestigationLifecycle | None = None,
        graph_analysis: GraphAnalysisLifecycle | None = None,
        investigation_chat: InvestigationChatLifecycle | None = None,
        auto_connect: bool = True,
    ) -> None:
        super().__init__()
        self.configuration_store = configuration_store or ConfigurationStore()
        self.chat_exports = ChatExportService()
        self.settings = self.configuration_store.load()
        self.infrastructure = infrastructure or InfrastructureService(self.settings)
        self.capabilities = CapabilityRegistry(
            self.settings.with_environment().skills.path,
            getattr(self.infrastructure, "ai_node", None),
            profile_settings=self.settings.with_environment().ai,
        )
        self.graph_analysis = graph_analysis
        self.investigation_chat = investigation_chat
        self._knowledge_bases: KnowledgeBaseStore | None = None
        if investigations is not None:
            self.investigations: InvestigationLifecycle | None = investigations
        elif isinstance(self.infrastructure, InfrastructureService):
            evidence_root = self.settings.with_environment().storage.path
            knowledge_bases = KnowledgeBaseStore(evidence_root)
            knowledge_bases.configure_root(evidence_root)
            self._knowledge_bases = knowledge_bases
            self.investigations = InvestigationService(
                self.infrastructure.mongo_repository,
                knowledge_bases,
            )
            if self.graph_analysis is None:
                self.graph_analysis = GraphAnalysisService(
                    self.infrastructure.mongo_repository,
                    self.infrastructure.neo4j_repository,
                    self.infrastructure.ai_node,
                    knowledge_bases,
                    self.settings.with_environment().dictionaries.path,
                )
            if self.investigation_chat is None:
                self.investigation_chat = InvestigationChatService(
                    self.infrastructure.mongo_repository,
                    self.infrastructure.qdrant_repository,
                    self.infrastructure.ai_node,
                    knowledge_bases,
                    self.infrastructure.neo4j_repository,
                )
        else:
            self.investigations = None
        self.graph_jobs = (
            GraphAnalysisQueue(self.graph_analysis) if self.graph_analysis is not None else None
        )
        self.auto_connect = auto_connect
        self.service_statuses = {
            service: ServiceStatus.checking(service) for service in ServiceName
        }
        self._status_generation = 0

    def on_mount(self) -> None:
        """Open the home screen once the terminal is ready."""
        self.push_screen(HomeScreen())

    def on_unmount(self) -> None:
        if self.graph_jobs is not None:
            self.graph_jobs.close()
        self.infrastructure.close()

    def action_navigate(self, target: str) -> None:
        self.navigate(target)

    def navigate(self, target: str) -> None:
        """Resolve top-menu targets without coupling widgets to screen lifecycle."""
        if target == "home":
            if isinstance(
                self.screen,
                (
                    ConfigurationScreen,
                    InvestigationCatalogScreen,
                    InvestigationCreateScreen,
                    InvestigationWorkspaceScreen,
                    CapabilitiesScreen,
                ),
            ):
                while len(self.screen_stack) > 1 and not isinstance(self.screen, HomeScreen):
                    self.pop_screen()
            return
        if target == "capabilities":
            if not isinstance(self.screen, CapabilitiesScreen):
                self.push_screen(CapabilitiesScreen(self.capabilities))
            return
        if target == "configuration":
            if not isinstance(self.screen, ConfigurationScreen):
                self.push_screen(ConfigurationScreen(self.settings))
            return
        if target == "investigations":
            if isinstance(self.screen, (InvestigationCreateScreen, InvestigationWorkspaceScreen)):
                self.switch_screen(InvestigationCatalogScreen())
            elif not isinstance(self.screen, InvestigationCatalogScreen):
                self.push_screen(InvestigationCatalogScreen())
            return
        if target == "new-investigation":
            if isinstance(self.screen, InvestigationCreateScreen):
                return
            create_screen = InvestigationCreateScreen(self.analysis_domains())
            if isinstance(self.screen, InvestigationCatalogScreen):
                self.switch_screen(create_screen)
            else:
                self.push_screen(create_screen)
            return

    def on_top_navigation_navigate(self, event: TopNavigation.Navigate) -> None:
        self.navigate(event.target)

    def action_refresh_infrastructure(self) -> None:
        self.refresh_infrastructure()

    def refresh_infrastructure(self) -> None:
        """Check all services concurrently without blocking Textual's message loop."""
        self._status_generation += 1
        generation = self._status_generation
        for service in ServiceName:
            self._apply_service_status(ServiceStatus.checking(service), generation)
            self._initialize_service(service, generation)

    @work(thread=True, group="infrastructure")
    def _initialize_service(self, service: ServiceName, generation: int) -> None:
        status = self.infrastructure.initialize(service)
        self.call_from_thread(self._apply_service_status, status, generation)

    def _apply_service_status(self, status: ServiceStatus, generation: int) -> None:
        if generation != self._status_generation:
            return
        self.service_statuses[status.service] = status
        for screen in self.screen_stack:
            self.apply_cached_statuses(screen)

    def apply_cached_statuses(self, root: DOMNode) -> None:
        for indicator in root.query(ServiceStatusIndicator):
            indicator.set_status(self.service_statuses[indicator.service])

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
            self.configuration_store.save(settings)
        except (ConfigurationError, InvestigationPersistenceError) as error:
            if self._knowledge_bases is not None and previous_root is not None:
                self._knowledge_bases.configure_root(previous_root)
            if isinstance(self.graph_analysis, GraphAnalysisService):
                self.graph_analysis.configure_dictionary_root(previous_dictionary_root)
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

    def load_evidence_catalog(self, investigation, document):
        if document.investigation_id != investigation.investigation_id:
            raise InvestigationValidationError("Evidence does not belong to this investigation")
        repository = getattr(self.infrastructure, "mongo_repository", None)
        if repository is None:
            raise InvestigationPersistenceError("Catalog storage is not available")
        return repository.load_catalog(investigation.investigation_id, document.document_id)

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


def main() -> None:
    """Launch the interactive terminal application."""
    configure_logging()
    RavenApp().run()
