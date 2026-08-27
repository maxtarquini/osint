"""Behavior checks for the Raven TUI shell and infrastructure controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from textual.widgets import Select, TabbedContent, TextArea

from raven.app import RavenApp
from raven.config import (
    AI_PROVIDER_DEFAULT_URLS,
    AiNodeSettings,
    AiProvider,
    ConfigurationStore,
    DictionarySettings,
    EvidenceStorageSettings,
    InMemoryCredentialStore,
    Neo4jSettings,
    RavenSettings,
)
from raven.exceptions import InvestigationChatError, InvestigationPersistenceError
from raven.models import (
    AnalysisLanguage,
    ChatEventKind,
    ChatMessage,
    ChatStreamEvent,
    ConnectionState,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisProgress,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphEntity,
    GraphJobStatus,
    GraphRelationship,
    GraphRunStatus,
    Investigation,
    InvestigationDraft,
    InvestigationGraph,
    InvestigationStatus,
    RagIndexProgress,
    ServiceName,
    ServiceStatus,
    TokenUsage,
)
from raven.tui.screens.configuration import ConfigurationScreen
from raven.tui.screens.file_picker import (
    ConfirmEvidenceDelete,
    EvidenceFilePicker,
    EvidenceStorageDirectoryPicker,
    MarkdownExportPicker,
    NewDirectoryDialog,
    filter_directory_paths,
    filter_evidence_paths,
)
from raven.tui.screens.home import HelpScreen, HomeScreen
from raven.tui.screens.investigation import InvestigationCreateScreen
from raven.tui.screens.investigation_catalog import InvestigationCatalogScreen
from raven.tui.screens.investigation_workspace import (
    ConfirmClearChat,
    ConfirmInvestigationDelete,
    InvestigationWorkspaceScreen,
)
from raven.tui.widgets import GraphCanvas, LocalCommandView
from raven.tui.widgets.logo import COMPACT_LOGO, WIDE_LOGO, RavenLogo
from raven.tui.widgets.service_status import ServiceStatusIndicator


class FakeInfrastructure:
    def __init__(self) -> None:
        self.initialized: list[ServiceName] = []
        self.configured: RavenSettings | None = None
        self.closed = False
        self.tested_ai: AiNodeSettings | None = None

    def configure(self, settings: RavenSettings) -> None:
        self.configured = settings

    def initialize(self, service: ServiceName) -> ServiceStatus:
        self.initialized.append(service)
        return ServiceStatus.connected(service)

    def test_ai_node(self, settings: AiNodeSettings) -> ServiceStatus:
        self.tested_ai = settings
        return ServiceStatus.connected(ServiceName.AI)

    def close(self) -> None:
        self.closed = True


class FakeInvestigations:
    def __init__(self) -> None:
        self.draft: InvestigationDraft | None = None
        self.documents: list[EvidenceDocument] = []
        self.investigations: list[Investigation] = []

    def create(
        self,
        draft: InvestigationDraft,
    ) -> Investigation:
        self.draft = draft
        now = datetime.now(UTC)
        investigation = Investigation(
            investigation_id=f"00000000-0000-0000-0000-{len(self.investigations) + 1:012d}",
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
        self.investigations.append(investigation)
        return investigation

    def add_evidence(
        self,
        investigation_id: str,
        source: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> EvidenceDocument:
        evidence = EvidenceDocument(
            document_id="document-id",
            investigation_id=investigation_id,
            original_name=source.name,
            storage_key=f"{investigation_id}/document-id.pdf",
            media_type="application/pdf",
            file_format="PDF",
            size_bytes=8,
            sha256="0" * 64,
            page_count=2,
            page_count_estimated=False,
            ingestion_state=EvidenceIngestionState.PENDING,
            created_at=datetime.now(UTC),
        )
        self.documents.append(evidence)
        return evidence

    def delete_evidence(self, document: EvidenceDocument) -> None:
        self.documents = [
            item for item in self.documents if item.document_id != document.document_id
        ]

    def update(
        self,
        current: Investigation,
        draft: InvestigationDraft,
    ) -> Investigation:
        updated = replace(
            current,
            name=draft.name,
            description=draft.description,
            questions=draft.questions,
            analysis_language=draft.analysis_language,
            analysis_domain=draft.analysis_domain,
            updated_at=datetime.now(UTC),
        )
        self.investigations = [
            updated if item.investigation_id == current.investigation_id else item
            for item in self.investigations
        ]
        return updated

    def delete(self, investigation: Investigation) -> None:
        self.investigations = [
            item
            for item in self.investigations
            if item.investigation_id != investigation.investigation_id
        ]

    def list_investigations(self) -> tuple[Investigation, ...]:
        return tuple(self.investigations)


class FakeGraphAnalysis:
    def __init__(self) -> None:
        self.mode: EvidencePreparationMode | None = None
        self.graph: InvestigationGraph | None = None
        self.removed_investigations: list[str] = []

    def latest(self, investigation_id: str) -> InvestigationGraph | None:
        return self.graph

    def invalidate(self, investigation_id: str) -> None:
        self.graph = None

    def remove_investigation(self, investigation_id: str) -> None:
        self.removed_investigations.append(investigation_id)
        self.graph = None

    def analyze(
        self,
        investigation: Investigation,
        documents: tuple[EvidenceDocument, ...],
        preparation_mode: EvidencePreparationMode,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable | None = None,
    ) -> GraphAnalysisResult:
        self.mode = preparation_mode
        now = datetime.now(UTC)
        person = GraphEntity(
            "person-id",
            "PERSON",
            "Mario Rossi",
            evidence_ids=("document-id",),
        )
        company = GraphEntity(
            "company-id",
            "ORGANIZATION",
            "Alfa S.p.A.",
            evidence_ids=("document-id",),
        )
        relationship = GraphRelationship(
            "relationship-id",
            person.entity_id,
            company.entity_id,
            "WORKS_FOR",
            evidence_ids=("document-id",),
        )
        self.graph = InvestigationGraph(
            investigation.investigation_id,
            "run-id",
            (person, company),
            (relationship,),
            now,
        )
        run = GraphAnalysisRun(
            "run-id",
            investigation.investigation_id,
            GraphRunStatus.COMPLETED,
            preparation_mode,
            investigation.analysis_language.value,
            len(documents),
            len(documents),
            0,
            2,
            1,
            "scripted-model",
            now,
            now,
            now,
        )
        return GraphAnalysisResult(run, self.graph)


class FakeChat:
    def __init__(self) -> None:
        self.question = ""
        self.indexed_documents: list[str] = []
        self.removed_investigations: list[str] = []
        self.history_cleared = False

    def index_knowledge_base(self, investigation, documents, cancelled=None, progress=None) -> int:
        total = len(documents)
        for position, document in enumerate(documents, 1):
            if progress is not None:
                progress(
                    RagIndexProgress(
                        document.document_id,
                        document.original_name,
                        EvidenceIngestionState.PROCESSING,
                        position - 1,
                        total,
                    )
                )
            self.indexed_documents.append(document.document_id)
            if progress is not None:
                progress(
                    RagIndexProgress(
                        document.document_id,
                        document.original_name,
                        EvidenceIngestionState.READY,
                        position,
                        total,
                    )
                )
        return len(documents)

    def stream_answer(
        self,
        investigation,
        documents,
        graph,
        question,
        cancelled=None,
        index_progress=None,
    ):
        self.question = question
        yield ChatStreamEvent(ChatEventKind.STATUS, "Retrieving Evidence...")
        yield ChatStreamEvent(
            ChatEventKind.TOKEN,
            "Grounded result [E1].\n\n```mermaid\nflowchart LR\n  A --> B\n```",
        )
        yield ChatStreamEvent(
            ChatEventKind.COMPLETE,
            sources=("report.pdf · chunk 1",),
            usage=TokenUsage(180, 42, 222),
        )

    def load_history(self, investigation_id: str) -> tuple[ChatMessage, ...]:
        return ()

    def clear_history(self, investigation_id: str) -> None:
        self.history_cleared = True

    def remove_document(self, document: EvidenceDocument) -> None:
        return None

    def remove_investigation(self, investigation_id: str) -> None:
        self.removed_investigations.append(investigation_id)


def make_app(
    temporary_directory: Path,
    *,
    infrastructure: FakeInfrastructure | None = None,
    investigations: FakeInvestigations | None = None,
    graph_analysis: FakeGraphAnalysis | None = None,
    investigation_chat: FakeChat | None = None,
    auto_connect: bool = False,
) -> RavenApp:
    configuration_store = ConfigurationStore(
        temporary_directory / "config.json",
        InMemoryCredentialStore(),
    )
    return RavenApp(
        configuration_store=configuration_store,
        infrastructure=infrastructure,
        investigations=investigations,
        graph_analysis=graph_analysis,
        investigation_chat=investigation_chat,
        auto_connect=auto_connect,
    )


async def test_app_opens_home_with_top_menu_and_service_leds(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)
        assert app.screen.query_one("#nav-home").has_class("active")
        assert app.screen.query_one("#new-investigation").label.plain == "Start a new investigation"
        assert app.screen.query_one(RavenLogo).render().plain == WIDE_LOGO
        indicators = list(app.screen.query(ServiceStatusIndicator))
        assert [indicator.service for indicator in indicators] == list(ServiceName)
        assert all(indicator.status.state is ConnectionState.CHECKING for indicator in indicators)


async def test_first_home_mount_initializes_all_services(tmp_path: Path) -> None:
    infrastructure = FakeInfrastructure()
    app = make_app(tmp_path, infrastructure=infrastructure, auto_connect=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert set(infrastructure.initialized) == set(ServiceName)
        indicators = list(app.screen.query(ServiceStatusIndicator))
        assert all(indicator.status.state is ConnectionState.CONNECTED for indicator in indicators)


async def test_logo_switches_to_compact_art_in_narrow_terminal(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause()

        assert app.screen.query_one(RavenLogo).render().plain == COMPACT_LOGO


async def test_contextual_help_opens_and_closes_from_keyboard(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


async def test_top_menu_opens_configuration_and_saves_public_values(tmp_path: Path) -> None:
    infrastructure = FakeInfrastructure()
    app = make_app(tmp_path, infrastructure=infrastructure)
    dictionary_root = tmp_path / "dictionaries"
    dictionary_root.mkdir()
    bundled_root = DictionarySettings().path
    for name in ("core.json", "general-osint.json"):
        (dictionary_root / name).write_text(
            (bundled_root / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-configuration")
        await pilot.pause()
        assert isinstance(app.screen, ConfigurationScreen)

        app.screen.query_one("#mongo-database").value = "raven_test"
        app.screen.query_one("#evidence-storage-root").value = str(tmp_path / "evidence")
        app.screen.query_one("#dictionary-root").value = str(dictionary_root)
        app.screen.query_one("#neo4j-password").value = "session-secret"
        app.screen.query_one("#ai-model").value = "qwen3"
        app.screen.query_one("#embedding-model").value = "nomic-embed-text"
        app.screen.query_one("#ai-top-k").value = "32"
        app.screen.query_one("#ai-random-seed").value = "42"
        app.screen.query_one("#ai-context-size").value = "65536"
        app.screen.query_one("#ai-api-key").value = "ai-session-secret"
        await pilot.click("#save-configuration")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)
        assert app.settings.mongodb.database == "raven_test"
        assert app.settings.storage.path == tmp_path / "evidence"
        assert app.settings.dictionaries.path == dictionary_root
        assert app.settings.neo4j.password == "session-secret"
        assert app.settings.ai.model == "qwen3"
        assert app.settings.ai.embedding_model == "nomic-embed-text"
        assert app.settings.ai.top_k == 32
        assert app.settings.ai.random_seed == 42
        assert app.settings.ai.context_size == 65536
        assert app.settings.ai.api_key == "ai-session-secret"
        assert infrastructure.configured == app.settings
        assert app.configuration_store.load() == app.settings
        assert app.configuration_store.load().neo4j.password == "session-secret"
        assert "session-secret" not in (tmp_path / "config.json").read_text(encoding="utf-8")


async def test_dictionary_folder_can_be_selected_from_configuration(tmp_path: Path) -> None:
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())
    dictionary_root = DictionarySettings().path

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-configuration")
        app.screen.query_one("#configuration-tabs", TabbedContent).active = "dictionaries-tab"
        await pilot.pause()
        await pilot.click("#browse-dictionary-root")
        await pilot.pause()

        assert isinstance(app.screen, EvidenceStorageDirectoryPicker)
        assert app.screen.query_one(".path-picker-title").render().plain == (
            "SELECT DICTIONARY FOLDER"
        )
        app.screen._set_root(dictionary_root)
        await pilot.click("#confirm-storage-directory")
        await pilot.pause()

        assert isinstance(app.screen, ConfigurationScreen)
        assert app.screen.query_one("#dictionary-root").value == str(dictionary_root)


async def test_storage_directory_can_be_selected_from_configuration(tmp_path: Path) -> None:
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())
    selected = tmp_path / "selected-storage"
    selected.mkdir()

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-configuration")
        await pilot.click("#browse-evidence-storage")
        await pilot.pause()

        assert isinstance(app.screen, EvidenceStorageDirectoryPicker)
        storage_tree = app.screen.query_one("#storage-directory-tree")
        assert storage_tree.size.height >= 8
        storage_dialog = app.screen.query_one("#storage-picker-dialog")
        assert storage_tree.outer_size.height * 5 >= storage_dialog.size.height * 3
        assert storage_tree.has_focus
        app.screen._set_root(selected)
        await pilot.click("#confirm-storage-directory")
        await pilot.pause()

        assert isinstance(app.screen, ConfigurationScreen)
        assert app.screen.query_one("#evidence-storage-root").value == str(selected)


async def test_storage_picker_creates_and_selects_folder(tmp_path: Path) -> None:
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-configuration")
        await pilot.click("#browse-evidence-storage")
        await pilot.pause()

        assert isinstance(app.screen, EvidenceStorageDirectoryPicker)
        app.screen._set_root(tmp_path)
        await pilot.click("#storage-picker-add-folder")
        await pilot.pause()

        assert isinstance(app.screen, NewDirectoryDialog)
        name = app.screen.query_one("#new-directory-name")
        assert name.has_focus
        name.value = "case-files"
        await pilot.click("#confirm-new-directory")
        await pilot.pause()

        destination = tmp_path / "case-files"
        assert destination.is_dir()
        assert isinstance(app.screen, EvidenceStorageDirectoryPicker)
        assert app.screen.selected == destination
        assert app.screen.query_one("#selected-storage-directory").tooltip == str(destination)


async def test_configuration_reports_password_loaded_from_secure_vault(tmp_path: Path) -> None:
    credential_store = InMemoryCredentialStore()
    store = ConfigurationStore(tmp_path / "config.json", credential_store)
    store.save(RavenSettings(neo4j=Neo4jSettings(password="saved-password")))
    app = RavenApp(
        configuration_store=store,
        infrastructure=FakeInfrastructure(),
        auto_connect=False,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-configuration")
        await pilot.pause()

        status = app.screen.query_one("#neo4j-password-status")
        password = app.screen.query_one("#neo4j-password")
        assert status.render().plain == "● Password saved in system credential vault"
        assert password.value == ""
        assert password.placeholder.startswith("Saved")


def test_real_app_creates_configured_evidence_root_on_first_start(tmp_path: Path) -> None:
    store = ConfigurationStore(tmp_path / "config.json", InMemoryCredentialStore())
    evidence_root = tmp_path / "case-evidence"
    store.save(RavenSettings(storage=EvidenceStorageSettings(root=str(evidence_root))))

    app = RavenApp(configuration_store=store, auto_connect=False)

    assert evidence_root.is_dir()
    app.infrastructure.close()


async def test_investigations_menu_opens_catalog(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigations.create(InvestigationDraft(name="Operation Raven", questions=("Who?",)))
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCatalogScreen)
        assert app.screen.query_one("#nav-investigations").has_class("active")
        assert len(app.screen.query(".investigation-row")) == 1


async def test_ai_node_button_probes_draft_without_saving_it(tmp_path: Path) -> None:
    infrastructure = FakeInfrastructure()
    app = make_app(tmp_path, infrastructure=infrastructure)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-configuration")
        await pilot.pause()
        app.screen.query_one("#configuration-tabs", TabbedContent).active = "ai-tab"
        app.screen.query_one("#ai-model").value = "qwen3"
        app.screen.query_one("#ai-thinking", Select).value = "high"
        app.screen.query_one("#ai-top-k").value = "24"
        app.screen.query_one("#ai-random-seed").value = "17"
        app.screen.query_one("#ai-timeout-seconds").value = "80"
        app.screen.query_one("#ai-context-size").value = "65536"
        app.screen.query_one("#embedding-provider", Select).value = "vllm"
        app.screen.query_one("#embedding-model").value = "raven-embed"
        await pilot.pause()

        assert (
            app.screen.query_one("#embedding-base-url").value
            == (AI_PROVIDER_DEFAULT_URLS[AiProvider.VLLM])
        )

        await pilot.click("#test-ai-node")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert infrastructure.tested_ai is not None
        assert infrastructure.tested_ai.model == "qwen3"
        assert infrastructure.tested_ai.thinking.value == "high"
        assert infrastructure.tested_ai.top_k == 24
        assert infrastructure.tested_ai.random_seed == 17
        assert infrastructure.tested_ai.timeout_seconds == 80
        assert infrastructure.tested_ai.context_size == 65536
        assert infrastructure.tested_ai.embedding_provider is AiProvider.VLLM
        assert infrastructure.tested_ai.embedding_model == "raven-embed"
        assert app.settings.ai.model == ""
        assert app.screen.query_one("#ai-test-result").render().plain == "● Connected"

        app.screen.query_one("#ai-model").value = "another-model"
        await pilot.pause()
        assert app.screen.query_one("#ai-test-result").render().plain == "● Not tested"


async def test_primary_action_opens_investigation_creation(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#new-investigation")
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCreateScreen)


async def test_catalog_searches_sorts_and_opens_selected_investigation(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigations.create(InvestigationDraft(name="Zulu Case", questions=("Who?",)))
    investigations.create(InvestigationDraft(name="Alpha Case", questions=("When?",)))
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.pause()

        app.screen.query_one("#catalog-sort").value = "name"
        await pilot.pause()
        assert [
            row.query_one(".catalog-name").render().plain
            for row in app.screen.query(".investigation-row")
        ] == ["Alpha Case", "Zulu Case"]

        app.screen.query_one("#catalog-search").value = "alpha"
        await pilot.pause()
        rows = list(app.screen.query(".investigation-row"))
        assert len(rows) == 1
        assert rows[0].query_one(".catalog-name").render().plain == "Alpha Case"

        await pilot.click(".open-investigation")
        await pilot.pause()
        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        assert app.screen.investigation.name == "Alpha Case"


async def test_catalog_toolbar_controls_are_fully_visible(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigations.create(InvestigationDraft(name="Readable case", questions=("Who?",)))
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.pause()

        toolbar = app.screen.query_one("#catalog-toolbar")
        assert toolbar.content_size.height >= 3
        assert app.screen.query_one("#catalog-search").placeholder == "Search investigations"
        assert app.screen.query_one("#catalog-sort", Select).value == "updated"
        assert app.screen.query_one("#refresh-investigations").label.plain == "Refresh"
        assert app.screen.query_one("#new-investigation-catalog").label.plain == (
            "New investigation"
        )


async def test_catalog_deletes_complete_investigation_after_confirmation(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Disposable case", questions=("Why?",))
    )
    graph = FakeGraphAnalysis()
    chat = FakeChat()
    app = make_app(
        tmp_path,
        investigations=investigations,
        graph_analysis=graph,
        investigation_chat=chat,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.pause()

        row = app.screen.query_one(".investigation-row")
        assert row.query_one(".open-investigation").label.plain == "Open"
        delete_button = row.query_one(".delete-investigation-catalog")
        assert delete_button.label.plain == "Delete"
        assert delete_button.region.right <= row.region.right
        await pilot.click(".delete-investigation-catalog")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmInvestigationDelete)
        assert app.screen.query_one("#delete-investigation-name").render().plain == (
            "Disposable case"
        )
        await pilot.click("#confirm-delete-investigation")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCatalogScreen)
        assert investigations.investigations == []
        assert chat.removed_investigations == [investigation.investigation_id]
        assert graph.removed_investigations == [investigation.investigation_id]
        assert len(app.screen.query(".investigation-row")) == 0


def test_investigation_delete_keeps_primary_case_when_rag_cleanup_fails(tmp_path: Path) -> None:
    class FailingChat(FakeChat):
        def remove_investigation(self, investigation_id: str) -> None:
            raise InvestigationChatError("Qdrant unavailable")

    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Retryable case", questions=("Why?",))
    )
    app = make_app(
        tmp_path,
        investigations=investigations,
        graph_analysis=FakeGraphAnalysis(),
        investigation_chat=FailingChat(),
    )

    with pytest.raises(InvestigationPersistenceError, match="RAG cleanup failed"):
        app.delete_investigation(investigation)

    assert investigations.investigations == [investigation]


async def test_catalog_new_button_opens_creation_form(tmp_path: Path) -> None:
    app = make_app(tmp_path, investigations=FakeInvestigations())

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.click("#new-investigation-catalog")
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCreateScreen)
        assert app.screen.has_class("compact-investigation-form")
        assert app.screen.query_one("#investigation-questions").outer_size.height >= 7


async def test_investigation_questions_editor_uses_available_height(tmp_path: Path) -> None:
    app = make_app(tmp_path, investigations=FakeInvestigations())

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#new-investigation")
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCreateScreen)
        assert not app.screen.has_class("compact-investigation-form")
        assert app.screen.query_one("#investigation-description").outer_size.height == 4
        assert app.screen.query_one("#investigation-questions").outer_size.height >= 12


async def test_create_investigation_opens_workspace_without_requiring_evidence(
    tmp_path: Path,
) -> None:
    investigations = FakeInvestigations()
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#new-investigation")
        await pilot.pause()
        app.screen.query_one("#investigation-name").value = "Operation Raven"
        app.screen.query_one("#investigation-description", TextArea).text = "Initial context"
        app.screen.query_one("#investigation-analysis-language", Select).value = "italian"
        app.screen.query_one(
            "#investigation-analysis-domain", Select
        ).value = "MARITIME_INTELLIGENCE"
        await pilot.pause()
        assert "Vessels" in app.screen.query_one("#investigation-domain-description").render().plain
        app.screen.query_one(
            "#investigation-questions", TextArea
        ).text = "Who coordinated the event?\nWhen did it begin?"
        await pilot.click("#create-investigation")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        assert investigations.draft is not None
        assert investigations.draft.questions == (
            "Who coordinated the event?",
            "When did it begin?",
        )
        assert investigations.draft.analysis_language is AnalysisLanguage.ITALIAN
        assert investigations.draft.analysis_domain == "MARITIME_INTELLIGENCE"
        assert "MARITIME_INTELLIGENCE" in app.screen.query_one("#workspace-profile").render().plain
        assert app.screen.query_one("#graph-domain-detail").render().plain == (
            "Analysis domain\nMARITIME_INTELLIGENCE"
        )
        assert app.screen.documents == []
        destination = app.screen.query_one("#evidence-storage-path")
        assert destination.render().plain.startswith("Stored in")
        assert destination.tooltip == str(
            app.evidence_directory(app.screen.investigation.investigation_id)
        )
        assert list(app._notifications)[0].title == "Investigation created"


async def test_workspace_edits_dictionary_and_reference_language(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Editable case", questions=("Who?",))
    )
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(80, 24)) as pilot:
        app.open_investigation(investigation)
        await pilot.pause()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-overview-tab"
        await pilot.pause()
        await pilot.click("#edit-investigation")
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCreateScreen)
        assert app.screen.query_one("#investigation-title").render().plain == "Edit investigation"
        app.screen.query_one("#investigation-name").value = "Edited case"
        app.screen.query_one("#investigation-analysis-language", Select).value = "italian"
        app.screen.query_one(
            "#investigation-analysis-domain", Select
        ).value = "MARITIME_INTELLIGENCE"
        await pilot.click("#create-investigation")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        assert app.screen.investigation.name == "Edited case"
        assert app.screen.investigation.analysis_language is AnalysisLanguage.ITALIAN
        assert app.screen.investigation.analysis_domain == "MARITIME_INTELLIGENCE"
        assert "Italian" in app.screen.query_one("#workspace-profile").render().plain


async def test_workspace_deletes_investigation_after_named_confirmation(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Disposable case", questions=("Why?",))
    )
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(80, 24)) as pilot:
        app.open_investigation(investigation)
        await pilot.pause()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-overview-tab"
        await pilot.pause()
        await pilot.click("#delete-investigation")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmInvestigationDelete)
        assert (
            app.screen.query_one("#delete-investigation-name").render().plain == "Disposable case"
        )
        await pilot.click("#confirm-delete-investigation")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationCatalogScreen)
        assert investigations.investigations == []


async def test_workspace_file_picker_adds_and_deletes_evidence(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    chat = FakeChat()
    app = make_app(
        tmp_path,
        investigations=investigations,
        investigation_chat=chat,
    )
    app.settings = replace(
        app.settings,
        ai=AiNodeSettings(model="chat-model", embedding_model="embed-model"),
    )
    selected = tmp_path / "report.pdf"
    selected.write_bytes(b"pdf")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#new-investigation")
        app.screen.query_one("#investigation-name").value = "Operation Raven"
        app.screen.query_one("#investigation-questions", TextArea).text = "What happened?"
        await pilot.click("#create-investigation")
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.click("#add-evidence")
        await pilot.pause()
        assert isinstance(app.screen, EvidenceFilePicker)
        file_dialog = app.screen.query_one("#file-picker-dialog")
        assert file_dialog.outer_size.width >= 76
        assert file_dialog.outer_size.width <= 80
        assert file_dialog.outer_size.height >= 22
        evidence_tree = app.screen.query_one("#evidence-directory-tree")
        assert evidence_tree.size.height >= 8
        assert evidence_tree.outer_size.height * 5 >= file_dialog.size.height * 3
        assert evidence_tree.has_focus
        app.screen._select_file(selected)
        assert app.screen.query_one("#selected-evidence-file").render().plain == "report.pdf"
        assert app.screen.query_one("#selected-evidence-format").render().plain == "PDF"
        await pilot.click("#confirm-evidence-file")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        assert app.screen.query_one("#evidence-section-header").outer_size.height >= 6
        assert len(app.screen.documents) == 1
        row = app.screen.query_one("#evidence-document-id")
        assert row.query_one(".evidence-format").render().plain == "PDF"
        assert row.query_one(".evidence-pages").render().plain == "2"
        assert row.query_one(".evidence-state").render().plain == "Pending"

        await pilot.click("#index-evidence-rag")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert chat.indexed_documents == [row.document.document_id]
        assert row.query_one(".evidence-state").render().plain == "Indexed"
        assert (
            "RAG index ready" in app.screen.query_one("#evidence-operation-status").render().plain
        )
        assert app.screen.query_one("#cancel-rag-index").has_class("hidden")

        await pilot.click(".delete-evidence")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmEvidenceDelete)
        assert app.screen.query_one("#delete-evidence-name").render().plain == "report.pdf"
        await pilot.click("#confirm-delete-evidence")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        assert app.screen.documents == []
        assert len(app.screen.query("#evidence-empty")) == 1


async def test_evidence_header_action_bar_is_not_clipped(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Readable evidence", questions=("Who?",))
    )
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(160, 32)) as pilot:
        app.open_investigation(investigation)
        await pilot.pause()

        header = app.screen.query_one("#evidence-section-header")
        assert header.content_size.height >= 5
        for selector in ("#index-evidence-rag", "#add-evidence"):
            button = app.screen.query_one(selector)
            assert button.region.y >= header.content_region.y
            assert button.region.bottom <= header.content_region.bottom


async def test_graph_toolbar_controls_are_not_clipped(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Readable graph", questions=("Who?",))
    )
    app = make_app(tmp_path, investigations=investigations)

    async with app.run_test(size=(160, 32)) as pilot:
        app.open_investigation(investigation)
        await pilot.pause()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()

        toolbar = app.screen.query_one("#graph-toolbar")
        assert toolbar.content_size.height >= 5
        for selector in ("#graph-preparation-mode", "#analyze-evidence"):
            control = app.screen.query_one(selector)
            assert control.region.y >= toolbar.content_region.y
            assert control.region.bottom <= toolbar.content_region.bottom


async def test_workspace_analyzes_evidence_and_visualizes_proposed_graph(tmp_path: Path) -> None:
    investigations = FakeInvestigations()
    created = investigations.create(
        InvestigationDraft(
            name="Operation Raven",
            questions=("Who works for Alfa?",),
            analysis_language=AnalysisLanguage.ITALIAN,
        )
    )
    evidence = investigations.add_evidence(created.investigation_id, tmp_path / "report.pdf")
    investigations.investigations[0] = replace(created, evidence_documents=(evidence,))
    graph_analysis = FakeGraphAnalysis()
    app = make_app(
        tmp_path,
        investigations=investigations,
        graph_analysis=graph_analysis,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.click(".open-investigation")
        await app.workers.wait_for_complete()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()

        assert app.screen.query_one("#graph-toolbar").outer_size.height >= 5
        await pilot.click("#analyze-evidence")
        await app.workers.wait_for_complete()
        await pilot.pause()

        canvas = app.screen.query_one("#graph-canvas", GraphCanvas)
        rendered = canvas.plain_summary()
        assert canvas.size.width >= 40
        assert canvas.size.height >= 4
        assert app.screen.has_class("narrow-workspace")
        assert graph_analysis.mode is EvidencePreparationMode.COMPRESS
        assert "Mario Rossi" in rendered
        assert "WORKS_FOR" in rendered
        assert (
            app.screen.query_one("#graph-statistics")
            .render()
            .plain.startswith("2 entities · 1 relationships")
        )

        await pilot.click("#zoom-in-graph")
        await pilot.pause()
        assert app.screen.query_one("#graph-zoom-label").render().plain.endswith("%")
        await pilot.click("#fit-graph")
        await pilot.pause()
        assert app.screen.query_one("#graph-zoom-label").render().plain == "FIT"

        canvas.focus()
        await pilot.press("j")
        await pilot.pause()
        assert canvas.selected_entity is not None
        assert "Mario Rossi" in app.screen.query_one("#graph-selection-detail").render().plain

        search = app.screen.query_one("#graph-entity-search")
        search.value = "Alfa"
        search.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert canvas.selected_entity is not None
        assert canvas.selected_entity.canonical_name == "Alfa S.p.A."


async def test_graph_analysis_continues_after_leaving_and_reopening_case(tmp_path: Path) -> None:
    class BlockingGraphAnalysis(FakeGraphAnalysis):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def analyze(
            self,
            investigation,
            documents,
            preparation_mode,
            cancelled=None,
            progress=None,
        ) -> GraphAnalysisResult:
            if progress is not None:
                progress(
                    GraphAnalysisProgress(
                        GraphRunStatus.EXTRACTING,
                        0,
                        len(documents),
                        "Analyzing report.pdf",
                    )
                )
            self.started.set()
            assert self.release.wait(2)
            return super().analyze(
                investigation,
                documents,
                preparation_mode,
                cancelled,
                progress,
            )

    investigations = FakeInvestigations()
    created = investigations.create(InvestigationDraft(name="Persistent case", questions=("Who?",)))
    evidence = investigations.add_evidence(created.investigation_id, tmp_path / "report.pdf")
    investigation = replace(created, evidence_documents=(evidence,))
    investigations.investigations[0] = investigation
    graph_analysis = BlockingGraphAnalysis()
    app = make_app(tmp_path, investigations=investigations, graph_analysis=graph_analysis)

    async with app.run_test(size=(120, 32)) as pilot:
        app.open_investigation(investigation)
        await pilot.pause()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()
        await pilot.click("#analyze-evidence")
        for _ in range(20):
            await pilot.pause(0.05)
            if graph_analysis.started.is_set():
                break
        assert graph_analysis.started.is_set()

        app.navigate("investigations")
        await pilot.pause()
        assert isinstance(app.screen, InvestigationCatalogScreen)

        app.open_investigation(investigation)
        await pilot.pause(0.2)
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()
        assert "Running" in app.screen.query_one("#graph-analysis-status").render().plain
        assert app.screen.query_one("#analyze-evidence").disabled

        graph_analysis.release.set()
        for _ in range(20):
            await pilot.pause(0.05)
            job = app.graph_analysis_job(investigation.investigation_id)
            if job is not None and job.status is GraphJobStatus.COMPLETED:
                break

        completed = app.graph_analysis_job(investigation.investigation_id)
        assert completed is not None
        assert completed.status is GraphJobStatus.COMPLETED
        await pilot.pause(0.2)
        assert app.screen.graph is not None
        assert "Completed" in app.screen.query_one("#graph-analysis-status").render().plain


async def test_workspace_chat_streams_grounded_markdown_and_renders_mermaid(
    tmp_path: Path,
) -> None:
    investigations = FakeInvestigations()
    investigation = investigations.create(
        InvestigationDraft(name="Chat case", questions=("What connects A and B?",))
    )
    chat = FakeChat()
    app = make_app(
        tmp_path,
        investigations=investigations,
        investigation_chat=chat,
    )

    async with app.run_test(size=(100, 32)) as pilot:
        app.open_investigation(investigation)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-chat-tab"
        app.screen.query_one("#chat-input", TextArea).text = "Explain the connection"
        await pilot.pause()

        assert await pilot.click("#send-chat")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert chat.question == "Explain the connection"
        rendered_diagram = "\n".join(
            label.render().plain for label in app.screen.query(".mermaid-rendered Label")
        )
        assert "A" in rendered_diagram and "B" in rendered_diagram
        assert (
            "Grounded answer complete"
            in app.screen.query_one("#chat-operation-status").render().plain
        )
        assert "222 tokens" in app.screen.query_one("#chat-operation-status").render().plain
        assert "222 total" in app.screen.query_one("#chat-token-usage").render().plain
        assert "input 180" in app.screen.query_one(".chat-message-usage").render().plain
        assert "report.pdf" in app.screen.query_one(".chat-message-sources").render().plain

        app.screen.query_one("#chat-input", TextArea).text = "/stats"
        await pilot.press("ctrl+enter")
        await pilot.pause()
        statistics = list(app.screen.query(LocalCommandView))[-1].markdown
        assert "Total tokens: **222**" in statistics
        assert "Saved messages: **2**" in statistics
        assert "local command · 0 tokens" in (
            app.screen.query_one("#chat-operation-status").render().plain
        )

        app.screen.query_one("#chat-input", TextArea).text = "/INFO"
        await pilot.press("ctrl+enter")
        await pilot.pause()
        information = list(app.screen.query(LocalCommandView))[-1].markdown
        assert "Active investigation context" in information
        assert "report.pdf · chunk 1" in information
        assert "Evidence sources" in information

        app.screen._last_export_directory = tmp_path
        app.screen.query_one("#chat-input", TextArea).text = "/SAVE"
        await pilot.press("ctrl+enter")
        await pilot.pause()
        assert isinstance(app.screen, MarkdownExportPicker)
        app.screen.query_one("#markdown-export-name").value = "grounded-answer.md"
        await pilot.click("#confirm-markdown-export")
        await app.workers.wait_for_complete()
        await pilot.pause()
        export = tmp_path / "grounded-answer.md"
        assert export.exists()
        assert "Grounded result [E1]" in export.read_text()
        assert "report.pdf · chunk 1" in export.read_text()

        app.screen.query_one("#chat-input", TextArea).text = "/NEW"
        await pilot.press("ctrl+enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmClearChat)
        assert app.screen.query_one("#clear-chat-investigation").render().plain == "Chat case"
        await pilot.click("#confirm-clear-chat")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert chat.history_cleared
        assert len(app.screen.query(LocalCommandView)) == 0


def test_file_picker_filters_unsupported_and_hidden_paths(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    hidden_folder = tmp_path / ".private"
    hidden_folder.mkdir()
    pdf = tmp_path / "report.pdf"
    pdf.touch()
    hidden_pdf = tmp_path / ".secret.pdf"
    hidden_pdf.touch()
    text = tmp_path / "notes.txt"
    text.touch()

    visible = filter_evidence_paths((hidden_folder, folder, hidden_pdf, pdf, text))

    assert visible == [folder, pdf]


def test_folder_picker_filters_hidden_directories(tmp_path: Path) -> None:
    hidden_folder = tmp_path / ".private"
    hidden_folder.mkdir()
    visible_folder = tmp_path / "documents"
    visible_folder.mkdir()
    regular_file = tmp_path / "notes.md"
    regular_file.touch()

    visible = filter_directory_paths((hidden_folder, visible_folder, regular_file))

    assert visible == [visible_folder]


async def test_file_picker_height_tracks_a_tall_terminal(tmp_path: Path) -> None:
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())

    async with app.run_test(size=(80, 48)) as pilot:
        app.push_screen(EvidenceFilePicker(tmp_path))
        await pilot.pause()

        dialog = app.screen.query_one("#file-picker-dialog")
        assert dialog.outer_size.height >= 44
        assert dialog.outer_size.height <= 48


async def test_markdown_export_picker_keeps_directory_tree_navigable(tmp_path: Path) -> None:
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())

    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(MarkdownExportPicker(tmp_path, "latest-response.md"))
        await pilot.pause()

        dialog = app.screen.query_one("#markdown-export-dialog")
        tree = app.screen.query_one("#markdown-export-directory-tree")
        assert dialog.outer_size.height >= 22
        assert tree.size.height >= 5
        assert app.screen.has_class("compact-path-picker")


async def test_expanding_a_folder_preserves_tree_scroll_position(tmp_path: Path) -> None:
    browser_root = tmp_path / "browser"
    browser_root.mkdir()
    for index in range(70):
        folder = browser_root / f"{index:02d}-folder"
        folder.mkdir()
        (folder / "document.pdf").touch()
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())

    async with app.run_test(size=(80, 48)) as pilot:
        app.push_screen(EvidenceFilePicker(browser_root))
        await pilot.pause(0.5)
        tree = app.screen.query_one("#evidence-directory-tree")
        tree.scroll_to(y=20, animate=False, immediate=True)
        tree.cursor_line = 0
        await pilot.pause()
        previous_scroll = tree.scroll_y

        await pilot.click("#evidence-directory-tree", offset=(3, 2))
        await pilot.pause(0.5)

        assert previous_scroll == 20
        assert tree.scroll_y == previous_scroll
        assert tree.cursor_line > 0
