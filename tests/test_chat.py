"""Grounding, isolation, and streaming tests for investigation chat."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from raven.exceptions import InvestigationChatError
from raven.models import (
    AnalysisLanguage,
    ChatEventKind,
    ChatMessage,
    ChatRole,
    EvidenceDocument,
    EvidenceIngestionState,
    GraphEntity,
    GraphRelationship,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
    RagIndexProgress,
    RetrievedEvidenceChunk,
    TokenUsage,
)
from raven.services.chat import InvestigationChatService


class FakeRepository:
    def __init__(self) -> None:
        self.states: list[tuple[str, EvidenceIngestionState]] = []
        self.messages: list[ChatMessage] = []

    def set_evidence_ingestion_state(self, document_id: str, state: EvidenceIngestionState) -> None:
        self.states.append((document_id, state))

    def save_chat_message(self, message: ChatMessage) -> None:
        self.messages.append(message)

    def list_chat_messages(self, investigation_id: str, *, limit: int = 100):
        return tuple(
            message
            for message in self.messages[-limit:]
            if message.investigation_id == investigation_id
        )

    def clear_chat_messages(self, investigation_id: str) -> None:
        self.messages = [
            message for message in self.messages if message.investigation_id != investigation_id
        ]


class FakeVectors:
    def __init__(self) -> None:
        self.manifest: dict[str, str] = {}
        self.upserts: list[tuple[EvidenceDocument, tuple[str, ...]]] = []
        self.removed: list[tuple[str, str]] = []
        self.search_investigation_id = ""

    def indexed_document_hashes(self, investigation_id: str) -> dict[str, str]:
        return dict(self.manifest)

    def upsert_document(self, document, chunks, vectors, *, index_signature=None) -> None:
        assert len(chunks) == len(vectors)
        self.upserts.append((document, chunks))
        self.manifest[document.document_id] = index_signature or document.sha256

    def remove_document(self, investigation_id: str, document_id: str) -> None:
        self.removed.append((investigation_id, document_id))

    def remove_investigation(self, investigation_id: str) -> None:
        self.manifest.clear()

    def search(self, investigation_id: str, vector, *, limit: int = 6):
        self.search_investigation_id = investigation_id
        return (
            RetrievedEvidenceChunk(
                "document-id",
                "brief.md",
                0,
                "Acme controls Beta through a majority holding.",
                0.94,
                1,
            ),
        )


class FakeAiNode:
    def __init__(self) -> None:
        self.system_message = ""
        self.messages: list[dict[str, str]] = []

    def embed(self, texts: list[str]):
        return tuple((0.1, 0.2, 0.3) for _ in texts)

    def chat(
        self, system_message: str, user_message: str, *, json_mode: bool = False, **request_options
    ):
        if "Language Detection" in system_message:
            return "en"
        return user_message.split("Evidence:\n", 1)[-1]

    def stream_chat(
        self,
        system_message: str,
        messages: list[dict[str, str]],
        *,
        on_usage=None,
    ):
        self.system_message = system_message
        self.messages = messages
        yield "Acme controls Beta [E1].\n\n"
        yield "```mermaid\nflowchart LR\n  Acme --> Beta\n```"
        if on_usage is not None:
            on_usage(TokenUsage(240, 60, 300))


class FakeKnowledgeBase:
    def extract_text(self, document, cancelled=None):
        return "First paragraph about Acme.\n\nSecond paragraph about Beta."


def _investigation() -> Investigation:
    now = datetime.now(UTC)
    return Investigation(
        investigation_id="00000000-0000-0000-0000-000000000001",
        name="Ownership case",
        description="Trace control",
        questions=("Who controls Beta?",),
        status=InvestigationStatus.DRAFT,
        evidence_documents=(),
        created_at=now,
        updated_at=now,
        analysis_language=AnalysisLanguage.ENGLISH,
        analysis_domain="CORPORATE_OWNERSHIP",
    )


def _document(investigation_id: str) -> EvidenceDocument:
    return EvidenceDocument(
        document_id="document-id",
        investigation_id=investigation_id,
        original_name="brief.md",
        storage_key=f"{investigation_id}/document-id.md",
        media_type="text/markdown",
        file_format="Markdown",
        size_bytes=64,
        sha256="a" * 64,
        page_count=1,
        page_count_estimated=True,
        ingestion_state=EvidenceIngestionState.PENDING,
        created_at=datetime.now(UTC),
    )


def test_index_is_incremental_and_removes_stale_documents() -> None:
    investigation = _investigation()
    document = _document(investigation.investigation_id)
    repository = FakeRepository()
    vectors = FakeVectors()
    vectors.manifest = {"stale-document": "old"}
    service = InvestigationChatService(repository, vectors, FakeAiNode(), FakeKnowledgeBase())
    progress: list[RagIndexProgress] = []

    count = service.index_knowledge_base(investigation, (document,), progress=progress.append)
    service.index_knowledge_base(investigation, (document,))

    assert count == 1
    assert vectors.removed[0] == (investigation.investigation_id, "stale-document")
    assert len(vectors.upserts) == 1
    assert repository.states == [
        (document.document_id, EvidenceIngestionState.PROCESSING),
        (document.document_id, EvidenceIngestionState.READY),
    ]
    assert [update.state for update in progress] == [
        EvidenceIngestionState.PROCESSING,
        EvidenceIngestionState.READY,
    ]
    assert [(update.completed, update.total) for update in progress] == [(0, 1), (1, 1)]


def test_investigation_rag_deletion_reports_backend_failure() -> None:
    class FailingVectors(FakeVectors):
        def remove_investigation(self, investigation_id: str) -> None:
            raise RuntimeError("Qdrant unavailable")

    service = InvestigationChatService(
        FakeRepository(),
        FailingVectors(),
        FakeAiNode(),
        FakeKnowledgeBase(),
    )

    with pytest.raises(InvestigationChatError, match="RAG vectors"):
        service.remove_investigation("investigation-id")


def test_failed_rag_document_is_reported_and_persisted() -> None:
    investigation = _investigation()
    document = _document(investigation.investigation_id)
    repository = FakeRepository()
    progress: list[RagIndexProgress] = []

    class FailingKnowledgeBase:
        def extract_text(self, document, cancelled=None):
            raise OSError("unreadable")

    service = InvestigationChatService(
        repository,
        FakeVectors(),
        FakeAiNode(),
        FailingKnowledgeBase(),
    )

    with pytest.raises(InvestigationChatError):
        service.index_knowledge_base(
            investigation,
            (document,),
            progress=progress.append,
        )

    assert [update.state for update in progress] == [
        EvidenceIngestionState.PROCESSING,
        EvidenceIngestionState.FAILED,
    ]
    assert repository.states == [
        (document.document_id, EvidenceIngestionState.PROCESSING),
        (document.document_id, EvidenceIngestionState.FAILED),
    ]


def test_streamed_answer_injects_retrieved_evidence_and_current_graph() -> None:
    investigation = _investigation()
    document = _document(investigation.investigation_id)
    repository = FakeRepository()
    vectors = FakeVectors()
    ai = FakeAiNode()
    service = InvestigationChatService(repository, vectors, ai, FakeKnowledgeBase())
    graph = InvestigationGraph(
        investigation.investigation_id,
        "run-id",
        (
            GraphEntity("acme", "ORGANIZATION", "Acme", evidence_ids=(document.document_id,)),
            GraphEntity("beta", "ORGANIZATION", "Beta", evidence_ids=(document.document_id,)),
        ),
        (
            GraphRelationship(
                "control",
                "acme",
                "beta",
                "CONTROLS",
                evidence_ids=(document.document_id,),
            ),
        ),
        datetime.now(UTC),
    )

    events = tuple(
        service.stream_answer(
            investigation,
            (document,),
            graph,
            "Explain the ownership and draw it",
        )
    )

    assert vectors.search_investigation_id == investigation.investigation_id
    assert [event.kind for event in events].count(ChatEventKind.TOKEN) == 2
    assert events[-1].kind is ChatEventKind.COMPLETE
    assert events[-1].sources == ("brief.md · chunk 1",)
    assert events[-1].usage == TokenUsage(240, 60, 300)
    assert "Mermaid" in ai.system_message
    assert "Acme controls Beta" in ai.messages[-1]["content"]
    assert '"type":"CONTROLS"' in ai.messages[-1]["content"]
    assert [message.role for message in repository.messages] == [
        ChatRole.USER,
        ChatRole.ASSISTANT,
    ]
    assert "```mermaid" in repository.messages[-1].content
    assert repository.messages[-1].usage == TokenUsage(240, 60, 300)


def test_chunking_preserves_overlap_and_bounds_large_text() -> None:
    text = " ".join(f"word-{index}" for index in range(1200))

    chunks = InvestigationChatService.chunk_text(text, size=500, overlap=80)

    assert len(chunks) > 2
    assert all(200 <= len(chunk) <= 502 for chunk in chunks[:-1])
    assert chunks[0][-40:] in chunks[1]


def test_reference_language_is_part_of_index_signature_and_translates_chunks() -> None:
    investigation = _investigation()
    document = _document(investigation.investigation_id)
    repository = FakeRepository()
    vectors = FakeVectors()
    ai = FakeAiNode()

    def translated_chat(
        system_message: str, user_message: str, *, json_mode: bool = False, **request_options
    ):
        if "Language Detection" in system_message:
            return "it"
        return "Translated Evidence"

    ai.chat = translated_chat
    service = InvestigationChatService(repository, vectors, ai, FakeKnowledgeBase())

    service.index_knowledge_base(investigation, (document,))

    assert vectors.upserts[0][1] == ("Translated Evidence",)
    assert vectors.manifest[document.document_id] == f"{document.sha256}:english"
