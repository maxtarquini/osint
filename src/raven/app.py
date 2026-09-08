"""Application bootstrap and infrastructure lifecycle for the Raven TUI."""

from __future__ import annotations

import logging
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
    InvestigationPersistenceError,
    InvestigationValidationError,
)
from raven.graph import NamedEntityVocabularyCatalog
from raven.models import (
    AnalysisLanguage,
    BackgroundJob,
    ChatMessage,
    ChatStreamEvent,
    EvidenceDocument,
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphItemStatus,
    Investigation,
    InvestigationDomain,
    InvestigationDraft,
    InvestigationGraph,
    JobKind,
    JobStatus,
    RagIndexProgress,
    ServiceName,
    ServiceStatus,
)
from raven.repositories import KnowledgeBaseStore
from raven.services import (
    ChatExportService,
    GraphAnalysisQueue,
    GraphAnalysisService,
    GraphExportService,
    InfrastructureService,
    InvestigationChatService,
    InvestigationService,
    OcrService,
    RagIndexQueue,
)
from raven.services.case_actions import CaseActions
from raven.services.operations import InvestigationOperations
from raven.services.page_catalog import PageCatalogService, catalog_source_units
from raven.tui.design import raven_theme
from raven.tui.events import BackgroundJobsChanged
from raven.tui.screens.configuration import ConfigurationScreen
from raven.tui.screens.evidence_inspector import EvidenceInspectorScreen
from raven.tui.screens.home import HomeScreen
from raven.tui.screens.investigation import InvestigationCreateScreen
from raven.tui.screens.investigation_catalog import InvestigationCatalogScreen
from raven.tui.screens.investigation_workspace import InvestigationWorkspaceScreen
from raven.tui.screens.jobs import JobsScreen
from raven.tui.widgets import ServiceStatusIndicator, TopNavigation

