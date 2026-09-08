"""Hudiny-derived preprocessing, extraction, grounding, and consolidation pipeline."""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from collections.abc import Callable, Iterable
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
from raven.exceptions import GraphAgentError, GraphAnalysisCancelledError
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

PROMPT_VERSION = "raven-grounded-v3"
DEFAULT_CHUNK_WORDS = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_PAGE_GROUP_PAGES = 2
RETRY_CHUNK_WORDS = 400
RETRY_CHUNK_OVERLAP = 40
LANGUAGE_SAMPLE_CHARACTERS = 12_000
logger = logging.getLogger(__name__)

ExtractionProgress = Callable[[str], None]
ExtractionWarning = Callable[[str], None]
CancelledCallback = Callable[[], bool]


class EvidenceGraphExtractor:
    """Run mandatory LLM extraction without regex-generated graph entities."""

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
        progress: ExtractionProgress | None = None,
        cancelled: CancelledCallback | None = None,
        evidence_segments: tuple[str, ...] | None = None,
        warning: ExtractionWarning | None = None,
    ) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...], str]:
        active_vocabulary = vocabulary or self.resolve_vocabulary(analysis_domain)
        if not self.node.available:
            raise GraphAgentError(
                "The shared AI node is not connected; semantic Evidence analysis cannot start"
            )
        try:
            segments = self._prepare_segments(
                investigation_id,
                text,
                analysis_language,
                preparation_mode,
                progress,
                cancelled,
                evidence_segments,
                warning,
            )
            entity_groups: list[tuple[GraphEntity, ...]] = []
            relationship_groups: list[tuple[GraphRelationship, ...]] = []
            extraction_failures: list[str] = []
            successful_segments = 0
            total_segments = len(segments)
            unit = "page group" if evidence_segments is not None else "segment"
            for index, segment in enumerate(segments, 1):
                self._check_cancelled(cancelled)
                self._report(progress, f"Extracting entities · {unit} {index}/{total_segments}")
                try:
                    entities = self.entity_extraction.extract(
                        investigation_id,
                        evidence_id,
                        segment,
                        active_vocabulary,
                    )
                except GraphAgentError as error:
                    message = f"Entity extraction skipped {unit} {index}/{total_segments}: {error}"
                    extraction_failures.append(message)
                    self._warn(progress, warning, message)
                    continue
                successful_segments += 1
                entity_groups.append(entities)
                if entities:
                    self._check_cancelled(cancelled)
                    self._report(
                        progress,
                        f"Extracting relationships · {unit} {index}/{total_segments}",
                    )
                    try:
                        relationships = self.relationship_extraction.extract(
                            investigation_id,
                            evidence_id,
                            segment,
                            entities,
                        )
                    except GraphAgentError as error:
                        message = (
                            f"Relationship extraction skipped {unit} {index}/{total_segments}: "
                            f"{error}"
                        )
                        extraction_failures.append(message)
                        self._warn(progress, warning, message)
                    else:
                        relationship_groups.append(relationships)
            if not successful_segments and extraction_failures:
                raise GraphAgentError(
                    "All prepared Evidence groups failed semantic extraction; "
                    f"first failure: {extraction_failures[0]}"
                )
        except GraphAgentError as error:
            logger.warning(
                "Semantic graph extraction failed; no fallback graph will be generated. "
                "investigation_id=%s evidence_id=%s error_type=%s",
                investigation_id,
                evidence_id,
                type(error).__name__,
            )
            raise GraphAgentError(f"Semantic Evidence analysis failed: {error}") from error
        entities, relationships = consolidate_graph(entity_groups, relationship_groups)
        model = self.node.settings.model if self.node.settings is not None else "unknown-ai-model"
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
        cancelled: CancelledCallback | None = None,
    ) -> tuple[tuple[GraphEntity, ...], tuple[GraphRelationship, ...]]:
        """Link exact matches deterministically and ask the agent only for bounded ambiguity."""
        if not existing_entities:
            return entities, relationships
        remapped: dict[str, str] = {}
        resolved: list[GraphEntity] = []
        for mention in entities:
            self._check_cancelled(cancelled)
            same_type = tuple(
                candidate
                for candidate in existing_entities
                if candidate.entity_type == mention.entity_type
                and not identifiers_conflict(mention, candidate)
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
                        mention = replace(
                            mention,
                            resolution_notes=(
                                *mention.resolution_notes,
                                f"{decision.decision}: {decision.rationale}",
                            ),
                        )
                        if decision.decision == "LINK" and decision.confidence >= 0.9:
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

    def _prepare_segments(
        self,
        investigation_id: str,
        text: str,
        language: AnalysisLanguage,
        mode: EvidencePreparationMode,
        progress: ExtractionProgress | None,
        cancelled: CancelledCallback | None,
        evidence_segments: tuple[str, ...] | None,
        warning: ExtractionWarning | None,
    ) -> tuple[str, ...]:
        """Split long Evidence before expensive translation/compression model calls."""
        self._check_cancelled(cancelled)
        translate = False
        if language is not AnalysisLanguage.ORIGINAL:
            self._report(progress, "Detecting Evidence language")
            detected = self.language_detection.detect(
                investigation_id,
                _language_sample(text),
            )
            translate = detected != language.language_code

        words = len(text.split())
        must_segment = mode.chunk_evidence or words > DEFAULT_CHUNK_WORDS
        if evidence_segments is not None:
            segments = evidence_segments
        else:
            segments = (
                word_chunks(text, DEFAULT_CHUNK_WORDS, DEFAULT_CHUNK_OVERLAP)
                if must_segment
                else (text,)
            )
        if evidence_segments is None and must_segment and not mode.chunk_evidence:
            self._report(
                progress,
                f"Automatic model-safe segmentation · {len(segments)} segments",
            )

        prepared_segments: list[str] = []
        preparation_failures: list[str] = []
        total_segments = len(segments)
        unit = "page group" if evidence_segments is not None else "segment"
        for index, segment in enumerate(segments, 1):
            self._check_cancelled(cancelled)
            try:
                prepared = self._prepare_segment(
                    investigation_id,
                    segment,
                    language,
                    mode,
                    translate,
                    progress,
                    cancelled,
                    f"{unit} {index}/{total_segments}",
                )
            except GraphAgentError as error:
                retry_segments = _retry_segments(segment)
                if retry_segments == (segment,):
                    message = f"Preparation skipped {unit} {index}/{total_segments}: {error}"
                    preparation_failures.append(message)
                    self._warn(progress, warning, message)
                    continue
                self._report(
                    progress,
                    f"{unit.title()} {index}/{total_segments} failed; retrying as "
                    f"{len(retry_segments)} smaller groups",
                )
                recovered = 0
                retry_failures: list[str] = []
                for retry_index, retry_segment in enumerate(retry_segments, 1):
                    try:
                        prepared = self._prepare_segment(
                            investigation_id,
                            retry_segment,
                            language,
                            mode,
                            translate,
                            progress,
                            cancelled,
                            f"retry group {retry_index}/{len(retry_segments)}",
                        )
                    except GraphAgentError as retry_error:
                        message = (
                            f"Preparation skipped retry group {retry_index}/"
                            f"{len(retry_segments)}: {retry_error}"
                        )
                        retry_failures.append(message)
                        self._warn(progress, warning, message)
                    else:
                        recovered += 1
                        prepared_segments.append(prepared)
                if not recovered:
                    message = (
                        f"{unit.title()} {index}/{total_segments} failed and all smaller "
                        f"retries failed: {error}"
                    )
                    preparation_failures.append(message)
                    self._warn(progress, warning, message)
                    continue
                if retry_failures:
                    self._warn(
                        progress,
                        warning,
                        f"{unit.title()} {index}/{total_segments} completed partially: "
                        f"{len(retry_failures)} smaller group(s) skipped",
                    )
            else:
                prepared_segments.append(prepared)
        if not prepared_segments and preparation_failures:
            raise GraphAgentError(
                f"All Evidence groups failed preparation; first failure: {preparation_failures[0]}"
            )
        return tuple(prepared_segments)

    def _prepare_segment(
        self,
        investigation_id: str,
        segment: str,
        language: AnalysisLanguage,
        mode: EvidencePreparationMode,
        translate: bool,
        progress: ExtractionProgress | None,
        cancelled: CancelledCallback | None,
        label: str,
    ) -> str:
        prepared = segment
        if translate:
            self._report(progress, f"Translating Evidence · {label}")
            prepared = self.translation.translate(investigation_id, prepared, language)
        if mode.compress_evidence:
            self._check_cancelled(cancelled)
            self._report(progress, f"Compressing Evidence · {label}")
            prepared = self.compression.compress(investigation_id, prepared, language)
        if not prepared.strip():
            raise GraphAgentError(f"Evidence preparation returned empty text for {label}")
        return prepared

    @staticmethod
    def _check_cancelled(cancelled: CancelledCallback | None) -> None:
        if cancelled is not None and cancelled():
            raise GraphAnalysisCancelledError("Graph analysis cancelled")

    @staticmethod
    def _report(progress: ExtractionProgress | None, message: str) -> None:
        if progress is not None:
            progress(message)

    @staticmethod
    def _warn(
        progress: ExtractionProgress | None,
        warning: ExtractionWarning | None,
        message: str,
    ) -> None:
        if warning is not None:
            warning(message)
        if progress is not None:
            progress(f"Warning · {message}")


def _language_sample(text: str) -> str:
    """Sample the beginning, middle and end without sending a whole long document."""
    if len(text) <= LANGUAGE_SAMPLE_CHARACTERS:
        return text
    part = LANGUAGE_SAMPLE_CHARACTERS // 3
    middle = len(text) // 2
    return "\n\n".join((text[:part], text[middle - part // 2 : middle + part // 2], text[-part:]))


def page_groups(
    pages: tuple[str, ...],
    maximum_words: int = DEFAULT_CHUNK_WORDS,
    overlap_pages: int = 1,
    maximum_pages: int = DEFAULT_PAGE_GROUP_PAGES,
) -> tuple[str, ...]:
    """Build model-safe page groups while retaining stable page markers."""
    if (
        maximum_words <= 0
        or maximum_pages <= 0
        or overlap_pages < 0
        or overlap_pages >= maximum_pages
    ):
        raise ValueError("Invalid Evidence page-group configuration")
    indexed_pages = tuple(
        (index, page.strip()) for index, page in enumerate(pages, 1) if page.strip()
    )
    if not indexed_pages:
        return ()

    groups: list[str] = []
    start = 0
    while start < len(indexed_pages):
        end = start
        word_count = 0
        rendered: list[str] = []
        while end < len(indexed_pages):
            page_number, content = indexed_pages[end]
            page_words = len(content.split())
            if rendered and (
                word_count + page_words > maximum_words or len(rendered) >= maximum_pages
            ):
                break
            if not rendered and page_words > maximum_words:
                parts = word_chunks(content, maximum_words, min(100, maximum_words - 1))
                groups.extend(
                    f"[PAGE {page_number} · PART {part_index}/{len(parts)}]\n{part}"
                    for part_index, part in enumerate(parts, 1)
                )
                end += 1
                rendered = []
                break
            rendered.append(f"[PAGE {page_number}]\n{content}")
            word_count += page_words
            end += 1
        if rendered:
            groups.append("\n\n".join(rendered))
        if end >= len(indexed_pages):
            break
        if end <= start:
            end = start + 1
        start = max(start + 1, end - min(overlap_pages, end - start - 1))
    return tuple(groups)


def _retry_segments(segment: str) -> tuple[str, ...]:
    """Split a failed model input while preserving every available page marker."""
    matches = tuple(re.finditer(r"(?m)^\[PAGE [^\]]+\]\n", segment))
    page_sections: list[tuple[str, str]] = []
    if matches:
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(segment)
            page_sections.append((match.group(0).strip(), segment[match.end() : end].strip()))
    else:
        page_sections.append(("", segment.strip()))

    retries: list[str] = []
    for marker, content in page_sections:
        chunks = word_chunks(content, RETRY_CHUNK_WORDS, RETRY_CHUNK_OVERLAP)
        for chunk in chunks:
            retries.append(f"{marker}\n{chunk}".strip() if marker else chunk)
    result = tuple(retry for retry in retries if retry.strip())
    return result or (segment,)


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
    keys_by_id: dict[str, str] = {}
    identity_map: dict[str, str] = {}
    for candidate in (entity for group in entity_groups for entity in group):
        key = keys_by_id.get(candidate.entity_id, _entity_key(candidate))
        existing = entities.get(key)
        if existing is not None and identifiers_conflict(existing, candidate):
            key = f"{key}:{candidate.entity_id}"
            existing = entities.get(key)
        if existing is None:
            entities[key] = candidate
            keys_by_id[candidate.entity_id] = key
            identity_map[candidate.entity_id] = candidate.entity_id
        else:
            identity_map[candidate.entity_id] = existing.entity_id
            keys_by_id[candidate.entity_id] = key
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


# Descriptive attributes are not unique identity keys.
_NON_IDENTITY = {
    "date",
    "datetime",
    "timestamp",
    "start_date",
    "end_date",
    "time",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "country",
}


def _identifiers(entity: GraphEntity) -> set[tuple[str, str]]:
    return {
        (scheme.casefold(), value.strip().casefold())
        for scheme, value in entity.external_identifiers
        if scheme and value and scheme.casefold() not in _NON_IDENTITY
    }


def identifiers_conflict(first: GraphEntity, second: GraphEntity) -> bool:
    left, right = _identifiers(first), _identifiers(second)
    schemes = {scheme for scheme, _ in left} & {scheme for scheme, _ in right}
    return any(
        {value for key, value in left if key == scheme}.isdisjoint(
            value for key, value in right if key == scheme
        )
        for scheme in schemes
    )


def _entity_key(entity: GraphEntity) -> str:
    identifiers = sorted(_identifiers(entity))
    identity = (
        repr(identifiers)
        if identifiers
        else (_name(entity.canonical_name) + ":" + ",".join(sorted(entity.evidence_ids)))
    )
    return f"{entity.entity_type}:{entity.subtype}:{identity}"


def _exact_match(mention: GraphEntity, candidates: tuple[GraphEntity, ...]) -> GraphEntity | None:
    matches = [
        candidate
        for candidate in candidates
        if not identifiers_conflict(mention, candidate)
        and _identifiers(mention).intersection(_identifiers(candidate))
    ]
    return matches[0] if len(matches) == 1 else None


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
        support=tuple(dict.fromkeys((*first.support, *second.support))),
    )


def _name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _merge_text(first: str, second: str) -> str:
    if not second or second in first:
        return first
    return f"{first} | {second}" if first else second
