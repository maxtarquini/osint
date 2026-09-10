"""Presentation-only tabs for application configuration."""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, TabPane

from raven.config import AiProvider, AiThinkingLevel, RavenSettings


class ConfigurationPanel(TabPane):
    """Base class used to target every configuration tab consistently in TCSS."""


class StoragePanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("Storage", id="storage-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
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


class DictionariesPanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("Dictionaries", id="dictionaries-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
            yield Label("OSINT dictionary directory")
            with Horizontal(id="dictionary-root-row"):
                yield Input(value=self.settings.dictionaries.root, id="dictionary-root")
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


class CapabilitiesPanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("Skills & Tools", id="capabilities-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
            yield Label("Skill folder · Markdown files with .SKILL extension")
            yield Input(value=self.settings.skills.root, id="skill-root")
            yield Button("Browse folder", id="browse-skill-root")
            yield Static(
                "Save configuration to apply this folder. RAVEN_SKILL_ROOT overrides it. "
                "Existing files are not moved. The catalog is stored beside the skills.",
                classes="config-field-hint",
            )
            yield Button("Manage skills & tools", id="manage-capabilities", variant="primary")
            yield Static(
                "Consult and edit skills, inspect tool contracts and build the AI catalog. "
                "This registry prepares future orchestration; existing investigations use "
                "their current pipeline.",
                classes="config-field-hint",
            )


class MongoPanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("MongoDB", id="mongodb-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
            yield Label("URI")
            yield Input(value=self.settings.mongodb.uri, id="mongo-uri")
            yield Label("Database")
            yield Input(value=self.settings.mongodb.database, id="mongo-database")


class QdrantPanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("Qdrant", id="qdrant-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
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


class Neo4jPanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("Neo4j", id="neo4j-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
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


class AiPanel(ConfigurationPanel):
    def __init__(self, settings: RavenSettings) -> None:
        super().__init__("AI Node", id="ai-tab")
        self.settings = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="config-form"):
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
                    yield Input(value=str(self.settings.ai.top_k), id="ai-top-k", type="integer")
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
            yield Static("EMBEDDING ENDPOINT · INVESTIGATION RAG", classes="config-section-title")
            yield Label("Embedding provider")
            yield Select(
                [(provider.value, provider.value) for provider in AiProvider],
                value=self.settings.ai.embedding_provider.value,
                allow_blank=False,
                id="embedding-provider",
            )
            yield Label("Embedding API base URL")
            yield Input(value=self.settings.ai.embedding_base_url, id="embedding-base-url")
            yield Label("Embedding model")
            yield Input(
                value=self.settings.ai.embedding_model,
                id="embedding-model",
                placeholder="e.g. nomic-embed-text or text-embedding-3-small",
            )
            yield Label("Embedding API key (session only)")
            yield Input(id="embedding-api-key", password=True, placeholder="Not saved to disk")
            yield Label("Embedding timeout · seconds")
            yield Input(
                value=str(self.settings.ai.embedding_timeout_seconds),
                id="embedding-timeout-seconds",
                type="number",
            )


def configuration_panels(settings: RavenSettings) -> Iterable[ConfigurationPanel]:
    return (
        StoragePanel(settings),
        DictionariesPanel(settings),
        CapabilitiesPanel(settings),
        MongoPanel(settings),
        QdrantPanel(settings),
        Neo4jPanel(settings),
        AiPanel(settings),
    )
