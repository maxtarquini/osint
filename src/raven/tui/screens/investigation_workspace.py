"""Opened investigation workspace with independent evidence management."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    Static,
    TabbedContent,
)

from raven.models import (
    EvidenceDocument,
    Investigation,
    InvestigationGraph,
)
from raven.tui.actions.workspace_chat import WorkspaceChatActions
from raven.tui.actions.workspace_evidence import WorkspaceEvidenceActions
from raven.tui.actions.workspace_graph import WorkspaceGraphActions
from raven.tui.actions.workspace_overview import WorkspaceOverviewActions
from raven.tui.screens.graph_claims import GraphClaimsScreen
from raven.tui.state import WorkspaceViewState
from raven.tui.widgets import (
    GraphCanvas,
    StreamingAssistantView,
    TopNavigation,
)
from raven.tui.widgets.dialogs import ConfirmDialog
from raven.tui.widgets.graph_activity import GraphBuildActivity
from raven.tui.widgets.resizable_split import ResizableSplit
from raven.tui.widgets.workspace import ChatPanel, EvidencePanel, GraphPanel, OverviewPanel

if TYPE_CHECKING:
    from raven.app import RavenApp

logger = logging.getLogger(__name__)


class ConfirmClearChat(ConfirmDialog):
    """Require explicit confirmation before deleting one investigation's chat history."""

    def __init__(self, investigation: Investigation) -> None:
        self.investigation = investigation
        super().__init__(
            dialog_id="clear-chat-dialog",
            title="CLEAR CHAT HISTORY",
            title_id="clear-chat-title",
            subject=investigation.name,
            subject_id="clear-chat-investigation",
            warning=(
                "Delete every saved chat turn for this investigation? Evidence and graph data "
                "will not be changed."
            ),
            warning_id="clear-chat-warning",
            actions_id="clear-chat-actions",
            confirm_label="Delete history",
            confirm_id="confirm-clear-chat",
            cancel_id="cancel-clear-chat",
        )


class ConfirmInvestigationDelete(ConfirmDialog):
    """Require explicit confirmation before deleting an entire investigation."""

    def __init__(self, investigation: Investigation) -> None:
        self.investigation = investigation
        super().__init__(
            dialog_id="delete-investigation-dialog",
            title="DELETE INVESTIGATION",
            title_id="delete-investigation-title",
            subject=investigation.name,
            subject_id="delete-investigation-name",
            warning=(
                "This permanently removes the case, copied Evidence files, chat history, "
                "RAG vectors, graph data, and any local case cache. Original source files "
                "are not changed."
            ),
            warning_id="delete-investigation-warning",
            actions_id="delete-investigation-actions",
            confirm_label="Delete investigation",
            confirm_id="confirm-delete-investigation",
            cancel_id="cancel-delete-investigation",
        )


