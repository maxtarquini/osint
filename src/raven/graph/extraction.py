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
from raven.exceptions.graph import GraphAnalysisCancelledError
from raven.graph.grounding import ground_items
from raven.graph.vocabulary import (
    DEFAULT_DOMAIN_CODE,
    NamedEntityVocabularyCatalog,
    ResolvedVocabulary,
)
from raven.models import (
    AnalysisLanguage,
    EvidencePreparationMode,
    EvidenceSpan,
    GraphEntity,
    GraphItemStatus,
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
        *,
        pages: tuple[str, ...] | None = None,
        cancelled=None,
    ) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...], str]:
        active_vocabulary = vocabulary or self.resolve_vocabulary(analysis_domain)
        source_pages = pages if pages is not None else (text,)
        deterministic, _ = consolidate_graph(
            (
                deterministic_entities(investigation_id, evidence_id, page, page_number=number)
                for number, page in enumerate(source_pages, 1)
            ),
            (),
        )
        if cancelled and cancelled():
            raise GraphAnalysisCancelledError("Graph analysis cancelled")
        if not self.node.available:
            return deterministic, (), "deterministic"
        try:
            entity_groups: list[tuple[GraphEntity, ...]] = [deterministic]
            relationship_groups: list[tuple[GraphRelationship, ...]] = []
            for original in page_groups(source_pages):
                if cancelled and cancelled():
                    raise GraphAnalysisCancelledError("Graph analysis cancelled")
                prepared = self._prepare(
                    investigation_id, original, analysis_language, preparation_mode, cancelled
                )
                segment = (
                    f"ANALYSIS TEXT (derived, not a quotation source)\n{prepared}\n\n"
                    if prepared != original
                    else ""
                ) + f"ORIGINAL SOURCE PAGES (quote only these)\n{original}"
                entities = self.entity_extraction.extract(
                    investigation_id,
                    evidence_id,
                    segment,
                    active_vocabulary,
                    cancelled=cancelled,
                )
                entity_groups.append(entities)
                if entities:
                    relationship_groups.append(
                        self.relationship_extraction.extract(
                            investigation_id,
                            evidence_id,
                            segment,
                            entities,
                            cancelled=cancelled,
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
        entities = ground_items(entities, evidence_id, source_pages)
        relationships = ground_items(relationships, evidence_id, source_pages)
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
        *,
        cancelled=None,
    ) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...]]:
        """Resolve corroborated identities without turning names into identity keys."""
        known = {entity.entity_id: entity for entity in existing_entities}
        remapped: dict[str, str] = {}
        resolved: list[GraphEntity] = []
        for mention in entities:
            if cancelled and cancelled():
                raise GraphAnalysisCancelledError("Graph analysis cancelled")
            same_type = tuple(
                candidate
                for candidate in known.values()
                if candidate.entity_type == mention.entity_type
                and not identifiers_conflict(mention, candidate)
            )
            target = _exact_match(mention, same_type)
            if target is None:
                ambiguous = _resolution_candidates(mention, same_type)
                # Truncation would hide equally plausible identities from the agent.
                if len(ambiguous) > 10:
                    mention = _resolution_note(
                        mention, "REVIEW: More than ten plausible identities; kept separate"
                    )
                elif (
                    sum(
                        bool(_hard_identifiers(mention).intersection(_hard_identifiers(candidate)))
                        for candidate in ambiguous
                    )
                    > 1
                ):
                    mention = _resolution_note(
                        mention, "REVIEW: Hard identifier matches multiple identities"
                    )
                elif ambiguous and not any(
                    _corroborating_identifiers(mention, candidate) for candidate in ambiguous
                ):
                    mention = _resolution_note(
                        mention, "REVIEW: Matching names alone are insufficient identity evidence"
                    )
                elif ambiguous and self.node.available:
                    try:
                        decision = self.entity_resolution.resolve(
                            investigation_id,
                            mention,
                            ambiguous,
                            cancelled=cancelled,
                        )
                    except GraphAgentError:
                        logger.warning(
                            "Entity resolution agent unavailable; keeping mention separate. "
                            "investigation_id=%s",
                            investigation_id,
                        )
                        mention = _resolution_note(
                            mention, "REVIEW: Entity resolution unavailable; kept separate"
                        )
                    else:
                        mention = _resolution_note(
                            mention, f"{decision.decision}: {decision.rationale}"
                        )
                        proposed = next(
                            (
                                candidate
                                for candidate in ambiguous
                                if candidate.entity_id == decision.candidate_entity_id
                            ),
                            None,
                        )
                        if (
                            decision.decision == "LINK"
                            and decision.confidence >= 0.9
                            and proposed is not None
                            and _corroborating_identifiers(mention, proposed)
                        ):
                            target = proposed
                        elif decision.decision == "LINK":
                            mention = _resolution_note(
                                mention, "REVIEW: Proposed link lacks corroboration or confidence"
                            )
                elif ambiguous:
                    mention = _resolution_note(
                        mention, "REVIEW: Identity comparison requires an available agent"
                    )
                elif any(
                    candidate.entity_type == mention.entity_type
                    and identifiers_conflict(mention, candidate)
                    and _names_similar(mention, candidate)
                    for candidate in known.values()
                ):
                    mention = _resolution_note(
                        mention, "KEEP_SEPARATE: Incompatible hard identifiers"
                    )
            if target is None:
                resolved.append(mention)
                remapped[mention.entity_id] = mention.entity_id
                known[mention.entity_id] = mention
            else:
                linked = _merge_entity(target, mention)
                resolved.append(linked)
                remapped[mention.entity_id] = target.entity_id
                known[target.entity_id] = linked
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
        cancelled=None,
    ) -> str:
        if mode is EvidencePreparationMode.COMPRESS:
            return self.compression.compress(investigation_id, text, language, cancelled=cancelled)
        if language is AnalysisLanguage.ORIGINAL:
            return text
        detected = self.language_detection.detect(investigation_id, text, cancelled=cancelled)
        if detected == language.language_code:
            return text
        return self.translation.translate(investigation_id, text, language, cancelled=cancelled)


