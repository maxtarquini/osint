"""Hudiny-derived preprocessing, extraction, grounding, and consolidation pipeline."""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import replace
from difflib import SequenceMatcher
from uuid import NAMESPACE_URL, uuid5

from raven.agents import (
    EntityExtractionAgent,
    EntityResolutionAgent,
    EvidenceCompressionAgent,
    EvidenceLanguageDetectionAgent,
    EvidenceTranslationAgent,
    RelationshipExtractionAgent,
)
from raven.ai import SharedAiNode
from raven.config import DictionarySettings
from raven.exceptions import GraphAgentError
from raven.graph.vocabulary import (
    DEFAULT_DOMAIN_CODE,
    NamedEntityVocabularyCatalog,
    ResolvedVocabulary,
)
from raven.models import (
    AnalysisLanguage,
    EvidencePreparationMode,
    GraphEntity,
    GraphRelationship,
)

PROMPT_VERSION = "raven-hudiny-r2.11-vocabulary"
DEFAULT_CHUNK_WORDS = 1000
DEFAULT_CHUNK_OVERLAP = 100
logger = logging.getLogger(__name__)

_OBSERVABLES = (
    ("EMAIL_ADDRESS", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b"), "email"),
    ("URL", re.compile(r"(?i)https?://[^\s<>\"']+"), "url"),
    (
        "IP_ADDRESS",
        re.compile(
            r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
        ),
        "ip",
    ),
    ("FILE_HASH", re.compile(r"(?i)\b(?:[a-f0-9]{64}|[a-f0-9]{40}|[a-f0-9]{32})\b"), "hash"),
    (
        "DOMAIN",
        re.compile(r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b"),
        "domain",
    ),
)


class EvidenceGraphExtractor:
    """Run deterministic extraction and the optional shared-node LLM stages."""

    def __init__(
        self,
        node: SharedAiNode,
        vocabulary_catalog: NamedEntityVocabularyCatalog | None = None,
    ) -> None:
        self.node = node
        self.vocabulary_catalog = vocabulary_catalog or NamedEntityVocabularyCatalog(
            DictionarySettings().path
        )
        self.language_detection = EvidenceLanguageDetectionAgent(node)
        self.translation = EvidenceTranslationAgent(node)
        self.compression = EvidenceCompressionAgent(node)
        self.entity_extraction = EntityExtractionAgent(node)
        self.relationship_extraction = RelationshipExtractionAgent(node)
        self.entity_resolution = EntityResolutionAgent(node)

    def extract(
        self,
        investigation_id: str,
        evidence_id: str,
        text: str,
        analysis_language: AnalysisLanguage,
        preparation_mode: EvidencePreparationMode,
        analysis_domain: str = DEFAULT_DOMAIN_CODE,
        vocabulary: ResolvedVocabulary | None = None,
    ) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...], str]:
        active_vocabulary = vocabulary or self.resolve_vocabulary(analysis_domain)
        deterministic = deterministic_entities(investigation_id, evidence_id, text)
        if not self.node.available:
            return deterministic, (), "deterministic"
        try:
            prepared = self._prepare(
                investigation_id,
                text,
                analysis_language,
                preparation_mode,
            )
            segments = (
                word_chunks(prepared, DEFAULT_CHUNK_WORDS, DEFAULT_CHUNK_OVERLAP)
                if preparation_mode is EvidencePreparationMode.TRANSLATE_AND_CHUNK
                else (prepared,)
            )
            entity_groups: list[tuple[GraphEntity, ...]] = [deterministic]
            relationship_groups: list[tuple[GraphRelationship, ...]] = []
            for segment in segments:
                entities = self.entity_extraction.extract(
                    investigation_id,
                    evidence_id,
                    segment,
                    active_vocabulary,
                )
                entity_groups.append(entities)
                if entities:
                    relationship_groups.append(
                        self.relationship_extraction.extract(
                            investigation_id,
                            evidence_id,
                            segment,
                            entities,
                        )
                    )
        except GraphAgentError:
            logger.warning(
                "LLM graph extraction unavailable; deterministic candidates retained. "
                "investigation_id=%s evidence_id=%s",
                investigation_id,
                evidence_id,
            )
            return deterministic, (), "deterministic-fallback"
        entities, relationships = consolidate_graph(entity_groups, relationship_groups)
        model = self.node.settings.model if self.node.settings is not None else "deterministic"
        return entities, relationships, model

    def resolve_vocabulary(
        self,
        analysis_domain: str = DEFAULT_DOMAIN_CODE,
    ) -> ResolvedVocabulary:
        """Resolve one domain without including unrelated selectable domains."""
        return self.vocabulary_catalog.resolve(analysis_domain)

    def resolve_against(
        self,
        investigation_id: str,
        entities: tuple[GraphEntity, ...],
        relationships: tuple[GraphRelationship, ...],
        existing_entities: tuple[GraphEntity, ...],
    ) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...]]:
        """Link exact matches deterministically and ask the agent only for bounded ambiguity."""
        if not existing_entities:
            return entities, relationships
        remapped: dict[str, str] = {}
        resolved: list[GraphEntity] = []
        for mention in entities:
            same_type = tuple(
                candidate
                for candidate in existing_entities
                if candidate.entity_type == mention.entity_type
            )
            target = _exact_match(mention, same_type)
            if target is None and self.node.available:
                bounded = tuple(
                    candidate
                    for candidate in same_type
                    if SequenceMatcher(
                        None,
                        _name(mention.canonical_name),
                        _name(candidate.canonical_name),
                    ).ratio()
                    >= 0.82
                )[:10]
                if bounded:
                    try:
                        decision = self.entity_resolution.resolve(
                            investigation_id,
                            mention,
                            bounded,
                        )
                    except GraphAgentError:
                        logger.warning(
                            "Entity resolution agent unavailable; keeping mention separate. "
                            "investigation_id=%s",
                            investigation_id,
                        )
                    else:
                        if decision.decision == "LINK":
                            target = next(
                                (
                                    candidate
                                    for candidate in bounded
                                    if candidate.entity_id == decision.candidate_entity_id
                                ),
                                None,
                            )
            if target is None:
                resolved.append(mention)
                remapped[mention.entity_id] = mention.entity_id
            else:
                linked = _merge_entity(target, mention)
                resolved.append(linked)
                remapped[mention.entity_id] = target.entity_id
        grounded_relationships = tuple(
            replace(
                relationship,
                source_entity_id=remapped.get(
                    relationship.source_entity_id,
                    relationship.source_entity_id,
                ),
                target_entity_id=remapped.get(
                    relationship.target_entity_id,
                    relationship.target_entity_id,
                ),
            )
            for relationship in relationships
        )
        return tuple(resolved), grounded_relationships

    def _prepare(
        self,
        investigation_id: str,
        text: str,
        language: AnalysisLanguage,
        mode: EvidencePreparationMode,
    ) -> str:
        if mode is EvidencePreparationMode.COMPRESS:
            return self.compression.compress(investigation_id, text, language)
        if language is AnalysisLanguage.ORIGINAL:
            return text
        detected = self.language_detection.detect(investigation_id, text)
        if detected == language.language_code:
            return text
        return self.translation.translate(investigation_id, text, language)