logger = logging.getLogger(__name__)


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
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "tui/raven.tcss"

    def __init__(
        self,
        *,
        configuration_store: ConfigurationStore | None = None,
        infrastructure: InfrastructureLifecycle | None = None,
        investigations: InvestigationLifecycle | None = None,
        graph_analysis: GraphAnalysisLifecycle | None = None,
        investigation_chat: InvestigationChatLifecycle | None = None,
        page_catalog: PageCatalogService | None = None,
        auto_connect: bool = True,
    ) -> None:
        super().__init__()
        self.configuration_store = configuration_store or ConfigurationStore()
        self.chat_exports = ChatExportService()
        self.graph_exports = GraphExportService()
        self.ocr = OcrService()
        self.settings = self.configuration_store.load()
        self.apply_design()
        self.infrastructure = infrastructure or InfrastructureService(self.settings)
        self.operations = InvestigationOperations()
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
            self.page_catalog = page_catalog or PageCatalogService(
                self.infrastructure.mongo_repository,
                knowledge_bases,
                self.infrastructure.ai_node,
                self.settings.with_environment().dictionaries.path,
                self.operations,
                settings_provider=lambda: self.settings.with_environment().ai,
            )
            if self.graph_analysis is None:
                self.graph_analysis = GraphAnalysisService(
                    self.infrastructure.mongo_repository,
                    self.infrastructure.neo4j_repository,
                    self.infrastructure.ai_node,
                    knowledge_bases,
                    self.settings.with_environment().dictionaries.path,
                    operations=self.operations,
                )
            if self.investigation_chat is None:
                self.investigation_chat = InvestigationChatService(
                    self.infrastructure.mongo_repository,
                    self.infrastructure.qdrant_repository,
                    self.infrastructure.ai_node,
                    knowledge_bases,
                    operations=self.operations,
                    catalog=self.page_catalog,
                )
        else:
            self.investigations = None
        job_recorder = (
            self.infrastructure.mongo_repository
            if investigations is None and isinstance(self.infrastructure, InfrastructureService)
            else None
        )
        self.graph_jobs = (
            GraphAnalysisQueue(self.graph_analysis, job_recorder, self._jobs_changed)
            if self.graph_analysis is not None
            else None
        )
        self.rag_jobs = (
            RagIndexQueue(self.investigation_chat, job_recorder, self._jobs_changed)
            if self.investigation_chat is not None
            else None
        )
        self.catalog_jobs = (
            RagIndexQueue(self.page_catalog, job_recorder, self._jobs_changed, kind=JobKind.CATALOG)
            if self.page_catalog is not None
            else None
        )
        self.case_actions = CaseActions(
            self.investigations,
            self.graph_analysis,
            self.investigation_chat,
            self.graph_jobs,
            self.rag_jobs,
            self.operations,
            catalog_jobs=self.catalog_jobs,
            catalog=self.page_catalog,
        )
        self.auto_connect = auto_connect
        self.service_statuses = {
            service: ServiceStatus.checking(service) for service in ServiceName
        }
        self._status_generation = 0

    def apply_design(self) -> None:
        theme = raven_theme()
        self.register_theme(theme)
        self.theme = theme.name
        for name in tuple(self.available_themes):
            if name != theme.name:
                self.unregister_theme(name)

    def search_themes(self) -> None:
        """Raven uses fixed semantic colors across every screen."""

    def action_toggle_dark(self) -> None:
        """Keep the fixed Raven appearance when legacy framework actions are invoked."""

    def on_mount(self) -> None:
        """Open the home screen once the terminal is ready."""
        self.push_screen(HomeScreen())

    def on_unmount(self) -> None:
        if self.graph_jobs is not None:
            self.graph_jobs.close()
        if self.rag_jobs is not None:
            self.rag_jobs.close()
        if self.catalog_jobs is not None:
            self.catalog_jobs.close()
        self.infrastructure.close()

    def action_navigate(self, target: str) -> None:
        self.navigate(target)

    def navigate(self, target: str) -> None:
        """Resolve top-menu targets without coupling widgets to screen lifecycle."""
        if target == "home":
            while len(self.screen_stack) > 1 and not isinstance(self.screen, HomeScreen):
                self.pop_screen()
            if not isinstance(self.screen, HomeScreen):
                self.push_screen(HomeScreen())
            return
        if target == "configuration":
            if not isinstance(self.screen, ConfigurationScreen):
                self.push_screen(ConfigurationScreen(self.settings))
            return
        if target == "jobs":
            if not isinstance(self.screen, JobsScreen):
                self.push_screen(JobsScreen())
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

    def _jobs_changed(self, investigation_id: str) -> None:
        self.post_message(BackgroundJobsChanged(investigation_id))

    def on_background_jobs_changed(self, event: BackgroundJobsChanged) -> None:
        for screen in self.screen_stack:
            if isinstance(screen, InvestigationWorkspaceScreen) and screen.is_mounted:
                if screen.investigation.investigation_id == event.investigation_id:
                    screen.refresh_job_state()
                    screen.refresh_catalogs()
            elif isinstance(screen, EvidenceInspectorScreen) and screen.is_mounted:
                if screen.document.investigation_id == event.investigation_id:
                    screen.refresh_catalog()
            elif isinstance(screen, JobsScreen) and screen.is_mounted:
                screen.action_refresh_jobs()

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
        if status.service in {ServiceName.MONGODB, ServiceName.NEO4J} and all(
            self.service_statuses[service].state.value == "connected"
            for service in (ServiceName.MONGODB, ServiceName.NEO4J)
        ):
            self._reconcile_graphs()

    @work(thread=True, exclusive=True, group="graph-reconciliation", exit_on_error=False)
    def _reconcile_graphs(self) -> None:
        if not isinstance(self.graph_analysis, GraphAnalysisService):
            return
        try:
            self.graph_analysis.reconcile_projections()
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Graph reconciliation deferred. error_type=%s", type(error).__name__
            )
            self.call_from_thread(
                self.notify,
                "Graph synchronization pending; refresh services to retry.",
                severity="warning",
            )

    def apply_cached_statuses(self, root: DOMNode) -> None:
        for indicator in root.query(ServiceStatusIndicator):
            indicator.set_status(self.service_statuses[indicator.service])

    def save_configuration(self, settings: RavenSettings) -> None:
        """Persist public settings, reload adapters, and return to the home screen."""
        self.persist_configuration(settings)
        self.configuration_saved(settings)

    def persist_configuration(self, settings: RavenSettings) -> None:
        """Perform disk, credential-vault and metadata I/O from a worker."""
        previous_root = self._knowledge_bases.root if self._knowledge_bases is not None else None
        previous_dictionary_root = self.settings.with_environment().dictionaries.path
        try:
            if self._knowledge_bases is not None:
                new_root = settings.with_environment().storage.path
                if previous_root != new_root and isinstance(
                    self.infrastructure, InfrastructureService
                ):
                    self.infrastructure.mongo_repository.anchor_evidence_root(str(previous_root))
                self._knowledge_bases.configure_root(new_root)
            if isinstance(self.graph_analysis, GraphAnalysisService):
                self.graph_analysis.configure_dictionary_root(
                    settings.with_environment().dictionaries.path
                )
            if self.page_catalog is not None:
                NamedEntityVocabularyCatalog(settings.with_environment().dictionaries.path)
            self.configuration_store.save(settings)
        except (ConfigurationError, InvestigationPersistenceError) as error:
            if self._knowledge_bases is not None and previous_root is not None:
                self._knowledge_bases.configure_root(previous_root)
            if isinstance(self.graph_analysis, GraphAnalysisService):
                self.graph_analysis.configure_dictionary_root(previous_dictionary_root)
            if isinstance(error, ConfigurationError):
                raise
            raise ConfigurationError(str(error)) from error

    def configuration_saved(self, settings: RavenSettings) -> None:
        """Apply a persisted configuration on the UI thread."""
        self.settings = settings
        if self.page_catalog is not None:
            self.page_catalog.dictionary_root = settings.with_environment().dictionaries.path
        self.apply_design()
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
        return self.case_actions.update(current, draft)

    def delete_investigation(self, investigation: Investigation) -> None:
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        self.case_actions.delete(investigation)

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
        document = self.case_actions.add_evidence(investigation_id, source, cancelled)
        if self.catalog_jobs is not None:
            try:
                investigation = next(
                    item
                    for item in self.list_investigations()
                    if item.investigation_id == investigation_id
                )
                documents = tuple(
                    item
                    for item in investigation.evidence_documents
                    if item.document_id != document.document_id
                ) + (document,)
                self.catalog_jobs.enqueue(investigation, documents)
                if (
                    self.rag_jobs is not None
                    and self.settings.with_environment().ai.embedding_model
                ):
                    self.rag_jobs.enqueue(investigation, documents)
            except Exception as error:
                logger.warning(
                    "Automatic catalog queue unavailable. error_type=%s", type(error).__name__
                )
        return document

    def enqueue_page_catalog(self, investigation, documents):
        if self.catalog_jobs is None:
            raise InvestigationPersistenceError("Page cataloging is unavailable")
        return self.catalog_jobs.enqueue(investigation, documents)

    def load_document_catalog(self, investigation, document, *, with_pages=True):
        if self.page_catalog is None:
            return None
        return self.page_catalog.load(investigation, document, with_pages=with_pages)

    def evidence_directory(self, investigation_id: str) -> Path:
        """Return the configured local directory for one investigation's Evidence."""
        if self._knowledge_bases is not None:
            return self._knowledge_bases.investigation_directory(investigation_id)
        return self.settings.with_environment().storage.path / investigation_id

    def evidence_text_preview(self, document: EvidenceDocument, limit: int = 40_000) -> str:
        """Return a bounded extracted-text preview through the storage boundary."""
        if self._knowledge_bases is None:
            return "Extracted-text preview is unavailable for this application adapter."
        text = self._knowledge_bases.extract_text(document)
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n\n[… preview truncated by Raven …]"

    def evidence_page_previews(self, document: EvidenceDocument) -> tuple[str, ...]:
        """Return page-addressable text used by the document Inspector and citations."""
        if self._knowledge_bases is None:
            return ("Extracted-text preview is unavailable for this application adapter.",)
        return catalog_source_units(document, self._knowledge_bases.extract_pages(document))

    def ocr_evidence_pages(
        self, document: EvidenceDocument, language: AnalysisLanguage
    ) -> tuple[str, ...]:
        if self._knowledge_bases is None:
            raise InvestigationPersistenceError("Local Evidence storage is unavailable")
        ocr_language = {
            AnalysisLanguage.ITALIAN: "ita",
            AnalysisLanguage.FRENCH: "fra",
            AnalysisLanguage.GERMAN: "deu",
            AnalysisLanguage.SPANISH: "spa",
            AnalysisLanguage.ARABIC: "ara",
        }.get(language, "eng")
        with self.operations.operation(document.investigation_id) as stopped:
            if stopped():
                raise InvestigationPersistenceError("The case changed; reopen the document")
            return self.ocr.extract_pdf(
                self._knowledge_bases.document_path(document),
                self._knowledge_bases.ocr_cache_path(document),
                ocr_language,
            )

    def delete_evidence(self, document: EvidenceDocument) -> None:
        if self.investigations is None:
            raise InvestigationPersistenceError("Investigation storage is not available")
        self.case_actions.delete_evidence(document)

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

    def review_graph_item(
        self,
        graph: InvestigationGraph,
        item_id: str,
        status: GraphItemStatus,
    ) -> InvestigationGraph:
        if self.graph_analysis is None or not hasattr(self.graph_analysis, "review_item"):
            raise InvestigationPersistenceError("Graph review is not available")
        return self.graph_analysis.review_item(graph, item_id, status)  # type: ignore[attr-defined]

    def graph_run_history(self, investigation_id: str) -> tuple[GraphAnalysisRun, ...]:
        if self.graph_analysis is None or not hasattr(self.graph_analysis, "runs"):
            return ()
        return self.graph_analysis.runs(investigation_id)  # type: ignore[attr-defined,no-any-return]

    def graph_run_snapshot(self, investigation_id: str, run_id: str) -> InvestigationGraph | None:
        if self.graph_analysis is None or not hasattr(self.graph_analysis, "snapshot"):
            return None
        return self.graph_analysis.snapshot(investigation_id, run_id)  # type: ignore[attr-defined,no-any-return]

    def export_graph(
        self, investigation: Investigation, graph: InvestigationGraph
    ) -> tuple[Path, ...]:
        directory = self.evidence_directory(investigation.investigation_id) / "exports"
        return self.graph_exports.export_all(investigation, graph, directory)

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

    def enqueue_rag_index(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
    ) -> BackgroundJob:
        if self.rag_jobs is None:
            raise InvestigationPersistenceError("Investigation RAG is not available")
        return self.rag_jobs.enqueue(investigation, documents)

    def rag_index_job(self, investigation_id: str) -> BackgroundJob | None:
        return self.rag_jobs.snapshot(investigation_id) if self.rag_jobs else None

    def rag_index_progress(self, investigation_id: str) -> RagIndexProgress | None:
        return self.rag_jobs.latest_progress(investigation_id) if self.rag_jobs else None

    def cancel_rag_index(self, investigation_id: str) -> BackgroundJob | None:
        return self.rag_jobs.cancel(investigation_id) if self.rag_jobs else None

    def list_background_jobs(self) -> tuple[BackgroundJob, ...]:
        """Merge persisted history with the freshest process-owned snapshots."""
        persisted: tuple[BackgroundJob, ...] = ()
        if isinstance(self.infrastructure, InfrastructureService):
            try:
                persisted = self.infrastructure.mongo_repository.list_background_jobs()
            except InvestigationPersistenceError:
                persisted = ()
        live: list[BackgroundJob] = list(self.rag_jobs.snapshots() if self.rag_jobs else ())
        if self.catalog_jobs:
            live.extend(self.catalog_jobs.snapshots())
        if self.graph_jobs:
            for snapshot in self.graph_jobs.snapshots():
                status = JobStatus(snapshot.status.value)
                live.append(
                    BackgroundJob(
                        snapshot.job_id,
                        snapshot.investigation_id,
                        JobKind.GRAPH,
                        status,
                        snapshot.progress.stage.value,
                        snapshot.progress.completed,
                        snapshot.progress.total,
                        snapshot.progress.message,
                        snapshot.submitted_at,
                        snapshot.updated_at,
                        snapshot.error,
                        self.graph_jobs.investigation_name(snapshot.investigation_id),
                    )
                )
        merged = {job.job_id: job for job in persisted}
        merged.update({job.job_id: job for job in live})
        return tuple(sorted(merged.values(), key=lambda item: item.updated_at, reverse=True))

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
    ) -> GraphAnalysisJob:
        """Queue graph work independently from the currently mounted screen."""
        if self.graph_jobs is None:
            raise InvestigationPersistenceError("Graph analysis is not available")
        return self.graph_jobs.enqueue(investigation, documents, preparation_mode)

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
