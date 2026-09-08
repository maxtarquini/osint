"""Local evidence storage isolated by investigation identifier."""

from __future__ import annotations

import hashlib
import math
import mimetypes
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import olefile
from platformdirs import user_data_path
from pypdf import PdfReader

from raven.exceptions import (
    InvestigationCancelledError,
    InvestigationPersistenceError,
    InvestigationValidationError,
)
from raven.models import EvidenceDocument, EvidenceIngestionState

SUPPORTED_EVIDENCE_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".md", ".markdown"})
MAX_EVIDENCE_SIZE_BYTES = 100 * 1024 * 1024
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class KnowledgeBaseStore:
    """Copy and remove individual documents in per-investigation directories."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or user_data_path("raven", appauthor=False) / "knowledge_bases").resolve()

    def configure_root(self, root: Path) -> None:
        """Switch future Evidence operations to a validated, writable directory."""
        resolved = root.expanduser().resolve()
        self._ensure_directory(resolved)
        self.root = resolved

    def investigation_directory(self, investigation_id: str, *, create: bool = False) -> Path:
        """Resolve the isolated directory for an investigation."""
        UUID(investigation_id)
        directory = self.root / investigation_id
        if create:
            self._ensure_directory(directory)
        return directory

    @staticmethod
    def _ensure_directory(directory: Path) -> None:
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as error:
            raise InvestigationPersistenceError(
                "Unable to create the Evidence storage directory"
            ) from error
        if not directory.is_dir():
            raise InvestigationPersistenceError("Evidence storage path is not a directory")

    def add(
        self,
        investigation_id: str,
        source: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> EvidenceDocument:
        UUID(investigation_id)
        source = self._validated_source(source)
        document_id = str(uuid4())
        stored_name = f"{document_id}{source.suffix.lower()}"
        directory = self.investigation_directory(investigation_id, create=True)
        temporary = directory / f".{stored_name}.upload"
        destination = directory / stored_name

        try:
            digest = self._copy_and_hash(source, temporary, cancelled)
            temporary.replace(destination)
            page_count, estimated = self._page_info(destination)
        except InvestigationCancelledError:
            temporary.unlink(missing_ok=True)
            raise
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise InvestigationPersistenceError("Unable to store evidence document") from error

        return EvidenceDocument(
            document_id=document_id,
            investigation_id=investigation_id,
            original_name=source.name,
            storage_key=f"{investigation_id}/{stored_name}",
            media_type=self._media_type(source),
            file_format=self._format(source),
            size_bytes=source.stat().st_size,
            sha256=digest,
            page_count=page_count,
            page_count_estimated=estimated,
            ingestion_state=EvidenceIngestionState.PENDING,
            created_at=datetime.now(UTC),
        )

    def discard_document(self, document: EvidenceDocument) -> None:
        self._document_path(document).unlink(missing_ok=True)

    def extract_text(
        self,
        document: EvidenceDocument,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Extract normalized text from Raven's immutable Evidence copy."""
        path = self._document_path(document)
        try:
            suffix = path.suffix.lower()
            if suffix in {".md", ".markdown"}:
                text = path.read_text(encoding="utf-8", errors="replace")
            elif suffix == ".pdf":
                text = self._pdf_text(path, cancelled)
            elif suffix == ".docx":
                text = self._docx_text(path)
            elif suffix == ".doc":
                text = self._legacy_doc_text(path)
            else:
                raise InvestigationValidationError(
                    f"Unsupported evidence format: {path.suffix or path.name}"
                )
        except InvestigationCancelledError:
            raise
        except InvestigationValidationError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError(
                f"Unable to extract text from evidence: {document.original_name}"
            ) from error
        if cancelled is not None and cancelled():
            raise InvestigationCancelledError("Evidence analysis cancelled")
        return self._normalize_text(text)

    def extract_pages(
        self,
        document: EvidenceDocument,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[str, ...]:
        """Preserve PDF page positions, including blank pages; other formats are one text unit."""
        path = self._document_path(document)
        if path.suffix.lower() != ".pdf":
            text = self.extract_text(document, cancelled)
            return (text,) if text else ()
        pages: list[str] = []
        try:
            for page in PdfReader(path).pages:
                if cancelled is not None and cancelled():
                    raise InvestigationCancelledError("Evidence analysis cancelled")
                pages.append(self._normalize_text(page.extract_text() or ""))
        except InvestigationCancelledError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError(
                f"Unable to extract text from evidence: {document.original_name}"
            ) from error
        return tuple(pages)

    def stage_delete(self, document: EvidenceDocument) -> Path:
        source = self._document_path(document)
        if not source.is_file():
            raise InvestigationPersistenceError("Stored evidence document is missing")
        staged = source.with_name(f".{source.name}.delete-{uuid4()}")
        try:
            source.replace(staged)
        except OSError as error:
            raise InvestigationPersistenceError("Unable to prepare evidence deletion") from error
        return staged

    def restore_delete(self, document: EvidenceDocument, staged: Path) -> None:
        try:
            staged.replace(self._document_path(document))
        except OSError as error:
            raise InvestigationPersistenceError("Unable to restore evidence document") from error

    def commit_delete(self, staged: Path) -> None:
        try:
            staged.unlink(missing_ok=True)
        except OSError as error:
            raise InvestigationPersistenceError("Unable to finalize evidence deletion") from error

    def stage_investigation_delete(self, investigation_id: str) -> Path | None:
        """Move one isolated investigation directory aside before metadata deletion."""
        directory = self.investigation_directory(investigation_id)
        if not directory.exists():
            return None
        staged = self.root / f".{investigation_id}.delete-{uuid4()}"
        try:
            directory.replace(staged)
        except OSError as error:
            raise InvestigationPersistenceError(
                "Unable to prepare investigation Evidence deletion"
            ) from error
        return staged

    def restore_investigation_delete(
        self,
        investigation_id: str,
        staged: Path | None,
    ) -> None:
        if staged is None or not staged.exists():
            return
        try:
            staged.replace(self.investigation_directory(investigation_id))
        except OSError as error:
            raise InvestigationPersistenceError(
                "Unable to restore the investigation Evidence directory"
            ) from error

    def commit_investigation_delete(self, staged: Path | None) -> None:
        if staged is None:
            return
        try:
            shutil.rmtree(staged)
        except OSError as error:
            raise InvestigationPersistenceError(
                "Unable to finalize investigation Evidence deletion"
            ) from error

    @staticmethod
    def _validated_source(path: Path) -> Path:
        source = path.expanduser().resolve()
        if not source.is_file():
            raise InvestigationValidationError(f"Evidence file does not exist: {source.name}")
        if source.suffix.lower() not in SUPPORTED_EVIDENCE_EXTENSIONS:
            raise InvestigationValidationError(
                f"Unsupported evidence format: {source.suffix or source.name}"
            )
        if source.stat().st_size > MAX_EVIDENCE_SIZE_BYTES:
            raise InvestigationValidationError(f"Evidence file exceeds 100 MiB: {source.name}")
        return source

    @staticmethod
    def _copy_and_hash(
        source: Path,
        destination: Path,
        cancelled: Callable[[], bool] | None,
    ) -> str:
        digest = hashlib.sha256()
        with source.open("rb") as source_file, destination.open("xb") as destination_file:
            while chunk := source_file.read(1024 * 1024):
                if cancelled is not None and cancelled():
                    raise InvestigationCancelledError("Evidence upload cancelled")
                destination_file.write(chunk)
                digest.update(chunk)
        destination.chmod(0o600)
        return digest.hexdigest()

    @classmethod
    def _page_info(cls, path: Path) -> tuple[int | None, bool]:
        try:
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                return len(PdfReader(path).pages), False
            if suffix == ".docx":
                return cls._docx_pages(path)
            if suffix == ".doc":
                with olefile.OleFileIO(path) as document:
                    pages = document.get_metadata().num_pages
                return (int(pages), False) if pages else (None, False)
            if suffix in {".md", ".markdown"}:
                words = len(path.read_text(encoding="utf-8", errors="replace").split())
                return max(1, math.ceil(words / 500)), True
        except (BadZipFile, OSError, ValueError, TypeError):
            return None, False
        except Exception:
            return None, False
        return None, False

    @classmethod
    def _docx_pages(cls, path: Path) -> tuple[int | None, bool]:
        with ZipFile(path) as archive:
            try:
                properties = ElementTree.fromstring(archive.read("docProps/app.xml"))
                pages = properties.findtext(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Pages"
                )
                if pages and int(pages) > 0:
                    return int(pages), False
            except (KeyError, ElementTree.ParseError, ValueError):
                pass
            document = ElementTree.fromstring(archive.read("word/document.xml"))
            words = sum(
                len((node.text or "").split()) for node in document.iter(f"{_WORD_NAMESPACE}t")
            )
            return max(1, math.ceil(words / 500)), True

    @staticmethod
    def _pdf_text(path: Path, cancelled: Callable[[], bool] | None) -> str:
        pages: list[str] = []
        for page in PdfReader(path).pages:
            if cancelled is not None and cancelled():
                raise InvestigationCancelledError("Evidence analysis cancelled")
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)

    @staticmethod
    def _docx_text(path: Path) -> str:
        with ZipFile(path) as archive:
            document = ElementTree.fromstring(archive.read("word/document.xml"))
        paragraphs: list[str] = []
        for paragraph in document.iter(f"{_WORD_NAMESPACE}p"):
            content = "".join(
                node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")
            ).strip()
            if content:
                paragraphs.append(content)
        return "\n".join(paragraphs)

    @staticmethod
    def _legacy_doc_text(path: Path) -> str:
        """Recover printable runs from the binary Word stream without executing converters."""
        with olefile.OleFileIO(path) as document:
            if not document.exists("WordDocument"):
                return ""
            payload = document.openstream("WordDocument").read()
        unicode_runs = [
            match.group().decode("utf-16-le", errors="ignore")
            for match in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", payload)
        ]
        ascii_runs = [
            match.group().decode("cp1252", errors="ignore")
            for match in re.finditer(rb"[\x20-\x7e]{6,}", payload)
        ]
        return "\n".join((*unicode_runs, *ascii_runs))

    @staticmethod
    def _normalize_text(text: str) -> str:
        lines = [
            re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")
        ]
        normalized: list[str] = []
        previous_blank = True
        for line in lines:
            if line:
                normalized.append(line)
                previous_blank = False
            elif not previous_blank:
                normalized.append("")
                previous_blank = True
        return "\n".join(normalized).strip()

    def _document_path(self, document: EvidenceDocument) -> Path:
        key = PurePosixPath(document.storage_key)
        if key.is_absolute() or len(key.parts) != 2 or key.parts[0] != document.investigation_id:
            raise InvestigationPersistenceError("Invalid evidence storage key")
        path = self.root.joinpath(*key.parts)
        if path.parent != self.root / document.investigation_id:
            raise InvestigationPersistenceError("Invalid evidence storage path")
        return path

    @staticmethod
    def _format(path: Path) -> str:
        return {
            ".pdf": "PDF",
            ".doc": "DOC",
            ".docx": "DOCX",
            ".md": "Markdown",
            ".markdown": "Markdown",
        }[path.suffix.lower()]

    @staticmethod
    def _media_type(path: Path) -> str:
        known_types = {
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pdf": "application/pdf",
        }
        return (
            known_types.get(path.suffix.lower())
            or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )
