"""Validated, typed configuration for Raven infrastructure."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from platformdirs import user_data_path

from raven.exceptions import ConfigurationError

_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,62}$")


def _require_url(value: str, schemes: set[str], label: str, *, allow_credentials: bool) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in schemes or not parsed.hostname:
        allowed = ", ".join(sorted(schemes))
        raise ConfigurationError(f"{label} must use one of these schemes: {allowed}")
    if not allow_credentials and (parsed.username or parsed.password):
        raise ConfigurationError(
            f"{label} credentials must be provided through environment variables"
        )
    return value.rstrip("/")


def _require_name(value: str, label: str) -> str:
    value = value.strip()
    if not _SAFE_NAME.fullmatch(value):
        raise ConfigurationError(
            f"{label} must start with a letter and contain only letters, numbers, _ or -"
        )
    return value


def _optional_int(value: Any, label: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{label} must be an integer or empty") from error


def _default_evidence_root() -> str:
    return str(user_data_path("raven", appauthor=False) / "knowledge_bases")


def _default_dictionary_root() -> str:
    source_copy = Path(__file__).resolve().parents[3] / "config" / "osint-vocabularies"
    packaged_copy = Path(__file__).resolve().parents[1] / "resources" / "dictionaries"
    return str(source_copy if source_copy.is_dir() else packaged_copy)


@dataclass(frozen=True, slots=True)
class EvidenceStorageSettings:
    """Local root containing one immutable Evidence directory per investigation."""

    root: str = field(default_factory=_default_evidence_root)

    @property
    def path(self) -> Path:
        return Path(self.root).expanduser().resolve()

    def validated(self) -> EvidenceStorageSettings:
        value = self.root.strip()
        if not value:
            raise ConfigurationError("Evidence storage directory cannot be empty")
        try:
            path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError) as error:
            raise ConfigurationError("Evidence storage directory is invalid") from error
        if path.exists() and not path.is_dir():
            raise ConfigurationError("Evidence storage path must be a directory")
        return EvidenceStorageSettings(root=str(path))


@dataclass(frozen=True, slots=True)
class DictionarySettings:
    """Folder containing Hudiny-compatible OSINT vocabulary JSON files."""

    root: str = field(default_factory=_default_dictionary_root)

    @property
    def path(self) -> Path:
        return Path(self.root).expanduser().resolve()

    def validated(self) -> DictionarySettings:
        value = self.root.strip()
        if not value:
            raise ConfigurationError("Dictionary folder cannot be empty")
        try:
            path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError) as error:
            raise ConfigurationError("Dictionary folder is invalid") from error
        if not path.is_dir():
            raise ConfigurationError("Dictionary path must be an existing directory")
        if not any(path.glob("*.json")):
            raise ConfigurationError("Dictionary folder must contain at least one JSON file")
        return DictionarySettings(root=str(path))


@dataclass(frozen=True, slots=True)
class MongoSettings:
    """MongoDB endpoint and Raven database name."""

    uri: str = "mongodb://localhost:27017"
    database: str = "raven"

    def validated(self, *, allow_credentials: bool = False) -> MongoSettings:
        return MongoSettings(
            uri=_require_url(
                self.uri,
                {"mongodb", "mongodb+srv"},
                "MongoDB URI",
                allow_credentials=allow_credentials,
            ),
            database=_require_name(self.database, "MongoDB database"),
        )


@dataclass(frozen=True, slots=True)
class QdrantSettings:
    """Qdrant endpoint and initial dense-vector collection."""

    url: str = "http://localhost:6333"
    collection: str = "raven_documents"
    vector_size: int = 1536
    api_key: str | None = field(default=None, repr=False, compare=False)

    def validated(self) -> QdrantSettings:
        if not 1 <= self.vector_size <= 65536:
            raise ConfigurationError("Qdrant vector size must be between 1 and 65536")
        return QdrantSettings(
            url=_require_url(
                self.url,
                {"http", "https"},
                "Qdrant URL",
                allow_credentials=False,
            ),
            collection=_require_name(self.collection, "Qdrant collection"),
            vector_size=self.vector_size,
            api_key=self.api_key,
        )


@dataclass(frozen=True, slots=True)
class Neo4jSettings:
    """Neo4j endpoint, login name, and logical database."""

    uri: str = "neo4j://localhost:7687"
    username: str = "neo4j"
    database: str = "neo4j"
    password: str | None = field(default=None, repr=False, compare=False)

    def validated(self) -> Neo4jSettings:
        username = self.username.strip()
        if not username:
            raise ConfigurationError("Neo4j username cannot be empty")
        return Neo4jSettings(
            uri=_require_url(
                self.uri,
                {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"},
                "Neo4j URI",
                allow_credentials=False,
            ),
            username=username,
            database=_require_name(self.database, "Neo4j database"),
            password=self.password,
        )


class AiProvider(StrEnum):
    """Supported backends for inference and embedding endpoints."""

    VLLM = "vllm"
    LLAMA_CPP = "llama.cpp"
    OLLAMA = "ollama"
    OPENAI = "openai"


class AiThinkingLevel(StrEnum):
    """Provider-neutral reasoning effort for inference models."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


