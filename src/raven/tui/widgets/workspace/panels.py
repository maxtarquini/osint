"""Presentation-only panels used by the investigation workspace."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, LoadingIndicator, Static, TabPane, TextArea

from raven.models import EvidenceDocument, Investigation
from raven.tui.copy import copy
from raven.tui.widgets.evidence import EvidenceRow
from raven.tui.widgets.graph import GraphCanvas
from raven.tui.widgets.graph_activity import GraphBuildActivity
from raven.tui.widgets.resizable_split import PaneDivider, ResizableSplit


def count_label(documents: list[EvidenceDocument]) -> str:
    count = len(documents)
    return f"{count} document" if count == 1 else f"{count} documents"


class OverviewPanel(TabPane):
    def __init__(self, investigation: Investigation, profile_label: str) -> None:
        super().__init__("Overview / Settings", id="workspace-overview-tab")
        self.investigation = investigation
        self.profile_label = profile_label

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="workspace-overview"):
            with Horizontal(id="overview-case-actions"):
                yield Static(
                    "Profile changes reprocess Evidence and invalidate the derived graph.",
                    id="overview-case-actions-hint",
                )
                yield Button("Edit configuration", id="edit-investigation")
                yield Button("Delete investigation", id="delete-investigation", variant="error")
            with Horizontal(id="overview-grid"):
                with Vertical(classes="overview-card", id="overview-brief-card"):
                    yield Static("CASE BRIEF", classes="panel-title")
                    yield Static(
                        self.investigation.description or "No context provided",
                        id="workspace-description",
                        markup=False,
                    )
                with Vertical(classes="overview-card", id="overview-profile-card"):
                    yield Static("ANALYSIS PROFILE", classes="panel-title")
                    yield Static(self.profile_label, id="workspace-profile")
            with Vertical(classes="overview-card", id="overview-questions-card"):
                yield Static("INVESTIGATION QUESTIONS", classes="panel-title")
                yield Static(
                    "\n".join(
                        f"{index:02}.  {question}"
                        for index, question in enumerate(self.investigation.questions, 1)
                    ),
                    id="workspace-questions",
                    markup=False,
                )


class EvidencePanel(TabPane):
    def __init__(
        self,
        investigation: Investigation,
        documents: list[EvidenceDocument],
        evidence_directory: Path,
        display_path: str,
    ) -> None:
        super().__init__("Evidence", id="workspace-evidence-tab")
        self.investigation = investigation
        self.documents = documents
        self.evidence_directory = evidence_directory
        self.display_path = display_path

    def compose(self) -> ComposeResult:
        with Horizontal(id="evidence-section-header"):
            with Vertical(classes="section-heading"):
                yield Static("EVIDENCE KNOWLEDGE BASE", classes="panel-title")
                storage_path = Static(
                    "Stored in  " + self.display_path,
                    id="evidence-storage-path",
                    classes="section-description",
                    markup=False,
                )
                storage_path.tooltip = str(self.evidence_directory)
                yield storage_path
            yield Static(count_label(self.documents), id="evidence-count")
            yield Button("Index RAG", id="index-evidence-rag")
            yield Button("Cancel RAG", id="cancel-rag-index", classes="hidden")
            yield Button("Add file", id="add-evidence", variant="primary")
            yield Button("Cancel", id="cancel-evidence-upload", classes="hidden")
        with Horizontal(id="evidence-operation-line"):
            yield LoadingIndicator(id="rag-activity", classes="hidden")
            yield Static(
                "● Cataloghi: verifica stato…",
                id="evidence-operation-status",
                classes="ready",
            )
        with Horizontal(id="evidence-header"):
            yield Static("File", classes="evidence-name")
            yield Static("Format", classes="evidence-format")
            yield Static("Pages", classes="evidence-pages")
            yield Static("RAG index", classes="evidence-state")
            yield Static("Catalogo", classes="catalog-state")
            yield Static("Action", classes="evidence-action")
        with VerticalScroll(id="evidence-list"):
            if not self.documents:
                yield Static(
                    "No evidence documents. Use Add evidence to select a file from disk.",
                    id="evidence-empty",
                )
            for document in self.documents:
                yield EvidenceRow(document)


class GraphPanel(TabPane):
    def __init__(self, investigation: Investigation, documents: list[EvidenceDocument]) -> None:
        super().__init__("Graph", id="workspace-graph-tab")
        self.investigation = investigation
        self.documents = documents

    def compose(self) -> ComposeResult:
        with Horizontal(id="graph-toolbar"):
            yield Static("Originali con contesto documentale", id="graph-extraction-basis")
            with Horizontal(id="graph-actions"):
                yield Button("New variant", id="analyze-evidence", variant="primary")
                yield Button("Variants / compare", id="graph-variants")
                yield Button(
                    copy.text("workspace.details"),
                    id="toggle-graph-details",
                    classes="graph-details-button",
                )
                yield Button("Cancel", id="cancel-graph-analysis", classes="hidden")
        yield Static(
            "● Ready · language: "
            + self.investigation.analysis_language.prompt_label
            + " · domain: "
            + self.investigation.analysis_domain,
            id="graph-analysis-status",
            classes="ready",
        )
        with Horizontal(id="graph-build-panel", classes="hidden"):
            yield GraphBuildActivity(id="graph-build-activity")
            with Vertical(id="graph-build-copy"):
                yield Static("FROM SOURCES TO CONNECTIONS", id="graph-build-title")
                yield Static("Waiting for analysis", id="graph-build-stage", markup=False)
                yield Static("Every connection leads back to its sources.", id="graph-build-hint")
        with ResizableSplit(id="graph-body"):
            with Vertical(id="graph-visual-panel"):
                with Vertical(id="graph-panel-header"):
                    with Horizontal(id="graph-panel-title-row"):
                        yield Static("PROPOSED GRAPH", classes="panel-title")
                        yield Static("0 entities · 0 relationships", id="graph-statistics")
                    with Horizontal(id="graph-view-controls"):
                        yield Static(
                            "Arrows pan · J/K select · +/- zoom", id="graph-navigation-hint"
                        )
                        yield Button(
                            "Claims / coverage",
                            id="open-graph-claims",
                            tooltip="Open claims, sources, and page coverage",
                        )
                        yield Static("FIT", id="graph-zoom-label")
                        yield Button(
                            "Fit",
                            id="fit-graph",
                            classes="graph-view-button",
                            tooltip="Arrange groups at readable size. Use arrows to pan.",
                        )
                        yield Button("−", id="zoom-out-graph", classes="graph-view-button")
                        yield Button("+", id="zoom-in-graph", classes="graph-view-button")
                yield GraphCanvas(id="graph-canvas")
            yield PaneDivider(id="graph-pane-divider")
            with VerticalScroll(id="graph-details-panel"):
                yield Static("ANALYSIS CONTEXT", classes="panel-title")
                yield Input(placeholder="Find entity · Enter", id="graph-entity-search")
                yield Static(
                    "SELECTED ITEM\nClick a node or edge, or focus the graph and use J/K.",
                    id="graph-selection-detail",
                    classes="graph-detail-block",
                    markup=False,
                )
                yield Static(
                    "Normalization language\n" + self.investigation.analysis_language.prompt_label,
                    id="graph-language-detail",
                    classes="graph-detail-block",
                )
                yield Static(
                    "Analysis domain\n" + self.investigation.analysis_domain,
                    id="graph-domain-detail",
                    classes="graph-detail-block",
                )
                yield Static(
                    "Knowledge base\n" + count_label(self.documents),
                    id="graph-evidence-detail",
                    classes="graph-detail-block",
                )
                yield Static(
                    "Entity types\nNo graph generated",
                    id="graph-breakdown",
                    classes="graph-detail-block",
                )
                yield Static(
                    "PROVENANCE\nAI output is Evidence-grounded and PROPOSED. "
                    "A quote found in the original source does not verify the claim. "
                    "Older graphs may contain document references only.",
                    id="graph-provenance-hint",
                )


class ChatPanel(TabPane):
    def __init__(self, context_label: str) -> None:
        super().__init__("Chat", id="workspace-chat-tab")
        self.context_label = context_label

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-toolbar"):
            with Vertical(classes="section-heading", id="chat-heading"):
                yield Static("INVESTIGATION COPILOT", classes="panel-title")
                yield Static(
                    "RAG over this investigation's Evidence plus the latest graph",
                    classes="section-description",
                )
            yield Static("TOKENS\n0 total", id="chat-token-usage")
            yield Button("Index RAG", id="index-chat-kb")
            yield Button("Clear chat", id="clear-chat")
        yield Static("● Loading conversation...", id="chat-operation-status", classes="running")
        with Horizontal(id="chat-body"):
            with VerticalScroll(id="chat-conversation"):
                yield Static(
                    "Ask about documents, entities, relationships, contradictions, or request "
                    "a Mermaid diagram. Commands: /NEW · /SAVE · /STATS · /INFO.",
                    id="chat-empty",
                )
            with VerticalScroll(id="chat-context-panel"):
                yield Static("ACTIVE CONTEXT", classes="panel-title")
                yield Static(self.context_label, id="chat-context-summary", markup=False)
                yield Static(
                    "GROUNDING POLICY\nEvidence citations use [E1], [E2]... Graph items "
                    "remain hypotheses while marked PROPOSED.",
                    classes="chat-context-note",
                    markup=False,
                )
        with Vertical(id="chat-composer"):
            yield TextArea(id="chat-input", classes="chat-input", language=None)
            with Horizontal(id="chat-composer-actions"):
                yield Static(
                    "/NEW · /SAVE · /STATS · /INFO  ·  Ctrl+Enter send",
                    id="chat-composer-hint",
                )
                yield Button("Cancel", id="cancel-chat", classes="hidden")
                yield Button("Send", id="send-chat", variant="primary")