class InvestigationWorkspaceScreen(
    WorkspaceOverviewActions,
    WorkspaceEvidenceActions,
    WorkspaceChatActions,
    WorkspaceGraphActions,
    Screen[None],
):
    """Operate on one opened investigation and its knowledge base."""

    BINDINGS = [
        Binding("escape", "app.navigate('home')", "Home"),
        Binding("a", "add_evidence", "Add evidence", show=False),
        Binding("o", "show_overview", "Overview", show=False),
        Binding("e", "show_evidence", "Evidence", show=False),
        Binding("g", "show_graph", "Graph", show=False),
        Binding("c", "show_chat", "Chat", show=False),
        Binding("ctrl+enter", "send_chat", "Send chat"),
        Binding("ctrl+i", "index_rag", "Index RAG", show=False),
        Binding("slash", "focus_graph_search", "Find entity", show=False),
        Binding("ctrl+g", "analyze_graph", "Analyze graph", show=False),
        Binding("d", "toggle_graph_details", "Graph details", show=False),
        Binding("question_mark", "app.context_help", "Help"),
    ]

    def __init__(self, investigation: Investigation) -> None:
        super().__init__()
        self.investigation = investigation
        self.view_state = WorkspaceViewState.from_investigation(investigation)
        self.documents = list(investigation.evidence_documents)
        self._busy = False
        self._upload_cancel = Event()
        self._graph_busy = False
        self._applied_graph_job_id: str | None = None
        self.graph: InvestigationGraph | None = None
        self._last_evidence_source_directory = Path.home()
        self._chat_busy = False
        self._chat_cancel = Event()
        self._active_response: StreamingAssistantView | None = None
        self._chat_sources: tuple[str, ...] = ()
        self._rag_indexing = False
        self._rag_target = None
        self._rag_state_revision = 0
        self._chat_input_tokens = 0
        self._chat_output_tokens = 0
        self._chat_total_tokens = 0
        self._chat_saved_messages = 0
        self._last_assistant_markdown: str | None = None
        self._last_assistant_sources: tuple[str, ...] = ()
        self._last_export_directory = Path.home()
        self._deleting = False

    @property
    def documents(self) -> list[EvidenceDocument]:
        return self.view_state.evidence.documents

    @documents.setter
    def documents(self, value: list[EvidenceDocument]) -> None:
        self.view_state.evidence.documents = value

    @property
    def graph(self) -> InvestigationGraph | None:
        return self.view_state.graph.graph

    @graph.setter
    def graph(self, value: InvestigationGraph | None) -> None:
        self.view_state.graph.graph = value

    @property
    def _busy(self) -> bool:
        return self.view_state.evidence.busy

    @_busy.setter
    def _busy(self, value: bool) -> None:
        self.view_state.evidence.busy = value

    @property
    def _graph_busy(self) -> bool:
        return self.view_state.graph.busy

    @_graph_busy.setter
    def _graph_busy(self, value: bool) -> None:
        self.view_state.graph.busy = value

    @property
    def _applied_graph_job_id(self) -> str | None:
        return self.view_state.graph.applied_job_id

    @_applied_graph_job_id.setter
    def _applied_graph_job_id(self, value: str | None) -> None:
        self.view_state.graph.applied_job_id = value

    @property
    def _chat_busy(self) -> bool:
        return self.view_state.chat.busy

    @_chat_busy.setter
    def _chat_busy(self, value: bool) -> None:
        self.view_state.chat.busy = value

    @property
    def _chat_sources(self) -> tuple[str, ...]:
        return self.view_state.chat.sources

    @_chat_sources.setter
    def _chat_sources(self, value: tuple[str, ...]) -> None:
        self.view_state.chat.sources = value

    @property
    def _rag_indexing(self) -> bool:
        return self.view_state.evidence.rag_indexing

    @_rag_indexing.setter
    def _rag_indexing(self, value: bool) -> None:
        self.view_state.evidence.rag_indexing = value

    @property
    def _rag_target(self) -> str | None:
        return self.view_state.evidence.rag_target

    @_rag_target.setter
    def _rag_target(self, value: str | None) -> None:
        self.view_state.evidence.rag_target = value

    @property
    def _rag_state_revision(self) -> int:
        return self.view_state.evidence.revision

    @_rag_state_revision.setter
    def _rag_state_revision(self, value: int) -> None:
        self.view_state.evidence.revision = value

    @property
    def _chat_input_tokens(self) -> int:
        return self.view_state.chat.input_tokens

    @_chat_input_tokens.setter
    def _chat_input_tokens(self, value: int) -> None:
        self.view_state.chat.input_tokens = value

    @property
    def _chat_output_tokens(self) -> int:
        return self.view_state.chat.output_tokens

    @_chat_output_tokens.setter
    def _chat_output_tokens(self, value: int) -> None:
        self.view_state.chat.output_tokens = value

    @property
    def _chat_total_tokens(self) -> int:
        return self.view_state.chat.total_tokens

    @_chat_total_tokens.setter
    def _chat_total_tokens(self, value: int) -> None:
        self.view_state.chat.total_tokens = value

    @property
    def _chat_saved_messages(self) -> int:
        return self.view_state.chat.saved_messages

    @_chat_saved_messages.setter
    def _chat_saved_messages(self, value: int) -> None:
        self.view_state.chat.saved_messages = value

    @property
    def _last_assistant_markdown(self) -> str | None:
        return self.view_state.chat.last_assistant_markdown

    @_last_assistant_markdown.setter
    def _last_assistant_markdown(self, value: str | None) -> None:
        self.view_state.chat.last_assistant_markdown = value

    @property
    def _last_assistant_sources(self) -> tuple[str, ...]:
        return self.view_state.chat.last_assistant_sources

    @_last_assistant_sources.setter
    def _last_assistant_sources(self, value: tuple[str, ...]) -> None:
        self.view_state.chat.last_assistant_sources = value

    @property
    def _deleting(self) -> bool:
        return self.view_state.deleting

    @_deleting.setter
    def _deleting(self, value: bool) -> None:
        self.view_state.deleting = value

    def compose(self) -> ComposeResult:
        yield TopNavigation(active="investigations")
        with Horizontal(id="workspace-summary"):
            with Vertical(id="workspace-heading"):
                yield Static("INVESTIGATION WORKSPACE", classes="section-kicker")
                yield Label(self.investigation.name, id="workspace-title")
                yield Static(
                    f"ID {self.investigation.investigation_id[:8]}  ·  "
                    f"updated {self.investigation.updated_at.astimezone():%Y-%m-%d %H:%M}",
                    id="workspace-identifier",
                )
            with Horizontal(id="workspace-metrics"):
                yield Static(
                    "REFERENCE\n" + self.investigation.analysis_language.value.title(),
                    classes="workspace-metric",
                    id="workspace-language-metric",
                )
                yield Static(
                    "EVIDENCE\n" + self._count_label(),
                    classes="workspace-metric",
                    id="workspace-evidence-metric",
                )
                yield Static(
                    "GRAPH\nPending",
                    classes="workspace-metric",
                    id="workspace-graph-metric",
                )
        evidence_directory = self._raven_app.evidence_directory(self.investigation.investigation_id)
        with TabbedContent(initial="workspace-evidence-tab", id="workspace-tabs"):
            yield OverviewPanel(self.investigation, self._analysis_profile_label())
            yield EvidencePanel(
                self.investigation,
                self.documents,
                evidence_directory,
                self._display_path(evidence_directory),
            )
            yield GraphPanel(self.investigation, self.documents)
            yield ChatPanel(self._chat_context_label())
        yield Footer()

    def on_mount(self) -> None:
        # Thread workers may outlive the active-screen context. Retain the app
        # that owns this workspace instead of resolving ``self.app`` in them.
        self._owner_app = self.app
        self._set_responsive_layout(self.size.width, self.size.height)
        self._load_latest_graph()
        self._load_chat_history()
        self._load_rag_states(self._rag_state_revision, tuple(self.documents))
        self._load_catalog_states(
            self.view_state.evidence.catalog_revision,
            tuple(self.documents),
        )
        self._sync_graph_analysis_job()
        self.set_interval(0.15, self._sync_graph_analysis_job)

    def on_resizable_split_resized(self, event: ResizableSplit.Resized) -> None:
        compact = event.main_width < 85
        self.query_one("#graph-visual-panel").set_class(compact, "compact-graph-pane")
        self.query_one("#open-graph-claims", Button).label = (
            "Affermazioni" if compact else "Affermazioni / copertura"
        )

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.width, event.size.height)

    def _set_responsive_layout(self, width: int, height: int) -> None:
        self.set_class(height <= 26, "compact-workspace")
        self.set_class(width < 100, "narrow-workspace")
        self.set_class(width < 125, "compact-evidence")
        compact_activity = width < 100 or height < 40
        self.set_class(compact_activity, "compact-graph-activity")
        for activity in self.query(GraphBuildActivity):
            activity.set_class(compact_activity, "compact")
        if self.graph is not None:
            for statistics in self.query("#graph-statistics"):
                statistics.update(self._graph_statistics_label(self.graph, width))

    def action_add_evidence(self) -> None:
        self._open_file_picker()

    def action_show_overview(self) -> None:
        self._show_tab("workspace-overview-tab")

    def action_show_evidence(self) -> None:
        self._show_tab("workspace-evidence-tab")

    def action_show_graph(self) -> None:
        self._show_tab("workspace-graph-tab")

    def action_show_chat(self) -> None:
        self._show_tab("workspace-chat-tab")

    async def action_send_chat(self) -> None:
        if self.query_one("#workspace-tabs", TabbedContent).active == "workspace-chat-tab":
            await self._start_chat()

    def action_analyze_graph(self) -> None:
        self._show_tab("workspace-graph-tab")
        self._start_graph_analysis()

    def action_index_rag(self) -> None:
        self._show_tab("workspace-evidence-tab")
        self._start_chat_index()

    def action_focus_graph_search(self) -> None:
        self._show_tab("workspace-graph-tab")
        self.query_one("#graph-entity-search", Input).focus()

    def action_toggle_graph_details(self) -> None:
        self._show_tab("workspace-graph-tab")
        split = self.query_one("#graph-body", ResizableSplit)
        visible = split.has_class("details-collapsed")
        split.set_class(not visible, "details-collapsed")
        self.view_state.graph.details_visible = visible

    def _show_tab(self, tab_id: str) -> None:
        self.query_one("#workspace-tabs", TabbedContent).active = tab_id

    def _clear_chat_dialog(self) -> ConfirmClearChat:
        return ConfirmClearChat(self.investigation)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-evidence":
            self._open_file_picker()
        elif event.button.id == "index-evidence-rag":
            self._start_chat_index()
        elif event.button.id == "cancel-rag-index":
            self._cancel_rag_index()
        elif event.button.id == "cancel-evidence-upload":
            self._upload_cancel.set()
            self._set_operation_status("● Cancelling upload...", "running")
        elif event.button.id == "graph-variants":
            self._open_variants()
        elif event.button.id == "analyze-evidence":
            self._start_graph_analysis()
        elif event.button.id == "cancel-graph-analysis":
            self._raven_app.cancel_graph_analysis(self.investigation.investigation_id)
            self._sync_graph_analysis_job()
        elif event.button.id == "open-graph-claims":
            self.app.push_screen(
                GraphClaimsScreen(self.investigation, self.graph, tuple(self.documents))
            )
        elif event.button.id == "fit-graph":
            self.query_one("#graph-canvas", GraphCanvas).fit()
        elif event.button.id == "zoom-out-graph":
            self.query_one("#graph-canvas", GraphCanvas).zoom_out()
        elif event.button.id == "zoom-in-graph":
            self.query_one("#graph-canvas", GraphCanvas).zoom_in()
        elif event.button.id == "toggle-graph-details":
            # Defer the reflow until Textual has completed the button's mouse-up cycle.
            # Otherwise the control can retain its pressed state while the split resizes.
            self.call_after_refresh(self._toggle_graph_details_from_button, event.button)
        elif event.button.id == "send-chat":
            await self._start_chat()
        elif event.button.id == "cancel-chat":
            if self._rag_indexing:
                self._cancel_rag_index()
            else:
                self._chat_cancel.set()
                self._set_chat_status("● Cancelling after the active provider event...", "running")
        elif event.button.id == "index-chat-kb":
            self._start_chat_index()
        elif event.button.id == "clear-chat" and not self._chat_busy:
            self.app.push_screen(
                ConfirmClearChat(self.investigation),
                self._clear_chat_confirmed,
            )
        elif event.button.id == "edit-investigation" and not self._deleting:
            self._raven_app.edit_investigation(self.investigation)
        elif event.button.id == "delete-investigation" and not self._deleting:
            self.app.push_screen(
                ConfirmInvestigationDelete(self.investigation),
                self._delete_investigation_confirmed,
            )

    def _toggle_graph_details_from_button(self, button: Button) -> None:
        self.action_toggle_graph_details()
        button.remove_class("-active")

    def _count_label(self) -> str:
        count = len(self.documents)
        return f"{count} document{'s' if count != 1 else ''}"

    def _analysis_profile_label(self) -> str:
        return (
            "Normalization language\n"
            + self.investigation.analysis_language.prompt_label
            + "\n\nAnalysis domain\n"
            + self.investigation.analysis_domain
            + "\n\nKnowledge base\n"
            + self._count_label()
        )

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return str(Path("~") / path.relative_to(Path.home()))
        except ValueError:
            return str(path)

    def _chat_context_label(self) -> str:
        graph_label = (
            f"{len(self.graph.entities)} entities · {len(self.graph.relationships)} relationships"
            if self.graph is not None
            else "No graph snapshot"
        )
        ai_settings = self._raven_app.settings.with_environment().ai
        embedding_model = ai_settings.embedding_model or "Not configured"
        return (
            f"Evidence KB\n{self._count_label()}\n\n"
            f"Graph\n{graph_label}\n\n"
            "Normalization language\n"
            f"{self.investigation.analysis_language.prompt_label}\n\n"
            "Embedding node\n"
            f"{ai_settings.embedding_provider.value} · {embedding_model}\n\n"
            f"Inference context\n{ai_settings.context_size:,} tokens"
        )

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
