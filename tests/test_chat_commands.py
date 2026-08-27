"""Local slash-command parsing and Markdown export safety."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from raven.exceptions import InvestigationChatError
from raven.models import Investigation, InvestigationStatus
from raven.services import ChatExportService
from raven.tui.actions import ChatCommand, ChatCommandError, parse_chat_command


def _investigation() -> Investigation:
    now = datetime.now(UTC)
    return Investigation(
        investigation_id="investigation-id",
        name="Operation Raven / Alpha",
        description="",
        questions=("Who?",),
        status=InvestigationStatus.DRAFT,
        evidence_documents=(),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("value", ("/new", " /NEW ", "/NeW"))
def test_chat_commands_are_case_insensitive(value: str) -> None:
    assert parse_chat_command(value) is ChatCommand.NEW


def test_chat_command_parser_keeps_regular_prompts_and_rejects_unknown_commands() -> None:
    assert parse_chat_command("Explain /INFO in the evidence") is None
    with pytest.raises(ChatCommandError, match="/SAVE"):
        parse_chat_command("/unknown")


def test_markdown_export_creates_new_file_with_response_and_sources(tmp_path) -> None:
    service = ChatExportService()
    investigation = _investigation()
    destination = tmp_path / "answer.md"

    saved = service.save(
        investigation,
        "## Finding\n\nEvidence-grounded result.",
        ("report.pdf · chunk 1",),
        destination,
    )

    content = saved.read_text()
    assert saved == destination
    assert "# Raven response" in content
    assert "Evidence-grounded result" in content
    assert "report.pdf · chunk 1" in content
    assert service.suggested_filename(investigation) == "Operation-Raven-Alpha-latest-response.md"


def test_markdown_export_never_overwrites_existing_file(tmp_path) -> None:
    destination = tmp_path / "answer.md"
    destination.write_text("keep")

    with pytest.raises(InvestigationChatError, match="already exists"):
        ChatExportService().save(_investigation(), "new answer", (), destination)

    assert destination.read_text() == "keep"
