"""Infrastructure, storage, and secure credential configuration screen."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static, TabbedContent

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
    SkillSettings,
)
from raven.exceptions import ConfigurationError
from raven.models import ConnectionState, ServiceStatus
from raven.tui.screens.file_picker import EvidenceStorageDirectoryPicker
from raven.tui.widgets import TopNavigation
from raven.tui.widgets.configuration import configuration_panels

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
        Binding("question_mark", "app.context_help", "Help"),
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
            yield from configuration_panels(self.settings)
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
        elif event.button.id == "manage-capabilities":
            self._raven_app.navigate("capabilities")
        elif event.button.id == "browse-skill-root":
            value = Path(self.query_one("#skill-root", Input).value).expanduser()
            self.app.push_screen(
                EvidenceStorageDirectoryPicker(value if value.is_dir() else Path.home()),
                self._skill_directory_selected,
            )
        elif event.button.id == "cancel-configuration":
            self._raven_app.navigate("home")

    def _skill_directory_selected(self, path: Path | None) -> None:
        if path is not None:
            self.query_one("#skill-root", Input).value = str(path)

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
                skills=SkillSettings(root=self.query_one("#skill-root", Input).value),
                ai=self._draft_ai_settings(),
            ).validated()
            self._raven_app.save_configuration(settings)
        except (ConfigurationError, ValueError) as error:
            self.notify(str(error), title="Invalid configuration", severity="error")

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
            ConnectionState.CONFIGURATION_REQUIRED: "● Invalid model",
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
