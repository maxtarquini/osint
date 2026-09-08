"""Streaming investigation-chat presentation with terminal-native Mermaid diagrams."""

from __future__ import annotations

import re

from rich.text import Text
from termaid import render_rich
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, Markdown, Static, TextArea
from textual.widgets.markdown import MarkdownStream

from raven.models import ChatMessage, ChatRole, EvidenceCitation, TokenUsage

_MERMAID_FENCE = re.compile(
    r"```mermaid[^\n]*\n(?P<source>.*?)```",
    flags=re.IGNORECASE | re.DOTALL,
)


class ChatInput(TextArea):
    """Multiline composer where Enter submits and Shift+Enter inserts a line break."""

    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("enter", "submit", "Send", show=False, priority=True),
        Binding("shift+enter", "newline", "New line", show=False, priority=True),
    ]

    class Submit(Message):
        """Request submission of the current composer content."""

    def action_submit(self) -> None:
        if self.text.strip():
            self.post_message(self.Submit())

    def action_newline(self) -> None:
        start, end = self.selection
        self.replace("\n", start, end, maintain_selection_offset=False)


class MermaidDiagram(Markdown):
    """Render a Mermaid fence as themed Unicode without a browser or subprocess."""

    def __init__(self, source: str) -> None:
        self.mermaid_source = source.strip()
        self._rendered = self._render_source(self.mermaid_source)
        super().__init__(
            f"```text\n{self._rendered.plain}\n```",
            classes="chat-mermaid-diagram",
        )
        lines = self._rendered.plain.splitlines() or [""]
        self.diagram_height = max(1, len(lines))
        self.styles.height = self.diagram_height + 3

    @staticmethod
    def _render_source(source: str) -> Text:
        try:
            return render_rich(
                source,
                theme="phosphor",
                padding_x=2,
                padding_y=1,
                gap=2,
            )
        except Exception as error:
            fallback = Text("Mermaid rendering failed\n", style="bold #ff6b6b")
            fallback.append(f"{type(error).__name__}\n\n", style="#76928b")
            fallback.append(source)
            return fallback


def _render_mermaid_fences(markdown: str) -> str:
    """Replace Mermaid source fences with Termaid Unicode inside Markdown code blocks."""

    def replace(match: re.Match[str]) -> str:
        source = match.group("source").strip()
        rendered = MermaidDiagram._render_source(source).plain
        return f"**MERMAID · TERMINAL RENDER**\n\n```text\n{rendered}\n```"

    return _MERMAID_FENCE.sub(replace, markdown)


def _content_block(markdown: str) -> Markdown:
    classes = (
        "chat-markdown mermaid-rendered" if _MERMAID_FENCE.search(markdown) else "chat-markdown"
    )
    return Markdown(_render_mermaid_fences(markdown), classes=classes)


def token_usage_label(usage: TokenUsage) -> str:
    """Render provider-reported usage consistently across live and saved turns."""
    return (
        f"TOKENS · context {usage.input_tokens:,} · generated {usage.output_tokens:,} · "
        f"used {usage.total_tokens:,} · provider reported"
    )


def citation_passages(citations: tuple[EvidenceCitation, ...]) -> Collapsible:
    return Collapsible(
        *(
            Static(
                f"[{item.label}] {item.document_name} · "
                + (
                    f"page {item.page_number}"
                    if item.page_number
                    else f"section {item.section_number}"
                    if item.section_number is not None
                    else f"chunk {item.chunk_index + 1}"
                )
                + f"\n{item.text}\n",
                markup=False,
            )
            for item in citations
        ),
        title="Retrieved passages",
        collapsed=True,
        classes="chat-citations",
    )


class ChatMessageView(Vertical):
    """One persisted user or assistant turn."""

    def __init__(self, message: ChatMessage) -> None:
        role_class = "user" if message.role is ChatRole.USER else "assistant"
        super().__init__(classes=f"chat-message {role_class}")
        self.message = message

    def compose(self) -> ComposeResult:
        label = "YOU" if self.message.role is ChatRole.USER else "RAVEN"
        timestamp = self.message.created_at.astimezone().strftime("%H:%M")
        yield Static(f"{label}  ·  {timestamp}", classes="chat-message-header")
        yield _content_block(self.message.content)
        if self.message.sources:
            yield Static(
                "SOURCES  " + "  ·  ".join(self.message.sources),
                classes="chat-message-sources",
                markup=False,
            )
        if self.message.usage is not None:
            yield Static(
                token_usage_label(self.message.usage),
                classes="chat-message-usage",
                markup=False,
            )
        if self.message.citations:
            yield citation_passages(self.message.citations)


class LocalCommandView(Vertical):
    """Render command output distinctly from persisted model responses."""

    def __init__(self, markdown: str) -> None:
        self.markdown = markdown
        super().__init__(classes="chat-message assistant local-command")

    def compose(self) -> ComposeResult:
        yield Static("RAVEN  ·  LOCAL COMMAND", classes="chat-message-header")
        yield _content_block(self.markdown)


class StreamingAssistantView(Vertical):
    """Append model fragments through Textual's incremental Markdown parser."""

    def __init__(self) -> None:
        super().__init__(classes="chat-message assistant streaming")
        self._source = ""
        self._markdown_stream: MarkdownStream | None = None

    def compose(self) -> ComposeResult:
        yield Static("RAVEN  ·  STREAMING", classes="chat-message-header")
        yield Vertical(
            Markdown("", classes="chat-markdown", id="streamed-chat-markdown"),
            id="streamed-chat-content",
        )

    @property
    def markdown_source(self) -> str:
        """Return the exact streamed Markdown for local export after completion."""
        return self._source

    async def append_fragment(self, fragment: str) -> None:
        self._source += fragment
        markdown = self.query_one("#streamed-chat-markdown", Markdown)
        if self._markdown_stream is None:
            self._markdown_stream = Markdown.get_stream(markdown)
        await self._markdown_stream.write(fragment)

    async def complete(
        self,
        sources: tuple[str, ...] = (),
        usage: TokenUsage | None = None,
        *,
        show_usage: bool = False,
        citations: tuple[EvidenceCitation, ...] = (),
    ) -> None:
        if self._markdown_stream is not None:
            await self._markdown_stream.stop()
        self.remove_class("streaming")
        if citations:
            await self.mount(citation_passages(citations))
        self.query_one(".chat-message-header", Static).update("RAVEN")
        content = self.query_one("#streamed-chat-content", Vertical)
        if _MERMAID_FENCE.search(self._source):
            await content.remove_children()
            await content.mount(_content_block(self._source))
        if sources:
            await self.mount(
                Static(
                    "SOURCES  " + "  ·  ".join(sources),
                    classes="chat-message-sources",
                    markup=False,
                )
            )
        if show_usage:
            await self.mount(
                Static(
                    (
                        token_usage_label(usage)
                        if usage is not None
                        else "TOKENS  usage not reported by provider"
                    ),
                    classes="chat-message-usage",
                    markup=False,
                )
            )
