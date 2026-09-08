"""Grounding, isolation, and streaming tests for investigation chat."""

from __future__ import annotations

from dataclasses import replace
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

    def set_evidence_rag_state(self, document_id: str, state: EvidenceIngestionState) -> None:
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
        self.vector_size = 3
        self.manifest: dict[str, str] = {}
        self.upserts: list[tuple[EvidenceDocument, tuple[str, ...]]] = []
        self.chunk_counts: dict[str, int] = {}
        self.removed: list[tuple[str, str]] = []
        self.search_investigation_id = ""

    def indexed_document_hashes(self, investigation_id: str) -> dict[str, str]:
        return dict(self.manifest)

    def upsert_document(
        self,
        document,
        chunks,
        vectors,
        *,
        index_signature=None,
        page_numbers=None,
    ) -> None:
        assert len(chunks) == len(vectors)
        assert page_numbers is None or len(page_numbers) == len(chunks)
        self.upserts.append((document, chunks))
        self.manifest[document.document_id] = index_signature or document.sha256
        self.chunk_counts[document.document_id] = len(chunks)

    def document_chunk_count(self, investigation_id: str, document_id: str) -> int:
        return self.chunk_counts.get(document_id, 0)

    def remove_document(self, investigation_id: str, document_id: str) -> None:
        self.removed.append((investigation_id, document_id))
        self.manifest.pop(document_id, None)
        self.chunk_counts.pop(document_id, None)

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

    def chat(self, system_message: str, user_message: str, *, json_mode: bool = False, **options):
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

    def extract_pages(self, document, cancelled=None):
        return (self.extract_text(document, cancelled),)


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
        (document.document_id, EvidenceIngestionState.READY),
    ]
    assert progress[0].detail == "Checking embedding compatibility"
    assert progress[-1].state is EvidenceIngestionState.READY
    assert progress[-1].detail == "Verified 1 chunks in Qdrant"
    assert progress[-1].chunk_count == 1
    assert (progress[-1].completed, progress[-1].total) == (1, 1)


def test_embedding_dimension_mismatch_fails_before_document_processing() -> None:
    investigation = _investigation()
    document = _document(investigation.investigation_id)
    repository = FakeRepository()
    vectors = FakeVectors()
    vectors.vector_size = 1536
    progress: list[RagIndexProgress] = []

    with pytest.raises(InvestigationChatError, match="model returns 3.*expects 1536"):
        InvestigationChatService(
            repository,
            vectors,
            FakeAiNode(),
            FakeKnowledgeBase(),
        ).index_knowledge_base(investigation, (document,), progress=progress.append)

    assert vectors.upserts == []
    assert repository.states == [(document.document_id, EvidenceIngestionState.FAILED)]
    assert progress[-1].state is EvidenceIngestionState.FAILED
    assert "dimension mismatch" in progress[-1].detail


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
        def extract_pages(self, document, cancelled=None):
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

    assert progress[0].state is EvidenceIngestionState.PROCESSING
    assert progress[0].detail == "Checking embedding compatibility"
    assert progress[-1].state is EvidenceIngestionState.FAILED
    assert progress[-1].detail == "Unable to complete the Evidence indexing stage"
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
    assert events[-1].sources == ("[E1] brief.md · chunk 1",)
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
        system_message: str, user_message: str, *, json_mode: bool = False, **options
    ):
        if "Language Detection" in system_message:
            return "it"
        return "Translated Evidence"

    ai.chat = translated_chat
    service = InvestigationChatService(repository, vectors, ai, FakeKnowledgeBase())

    service.index_knowledge_base(investigation, (document,))

    assert vectors.upserts[0][1] == ("Translated Evidence",)
    original_signature = vectors.manifest[document.document_id]
    service.index_knowledge_base(investigation, (document,))
    assert len(vectors.upserts) == 1
    service.index_knowledge_base(
        replace(investigation, analysis_language=AnalysisLanguage.ITALIAN), (document,)
    )
    assert len(vectors.upserts) == 2
    assert vectors.manifest[document.document_id] != original_signature


def test_rag_translation_has_bounded_requests_and_reports_each_chunk():
    from raven.config import AiThinkingLevel

    class TranslatingNode(FakeAiNode):
        def __init__(self):
            super().__init__()
            self.calls = []

        def chat(self, system_message, user_message, **options):
            self.calls.append(options)
            return "it" if "Language Detection" in system_message else "Translated passage"

    node = TranslatingNode()
    service = InvestigationChatService(FakeRepository(), FakeVectors(), node, FakeKnowledgeBase())
    case = replace(_investigation(), analysis_language=AnalysisLanguage.ENGLISH)
    updates = []

    def cancelled():
        return False

    chunks = service._normalize_chunks(
        case,
        ("Primo passaggio", "Secondo passaggio"),
        cancelled,
        on_chunk=lambda n, total: updates.append((n, total)),
    )
    assert chunks == ("Translated passage", "Translated passage")
    assert updates == [(1, 2), (2, 2)]
    assert node.calls[0]["timeout_seconds"] == 60
    assert all(call["timeout_seconds"] == 120 for call in node.calls[1:])
    assert all(call["thinking"] is AiThinkingLevel.LOW for call in node.calls)
    assert all(call["cancelled"] is cancelled for call in node.calls)
    assert all(call["max_output_tokens"] > 0 for call in node.calls)