AI_PROVIDER_DEFAULT_URLS = {
    AiProvider.VLLM: "http://localhost:8000/v1",
    AiProvider.LLAMA_CPP: "http://localhost:8080/v1",
    AiProvider.OLLAMA: "http://localhost:11434",
    AiProvider.OPENAI: "https://api.openai.com/v1",
}


def _require_ai_provider(value: AiProvider | str) -> AiProvider:
    try:
        return AiProvider(value)
    except ValueError as error:
        supported = ", ".join(provider.value for provider in AiProvider)
        raise ConfigurationError(f"AI provider must be one of: {supported}") from error


def _require_thinking_level(value: AiThinkingLevel | str) -> AiThinkingLevel:
    try:
        return AiThinkingLevel(value)
    except ValueError as error:
        raise ConfigurationError("Thinking level must be low, medium or high") from error


@dataclass(frozen=True, slots=True)
class AiNodeSettings:
    """Independent inference and embedding endpoints plus generation controls."""

    provider: AiProvider = AiProvider.OLLAMA
    base_url: str = AI_PROVIDER_DEFAULT_URLS[AiProvider.OLLAMA]
    model: str = ""
    api_key: str | None = field(default=None, repr=False, compare=False)
    thinking: AiThinkingLevel = AiThinkingLevel.MEDIUM
    top_k: int = 40
    random_seed: int | None = None
    timeout_seconds: float = 120.0
    context_size: int = 32768
    embedding_provider: AiProvider = AiProvider.OLLAMA
    embedding_base_url: str = AI_PROVIDER_DEFAULT_URLS[AiProvider.OLLAMA]
    embedding_model: str = ""
    embedding_api_key: str | None = field(default=None, repr=False, compare=False)
    embedding_timeout_seconds: float = 120.0

    def validated(self) -> AiNodeSettings:
        provider = _require_ai_provider(self.provider)
        embedding_provider = _require_ai_provider(self.embedding_provider)
        if not 0 <= self.top_k <= 10000:
            raise ConfigurationError("Top K must be between 0 and 10000")
        if self.random_seed is not None and not 0 <= self.random_seed <= 4294967295:
            raise ConfigurationError("Random seed must be between 0 and 4294967295")
        if not 1 <= self.timeout_seconds <= 3600:
            raise ConfigurationError("Inference timeout must be between 1 and 3600 seconds")
        if not 512 <= self.context_size <= 1048576:
            raise ConfigurationError("Context size must be between 512 and 1048576 tokens")
        if not 1 <= self.embedding_timeout_seconds <= 3600:
            raise ConfigurationError("Embedding timeout must be between 1 and 3600 seconds")
        return AiNodeSettings(
            provider=provider,
            base_url=_require_url(
                self.base_url,
                {"http", "https"},
                "AI node base URL",
                allow_credentials=False,
            ),
            model=self.model.strip(),
            api_key=self.api_key,
            thinking=_require_thinking_level(self.thinking),
            top_k=self.top_k,
            random_seed=self.random_seed,
            timeout_seconds=float(self.timeout_seconds),
            context_size=self.context_size,
            embedding_provider=embedding_provider,
            embedding_base_url=_require_url(
                self.embedding_base_url,
                {"http", "https"},
                "Embedding API base URL",
                allow_credentials=False,
            ),
            embedding_model=self.embedding_model.strip(),
            embedding_api_key=self.embedding_api_key,
            embedding_timeout_seconds=float(self.embedding_timeout_seconds),
        )


