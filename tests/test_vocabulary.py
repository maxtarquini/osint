"""Hudiny-compatible dictionary catalog behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from raven.config import DictionarySettings
from raven.exceptions import ConfigurationError
from raven.graph import NamedEntityVocabularyCatalog


def test_bundled_hudiny_dictionaries_resolve_general_osint() -> None:
    root = DictionarySettings().path
    catalog = NamedEntityVocabularyCatalog(root)

    snapshot = catalog.resolve()

    assert len(tuple(root.glob("*.json"))) == 11
    assert len(catalog.list_domains()) == 10
    assert snapshot.domain_code == "GENERAL_OSINT"
    assert snapshot.vocabulary_versions == ("CORE@2.0.0", "GENERAL_OSINT@1.0.0")
    assert len(snapshot.entity_types) == 41
    assert ("PERSON", None) in snapshot.allowed_classifications
    assert ("EMAIL_ADDRESS", None) in snapshot.allowed_classifications
    assert len(snapshot.sha256) == 64


def test_catalog_resolves_inheritance_and_specialized_subtypes(tmp_path: Path) -> None:
    core = {
        "schema_version": "1.0",
        "code": "CORE",
        "name": "Core",
        "description": "Core types",
        "version": "1.0.0",
        "selectable_domain": False,
        "extends": [],
        "entity_types": [
            {
                "code": "PERSON",
                "base_type": "PERSON",
                "label": "Person",
                "description": "A named person",
            }
        ],
    }
    domain = {
        "schema_version": "1.0",
        "code": "GENERAL_OSINT",
        "name": "General",
        "description": "General domain",
        "version": "1.1.0",
        "selectable_domain": True,
        "extends": ["CORE"],
        "entity_types": [
            {
                "code": "JOURNALIST",
                "base_type": "PERSON",
                "label": "Journalist",
                "description": "A person explicitly identified as a journalist",
                "exclude_when": ["The profession is inferred"],
            }
        ],
    }
    (tmp_path / "core.json").write_text(json.dumps(core), encoding="utf-8")
    (tmp_path / "general.json").write_text(json.dumps(domain), encoding="utf-8")

    snapshot = NamedEntityVocabularyCatalog(tmp_path).resolve()

    assert snapshot.allowed_classifications == frozenset(
        {("PERSON", None), ("PERSON", "JOURNALIST")}
    )
    assert '"subtype":"JOURNALIST"' in snapshot.json


def test_catalog_rejects_missing_inherited_dictionary(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "code": "GENERAL_OSINT",
        "name": "General",
        "description": "General domain",
        "version": "1.0.0",
        "selectable_domain": True,
        "extends": ["CORE"],
        "entity_types": [],
    }
    (tmp_path / "general.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="extends missing"):
        NamedEntityVocabularyCatalog(tmp_path)
