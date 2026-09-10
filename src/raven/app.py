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
from raven.models import (
    ChatMessage,
    ChatStreamEvent,
    EvidenceDocument,
    EvidencePreparationMode,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    Investigation,
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
    PageCatalogService,
)
from raven.services.capabilities import CapabilityRegistry
from raven.tui.actions.application import RavenApplicationActions
from raven.tui.screens.capabilities import CapabilitiesScreen
from raven.tui.screens.configuration import ConfigurationScreen
from raven.tui.screens.help import ContextHelpScreen
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


class PageCatalogLifecycle(Protocol):
    def load(self, investigation, document, *, with_pages: bool = True): ...

    def catalog_document(
        self,
        investigation,
        document,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[RagIndexProgress], None] | None = None,
        *,
        force: bool = False,
    ): ...


class RavenApp(RavenApplicationActions, App[None]):
    """Keyboard-first shell for Raven's OSINT graph workflows."""

    TITLE = "Raven"
    SUB_TITLE = "OSINT Graph Intelligence"
    CSS_PATH = [
        "tui/styles/tokens.tcss",
        "tui/styles/foundation.tcss",
        "tui/styles/forms.tcss",
        "tui/styles/workspace.tcss",
        "tui/styles/pickers.tcss",
        "tui/styles/catalogs.tcss",
        "tui/styles/graph_chat.tcss",
        "tui/styles/extensions.tcss",
        "tui/styles/refactor.tcss",
    ]

    def __init__(
        self,
        *,
        configuration_store: ConfigurationStore | None = None,
        infrastructure: InfrastructureLifecycle | None = None,
        investigations: InvestigationLifecycle | None = None,
        graph_analysis: GraphAnalysisLifecycle | None = None,
        investigation_chat: InvestigationChatLifecycle | None = None,
        page_catalog: PageCatalogLifecycle | None = None,
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
        self.page_catalog = page_catalog
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
            if self.page_catalog is None:
                self.page_catalog = PageCatalogService(
                    self.infrastructure.mongo_repository,
                    knowledge_bases,
                    self.infrastructure.ai_node,
                    self.settings.with_environment().dictionaries.path,
                    settings_provider=lambda: self.settings.with_environment().ai,
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

    def action_context_help(self) -> None:
        """Open help generated from the active screen's keyboard contract."""
        screen = self.screen
        name = screen.__class__.__name__.removesuffix("Screen")
        bindings = tuple(
            binding for binding in getattr(screen, "BINDINGS", ()) if hasattr(binding, "key")
        )
        self.push_screen(ContextHelpScreen(name, bindings))

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


def main() -> None:
    """Launch the interactive terminal application."""
    configure_logging()
    RavenApp().run()