@dataclass(frozen=True, slots=True)
class RavenSettings:
    """Complete application settings with secrets loaded only from the environment."""

    storage: EvidenceStorageSettings = field(default_factory=EvidenceStorageSettings)
    dictionaries: DictionarySettings = field(default_factory=DictionarySettings)
    mongodb: MongoSettings = field(default_factory=MongoSettings)
    qdrant: QdrantSettings = field(default_factory=QdrantSettings)
    neo4j: Neo4jSettings = field(default_factory=Neo4jSettings)
    ai: AiNodeSettings = field(default_factory=AiNodeSettings)

    def validated(self) -> RavenSettings:
        return RavenSettings(
            storage=self.storage.validated(),
            dictionaries=self.dictionaries.validated(),
            mongodb=self.mongodb.validated(allow_credentials=False),
            qdrant=self.qdrant.validated(),
            neo4j=self.neo4j.validated(),
            ai=self.ai.validated(),
        )

    def with_environment(self, environ: dict[str, str] | None = None) -> RavenSettings:
        env = os.environ if environ is None else environ
        mongodb_uri = env.get("RAVEN_MONGODB_URI", self.mongodb.uri)
        return RavenSettings(
            storage=EvidenceStorageSettings(
                root=env.get("RAVEN_EVIDENCE_ROOT", self.storage.root)
            ).validated(),
            dictionaries=DictionarySettings(
                root=env.get("RAVEN_DICTIONARY_ROOT", self.dictionaries.root)
            ).validated(),
            mongodb=MongoSettings(uri=mongodb_uri, database=self.mongodb.database).validated(
                allow_credentials=True
            ),
            qdrant=QdrantSettings(
                url=env.get("RAVEN_QDRANT_URL", self.qdrant.url),
                collection=self.qdrant.collection,
                vector_size=self.qdrant.vector_size,
                api_key=env.get("RAVEN_QDRANT_API_KEY", self.qdrant.api_key),
            ).validated(),
            neo4j=Neo4jSettings(
                uri=env.get("RAVEN_NEO4J_URI", self.neo4j.uri),
                username=env.get("RAVEN_NEO4J_USERNAME", self.neo4j.username),
                database=self.neo4j.database,
                password=env.get("RAVEN_NEO4J_PASSWORD", self.neo4j.password),
            ).validated(),
            ai=AiNodeSettings(
                provider=_require_ai_provider(env.get("RAVEN_AI_PROVIDER", self.ai.provider.value)),
                base_url=env.get("RAVEN_AI_BASE_URL", self.ai.base_url),
                model=env.get("RAVEN_AI_MODEL", self.ai.model),
                api_key=env.get("RAVEN_AI_API_KEY", self.ai.api_key),
                thinking=_require_thinking_level(
                    env.get("RAVEN_AI_THINKING", self.ai.thinking.value)
                ),
                top_k=int(env.get("RAVEN_AI_TOP_K", self.ai.top_k)),
                random_seed=_optional_int(
                    env.get("RAVEN_AI_RANDOM_SEED", self.ai.random_seed),
                    "Random seed",
                ),
                timeout_seconds=float(env.get("RAVEN_AI_TIMEOUT_SECONDS", self.ai.timeout_seconds)),
                context_size=int(env.get("RAVEN_AI_CONTEXT_SIZE", self.ai.context_size)),
                embedding_provider=_require_ai_provider(
                    env.get(
                        "RAVEN_EMBEDDING_PROVIDER",
                        self.ai.embedding_provider.value,
                    )
                ),
                embedding_base_url=env.get(
                    "RAVEN_EMBEDDING_BASE_URL",
                    self.ai.embedding_base_url,
                ),
                embedding_model=env.get(
                    "RAVEN_EMBEDDING_MODEL",
                    env.get("RAVEN_AI_EMBEDDING_MODEL", self.ai.embedding_model),
                ),
                embedding_api_key=env.get(
                    "RAVEN_EMBEDDING_API_KEY",
                    self.ai.embedding_api_key,
                ),
                embedding_timeout_seconds=float(
                    env.get(
                        "RAVEN_EMBEDDING_TIMEOUT_SECONDS",
                        self.ai.embedding_timeout_seconds,
                    )
                ),
            ).validated(),
        )

    def to_public_dict(self) -> dict[str, dict[str, Any]]:
        """Return only values safe to persist on disk."""
        return {
            "storage": {"root": self.storage.root},
            "dictionaries": {"root": self.dictionaries.root},
            "mongodb": {"uri": self.mongodb.uri, "database": self.mongodb.database},
            "qdrant": {
                "url": self.qdrant.url,
                "collection": self.qdrant.collection,
                "vector_size": self.qdrant.vector_size,
            },
            "neo4j": {
                "uri": self.neo4j.uri,
                "username": self.neo4j.username,
                "database": self.neo4j.database,
            },
            "ai": {
                "provider": self.ai.provider.value,
                "base_url": self.ai.base_url,
                "model": self.ai.model,
                "thinking": self.ai.thinking.value,
                "top_k": self.ai.top_k,
                "random_seed": self.ai.random_seed,
                "timeout_seconds": self.ai.timeout_seconds,
                "context_size": self.ai.context_size,
                "embedding_provider": self.ai.embedding_provider.value,
                "embedding_base_url": self.ai.embedding_base_url,
                "embedding_model": self.ai.embedding_model,
                "embedding_timeout_seconds": self.ai.embedding_timeout_seconds,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RavenSettings:
        defaults = cls()
        try:
            mongodb = data.get("mongodb", {})
            storage = data.get("storage", {})
            dictionaries = data.get("dictionaries", {})
            qdrant = data.get("qdrant", {})
            neo4j = data.get("neo4j", {})
            ai = data.get("ai", {})
            ai_provider = AiProvider(ai.get("provider", defaults.ai.provider.value))
            ai_base_url = str(ai.get("base_url", defaults.ai.base_url))
            settings = cls(
                storage=EvidenceStorageSettings(
                    root=str(storage.get("root", defaults.storage.root)),
                ),
                dictionaries=DictionarySettings(
                    root=str(dictionaries.get("root", defaults.dictionaries.root)),
                ),
                mongodb=MongoSettings(
                    uri=str(mongodb.get("uri", defaults.mongodb.uri)),
                    database=str(mongodb.get("database", defaults.mongodb.database)),
                ),
                qdrant=QdrantSettings(
                    url=str(qdrant.get("url", defaults.qdrant.url)),
                    collection=str(qdrant.get("collection", defaults.qdrant.collection)),
                    vector_size=int(qdrant.get("vector_size", defaults.qdrant.vector_size)),
                ),
                neo4j=Neo4jSettings(
                    uri=str(neo4j.get("uri", defaults.neo4j.uri)),
                    username=str(neo4j.get("username", defaults.neo4j.username)),
                    database=str(neo4j.get("database", defaults.neo4j.database)),
                ),
                ai=AiNodeSettings(
                    provider=ai_provider,
                    base_url=ai_base_url,
                    model=str(ai.get("model", defaults.ai.model)),
                    thinking=AiThinkingLevel(ai.get("thinking", defaults.ai.thinking.value)),
                    top_k=int(ai.get("top_k", defaults.ai.top_k)),
                    random_seed=_optional_int(
                        ai.get("random_seed", defaults.ai.random_seed),
                        "Random seed",
                    ),
                    timeout_seconds=float(ai.get("timeout_seconds", defaults.ai.timeout_seconds)),
                    context_size=int(ai.get("context_size", defaults.ai.context_size)),
                    embedding_provider=AiProvider(ai.get("embedding_provider", ai_provider.value)),
                    embedding_base_url=str(ai.get("embedding_base_url", ai_base_url)),
                    embedding_model=str(ai.get("embedding_model", defaults.ai.embedding_model)),
                    embedding_timeout_seconds=float(
                        ai.get(
                            "embedding_timeout_seconds",
                            defaults.ai.embedding_timeout_seconds,
                        )
                    ),
                ),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ConfigurationError("Configuration file has an invalid structure") from error
        return settings.validated()
