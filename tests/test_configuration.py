"""Tests for typed configuration validation and secret-safe persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from raven.config import (
    AiNodeSettings,
    AiProvider,
    AiThinkingLevel,
    ConfigurationStore,
    DictionarySettings,
    EvidenceStorageSettings,
    InMemoryCredentialStore,
    MongoSettings,
    Neo4jSettings,
    RavenSettings,
)
from raven.exceptions import ConfigurationError


def test_store_round_trip_never_persists_environment_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "raven" / "config.json"
    credential_store = InMemoryCredentialStore()
    store = ConfigurationStore(path, credential_store)
    settings = RavenSettings(
        mongodb=MongoSettings(database="casefiles"),
        neo4j=Neo4jSettings(password="vault-secret"),
    )
    monkeypatch.setenv("RAVEN_MONGODB_URI", "mongodb://agent:secret@localhost:27017")
    monkeypatch.setenv("RAVEN_QDRANT_API_KEY", "qdrant-secret")
    monkeypatch.setenv("RAVEN_NEO4J_PASSWORD", "neo4j-secret")
    monkeypatch.setenv("RAVEN_AI_API_KEY", "ai-secret")
    monkeypatch.setenv("RAVEN_EMBEDDING_API_KEY", "embedding-secret")

    store.save(settings)
    public = store.load()
    effective = public.with_environment()
    payload = path.read_text(encoding="utf-8")

    assert public.mongodb.uri == "mongodb://localhost:27017"
    assert public.neo4j.password == "vault-secret"
    assert effective.mongodb.uri == "mongodb://agent:secret@localhost:27017"
    assert effective.qdrant.api_key == "qdrant-secret"
    assert effective.neo4j.password == "neo4j-secret"
    assert effective.ai.api_key == "ai-secret"
    assert effective.ai.embedding_api_key == "embedding-secret"
    assert "secret" not in payload
    assert credential_store.get(ConfigurationStore.NEO4J_PASSWORD_ACCOUNT) == "vault-secret"
    assert json.loads(payload)["mongodb"]["database"] == "casefiles"


def test_ai_settings_round_trip_and_environment_overrides() -> None:
    settings = RavenSettings(
        ai=AiNodeSettings(
            provider=AiProvider.VLLM,
            base_url="http://inference.local:8000/v1",
            model="raven-model",
            thinking=AiThinkingLevel.HIGH,
            top_k=25,
            random_seed=7,
            timeout_seconds=90,
            context_size=65536,
            embedding_provider=AiProvider.OPENAI,
            embedding_base_url="https://api.openai.com/v1",
            embedding_model="raven-embed",
            embedding_timeout_seconds=45,
        )
    )
    restored = RavenSettings.from_dict(settings.to_public_dict())
    effective = restored.with_environment(
        {
            "RAVEN_AI_PROVIDER": "openai",
            "RAVEN_AI_BASE_URL": "https://api.openai.com/v1",
            "RAVEN_AI_MODEL": "gpt-5.4-mini",
            "RAVEN_AI_THINKING": "low",
            "RAVEN_AI_TOP_K": "12",
            "RAVEN_AI_RANDOM_SEED": "99",
            "RAVEN_AI_TIMEOUT_SECONDS": "60",
            "RAVEN_AI_CONTEXT_SIZE": "131072",
            "RAVEN_AI_API_KEY": "secret",
            "RAVEN_EMBEDDING_PROVIDER": "vllm",
            "RAVEN_EMBEDDING_BASE_URL": "http://embed.local:8001/v1",
            "RAVEN_EMBEDDING_MODEL": "text-embedding-3-small",
            "RAVEN_EMBEDDING_API_KEY": "embed-secret",
            "RAVEN_EMBEDDING_TIMEOUT_SECONDS": "30",
        }
    )

    assert restored.ai == settings.ai
    assert effective.ai.provider is AiProvider.OPENAI
    assert effective.ai.model == "gpt-5.4-mini"
    assert effective.ai.thinking is AiThinkingLevel.LOW
    assert effective.ai.top_k == 12
    assert effective.ai.random_seed == 99
    assert effective.ai.timeout_seconds == 60
    assert effective.ai.context_size == 131072
    assert restored.ai.embedding_model == "raven-embed"
    assert restored.ai.embedding_provider is AiProvider.OPENAI
    assert effective.ai.embedding_provider is AiProvider.VLLM
    assert effective.ai.embedding_model == "text-embedding-3-small"
    assert effective.ai.api_key == "secret"
    assert effective.ai.embedding_api_key == "embed-secret"
    assert effective.ai.embedding_timeout_seconds == 30
    assert "api_key" not in settings.to_public_dict()["ai"]
    assert "embedding_api_key" not in settings.to_public_dict()["ai"]


def test_legacy_shared_embedding_endpoint_is_migrated() -> None:
    settings = RavenSettings.from_dict(
        {
            "ai": {
                "provider": "vllm",
                "base_url": "http://models.local:8000/v1",
                "model": "chat-model",
                "embedding_model": "embed-model",
            }
        }
    )

    assert settings.ai.embedding_provider is AiProvider.VLLM
    assert settings.ai.embedding_base_url == "http://models.local:8000/v1"
    assert settings.ai.embedding_model == "embed-model"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("top_k", 10001, "Top K"),
        ("random_seed", -1, "Random seed"),
        ("timeout_seconds", 0, "Inference timeout"),
        ("context_size", 128, "Context size"),
        ("embedding_timeout_seconds", 0, "Embedding timeout"),
    ],
)
def test_ai_generation_controls_are_validated(field: str, value, message: str) -> None:
    settings = AiNodeSettings(**{field: value})

    with pytest.raises(ConfigurationError, match=message):
        settings.validated()


def test_evidence_storage_round_trip_and_environment_override(tmp_path: Path) -> None:
    configured_root = tmp_path / "configured-evidence"
    environment_root = tmp_path / "environment-evidence"
    settings = RavenSettings(storage=EvidenceStorageSettings(root=str(configured_root)))

    restored = RavenSettings.from_dict(settings.to_public_dict())
    effective = restored.with_environment({"RAVEN_EVIDENCE_ROOT": str(environment_root)})

    assert restored.storage.path == configured_root
    assert effective.storage.path == environment_root
    assert settings.to_public_dict()["storage"]["root"] == str(configured_root)


def test_evidence_storage_rejects_a_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("file")

    with pytest.raises(ConfigurationError, match="must be a directory"):
        EvidenceStorageSettings(root=str(file_path)).validated()


def test_dictionary_settings_round_trip_and_environment_override(tmp_path: Path) -> None:
    configured = DictionarySettings().path
    environment = tmp_path / "custom-dictionaries"
    environment.mkdir()
    (environment / "domain.json").write_text("{}", encoding="utf-8")
    settings = RavenSettings(dictionaries=DictionarySettings(root=str(configured)))

    restored = RavenSettings.from_dict(settings.to_public_dict())
    effective = restored.with_environment({"RAVEN_DICTIONARY_ROOT": str(environment)})

    assert restored.dictionaries.path == configured
    assert effective.dictionaries.path == environment
    assert settings.to_public_dict()["dictionaries"]["root"] == str(configured)


def test_dictionary_settings_require_json_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="at least one JSON"):
        DictionarySettings(root=str(tmp_path)).validated()


def test_invalid_public_uri_with_credentials_is_rejected() -> None:
    settings = RavenSettings(mongodb=MongoSettings(uri="mongodb://agent:secret@localhost:27017"))

    with pytest.raises(ConfigurationError, match="environment variables"):
        settings.validated()


def test_invalid_vector_size_is_rejected() -> None:
    data = RavenSettings().to_public_dict()
    data["qdrant"]["vector_size"] = 0

    with pytest.raises(ConfigurationError, match="vector size"):
        RavenSettings.from_dict(data)


def test_invalid_ai_provider_environment_value_is_rejected_safely() -> None:
    with pytest.raises(ConfigurationError, match="AI provider"):
        RavenSettings().with_environment({"RAVEN_AI_PROVIDER": "unknown"})