def deterministic_entities(
    investigation_id: str,
    evidence_id: str,
    text: str,
) -> tuple[GraphEntity, ...]:
    candidates: OrderedDict[tuple[str, str], GraphEntity] = OrderedDict()
    bounded = text[:250_000]
    for entity_type, pattern, scheme in _OBSERVABLES:
        for match in pattern.finditer(bounded):
            value = re.sub(r"[),.;:!?]+$", "", match.group()).strip()
            if not value:
                continue
            normalized = value.casefold()
            key = (entity_type, normalized)
            existing = candidates.get(key)
            if existing is not None:
                continue
            entity_id = str(
                uuid5(NAMESPACE_URL, f"raven:{investigation_id}:{entity_type}:{normalized}")
            )
            candidates[key] = GraphEntity(
                entity_id=entity_id,
                entity_type=entity_type,
                canonical_name=value,
                external_identifiers=((scheme, normalized),),
                evidence_ids=(evidence_id,),
                rationale="Deterministic observable extracted from normalized Evidence text",
                confidence=1.0,
            )
    return tuple(candidates.values())


def word_chunks(
    text: str,
    chunk_word_count: int = DEFAULT_CHUNK_WORDS,
    overlap_words: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[str, ...]:
    if chunk_word_count <= 0 or overlap_words < 0 or overlap_words >= chunk_word_count:
        raise ValueError("Invalid Evidence word chunk configuration")
    words = text.split()
    if len(words) <= chunk_word_count:
        return (text,)
    step = chunk_word_count - overlap_words
    chunks: list[str] = []
    for start in range(0, len(words), step):
        end = min(start + chunk_word_count, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
    return tuple(chunks)


def consolidate_graph(
    entity_groups: Iterable[tuple[GraphEntity, ...]],
    relationship_groups: Iterable[tuple[GraphRelationship, ...]],
) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...]]:
    """Merge true duplicates and remap every relationship to the retained entity IDs."""
    entities: OrderedDict[str, GraphEntity] = OrderedDict()
    identity_map: dict[str, str] = {}
    for candidate in (entity for group in entity_groups for entity in group):
        key = _entity_key(candidate)
        existing = entities.get(key)
        if existing is None:
            entities[key] = candidate
            identity_map[candidate.entity_id] = candidate.entity_id
        else:
            identity_map[candidate.entity_id] = existing.entity_id
            entities[key] = _merge_entity(existing, candidate)

    relationships: OrderedDict[str, GraphRelationship] = OrderedDict()
    for candidate in (relationship for group in relationship_groups for relationship in group):
        source_id = identity_map.get(candidate.source_entity_id)
        target_id = identity_map.get(candidate.target_entity_id)
        if source_id is None or target_id is None:
            continue
        key = f"{source_id}:{candidate.relationship_type}:{target_id}"
        relationship_id = str(uuid5(NAMESPACE_URL, f"raven:relationship:{key}"))
        grounded = replace(
            candidate,
            relationship_id=relationship_id,
            source_entity_id=source_id,
            target_entity_id=target_id,
        )
        existing = relationships.get(key)
        relationships[key] = (
            grounded if existing is None else _merge_relationship(existing, grounded)
        )
    return tuple(entities.values()), tuple(relationships.values())


