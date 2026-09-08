"""Investigation and evidence knowledge-base value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from raven.exceptions import InvestigationValidationError

DEFAULT_ANALYSIS_DOMAIN = "GENERAL_OSINT"
_DOMAIN_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


class InvestigationStatus(StrEnum):
    """Lifecycle state of an OSINT investigation."""

    DRAFT = "draft"


class AnalysisLanguage(StrEnum):
    """Reference language used to normalize Evidence and all derived analysis."""

    ORIGINAL = "original"
    ITALIAN = "italian"
    ENGLISH = "english"
    FRENCH = "french"
    SPANISH = "spanish"
    GERMAN = "german"
    ARABIC = "arabic"

    @property
    def prompt_label(self) -> str:
        return {
            AnalysisLanguage.ORIGINAL: "the original language of each Evidence",
            AnalysisLanguage.ITALIAN: "Italian",
            AnalysisLanguage.ENGLISH: "English",
            AnalysisLanguage.FRENCH: "French",
            AnalysisLanguage.SPANISH: "Spanish",
            AnalysisLanguage.GERMAN: "German",
            AnalysisLanguage.ARABIC: "Arabic",
        }[self]

    @property
    def language_code(self) -> str | None:
        return {
            AnalysisLanguage.ORIGINAL: None,
            AnalysisLanguage.ITALIAN: "it",
            AnalysisLanguage.ENGLISH: "en",
            AnalysisLanguage.FRENCH: "fr",
            AnalysisLanguage.SPANISH: "es",
            AnalysisLanguage.GERMAN: "de",
            AnalysisLanguage.ARABIC: "ar",
        }[self]


class EvidenceIngestionState(StrEnum):
    """RAG ingestion/verification state, independent of graph extraction outcomes."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    OUTDATED = "outdated"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class InvestigationDomain:
    """One selectable named-entity dictionary domain."""

    code: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class InvestigationDraft:
    """User-provided values required to create an investigation."""

    name: str
    questions: tuple[str, ...]
    description: str = ""
    analysis_language: AnalysisLanguage = AnalysisLanguage.ORIGINAL
    analysis_domain: str = DEFAULT_ANALYSIS_DOMAIN

    def validated(self) -> InvestigationDraft:
        name = self.name.strip()
        description = self.description.strip()
        questions = tuple(question.strip() for question in self.questions if question.strip())
        if not name:
            raise InvestigationValidationError("Investigation name is required")
        if len(name) > 120:
            raise InvestigationValidationError("Investigation name cannot exceed 120 characters")
        if len(description) > 2000:
            raise InvestigationValidationError("Description cannot exceed 2000 characters")
        if not questions:
            raise InvestigationValidationError("Add at least one investigation question")
        if len(questions) > 20:
            raise InvestigationValidationError("An investigation can contain at most 20 questions")
        if any(len(question) > 500 for question in questions):
            raise InvestigationValidationError("Each question cannot exceed 500 characters")
        if len({question.casefold() for question in questions}) != len(questions):
            raise InvestigationValidationError("Investigation questions must be unique")
        analysis_domain = self.analysis_domain.strip().upper()
        if not _DOMAIN_CODE.fullmatch(analysis_domain):
            raise InvestigationValidationError("Select a valid investigation analysis domain")
        return InvestigationDraft(
            name=name,
            description=description,
            questions=questions,
            analysis_language=AnalysisLanguage(self.analysis_language),
            analysis_domain=analysis_domain,
        )


@dataclass(frozen=True, slots=True)
class EvidenceDocument:
    """Immutable metadata for a copied knowledge-base document."""

    document_id: str
    investigation_id: str
    original_name: str
    storage_key: str
    media_type: str
    file_format: str
    size_bytes: int
    sha256: str
    page_count: int | None
    page_count_estimated: bool
    ingestion_state: EvidenceIngestionState
    created_at: datetime

    @property
    def page_label(self) -> str:
        if self.page_count is None:
            return "N/D"
        prefix = "~" if self.page_count_estimated else ""
        return f"{prefix}{self.page_count}"


@dataclass(frozen=True, slots=True)
class Investigation:
    """Created investigation and its isolated evidence knowledge base."""

    investigation_id: str
    name: str
    description: str
    questions: tuple[str, ...]
    status: InvestigationStatus
    evidence_documents: tuple[EvidenceDocument, ...]
    created_at: datetime
    updated_at: datetime
    analysis_language: AnalysisLanguage = AnalysisLanguage.ORIGINAL
    analysis_domain: str = DEFAULT_ANALYSIS_DOMAIN
