"""Infrastructure, storage, and secure credential configuration screen."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static, TabbedContent, TabPane

from raven.config import (
    AI_PROVIDER_DEFAULT_URLS,
    AiNodeSettings,
    AiProvider,
    AiThinkingLevel,
    DictionarySettings,
    EvidenceStorageSettings,
    MongoSettings,
    Neo4jSettings,
    QdrantSettings,
    RavenSettings,
    UiLanguage,
)
from raven.exceptions import ConfigurationError
from raven.models import ConnectionState, ServiceStatus
from raven.tui.screens.file_picker import EvidenceStorageDirectoryPicker
from raven.tui.widgets import TopNavigation

if TYPE_CHECKING:
    from raven.app import RavenApp


class ConfigurationScreen(Screen[None]):
    """Edit settings while keeping persistent secrets out of the JSON file."""

    AI_FIELD_IDS = {
        "ai-base-url",
        "ai-model",
        "ai-api-key",
        "ai-top-k",
        "ai-random-seed",
        "ai-timeout-seconds",
        "ai-context-size",
        "embedding-base-url",
        "embedding-model",
        "embedding-api-key",
        "embedding-timeout-seconds",
    }

    BINDINGS = [
        Binding("escape", "app.navigate('home')", "Back"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, settings: RavenSettings) -> None:
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        yield TopNavigation(active="configuration")
        yield Label("Application configuration", id="configuration-title")
        yield Static(
            "Neo4j password: system vault · API keys: session or RAVEN_*",
            id="secret-hint",
        )
        with TabbedContent(initial="storage-tab", id="configuration-tabs"):
            with TabPane("Interface", id="interface-tab"), VerticalScroll(classes="config-form"):
                yield Label("Content density")
                yield Select(
                    [("Comfortable", "comfortable"), ("Compact", "compact")],
                    value=self.settings.interface_density,
                    allow_blank=False,
                    id="interface-density",
                )
                yield Label("Interface language")
                yield Select(
                    [("English", UiLanguage.ENGLISH.value), ("Italiano", UiLanguage.ITALIAN.value)],
                    value=self.settings.interface_language.value,
                    allow_blank=False,
                    id="interface-language",
                )
                yield Static(
                    "The selected language is applied when Raven returns to Home.",
                    classes="config-field-hint",
                )
            with TabPane("Storage", id="storage-tab"), VerticalScroll(classes="config-form"):
                yield Label("Evidence root directory")
                with Horizontal(id="storage-root-row"):
                    yield Input(value=self.settings.storage.root, id="evidence-storage-root")
                    yield Button("Browse", id="browse-evidence-storage")
                yield Static(
                    "Raven creates <root>/<investigation-id>/ and stores an immutable copy "
                    "of every uploaded document there.",
                    id="storage-layout-hint",
                )
                yield Static(
                    "Changing the root does not move Evidence already stored in another folder.",
                    id="storage-change-warning",
                )
                yield Static(
                    "RAVEN_EVIDENCE_ROOT overrides this value when the variable is set.",
                    id="storage-environment-hint",
                )
            with (
                TabPane("Dictionaries", id="dictionaries-tab"),
                VerticalScroll(classes="config-form"),
            ):
                yield Label("OSINT dictionary directory")
                with Horizontal(id="dictionary-root-row"):
                    yield Input(
                        value=self.settings.dictionaries.root,
                        id="dictionary-root",
                    )
                    yield Button("Browse", id="browse-dictionary-root")
                yield Static(
                    "The folder must contain Hudiny-compatible JSON vocabularies. "
                    "GENERAL_OSINT is used as the default graph-analysis domain.",
                    id="dictionary-layout-hint",
                )
                yield Static(
                    "RAVEN_DICTIONARY_ROOT overrides this value when the variable is set.",
                    id="dictionary-environment-hint",
                )
            with TabPane("MongoDB", id="mongodb-tab"), VerticalScroll(classes="config-form"):
                yield Label("URI")
                yield Input(value=self.settings.mongodb.uri, id="mongo-uri")
                yield Label("Database")
                yield Input(value=self.settings.mongodb.database, id="mongo-database")
            with TabPane("Qdrant", id="qdrant-tab"), VerticalScroll(classes="config-form"):
                yield Label("URL")
                yield Input(value=self.settings.qdrant.url, id="qdrant-url")
                yield Label("Collection")
                yield Input(value=self.settings.qdrant.collection, id="qdrant-collection")
                yield Label("Vector size")
                yield Input(
                    value=str(self.settings.qdrant.vector_size),
                    id="qdrant-vector-size",
                    type="integer",
                )
            with TabPane("Neo4j", id="neo4j-tab"), VerticalScroll(classes="config-form"):
                yield Label("URI")
                yield Input(value=self.settings.neo4j.uri, id="neo4j-uri")
                yield Label("Username")
                yield Input(value=self.settings.neo4j.username, id="neo4j-username")
                yield Label("Database")
                yield Input(value=self.settings.neo4j.database, id="neo4j-database")
                yield Label("Password (system credential vault)")
                yield Input(
                    id="neo4j-password",
                    password=True,
                    placeholder=(
                        "Saved · type a new password to replace it"
                        if self.settings.neo4j.password
                        else "Enter a password to store securely"
                    ),
                )
                yield Static(
                    (
                        "● Password saved in system credential vault"
                        if self.settings.neo4j.password
                        else "○ No saved password"
                    ),
                    id="neo4j-password-status",
                    classes="saved" if self.settings.neo4j.password else "not-saved",
                )
            with TabPane("AI Node", id="ai-tab"), VerticalScroll(classes="config-form"):
                yield Static("INFERENCE ENDPOINT", classes="config-section-title")
                yield Label("Inference provider")
                yield Select(
                    [(provider.value, provider.value) for provider in AiProvider],
                    value=self.settings.ai.provider.value,
                    allow_blank=False,
                    id="ai-provider",
                )
                yield Label("Inference API base URL")
                yield Input(value=self.settings.ai.base_url, id="ai-base-url")
                yield Label("Inference model")
                yield Input(
                    value=self.settings.ai.model,
                    id="ai-model",
                    placeholder="Select a model exposed by the provider",
                )
                yield Label("Inference API key (session only)")
                yield Input(id="ai-api-key", password=True, placeholder="Not saved to disk")
                yield Static("INFERENCE PARAMETERS", classes="config-section-title")
                with Horizontal(classes="ai-parameter-row"):
                    with Vertical(classes="ai-parameter-field"):
                        yield Label("Thinking effort")
                        yield Select(
                            [(level.value, level.value) for level in AiThinkingLevel],
                            value=self.settings.ai.thinking.value,
                            allow_blank=False,
                            id="ai-thinking",
                        )
                    with Vertical(classes="ai-parameter-field"):
                        yield Label("Top K")
                        yield Input(
                            value=str(self.settings.ai.top_k),
                            id="ai-top-k",
                            type="integer",
                        )
                with Horizontal(classes="ai-parameter-row"):
                    with Vertical(classes="ai-parameter-field"):
                        yield Label("Random seed · empty = random")
                        yield Input(
                            value=(
                                str(self.settings.ai.random_seed)
                                if self.settings.ai.random_seed is not None
                                else ""
                            ),
                            id="ai-random-seed",
                            type="integer",
                        )
                    with Vertical(classes="ai-parameter-field"):
                        yield Label("Timeout · seconds")
                        yield Input(
                            value=str(self.settings.ai.timeout_seconds),
                            id="ai-timeout-seconds",
                            type="number",
                        )
                yield Label("Context size · tokens")
                yield Input(
                    value=str(self.settings.ai.context_size),
                    id="ai-context-size",
                    type="integer",
                )
                yield Static(
                    "Raven uses this as its prompt budget. Ollama also receives num_ctx; "
                    "vLLM, llama.cpp and OpenAI retain the server/model hard limit.",
                    classes="config-field-hint",
                )
                yield Static(
                    "Thinking effort requires a compatible model. Top K is sent to Ollama, "
                    "vLLM and llama.cpp; OpenAI does not expose Top K.",
                    classes="config-field-hint",
                )
                yield Static(
                    "EMBEDDING ENDPOINT · INVESTIGATION RAG", classes="config-section-title"
                )
                yield Label("Embedding provider")
                yield Select(
                    [(provider.value, provider.value) for provider in AiProvider],
                    value=self.settings.ai.embedding_provider.value,
                    allow_blank=False,
                    id="embedding-provider",
                )
                yield Label("Embedding API base URL")
                yield Input(
                    value=self.settings.ai.embedding_base_url,
                    id="embedding-base-url",
                )
                yield Label("Embedding model")
                yield Input(
                    value=self.settings.ai.embedding_model,
                    id="embedding-model",
                    placeholder="e.g. nomic-embed-text or text-embedding-3-small",
                )
                yield Label("Embedding API key (session only)")
                yield Input(
                    id="embedding-api-key",
                    password=True,
                    placeholder="Not saved to disk",
                )
                yield Label("Embedding timeout · seconds")
                yield Input(
                    value=str(self.settings.ai.embedding_timeout_seconds),
                    id="embedding-timeout-seconds",
                    type="number",
                )
        with Center(id="configuration-actions"), Horizontal():
            yield Button("Test nodes", id="test-ai-node")
            yield Static("● Not tested", id="ai-test-result", classes="not-tested")
            yield Button("Save", id="save-configuration", variant="primary")
            yield Button("Cancel", id="cancel-configuration")
        yield Footer()

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.height)

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.height)

    def _set_responsive_layout(self, height: int) -> None:
        self.set_class(height <= 26, "compact-configuration")

    def action_save(self) -> None:
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-configuration":
            self._save()
        elif event.button.id == "test-ai-node":
            self._start_ai_node_test()
        elif event.button.id == "browse-evidence-storage":
            self._browse_evidence_storage()
        elif event.button.id == "browse-dictionary-root":
            self._browse_dictionary_root()
        elif event.button.id == "cancel-configuration":
            self._raven_app.navigate("home")

    def _browse_evidence_storage(self) -> None:
        value = self.query_one("#evidence-storage-root", Input).value.strip()
        candidate = Path(value).expanduser() if value else Path.home()
        if not candidate.is_dir():
            candidate = candidate.parent if candidate.parent.is_dir() else Path.home()
        self.app.push_screen(
            EvidenceStorageDirectoryPicker(candidate),
            self._storage_directory_selected,
        )

    def _storage_directory_selected(self, path: Path | None) -> None:
        if path is not None:
            self.query_one("#evidence-storage-root", Input).value = str(path)

    def _browse_dictionary_root(self) -> None:
        value = self.query_one("#dictionary-root", Input).value.strip()
        candidate = Path(value).expanduser() if value else Path.home()
        if not candidate.is_dir():
            candidate = candidate.parent if candidate.parent.is_dir() else Path.home()
        self.app.push_screen(
            EvidenceStorageDirectoryPicker(
                candidate,
                title="SELECT DICTIONARY FOLDER",
                description="Folder containing Hudiny-compatible JSON vocabularies",
                confirmation="Use folder",
            ),
            self._dictionary_directory_selected,
        )

    def _dictionary_directory_selected(self, path: Path | None) -> None:
        if path is not None:
            self.query_one("#dictionary-root", Input).value = str(path)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id not in {
            "ai-provider",
            "ai-thinking",
            "embedding-provider",
        }:
            return
        self._reset_ai_test_result()
        if event.select.id == "ai-thinking" or not isinstance(event.value, str):
            return
        base_url_id = "#ai-base-url" if event.select.id == "ai-provider" else "#embedding-base-url"
        base_url = self.query_one(base_url_id, Input)
        if base_url.value in AI_PROVIDER_DEFAULT_URLS.values():
            base_url.value = AI_PROVIDER_DEFAULT_URLS[AiProvider(event.value)]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in self.AI_FIELD_IDS:
            self._reset_ai_test_result()
        elif event.input.id == "neo4j-password":
            self._update_neo4j_password_status(event.value)

    def _update_neo4j_password_status(self, draft: str) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#neo4j-password-status", Static)
        if draft:
            status.set_classes("pending")
            status.update("● New password will be saved securely")
        elif self.settings.neo4j.password:
            status.set_classes("saved")
            status.update("● Password saved in system credential vault")
        else:
            status.set_classes("not-saved")
            status.update("○ No saved password")

    def _save(self) -> None:
        try:
            settings = RavenSettings(
                storage=EvidenceStorageSettings(
                    root=self.query_one("#evidence-storage-root", Input).value,
                ),
                dictionaries=DictionarySettings(
                    root=self.query_one("#dictionary-root", Input).value,
                ),
                mongodb=MongoSettings(
                    uri=self.query_one("#mongo-uri", Input).value,
                    database=self.query_one("#mongo-database", Input).value,
                ),
                qdrant=QdrantSettings(
                    url=self.query_one("#qdrant-url", Input).value,
                    collection=self.query_one("#qdrant-collection", Input).value,
                    vector_size=int(self.query_one("#qdrant-vector-size", Input).value),
                ),
                neo4j=Neo4jSettings(
                    uri=self.query_one("#neo4j-uri", Input).value,
                    username=self.query_one("#neo4j-username", Input).value,
                    database=self.query_one("#neo4j-database", Input).value,
                    password=(
                        self.query_one("#neo4j-password", Input).value
                        or self.settings.neo4j.password
                    ),
                ),
                ai=self._draft_ai_settings(),
                interface_language=UiLanguage(self.query_one("#interface-language", Select).value),
                interface_density=str(self.query_one("#interface-density", Select).value),
            ).validated()
            self.query_one("#save-configuration", Button).disabled = True
            self._persist_settings(settings)
        except (ConfigurationError, ValueError) as error:
            self.notify(str(error), title="Invalid configuration", severity="error")

    @work(thread=True, exclusive=True, group="configuration-save", exit_on_error=False)
    def _persist_settings(self, settings: RavenSettings) -> None:
        try:
            self._raven_app.persist_configuration(settings)
        except Exception as error:
            self.app.call_from_thread(self._save_failed, str(error))
        else:
            self.app.call_from_thread(self._raven_app.configuration_saved, settings)

    def _save_failed(self, detail: str) -> None:
        if self.is_mounted:
            self.query_one("#save-configuration", Button).disabled = False
            self.notify(detail, title="Configuration not saved", severity="error")

    def _start_ai_node_test(self) -> None:
        try:
            settings = self._draft_ai_settings().validated()
        except (ConfigurationError, ValueError) as error:
            self.notify(str(error), title="Invalid AI configuration", severity="error")
            return
        self._set_ai_test_controls_disabled(True)
        result = self.query_one("#ai-test-result", Static)
        result.set_classes("checking")
        result.update("● Testing...")
        self._test_ai_node(settings)

    @work(thread=True, exclusive=True, group="ai-node-test", exit_on_error=False)
    def _test_ai_node(self, settings: AiNodeSettings) -> None:
        status = self._raven_app.test_ai_node(settings)
        self.app.call_from_thread(self._apply_ai_test_status, status)

    def _apply_ai_test_status(self, status: ServiceStatus) -> None:
        if not self.is_mounted:
            return
        labels = {
            ConnectionState.CONNECTED: "● Connected",
            ConnectionState.AUTHENTICATION_REQUIRED: "● Auth required",
            ConnectionState.CONFIGURATION_REQUIRED: (
                "● Embedding mismatch"
                if "dimension" in status.detail.lower()
                else "● Invalid model"
            ),
            ConnectionState.UNAVAILABLE: "● Unavailable",
            ConnectionState.CHECKING: "● Testing...",
        }
        self._set_ai_test_controls_disabled(False)
        result = self.query_one("#ai-test-result", Static)
        result.set_classes(status.state.value)
        result.update(labels[status.state])
        result.tooltip = status.detail

    def _reset_ai_test_result(self) -> None:
        if not self.is_mounted:
            return
        result = self.query_one("#ai-test-result", Static)
        result.set_classes("not-tested")
        result.update("● Not tested")
        result.tooltip = None

    def _set_ai_test_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#test-ai-node", Button).disabled = disabled
        self.query_one("#ai-provider", Select).disabled = disabled
        self.query_one("#ai-thinking", Select).disabled = disabled
        self.query_one("#embedding-provider", Select).disabled = disabled
        for field_id in self.AI_FIELD_IDS:
            self.query_one(f"#{field_id}", Input).disabled = disabled

    def _draft_ai_settings(self) -> AiNodeSettings:
        seed = self.query_one("#ai-random-seed", Input).value.strip()
        return AiNodeSettings(
            provider=AiProvider(cast(str, self.query_one("#ai-provider", Select).value)),
            base_url=self.query_one("#ai-base-url", Input).value,
            model=self.query_one("#ai-model", Input).value,
            api_key=self.query_one("#ai-api-key", Input).value or self.settings.ai.api_key,
            thinking=AiThinkingLevel(cast(str, self.query_one("#ai-thinking", Select).value)),
            top_k=int(self.query_one("#ai-top-k", Input).value),
            random_seed=int(seed) if seed else None,
            timeout_seconds=float(self.query_one("#ai-timeout-seconds", Input).value),
            context_size=int(self.query_one("#ai-context-size", Input).value),
            embedding_provider=AiProvider(
                cast(str, self.query_one("#embedding-provider", Select).value)
            ),
            embedding_base_url=self.query_one("#embedding-base-url", Input).value,
            embedding_model=self.query_one("#embedding-model", Input).value,
            embedding_api_key=(
                self.query_one("#embedding-api-key", Input).value
                or self.settings.ai.embedding_api_key
            ),
            embedding_timeout_seconds=float(
                self.query_one("#embedding-timeout-seconds", Input).value
            ),
        )

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
