"""Safe Markdown export for the latest investigation-chat model response."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from raven.exceptions import InvestigationChatError
from raven.models import Investigation

logger = logging.getLogger(__name__)


class ChatExportService:
    """Render and exclusively create one analyst-selected Markdown export."""

    @staticmethod
    def suggested_filename(investigation: Investigation) -> str:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", investigation.name.strip()).strip("-._")
        return f"{stem or 'raven'}-latest-response.md"

    def save(
        self,
        investigation: Investigation,
        response: str,
        sources: tuple[str, ...],
        destination: Path,
    ) -> Path:
        """Create a Markdown export without overwriting any existing file."""
        if not response.strip():
            raise InvestigationChatError("There is no model response to export")
        destination = destination.expanduser()
        if destination.suffix.lower() != ".md" or destination.name in {".md", "..md"}:
            raise InvestigationChatError("Chat exports must use a valid .md filename")
        try:
            parent = destination.parent.resolve(strict=True)
        except OSError as error:
            raise InvestigationChatError("The selected export folder is unavailable") from error
        if not parent.is_dir():
            raise InvestigationChatError("The selected export location is not a folder")
        target = parent / destination.name
        markdown = self._markdown(investigation, response, sources)
        try:
            with target.open("x", encoding="utf-8", newline="\n") as export:
                export.write(markdown)
            target.chmod(0o600)
        except FileExistsError as error:
            raise InvestigationChatError("The selected Markdown file already exists") from error
        except OSError as error:
            raise InvestigationChatError("Unable to save the Markdown response") from error
        logger.info(
            "Chat response exported. investigation_id=%s source_count=%d",
            investigation.investigation_id,
            len(sources),
        )
        return target

    @staticmethod
    def _markdown(
        investigation: Investigation,
        response: str,
        sources: tuple[str, ...],
    ) -> str:
        source_section = ""
        if sources:
            safe_sources = [" ".join(source.split()) for source in sources]
            source_section = "\n\n## Sources\n\n" + "\n".join(
                f"- {source}" for source in safe_sources
            )
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        return (
            f"# Raven response — {investigation.name}\n\n"
            f"Investigation ID: `{investigation.investigation_id}`  \n"
            f"Exported: `{timestamp}`\n\n"
            f"{response.strip()}"
            f"{source_section}\n"
        )