def deterministic_entities(
    investigation_id: str,
    evidence_id: str,
    text: str,
    *,
    page_number: int = 1,
) -> tuple[GraphEntity, ...]:
    candidates: OrderedDict[tuple[str, str], GraphEntity] = OrderedDict()
    bounded = text[:250_000]
    for entity_type, pattern, scheme in _OBSERVABLES:
        for match in pattern.finditer(bounded):
            value = re.sub(r"[),.;:!?]+$", "", match.group()).strip()
            if not value:
                continue
            # URL paths may be case-sensitive; preserve them in deterministic identity keys.
            normalized = value if entity_type == "URL" else value.casefold()
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
                support=(EvidenceSpan(evidence_id, value, page_number, True),),
            )
    return tuple(candidates.values())


def page_groups(
    pages: tuple[str, ...], maximum_words: int = DEFAULT_CHUNK_WORDS
) -> tuple[str, ...]:
    """Bound model inputs while keeping the PDF numbering, including gaps from blank pages."""
    if maximum_words <= 0:
        raise ValueError("Invalid Evidence page-group size")
    groups = []
    current = []
    count = 0
    for number, text in enumerate(pages, 1):
        words = len(text.split())
        if not words:
            continue
        if current and (count + words > maximum_words or len(current) >= 5):
            groups.append("\n\n".join(current))
            current, count = [], 0
        if words > maximum_words:
            groups.extend(
                f"[PAGE {number}]\n{part}"
                for part in word_chunks(text, maximum_words, min(100, maximum_words - 1))
            )
        else:
            current.append(f"[PAGE {number}]\n{text}")
            count += words
    if current:
        groups.append("\n\n".join(current))
    return tuple(groups)


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
    """Combine already resolved IDs without overturning identity decisions."""
    entities: OrderedDict[str, GraphEntity] = OrderedDict()
    identity_map: dict[str, str] = {}
    for candidate in (entity for group in entity_groups for entity in group):
        key = _entity_key(candidate)
        existing = entities.get(key)
        if existing is None:
            entities[key] = candidate
            identity_map[candidate.entity_id] = candidate.entity_id
        else:
            if existing.entity_type != candidate.entity_type or identifiers_conflict(
                existing, candidate
            ):
                raise GraphAgentError("Conflicting identity data for an already resolved entity")
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
    # Only resolution may declare two mentions identical. Names, attributes, and
    # even shared identifiers must not undo KEEP_SEPARATE or REVIEW decisions.
    return entity.entity_id


_SCHEME_ALIASES = {
    "passport_number": "passport",
    "passport_no": "passport",
    "national_id_number": "national_id",
    "tax_identifier": "tax_id",
    "vat_number": "vat",
    "company_registration_number": "registration_number",
    "imo_number": "imo",
    "mmsi_number": "mmsi",
    "vehicle_identification_number": "vin",
    "email_address": "email",
    "telephone": "phone",
    "phone_number": "phone",
    "ip_address": "ip",
    "file_hash": "hash",
}

# Identifier strength depends on the entity: a shared mailbox does not identify
# one person, while its address does identify an EMAIL_ADDRESS observable.
_HARD_IDENTITY_SCHEMES = {
    "PERSON": {"passport", "national_id", "tax_id", "ssn"},
    "ORGANIZATION": {"vat", "tax_id", "registration_number", "lei"},
    "VESSEL": {"imo", "mmsi"},
    "VEHICLE": {"vin"},
    "AIRCRAFT": {"aircraft_registration", "icao24"},
    "FINANCIAL_ACCOUNT": {"iban"},
    "IBAN": {"iban"},
    "PASSPORT_NUMBER": {"passport"},
    "NATIONAL_ID": {"national_id"},
    "TAX_IDENTIFIER": {"tax_id"},
    "DOMAIN": {"domain"},
    "HOSTNAME": {"hostname"},
    "URL": {"url"},
    "EMAIL_ADDRESS": {"email"},
    "PHONE_NUMBER": {"phone"},
    "IP_ADDRESS": {"ip"},
    "FILE_HASH": {"hash", "md5", "sha1", "sha256", "sha512"},
    "CRYPTOCURRENCY_ADDRESS": {"cryptocurrency_address", "wallet_address"},
}
_SOFT_IDENTITY_SCHEMES = {"email", "phone", "username", "account_id", "url", "domain"}
_IDENTITY_SCHEMES = _SOFT_IDENTITY_SCHEMES.union(*_HARD_IDENTITY_SCHEMES.values())


