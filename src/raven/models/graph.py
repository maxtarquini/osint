"""Evidence-analysis run and evidence-grounded graph value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from raven.models.investigation import EvidenceIngestionState


class EvidencePreparationMode(StrEnum):
    """Hudiny-compatible preparation strategies for an analysis run."""

    COMPRESS = "compress"
    FULL_TEXT = "full_text"
    TRANSLATE_AND_CHUNK = "translate_and_chunk"


class GraphRunStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CONSOLIDATING = "consolidating"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GraphJobStatus(StrEnum):
    """Application-owned lifecycle for queued graph analysis work."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GraphItemStatus(StrEnum):
    """AI output is never silently promoted to a verified fact."""

    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    """Quoted support checked against an original source page, not a factual verdict."""

    evidence_id: str
    quote: str
    page_number: int | None = None
    verified_original: bool = False
    unit_id: str = ""
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True, slots=True)
class LiteralValue:
    value: str
    datatype: str = "string"
    unit: str = ""


@dataclass(frozen=True, slots=True)
class SourceAttribution:
    source_id: str = ""
    speaker: str = ""
    derived_from: tuple[str, ...] = ()
    reliability: str = "unassessed"


@dataclass(frozen=True, slots=True)
class ClaimReference:
    source: str
    predicate: str
    subject_name: str
    object_name: str = ""
    claim_id: str = ""


@dataclass(frozen=True, slots=True)
class GraphManifest:
    schema_version: int = 2
    method_id: str = "document_claims"
    method_version: str = "4"
    prompt_version: str = "raven-integrity-v5"
    documents: tuple[tuple[str, str], ...] = ()
    catalogs: tuple[tuple[str, str], ...] = ()
    dictionary_hash: str = ""
    dictionary_versions: tuple[str, ...] = ()
    dictionary_snapshot: str = ""
    model: str = ""
    configuration: str = "{}"