def _entity_key(entity: GraphEntity) -> str:
    identifiers = sorted(
        (scheme.casefold(), value.casefold())
        for scheme, value in entity.external_identifiers
        if scheme and value
    )
    identity = (
        f"{identifiers[0][0]}={identifiers[0][1]}" if identifiers else _name(entity.canonical_name)
    )
    return f"{entity.entity_type}:{identity}"


def _exact_match(
    mention: GraphEntity,
    candidates: tuple[GraphEntity, ...],
) -> GraphEntity | None:
    mention_identifiers = {
        (scheme.casefold(), value.casefold())
        for scheme, value in mention.external_identifiers
        if scheme and value
    }
    mention_names = {_name(mention.canonical_name), *(_name(alias) for alias in mention.aliases)}
    for candidate in candidates:
        candidate_identifiers = {
            (scheme.casefold(), value.casefold())
            for scheme, value in candidate.external_identifiers
            if scheme and value
        }
        candidate_names = {
            _name(candidate.canonical_name),
            *(_name(alias) for alias in candidate.aliases),
        }
        if mention_identifiers.intersection(candidate_identifiers) or mention_names.intersection(
            candidate_names
        ):
            return candidate
    return None


def _merge_entity(first: GraphEntity, second: GraphEntity) -> GraphEntity:
    canonical = max((first.canonical_name, second.canonical_name), key=len)
    aliases = tuple(
        dict.fromkeys(
            (
                *first.aliases,
                *second.aliases,
                *(
                    name
                    for name in (first.canonical_name, second.canonical_name)
                    if name != canonical
                ),
            )
        )
    )
    return replace(
        first,
        canonical_name=canonical,
        subtype=first.subtype or second.subtype,
        aliases=aliases,
        external_identifiers=tuple(
            dict.fromkeys((*first.external_identifiers, *second.external_identifiers))
        ),
        evidence_ids=tuple(dict.fromkeys((*first.evidence_ids, *second.evidence_ids))),
        rationale=_merge_text(first.rationale, second.rationale),
        confidence=max(first.confidence, second.confidence),
    )


def _merge_relationship(
    first: GraphRelationship,
    second: GraphRelationship,
) -> GraphRelationship:
    return replace(
        first,
        evidence_ids=tuple(dict.fromkeys((*first.evidence_ids, *second.evidence_ids))),
        rationale=_merge_text(first.rationale, second.rationale),
        confidence=max(first.confidence, second.confidence),
    )


def _name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _merge_text(first: str, second: str) -> str:
    if not second or second in first:
        return first
    return f"{first} | {second}" if first else second