def _identifiers(entity: GraphEntity) -> set[tuple[str, str]]:
    identifiers: set[tuple[str, str]] = set()
    for raw_scheme, raw_value in entity.external_identifiers:
        scheme = re.sub(r"[\s-]+", "_", raw_scheme.strip().casefold())
        scheme = _SCHEME_ALIASES.get(scheme, scheme)
        value = raw_value.strip()
        if scheme not in _IDENTITY_SCHEMES or not value:
            continue
        # URL paths and usernames may be case-sensitive. A missed match is safer
        # than silently identifying two different resources.
        if scheme not in {
            "url",
            "username",
            "account_id",
            "wallet_address",
            "cryptocurrency_address",
        }:
            value = value.casefold()
        identifiers.add((scheme, value))
    return identifiers


def _hard_identifiers(entity: GraphEntity) -> set[tuple[str, str]]:
    schemes = _HARD_IDENTITY_SCHEMES.get(entity.entity_type, set())
    return {item for item in _identifiers(entity) if item[0] in schemes}


def identifiers_conflict(first: GraphEntity, second: GraphEntity) -> bool:
    """Veto automatic merges when explicit hard identifiers disagree."""
    left, right = _hard_identifiers(first), _hard_identifiers(second)
    common_schemes = {scheme for scheme, _ in left} & {scheme for scheme, _ in right}
    return any(
        {value for scheme, value in left if scheme == common}.isdisjoint(
            value for scheme, value in right if scheme == common
        )
        for common in common_schemes
    )


def _corroborating_identifiers(first: GraphEntity, second: GraphEntity) -> bool:
    return bool(_identifiers(first).intersection(_identifiers(second)))


def _exact_match(
    mention: GraphEntity,
    candidates: tuple[GraphEntity, ...],
) -> GraphEntity | None:
    matches = {
        candidate.entity_id: candidate
        for candidate in candidates
        if candidate.entity_type == mention.entity_type
        and not identifiers_conflict(mention, candidate)
        and (
            candidate.entity_id == mention.entity_id
            or _hard_identifiers(mention).intersection(_hard_identifiers(candidate))
        )
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _entity_names(entity: GraphEntity) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            name
            for value in (entity.canonical_name, *entity.aliases[:20])
            if (name := _name(value))
        )
    )


def _names_similar(first: GraphEntity, second: GraphEntity) -> bool:
    return any(
        left == right or SequenceMatcher(None, left, right).ratio() >= 0.82
        for left in _entity_names(first)
        for right in _entity_names(second)
    )


def _resolution_candidates(
    mention: GraphEntity, candidates: tuple[GraphEntity, ...]
) -> tuple[GraphEntity, ...]:
    result: dict[str, GraphEntity] = {}
    for candidate in candidates:
        if _names_similar(mention, candidate) or _corroborating_identifiers(mention, candidate):
            result[candidate.entity_id] = candidate
            if len(result) > 10:
                break
    return tuple(result.values())


def _resolution_note(mention: GraphEntity, note: str) -> GraphEntity:
    return replace(
        mention, resolution_notes=tuple(dict.fromkeys((*mention.resolution_notes, note)))
    )


def _conservative_status(first: GraphItemStatus, second: GraphItemStatus) -> GraphItemStatus:
    if GraphItemStatus.REJECTED in (first, second):
        return GraphItemStatus.REJECTED
    if GraphItemStatus.PROPOSED in (first, second):
        return GraphItemStatus.PROPOSED
    return GraphItemStatus.VERIFIED


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
        resolution_notes=tuple(dict.fromkeys((*first.resolution_notes, *second.resolution_notes))),
        aliases=aliases,
        external_identifiers=tuple(
            dict.fromkeys((*first.external_identifiers, *second.external_identifiers))
        ),
        evidence_ids=tuple(dict.fromkeys((*first.evidence_ids, *second.evidence_ids))),
        rationale=_merge_text(first.rationale, second.rationale),
        confidence=max(first.confidence, second.confidence),
        status=_conservative_status(first.status, second.status),
        support=tuple(dict.fromkeys((*first.support, *second.support))),
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
        status=_conservative_status(first.status, second.status),
        support=tuple(dict.fromkeys((*first.support, *second.support))),
        resolution_notes=tuple(dict.fromkeys((*first.resolution_notes, *second.resolution_notes))),
    )


def _name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _merge_text(first: str, second: str) -> str:
    if not second or second in first:
        return first
    return f"{first} | {second}" if first else second
