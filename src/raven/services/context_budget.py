"""Allocate the complete chat input before selecting evidence or serializing graphs."""

from __future__ import annotations

from dataclasses import dataclass

from raven.exceptions import InvestigationChatError
from raven.models import ChatMessage

# A provider-independent character estimate, not an exact model tokenizer. Reserve
# one quarter of the configured window for generation and count every input frame.
CHARS_PER_INPUT_TOKEN = 3
MESSAGE_ENVELOPE_CHARS = 48
MIN_SOURCE_BUDGET = 1600
MIN_GRAPH_BUDGET = 2000
EMPTY_EVIDENCE_BUDGET = 128
OMITTED_GRAPH_BUDGET = 256


@dataclass(frozen=True, slots=True)
class ContextBudget:
    selected_history: tuple[dict[str, str], ...]
    evidence_budget: int
    graph_budget: int
    input_char_budget: int
    fixed_chars: int
    history_chars: int


def budget_context(
    context_size: int,
    system_text: str,
    question: str,
    status: str,
    history: tuple[ChatMessage, ...],
) -> ContextBudget:
    """Retain complete recent messages, reserving bounded space for source context.

    Questions and system instructions are never silently shortened. Callers must
    fit whole evidence/comparison groups into the returned evidence and graph
    budgets, including their own labels and any empty-context placeholder.
    """
    if type(context_size) is not int or context_size < 1:
        raise InvestigationChatError("Imposta una dimensione valida del contesto del modello.")
    input_char_budget = (context_size * 3 // 4) * CHARS_PER_INPUT_TOKEN
    labels = "QUESTION\n\n\nRETRIEVED EVIDENCE\n\n\nCURRENT INVESTIGATION GRAPH\n"
    if status:
        labels += "\n\nRETRIEVAL STATUS\n"
    fixed_chars = (
        len(system_text) + len(question) + len(status) + len(labels) + 2 * MESSAGE_ENVELOPE_CHARS
    )
    available = input_char_budget - fixed_chars
    if available < MIN_SOURCE_BUDGET:
        raise InvestigationChatError(
            "Il contesto del modello non basta per la domanda, le istruzioni e le fonti. "
            "Riduci la domanda o aumenta il contesto del modello."
        )

    # Do not spend the last space for a usable graph on optional conversation history.
    minimum_sources = (
        MIN_GRAPH_BUDGET + EMPTY_EVIDENCE_BUDGET
        if available >= MIN_GRAPH_BUDGET + EMPTY_EVIDENCE_BUDGET
        else MIN_SOURCE_BUDGET
    )
    history_budget = min(6000, available // 6, available - minimum_sources)
    selected: list[dict[str, str]] = []
    history_chars = 0
    for message in reversed(history[-12:]):
        cost = len(message.content) + MESSAGE_ENVELOPE_CHARS
        if history_chars + cost > history_budget:
            break
        selected.append({"role": message.role.value, "content": message.content})
        history_chars += cost
    selected.reverse()
    remaining = available - history_chars
    if remaining >= MIN_GRAPH_BUDGET + EMPTY_EVIDENCE_BUDGET:
        graph_budget = max(MIN_GRAPH_BUDGET, remaining * 2 // 5)
    else:
        # The caller can emit a valid omitted-graph object rather than partial JSON.
        graph_budget = min(OMITTED_GRAPH_BUDGET, remaining // 5)
    evidence_budget = remaining - graph_budget
    return ContextBudget(
        tuple(selected),
        evidence_budget,
        graph_budget,
        input_char_budget,
        fixed_chars,
        history_chars,
    )
