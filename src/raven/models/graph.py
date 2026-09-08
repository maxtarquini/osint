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


@dataclass(frozen=True, slots=True)
class InvestigationGraph:
    investigation_id: str
    run_id: str
    entities: tuple[GraphEntity, ...]
    relationships: tuple[GraphRelationship, ...]
    generated_at: datetime


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
    prompt_version: str = "raven-grounded-dev-v1"
    dictionary_domain: str = "GENERAL_OSINT"
    dictionary_hash: str = ""
    dictionary_versions: tuple[str, ...] = ()


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
