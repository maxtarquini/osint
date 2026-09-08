"""Value objects for an Evidence- and graph-grounded investigation chat."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from raven.models.investigation import EvidenceIngestionState


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-reported token counts for one model response."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class RagIndexProgress:
    """Per-document progress emitted while synchronizing an investigation RAG index."""

    document_id: str
    document_name: str
    state: EvidenceIngestionState
    completed: int
    total: int


@dataclass(frozen=True, slots=True)
class ChatMessage:
    message_id: str
    investigation_id: str
    role: ChatRole
    content: str
    created_at: datetime
    sources: tuple[str, ...] = ()
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class RetrievedEvidenceChunk:
    document_id: str
    document_name: str
    chunk_index: int
    text: str
    score: float
    page_count: int | None = None
    page_number: int | None = None
    original_text: str | None = None
    index_signature: str | None = None
    investigation_id: str | None = None


class ChatEventKind(StrEnum):
    STATUS = "status"
    TOKEN = "token"
    SOURCES = "sources"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ChatStreamEvent:
    kind: ChatEventKind
    text: str = ""
    sources: tuple[str, ...] = ()
    usage: TokenUsage | None = None