@dataclass(frozen=True, slots=True)
class GraphEntity:
    entity_id: str
    entity_type: str
    canonical_name: str
    subtype: str | None = None
    aliases: tuple[str, ...] = ()
    external_identifiers: tuple[tuple[str, str], ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = 0.0
    status: GraphItemStatus = GraphItemStatus.PROPOSED
    support: tuple[EvidenceSpan, ...] = ()
    resolution_notes: tuple[str, ...] = ()
    semantic_support: str = "unreviewed"
    mention_id: str = ""


@dataclass(frozen=True, slots=True)
class GraphRelationship:
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = 0.0
    status: GraphItemStatus = GraphItemStatus.PROPOSED
    support: tuple[EvidenceSpan, ...] = ()
    resolution_notes: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphClaim:
    """A source's assertion, including denials; never an automatic factual verdict."""

    claim_id: str
    subject_entity_id: str
    object_entity_id: str
    predicate: str
    polarity: str = "affirmed"
    modality: str = "asserted"
    valid_from: str | None = None
    valid_until: str | None = None
    asserted_at: str | None = None
    attribution: str = ""
    qualifiers: tuple[tuple[str, str], ...] = ()
    support: tuple[EvidenceSpan, ...] = ()
    confidence: float = 0.0
    status: GraphItemStatus = GraphItemStatus.PROPOSED
    resolution_notes: tuple[str, ...] = ()
    schema_version: int = 1
    epistemic_status: str = "reported"
    claim_kind: str = "relation"
    literal: LiteralValue | None = None
    source: SourceAttribution = SourceAttribution()
    references: tuple[ClaimReference, ...] = ()
    semantic_support: str = "unreviewed"
    review_rationale: str = ""
    typed_qualifiers: tuple[tuple[str, LiteralValue], ...] = ()

    @property
    def allows_missing_object(self) -> bool:
        """Unary event/cessation assertions need no invented second entity."""
        return bool(
            self.literal
            or self.references
            or self.claim_kind == "event"
            or (self.claim_kind == "ceases" and (self.valid_from or self.valid_until))
        )


@dataclass(frozen=True, slots=True)
class ClaimLink:
    """Reviewable comparison, not an adjudication of which source is true."""

    link_id: str
    source_claim_id: str
    target_claim_id: str
    kind: str
    rationale: str
    requires_identity_review: bool = False
    review_state: str = "unreviewed"
    review_rationale: str = ""

    @property
    def requires_joint_context(self) -> bool:
        """Keep meaningful comparison candidates together, not rejected retrieval pairs."""
        return self.review_state in {"unreviewed", "supported"} and self.kind.removeprefix(
            "candidate_"
        ) in {
            "agrees",
            "contradicts",
            "temporal_change",
            "dependent_source",
            "evidence_gap",
            "corrects",
            "retracts",
            "withdraws_certainty",
            "ceases",
        }


@dataclass(frozen=True, slots=True)
class PageGraphAnalysis:
    """Coverage and reusable extraction before any cross-page identity resolution."""

    evidence_id: str
    page_number: int
    text_hash: str
    signature: str
    state: str
    analyzed_at: datetime
    catalog_state: str = "missing"
    catalog_signature: str = ""
    catalog_uses: tuple[str, ...] = ()
    entities: tuple[GraphEntity, ...] = ()
    claims: tuple[GraphClaim, ...] = ()
    model_name: str = ""
    error: str = ""
    cache_origin: str = ""


@dataclass(frozen=True, slots=True)
class GraphEvent:
    """Source-specific event representation; competing records are not silently merged."""

    event_id: str
    event_type: str
    roles: tuple[tuple[str, str], ...]
    claim_ids: tuple[str, ...]
    valid_from: str | None = None
    valid_until: str | None = None
    values: tuple[tuple[str, LiteralValue], ...] = ()
    source: SourceAttribution = SourceAttribution()
    support: tuple[EvidenceSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class InvestigationGraph:
    investigation_id: str
    run_id: str
    entities: tuple[GraphEntity, ...]
    relationships: tuple[GraphRelationship, ...]
    generated_at: datetime
    claims: tuple[GraphClaim, ...] = ()
    claim_links: tuple[ClaimLink, ...] = ()
    pages: tuple[PageGraphAnalysis, ...] = ()
    variant_name: str = ""
    manifest: GraphManifest | None = None
    events: tuple[GraphEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphAnalysisRun:
    run_id: str
    investigation_id: str
    status: GraphRunStatus
    preparation_mode: EvidencePreparationMode
    analysis_language: str
    evidence_total: int
    evidence_completed: int
    evidence_failed: int
    entity_count: int
    relationship_count: int
    model_name: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    last_error: str | None = None
    prompt_version: str = "raven-catalog-claims-v2"
    dictionary_domain: str = "GENERAL_OSINT"
    dictionary_hash: str = ""
    dictionary_versions: tuple[str, ...] = ()
    page_outcomes: tuple[PageGraphAnalysis, ...] = ()
    method_id: str = "legacy"
    variant_name: str = ""
    manifest: GraphManifest | None = None


@dataclass(frozen=True, slots=True)
class GraphAnalysisProgress:
    stage: GraphRunStatus
    completed: int
    total: int
    message: str


@dataclass(frozen=True, slots=True)
class GraphAnalysisResult:
    run: GraphAnalysisRun
    graph: InvestigationGraph
    # Graph extraction outcomes only; never overwrite the document RAG ingestion state.
    evidence_states: tuple[tuple[str, EvidenceIngestionState], ...] = ()


@dataclass(frozen=True, slots=True)
class GraphAnalysisJob:
    """Immutable snapshot exposed by the application graph-analysis queue."""

    job_id: str
    investigation_id: str
    status: GraphJobStatus
    preparation_mode: EvidencePreparationMode
    submitted_at: datetime
    updated_at: datetime
    progress: GraphAnalysisProgress
    result: GraphAnalysisResult | None = None
    error: str | None = None
    method_id: str | None = None
    variant_name: str = ""
