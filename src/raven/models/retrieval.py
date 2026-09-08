"""Scoped retrieval selections and safe diagnostics for investigation answers."""

from dataclasses import dataclass

from raven.models.chat import RetrievedEvidenceChunk
from raven.models.graph import InvestigationGraph


@dataclass(frozen=True, slots=True)
class GraphRetrievalSelection:
    investigation_id: str
    run_id: str | None
    entity_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    relationship_ids: tuple[str, ...] = ()
    comparison_ids: tuple[str, ...] = ()
    state: str = "ready"
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    strategy: str
    vector_hits: int = 0
    graph_claims: int = 0
    graph_entities: int = 0
    linked_sources: int = 0
    elapsed_ms: float = 0
    warnings: tuple[str, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class HybridRetrievalResult:
    chunks: tuple[RetrievedEvidenceChunk, ...]
    graph: InvestigationGraph | None
    trace: RetrievalTrace
