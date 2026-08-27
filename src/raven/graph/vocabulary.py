"""Hudiny-compatible OSINT named-entity vocabulary catalog."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raven.exceptions import ConfigurationError

DEFAULT_DOMAIN_CODE = "GENERAL_OSINT"
SUPPORTED_SCHEMA_VERSION = "1.0"
MAX_FILES = 64
MAX_FILE_BYTES = 262_144
MAX_ENTITY_TYPES = 256
MAX_TEXT_LENGTH = 500
_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
_DEFINITION_KEYS = {
    "schema_version",
    "code",
    "name",
    "description",
    "version",
    "selectable_domain",
    "extends",
    "entity_types",
}
_ENTITY_KEYS = {
    "code",
    "base_type",
    "label",
    "description",
    "include_when",
    "exclude_when",
    "examples",
}


@dataclass(frozen=True, slots=True)
class VocabularyEntityType:
    """One allowed base type/subtype pair and its extraction guidance."""

    code: str
    base_type: str
    label: str
    description: str
    include_when: tuple[str, ...] = ()
    exclude_when: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()

    @property
    def subtype(self) -> str | None:
        return None if self.code == self.base_type else self.code

    def prompt_dict(self) -> dict[str, Any]:
        return {
            "type": self.base_type,
            "subtype": self.subtype,
            "label": self.label,
            "description": self.description,
            "include_when": list(self.include_when),
            "exclude_when": list(self.exclude_when),
            "examples": list(self.examples),
        }


@dataclass(frozen=True, slots=True)
class VocabularyDefinition:
    code: str
    name: str
    description: str
    version: str
    selectable_domain: bool
    extends: tuple[str, ...]
    entity_types: tuple[VocabularyEntityType, ...]


@dataclass(frozen=True, slots=True)
class ResolvedVocabulary:
    """Immutable prompt snapshot resolved from one selectable domain."""

    domain_code: str
    domain_name: str
    domain_description: str
    vocabulary_versions: tuple[str, ...]
    entity_types: tuple[VocabularyEntityType, ...]
    json: str
    sha256: str

    @property
    def allowed_classifications(self) -> frozenset[tuple[str, str | None]]:
        return frozenset((item.base_type, item.subtype) for item in self.entity_types)


class NamedEntityVocabularyCatalog:
    """Load, validate and resolve Hudiny JSON vocabularies from one folder."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._definitions = self._load_definitions()

    def list_domains(self) -> tuple[VocabularyDefinition, ...]:
        return tuple(
            sorted(
                (item for item in self._definitions.values() if item.selectable_domain),
                key=lambda item: (item.name.casefold(), item.code),
            )
        )

    def resolve(self, domain_code: str = DEFAULT_DOMAIN_CODE) -> ResolvedVocabulary:
        normalized = domain_code.strip().upper()
        domain = self._definitions.get(normalized)
        if domain is None or not domain.selectable_domain:
            raise ConfigurationError(f"Unsupported dictionary domain: {normalized}")
        ordered: dict[str, VocabularyDefinition] = {}
        self._collect(domain, set(), ordered)
        entity_types: dict[str, VocabularyEntityType] = {}
        for definition in ordered.values():
            for item in definition.entity_types:
                previous = entity_types.setdefault(item.code, item)
                if previous != item:
                    raise ConfigurationError(
                        f"Conflicting entity type {item.code} in dictionary {definition.code}"
                    )
                if len(entity_types) > MAX_ENTITY_TYPES:
                    raise ConfigurationError(
                        f"Resolved dictionary exceeds {MAX_ENTITY_TYPES} entity types"
                    )
        if not entity_types:
            raise ConfigurationError(f"Dictionary domain {domain.code} has no entity types")
        versions = tuple(f"{item.code}@{item.version}" for item in ordered.values())
        snapshot = {
            "domain_code": domain.code,
            "domain_name": domain.name,
            "domain_description": domain.description,
            "vocabulary_versions": list(versions),
            "entity_types": [item.prompt_dict() for item in entity_types.values()],
        }
        serialized = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        return ResolvedVocabulary(
            domain_code=domain.code,
            domain_name=domain.name,
            domain_description=domain.description,
            vocabulary_versions=versions,
            entity_types=tuple(entity_types.values()),
            json=serialized,
            sha256=hashlib.sha256(serialized.encode()).hexdigest(),
        )

    def _load_definitions(self) -> dict[str, VocabularyDefinition]:
        if not self.root.is_dir():
            raise ConfigurationError("Dictionary folder is not available")
        files = sorted(self.root.glob("*.json"))
        if not files:
            raise ConfigurationError("Dictionary folder contains no JSON vocabularies")
        if len(files) > MAX_FILES:
            raise ConfigurationError(f"Dictionary folder contains more than {MAX_FILES} files")
        definitions: dict[str, VocabularyDefinition] = {}
        for path in files:
            definition = self._load_definition(path)
            if definition.code in definitions:
                raise ConfigurationError(f"Duplicate dictionary code {definition.code}")
            definitions[definition.code] = definition
        for definition in definitions.values():
            for parent in definition.extends:
                if parent not in definitions:
                    raise ConfigurationError(
                        f"Dictionary {definition.code} extends missing dictionary {parent}"
                    )
        return definitions

    def _load_definition(self, path: Path) -> VocabularyDefinition:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ConfigurationError(f"Dictionary exceeds 256 KiB: {path.name}")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"Unable to read dictionary {path.name}") from error
        if not isinstance(payload, dict) or set(payload) - _DEFINITION_KEYS:
            raise ConfigurationError(f"Dictionary {path.name} has an invalid structure")
        if payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise ConfigurationError(
                f"Dictionary {path.name} must use schema_version {SUPPORTED_SCHEMA_VERSION}"
            )
        code = self._required_code(payload.get("code"), "dictionary code", path.name)
        version = self._required_text(payload.get("version"), "version", path.name)
        if not _VERSION.fullmatch(version):
            raise ConfigurationError(f"Dictionary {path.name} has an invalid semantic version")
        extends = self._string_list(payload.get("extends", []), "extends", path.name, codes=True)
        raw_types = payload.get("entity_types", [])
        if not isinstance(raw_types, list):
            raise ConfigurationError(f"Dictionary {path.name} has invalid entity_types")
        entity_types = tuple(self._entity_type(value, path.name) for value in raw_types)
        return VocabularyDefinition(
            code=code,
            name=self._required_text(payload.get("name"), "name", path.name),
            description=self._required_text(payload.get("description"), "description", path.name),
            version=version,
            selectable_domain=payload.get("selectable_domain") is True,
            extends=extends,
            entity_types=entity_types,
        )

    def _entity_type(self, value: Any, source: str) -> VocabularyEntityType:
        if not isinstance(value, dict) or set(value) - _ENTITY_KEYS:
            raise ConfigurationError(f"Dictionary {source} contains an invalid entity type")
        code = self._required_code(value.get("code"), "entity type code", source)
        return VocabularyEntityType(
            code=code,
            base_type=self._required_code(value.get("base_type"), "base type", source),
            label=self._required_text(value.get("label"), "entity label", source),
            description=self._required_text(value.get("description"), "entity description", source),
            include_when=self._string_list(value.get("include_when", []), "include_when", source),
            exclude_when=self._string_list(value.get("exclude_when", []), "exclude_when", source),
            examples=self._string_list(value.get("examples", []), "examples", source),
        )

    def _collect(
        self,
        definition: VocabularyDefinition,
        visiting: set[str],
        ordered: dict[str, VocabularyDefinition],
    ) -> None:
        if definition.code in ordered:
            return
        if definition.code in visiting:
            raise ConfigurationError(f"Dictionary inheritance cycle at {definition.code}")
        visiting.add(definition.code)
        for parent_code in definition.extends:
            self._collect(self._definitions[parent_code], visiting, ordered)
        visiting.remove(definition.code)
        ordered[definition.code] = definition

    @staticmethod
    def _required_code(value: Any, field: str, source: str) -> str:
        normalized = str(value or "").strip().upper()
        if not _CODE.fullmatch(normalized):
            raise ConfigurationError(f"Dictionary {source} has an invalid {field}")
        return normalized

    @staticmethod
    def _required_text(value: Any, field: str, source: str) -> str:
        text = str(value or "").strip()
        if (
            not text
            or len(text) > MAX_TEXT_LENGTH
            or any(ord(character) < 32 and character not in "\n\r\t" for character in text)
        ):
            raise ConfigurationError(f"Dictionary {source} has an invalid {field}")
        return text

    @classmethod
    def _string_list(
        cls,
        value: Any,
        field: str,
        source: str,
        *,
        codes: bool = False,
    ) -> tuple[str, ...]:
        if not isinstance(value, list) or len(value) > 16:
            raise ConfigurationError(f"Dictionary {source} has an invalid {field}")
        if codes:
            return tuple(cls._required_code(item, field, source) for item in value)
        return tuple(cls._required_text(item, field, source) for item in value)
