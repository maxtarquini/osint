"""Prompt budgeting counts system, question, status and complete history frames."""

from datetime import UTC, datetime

import pytest

from raven.exceptions import InvestigationChatError
from raven.models import ChatMessage, ChatRole
from raven.services.context_budget import (
    MESSAGE_ENVELOPE_CHARS,
    MIN_GRAPH_BUDGET,
    MIN_SOURCE_BUDGET,
    budget_context,
)


def history_message(index, content):
    return ChatMessage(str(index), "case", ChatRole.USER, content, datetime.now(UTC))


def test_every_allocated_character_is_accounted_for_with_output_reserve():
    budget = budget_context(32768, "system" * 300, "Acme?", "retrieving", ())

    assert budget.input_char_budget == (32768 * 3 // 4) * 3
    assert (
        budget.fixed_chars + budget.history_chars + budget.evidence_budget + budget.graph_budget
        == budget.input_char_budget
    )
    assert budget.evidence_budget >= 128
    assert budget.graph_budget >= MIN_GRAPH_BUDGET


@pytest.mark.parametrize(
    "system,question,status",
    [
        ("s" * 2700, "q" * 8000, ""),
        ("s" * 8000, "Acme?", ""),
        ("s" * 2700, "Acme?", "w" * 8000),
    ],
)
def test_oversized_fixed_input_has_clear_error_instead_of_shortening_question(
    system, question, status
):
    with pytest.raises(InvestigationChatError, match="Riduci la domanda o aumenta il contesto"):
        budget_context(3000, system, question, status, ())


def test_tiny_window_reports_insufficient_room_for_instructions_and_sources():
    with pytest.raises(InvestigationChatError, match="contesto del modello non basta"):
        budget_context(512, "System instructions", "Acme?", "", ())


def test_system_and_status_reduce_available_source_space():
    first = budget_context(4096, "system", "Acme?", "status", ())
    second = budget_context(4096, "system" + "x" * 1000, "Acme?", "status" + "y" * 100, ())

    assert (
        second.evidence_budget + second.graph_budget
        == first.evidence_budget + first.graph_budget - 1100
    )


def test_history_is_a_complete_recent_suffix_with_every_envelope_charged():
    history = tuple(history_message(index, f"Message {index}. " + "x" * 390) for index in range(8))
    budget = budget_context(4096, "s" * 2000, "Acme?", "", history)

    count = len(budget.selected_history)
    assert 0 < count < len(history)
    assert [row["content"] for row in budget.selected_history] == [
        row.content for row in history[-count:]
    ]
    assert budget.history_chars == sum(
        len(row["content"]) + MESSAGE_ENVELOPE_CHARS for row in budget.selected_history
    )
    assert budget.history_chars <= (budget.input_char_budget - budget.fixed_chars) // 6
    assert budget.evidence_budget + budget.graph_budget >= MIN_SOURCE_BUDGET


def test_oversized_latest_history_message_is_dropped_without_retaining_stale_older_frames():
    history = (history_message(1, "old small question"), history_message(2, "x" * 7000))
    budget = budget_context(4096, "System", "Acme?", "", history)

    assert budget.selected_history == () and budget.history_chars == 0


def test_history_never_exceeds_twelve_frames():
    history = tuple(history_message(index, str(index)) for index in range(20))
    budget = budget_context(32768, "System", "Acme?", "", history)

    assert len(budget.selected_history) == 12
    assert budget.selected_history[0]["content"] == "8"


def test_small_source_budget_reserves_space_for_omitted_graph_json():
    budget = budget_context(1000, "", "Acme?", "", ())

    assert 0 < budget.graph_budget < MIN_GRAPH_BUDGET
    assert budget.evidence_budget + budget.graph_budget >= MIN_SOURCE_BUDGET
