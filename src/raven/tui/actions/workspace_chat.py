"""Chat, RAG, and export actions for the investigation workspace."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from textual import work
from textual.containers import VerticalScroll
from textual.widgets import Button, LoadingIndicator, Static, TextArea

from raven.exceptions import (
    InvestigationChatCancelledError,
    InvestigationChatError,
    InvestigationError,
)
from raven.models import (
    ChatEventKind,
    ChatMessage,
    ChatRole,
    EvidenceDocument,
    EvidenceIngestionState,
    RagIndexProgress,
    TokenUsage,
)
from raven.tui.actions.chat_commands import ChatCommand, ChatCommandError, parse_chat_command
from raven.tui.screens.file_picker import MarkdownExportPicker
from raven.tui.widgets import ChatMessageView, EvidenceRow, LocalCommandView, StreamingAssistantView

logger = logging.getLogger(__name__)


class WorkspaceChatActions:
    """Handle chat and RAG workflows outside the presentation screen."""

    @work(thread=True, exclusive=True, group="chat-history", exit_on_error=False)
    def _load_chat_history(self) -> None:
        try:
            messages = self._raven_app.load_investigation_chat(self.investigation.investigation_id)
        except Exception as error:
            logger.warning(
                "Unable to load chat history. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._set_chat_status, "● Chat history unavailable", "warning"
            )
        else:
            self.app.call_from_thread(self._show_chat_history, messages)

    def _show_chat_history(self, messages: tuple[ChatMessage, ...]) -> None:
        if not self.is_mounted:
            return
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        if messages:
            self.query_one("#chat-empty", Static).remove()
            conversation.mount(*(ChatMessageView(message) for message in messages))
            conversation.scroll_end(animate=False)
        last_assistant = next(
            (message for message in reversed(messages) if message.role is ChatRole.ASSISTANT),
            None,
        )
        self._last_assistant_markdown = (
            last_assistant.content if last_assistant is not None else None
        )
        self._last_assistant_sources = last_assistant.sources if last_assistant is not None else ()
        self._chat_saved_messages = len(messages)
        self._replace_chat_usage(messages)
        self._set_chat_status(
            f"● Ready · {len(messages)} saved turn{'s' if len(messages) != 1 else ''}",
            "ready",
        )

    def _start_chat_index(
        self, *, silent: bool = False, document: EvidenceDocument | None = None
    ) -> None:
        if self._chat_busy or self._busy:
            return
        if not self._raven_app.settings.with_environment().ai.embedding_model:
            self._set_rag_status("● Configure an AI embedding model to index the KB", "warning")
            if not silent:
                self.notify(
                    "Set the embedding model in Configuration > AI Node.",
                    title="RAG configuration required",
                    severity="warning",
                )
            return
        if not self.documents:
            self._set_rag_status("● Add Evidence before indexing", "warning")
            if not silent:
                self.notify(
                    "Add at least one Evidence document before indexing the chat KB.",
                    title="No Evidence",
                    severity="warning",
                )
            return
        self._chat_busy = True
        self._rag_indexing = True
        self._rag_state_revision += 1
        self._rag_target = document.document_id if document else None
        self._chat_cancel.clear()
        self._set_chat_controls_disabled(True)
        self._set_rag_controls_disabled(True)
        self._set_rag_status("● Preparing investigation RAG index...", "running")
        self._index_chat_kb(silent, document)

    def _cancel_rag_index(self) -> None:
        if not self._rag_indexing:
            return
        self._chat_cancel.set()
        self._set_rag_status("● Cancelling after the active indexing step...", "running")

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _index_chat_kb(self, silent: bool, document: EvidenceDocument | None = None) -> None:
        try:
            if document is None:
                count = self._raven_app.index_investigation_knowledge_base(
                    self.investigation,
                    tuple(self.documents),
                    self._chat_cancel.is_set,
                    self._chat_index_progress,
                )
            else:
                count = self._raven_app.reindex_evidence_document(
                    self.investigation,
                    document,
                    self._chat_cancel.is_set,
                    self._chat_index_progress,
                )
        except InvestigationChatCancelledError:
            self.app.call_from_thread(self._chat_cancelled)
        except (InvestigationChatError, InvestigationError) as error:
            self.app.call_from_thread(self._chat_failed, str(error), silent)
        except Exception as error:
            logger.error(
                "Unexpected chat indexing failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._chat_failed, "Unable to index the investigation KB", silent
            )
        else:
            self.app.call_from_thread(self._chat_indexed, count)

    def _chat_index_progress(self, progress: RagIndexProgress) -> None:
        self.app.call_from_thread(self._show_rag_index_progress, progress)

    def _show_rag_index_progress(self, progress: RagIndexProgress) -> None:
        self._rag_state_revision += 1
        if not self.is_mounted:
            return
        self.documents = [
            replace(document, ingestion_state=progress.state)
            if document.document_id == progress.document_id
            else document
            for document in self.documents
        ]
        row = self.query_one(f"#evidence-{progress.document_id}", EvidenceRow)
        row.set_ingestion_state(progress.state)
        action = {
            EvidenceIngestionState.PROCESSING: "Indexing",
            EvidenceIngestionState.READY: "Indexed",
            EvidenceIngestionState.FAILED: "Failed",
            EvidenceIngestionState.PENDING: "Pending",
        }[progress.state]
        state = "error" if progress.state is EvidenceIngestionState.FAILED else "running"
        self._set_rag_status(
            f"● {action} {progress.document_name} ({progress.completed}/{progress.total})",
            state,
        )

    def _chat_indexed(self, count: int) -> None:
        if not self.is_mounted:
            return
        self.documents = [
            replace(document, ingestion_state=EvidenceIngestionState.READY)
            if self._rag_target is None or document.document_id == self._rag_target
            else document
            for document in self.documents
        ]
        for row in self.query(EvidenceRow):
            if self._rag_target is None or row.document.document_id == self._rag_target:
                row.set_ingestion_state(EvidenceIngestionState.READY)
        self._finish_chat_operation(f"● KB indexed · {count} document(s)", "success")
        self._finish_rag_operation(
            f"● RAG index ready · {count} document(s)",
            "success",
        )

    async def _start_chat(self) -> None:
        if self._chat_busy:
            return
        question = self.query_one("#chat-input", TextArea).text.strip()
        if not question:
            self._set_chat_status("● Write a question before sending", "warning")
            self.query_one("#chat-input", TextArea).focus()
            return
        try:
            command = parse_chat_command(question)
        except ChatCommandError as error:
            self._set_chat_status(f"● {error}", "warning")
            self.query_one("#chat-input", TextArea).focus()
            return
        if command is not None:
            self.query_one("#chat-input", TextArea).clear()
            await self._execute_chat_command(command)
            return
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        for empty in self.query("#chat-empty"):
            empty.remove()
        user_message = ChatMessage(
            message_id=str(uuid4()),
            investigation_id=self.investigation.investigation_id,
            role=ChatRole.USER,
            content=question,
            created_at=datetime.now(UTC),
        )
        response = StreamingAssistantView()
        await conversation.mount(ChatMessageView(user_message), response)
        conversation.scroll_end(animate=False)
        self._active_response = response
        self._rag_state_revision += 1
        self._chat_sources = ()
        self._chat_busy = True
        self._chat_cancel.clear()
        self._set_chat_controls_disabled(True)
        self.query_one("#chat-input", TextArea).clear()
        self._set_chat_status("● Preparing grounded context...", "running")
        self._stream_chat(question)

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _stream_chat(self, question: str) -> None:
        try:
            for event in self._raven_app.stream_investigation_chat(
                self.investigation,
                tuple(self.documents),
                self.graph,
                question,
                self._chat_cancel.is_set,
                self._chat_index_progress,
            ):
                if event.kind is ChatEventKind.STATUS:
                    self.app.call_from_thread(self._set_chat_status, f"● {event.text}", "running")
                elif event.kind is ChatEventKind.SOURCES:
                    self._chat_sources = event.sources
                elif event.kind is ChatEventKind.TOKEN:
                    self.app.call_from_thread(self._append_chat_fragment, event.text)
                elif event.kind is ChatEventKind.COMPLETE:
                    self.app.call_from_thread(
                        self._chat_completed,
                        event.sources or self._chat_sources,
                        event.usage,
                    )
        except InvestigationChatCancelledError:
            self.app.call_from_thread(self._chat_cancelled)
        except (InvestigationChatError, InvestigationError) as error:
            self.app.call_from_thread(self._chat_failed, str(error), False)
        except Exception as error:
            logger.error(
                "Unexpected streamed chat failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._chat_failed, "Unable to complete the investigation chat", False
            )

    async def _append_chat_fragment(self, fragment: str) -> None:
        if self._active_response is None or not self._active_response.is_mounted:
            return
        await self._active_response.append_fragment(fragment)
        self.query_one("#chat-conversation", VerticalScroll).scroll_end(animate=False)

    async def _chat_completed(
        self,
        sources: tuple[str, ...],
        usage: TokenUsage | None,
    ) -> None:
        if self._active_response is not None and self._active_response.is_mounted:
            self._last_assistant_markdown = self._active_response.markdown_source
            self._last_assistant_sources = sources
            await self._active_response.complete(sources, usage, show_usage=True)
        self._active_response = None
        self._chat_saved_messages += 2
        if usage is not None:
            self._add_chat_usage(usage)
            label = f"● Grounded answer complete · {usage.total_tokens:,} tokens"
        else:
            label = "● Grounded answer complete · token usage unavailable"
        self._finish_chat_operation(label, "success")
        self.call_after_refresh(self._scroll_chat_to_end)

    def _scroll_chat_to_end(self) -> None:
        self.query_one("#chat-conversation", VerticalScroll).scroll_end(animate=False)

    async def _chat_cancelled(self) -> None:
        if not self.is_mounted:
            return
        rag_indexing = self._rag_indexing
        if self._active_response is not None and self._active_response.is_mounted:
            await self._active_response.complete(self._chat_sources)
        self._active_response = None
        self._finish_chat_operation("● Chat operation cancelled", "cancelled")
        if rag_indexing:
            self._finish_rag_operation("● RAG indexing cancelled", "cancelled")

    async def _chat_failed(self, detail: str, silent: bool) -> None:
        if not self.is_mounted:
            return
        rag_indexing = self._rag_indexing
        if self._active_response is not None and self._active_response.is_mounted:
            await self._active_response.complete(self._chat_sources)
            self._active_response.add_class("error")
        self._active_response = None
        self._finish_chat_operation("● Chat operation failed", "error")
        if rag_indexing:
            self._finish_rag_operation("● RAG indexing failed", "error")
        status = self.query_one("#chat-operation-status", Static)
        status.tooltip = detail
        if rag_indexing:
            self.query_one("#evidence-operation-status", Static).tooltip = detail
        if not silent:
            self.notify(detail, title="Investigation chat failed", severity="error")

    def _finish_chat_operation(self, label: str, state: str) -> None:
        self._chat_busy = False
        self._set_chat_controls_disabled(False)
        self._set_chat_status(label, state)

    def _finish_rag_operation(self, label: str, state: str) -> None:
        self._rag_indexing = False
        self._rag_target = None
        self._set_rag_controls_disabled(False)
        self._set_operation_status(label, state)

    def _set_rag_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#rag-activity", LoadingIndicator).set_class(not disabled, "hidden")
        self.query_one("#index-evidence-rag", Button).disabled = disabled
        self.query_one("#add-evidence", Button).disabled = disabled
        self.query_one("#cancel-rag-index", Button).set_class(not disabled, "hidden")
        for row in self.query(EvidenceRow):
            row.query_one(".delete-evidence", Button).disabled = disabled
            row.query_one(".reindex-evidence", Button).disabled = disabled

    def _set_rag_status(self, label: str, state: str) -> None:
        self._set_operation_status(label, state)
        self._set_chat_status(label, state)

    def _set_chat_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#send-chat", Button).disabled = disabled
        self.query_one("#index-chat-kb", Button).disabled = disabled
        self.query_one("#clear-chat", Button).disabled = disabled
        self.query_one("#chat-input", TextArea).disabled = disabled
        self.query_one("#cancel-chat", Button).set_class(not disabled, "hidden")

    def _set_chat_status(self, label: str, state: str) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#chat-operation-status", Static)
        status.set_classes(state)
        status.update(label)
        status.tooltip = None

    def _clear_chat_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self._clear_chat_history()

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _clear_chat_history(self) -> None:
        self._chat_busy = True
        self.app.call_from_thread(self._set_chat_controls_disabled, True)
        try:
            self._raven_app.clear_investigation_chat(self.investigation.investigation_id)
        except Exception as error:
            self.app.call_from_thread(self._chat_failed, str(error), False)
        else:
            self.app.call_from_thread(self._chat_history_cleared)

    async def _chat_history_cleared(self) -> None:
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        await conversation.remove_children()
        await conversation.mount(
            Static(
                "Ask about documents, entities, relationships, contradictions, or request a "
                "Mermaid diagram. Commands: /NEW · /SAVE · /STATS · /INFO.",
                id="chat-empty",
            )
        )
        self._chat_saved_messages = 0
        self._last_assistant_markdown = None
        self._last_assistant_sources = ()
        self._replace_chat_usage(())
        self._finish_chat_operation("● Chat history cleared", "success")

    async def _execute_chat_command(self, command: ChatCommand) -> None:
        if command is ChatCommand.NEW:
            self.app.push_screen(
                self._clear_chat_dialog(),
                self._clear_chat_confirmed,
            )
            return
        if command is ChatCommand.SAVE:
            self._open_chat_export()
            return
        if command is ChatCommand.STATS:
            await self._mount_local_command(self._chat_statistics_markdown(), "Statistics ready")
            return
        await self._mount_local_command(self._chat_info_markdown(), "Context information ready")

    async def _mount_local_command(self, markdown: str, status: str) -> None:
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        for empty in self.query("#chat-empty"):
            empty.remove()
        await conversation.mount(LocalCommandView(markdown))
        conversation.scroll_end(animate=False)
        self._set_chat_status(f"● {status} · local command · 0 tokens", "success")

    def _open_chat_export(self) -> None:
        if not self._last_assistant_markdown:
            self._set_chat_status("● No model response is available to save", "warning")
            return
        self.app.push_screen(
            MarkdownExportPicker(
                self._last_export_directory,
                self._raven_app.suggested_chat_export_filename(self.investigation),
            ),
            self._chat_export_selected,
        )

    def _chat_export_selected(self, destination: Path | None) -> None:
        if destination is None or not self._last_assistant_markdown or self._chat_busy:
            return
        self._chat_busy = True
        self._set_chat_controls_disabled(True)
        self._set_chat_status("● Saving latest response as Markdown...", "running")
        self._save_chat_export(
            destination,
            self._last_assistant_markdown,
            self._last_assistant_sources,
        )

    @work(thread=True, exclusive=True, group="chat-export", exit_on_error=False)
    def _save_chat_export(
        self,
        destination: Path,
        response: str,
        sources: tuple[str, ...],
    ) -> None:
        try:
            saved = self._raven_app.export_investigation_chat_response(
                self.investigation,
                response,
                sources,
                destination,
            )
        except InvestigationChatError as error:
            self.app.call_from_thread(self._chat_export_failed, str(error))
        except Exception as error:
            logger.error(
                "Unexpected chat export failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._chat_export_failed,
                "Unable to save the Markdown response",
            )
        else:
            self.app.call_from_thread(self._chat_export_succeeded, saved)

    def _chat_export_succeeded(self, destination: Path) -> None:
        self._last_export_directory = destination.parent
        self._finish_chat_operation(f"● Response saved · {destination.name}", "success")
        self.notify(str(destination), title="Markdown response saved")

    def _chat_export_failed(self, detail: str) -> None:
        self._finish_chat_operation("● Markdown export failed", "error")
        self.notify(detail, title="Response not saved", severity="error")

    def _chat_statistics_markdown(self) -> str:
        indexed = sum(
            document.ingestion_state is EvidenceIngestionState.READY for document in self.documents
        )
        entities = len(self.graph.entities) if self.graph is not None else 0
        relationships = len(self.graph.relationships) if self.graph is not None else 0
        return (
            "## Chat statistics\n\n"
            f"- Saved messages: **{self._chat_saved_messages:,}**\n"
            f"- Input tokens: **{self._chat_input_tokens:,}**\n"
            f"- Output tokens: **{self._chat_output_tokens:,}**\n"
            f"- Total tokens: **{self._chat_total_tokens:,}**\n"
            f"- Evidence documents: **{len(self.documents):,}**\n"
            f"- RAG-ready documents: **{indexed:,}/{len(self.documents):,}**\n"
            f"- Graph: **{entities:,} entities · {relationships:,} relationships**"
        )

    def _chat_info_markdown(self) -> str:
        settings = self._raven_app.settings.with_environment().ai
        graph_label = (
            f"{len(self.graph.entities):,} entities · "
            f"{len(self.graph.relationships):,} relationships"
            if self.graph is not None
            else "No graph snapshot"
        )
        documents = (
            "\n".join(
                f"- `{self._safe_code(document.original_name)}` · {document.file_format} · "
                f"{document.page_label} pages · {document.ingestion_state.value}"
                for document in self.documents
            )
            if self.documents
            else "- No Evidence documents"
        )
        last_sources = (
            "\n".join(f"- `{self._safe_code(source)}`" for source in self._last_assistant_sources)
            if self._last_assistant_sources
            else "- No sources reported for the latest model response"
        )
        return (
            "## Active investigation context\n\n"
            f"- Investigation: **{self.investigation.name}**\n"
            f"- Reference language: **{self.investigation.analysis_language.prompt_label}**\n"
            f"- Analysis domain: **{self.investigation.analysis_domain}**\n"
            f"- Graph: **{graph_label}**\n"
            f"- Inference: **{settings.provider.value} · {settings.model or 'not configured'}**\n"
            f"- Context budget: **{settings.context_size:,} tokens**\n"
            f"- Embedding: **{settings.embedding_provider.value} · "
            f"{settings.embedding_model or 'not configured'}**\n\n"
            "### Evidence sources\n\n"
            f"{documents}\n\n"
            "### Latest answer citations\n\n"
            f"{last_sources}"
        )

    @staticmethod
    def _safe_code(value: str) -> str:
        return " ".join(value.replace("`", "'").split())

    def _replace_chat_usage(self, messages: tuple[ChatMessage, ...]) -> None:
        usage = tuple(message.usage for message in messages if message.usage is not None)
        self._chat_input_tokens = sum(item.input_tokens for item in usage)
        self._chat_output_tokens = sum(item.output_tokens for item in usage)
        self._chat_total_tokens = sum(item.total_tokens for item in usage)
        self._refresh_chat_usage()

    def _add_chat_usage(self, usage: TokenUsage) -> None:
        self._chat_input_tokens += usage.input_tokens
        self._chat_output_tokens += usage.output_tokens
        self._chat_total_tokens += usage.total_tokens
        self._refresh_chat_usage()

    def _refresh_chat_usage(self) -> None:
        if not self.is_mounted:
            return
        summary = self.query_one("#chat-token-usage", Static)
        summary.update(f"TOKENS\n{self._chat_total_tokens:,} total")
        summary.tooltip = (
            f"Input: {self._chat_input_tokens:,} · "
            f"Output: {self._chat_output_tokens:,} · "
            f"Total: {self._chat_total_tokens:,}"
        )
