"""Textual rendering checks for streamed Markdown and Mermaid replacement."""

from textual.app import App, ComposeResult
from textual.widgets import Markdown, Static

from raven.tui.widgets import StreamingAssistantView


class ChatWidgetApp(App[None]):
    def compose(self) -> ComposeResult:
        yield StreamingAssistantView()


async def test_streamed_mermaid_fence_becomes_terminal_diagram() -> None:
    app = ChatWidgetApp()

    async with app.run_test(size=(100, 32)):
        response = app.query_one(StreamingAssistantView)
        await response.append_fragment("Ownership:\n\n```mermaid\nflowchart LR\n")
        await response.append_fragment("  Acme --> Beta\n```\n")
        await response.complete(("brief.md · chunk 1",))

        rendered_markdown = response.query_one(".mermaid-rendered", Markdown)
        rendered = "\n".join(
            child.render().plain
            for child in rendered_markdown.walk_children()
            if hasattr(child.render(), "plain")
        )
        assert "Acme" in rendered
        assert "Beta" in rendered
        assert "brief.md" in response.query_one(".chat-message-sources", Static).render().plain
