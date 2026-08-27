"""Investigation creation and independent evidence-management tests."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter

from raven.exceptions import (
    InvestigationCancelledError,
    InvestigationPersistenceError,
    InvestigationValidationError,
)
from raven.models import (
    AnalysisLanguage,
    EvidenceDocument,
    EvidenceIngestionState,
    Investigation,
    InvestigationDraft,
)
from raven.repositories import KnowledgeBaseStore
from raven.services import InvestigationService


class InvestigationRepository:
    def __init__(self, *, evidence_fails: bool = False) -> None:
        self.evidence_fails = evidence_fails
        self.created: Investigation | None = None
        self.documents: list[EvidenceDocument] = []
        self.graph_cleared = False

    def create_investigation(self, investigation: Investigation) -> None:
        self.created = investigation

    def add_evidence(self, document: EvidenceDocument) -> None:
        if self.evidence_fails:
            raise InvestigationPersistenceError("MongoDB unavailable")
        self.documents.append(document)

    def update_investigation(self, investigation: Investigation) -> None:
        self.created = investigation

    def delete_investigation(self, investigation_id: str) -> None:
        self.created = None
        self.documents.clear()

    def clear_graph_data(self, investigation_id: str) -> None:
        self.graph_cleared = True

    def reset_evidence_ingestion_states(self, investigation_id: str) -> None:
        self.documents = [
            EvidenceDocument(
                document.document_id,
                document.investigation_id,
                document.original_name,
                document.storage_key,
                document.media_type,
                document.file_format,
                document.size_bytes,
                document.sha256,
                document.page_count,
                document.page_count_estimated,
                EvidenceIngestionState.PENDING,
                document.created_at,
            )
            for document in self.documents
        ]

    def delete_evidence(self, document: EvidenceDocument) -> None:
        self.documents.remove(document)

    def list_investigations(self) -> tuple[Investigation, ...]:
        return (self.created,) if self.created is not None else ()


def make_pdf(path: Path) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output:
        writer.write(output)
    return path


def make_docx(path: Path, pages: int = 3) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "docProps/app.xml",
            "<Properties xmlns='http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'>"
            f"<Pages>{pages}</Pages></Properties>",
        )
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
            "<w:body><w:p><w:r><w:t>Evidence</w:t></w:r></w:p></w:body></w:document>",
        )
    return path


def make_markdown(path: Path) -> Path:
    path.write_text(" ".join(["evidence"] * 600))
    return path


def create_investigation(service: InvestigationService) -> Investigation:
    return service.create(
        InvestigationDraft(
            name=" Operation Raven ",
            description=" Initial context ",
            questions=("Who coordinated the event?", "When did it begin?"),
        )
    )


def test_investigation_creation_preallocates_isolated_knowledge_base(tmp_path: Path) -> None:
    repository = InvestigationRepository()
    knowledge_root = tmp_path / "knowledge-bases"
    service = InvestigationService(repository, KnowledgeBaseStore(knowledge_root))

    investigation = create_investigation(service)

    assert repository.created == investigation
    assert investigation.name == "Operation Raven"
    assert investigation.analysis_domain == "GENERAL_OSINT"
    assert investigation.evidence_documents == ()
    assert (knowledge_root / investigation.investigation_id).is_dir()
    assert not list((knowledge_root / investigation.investigation_id).iterdir())
    assert service.list_investigations() == (investigation,)


def test_add_evidence_extracts_format_and_page_metadata(tmp_path: Path) -> None:
    repository = InvestigationRepository()
    knowledge_root = tmp_path / "knowledge-bases"
    service = InvestigationService(repository, KnowledgeBaseStore(knowledge_root))
    investigation = create_investigation(service)
    paths = (
        make_pdf(tmp_path / "report.pdf"),
        make_docx(tmp_path / "notes.docx"),
        make_markdown(tmp_path / "timeline.md"),
    )

    documents = tuple(service.add_evidence(investigation.investigation_id, path) for path in paths)

    assert repository.documents == list(documents)
    assert [(item.file_format, item.page_label) for item in documents] == [
        ("PDF", "1"),
        ("DOCX", "3"),
        ("Markdown", "~2"),
    ]
    assert all(len(document.sha256) == 64 for document in documents)
    assert len(list((knowledge_root / investigation.investigation_id).iterdir())) == 3


def test_evidence_metadata_failure_removes_only_new_raven_copy(tmp_path: Path) -> None:
    repository = InvestigationRepository(evidence_fails=True)
    knowledge_root = tmp_path / "knowledge-bases"
    service = InvestigationService(repository, KnowledgeBaseStore(knowledge_root))
    investigation = create_investigation(service)
    source = make_pdf(tmp_path / "report.pdf")

    with pytest.raises(InvestigationPersistenceError, match="MongoDB"):
        service.add_evidence(investigation.investigation_id, source)

    assert source.exists()
    assert not list((knowledge_root / investigation.investigation_id).iterdir())


def test_evidence_upload_can_be_cancelled(tmp_path: Path) -> None:
    repository = InvestigationRepository()
    service = InvestigationService(
        repository,
        KnowledgeBaseStore(tmp_path / "knowledge-bases"),
    )
    investigation = create_investigation(service)

    with pytest.raises(InvestigationCancelledError):
        service.add_evidence(
            investigation.investigation_id,
            make_pdf(tmp_path / "report.pdf"),
            cancelled=lambda: True,
        )

    assert repository.documents == []


def test_delete_evidence_removes_raven_copy_but_preserves_source(tmp_path: Path) -> None:
    repository = InvestigationRepository()
    knowledge_root = tmp_path / "knowledge-bases"
    service = InvestigationService(repository, KnowledgeBaseStore(knowledge_root))
    investigation = create_investigation(service)
    source = make_markdown(tmp_path / "notes.md")
    document = service.add_evidence(investigation.investigation_id, source)

    service.delete_evidence(document)

    assert source.exists()
    assert repository.documents == []
    assert not (knowledge_root / document.storage_key).exists()


def test_unsupported_evidence_format_is_rejected_after_creation(tmp_path: Path) -> None:
    unsupported = tmp_path / "raw.txt"
    unsupported.write_text("not accepted")
    service = InvestigationService(
        InvestigationRepository(),
        KnowledgeBaseStore(tmp_path / "knowledge-bases"),
    )
    investigation = create_investigation(service)

    with pytest.raises(InvestigationValidationError, match="Unsupported"):
        service.add_evidence(investigation.investigation_id, unsupported)


def test_draft_requires_unique_questions_but_not_evidence() -> None:
    with pytest.raises(InvestigationValidationError, match="unique"):
        InvestigationDraft(name="Case", questions=("Who?", " who? ")).validated()

    draft = InvestigationDraft(name="Case", questions=("Who?",)).validated()
    assert draft.name == "Case"


def test_draft_normalizes_and_validates_analysis_domain() -> None:
    draft = InvestigationDraft(
        name="Case",
        questions=("Who?",),
        analysis_domain=" maritime_intelligence ",
    ).validated()

    assert draft.analysis_domain == "MARITIME_INTELLIGENCE"

    with pytest.raises(InvestigationValidationError, match="analysis domain"):
        InvestigationDraft(
            name="Case",
            questions=("Who?",),
            analysis_domain="not a domain",
        ).validated()


def test_update_changes_reference_language_and_dictionary_and_invalidates_analysis(
    tmp_path: Path,
) -> None:
    repository = InvestigationRepository()
    service = InvestigationService(repository, KnowledgeBaseStore(tmp_path / "knowledge-bases"))
    investigation = create_investigation(service)
    document = service.add_evidence(
        investigation.investigation_id,
        make_markdown(tmp_path / "notes.md"),
    )
    current = Investigation(
        investigation.investigation_id,
        investigation.name,
        investigation.description,
        investigation.questions,
        investigation.status,
        (document,),
        investigation.created_at,
        investigation.updated_at,
        investigation.analysis_language,
        investigation.analysis_domain,
    )

    updated = service.update(
        current,
        InvestigationDraft(
            name="Updated Raven",
            description="Revised scope",
            questions=("Where?",),
            analysis_language=AnalysisLanguage.ITALIAN,
            analysis_domain="MARITIME_INTELLIGENCE",
        ),
    )

    assert updated.name == "Updated Raven"
    assert updated.analysis_language is AnalysisLanguage.ITALIAN
    assert updated.analysis_domain == "MARITIME_INTELLIGENCE"
    assert updated.evidence_documents[0].ingestion_state is EvidenceIngestionState.PENDING
    assert repository.graph_cleared


def test_delete_removes_only_raven_investigation_directory(tmp_path: Path) -> None:
    repository = InvestigationRepository()
    knowledge_root = tmp_path / "knowledge-bases"
    service = InvestigationService(repository, KnowledgeBaseStore(knowledge_root))
    investigation = create_investigation(service)
    source = make_markdown(tmp_path / "source.md")
    service.add_evidence(investigation.investigation_id, source)

    service.delete(investigation)

    assert repository.created is None
    assert source.exists()
    assert not (knowledge_root / investigation.investigation_id).exists()
