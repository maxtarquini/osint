"""Parse slash commands locally before investigation-chat model dispatch."""

from enum import StrEnum


class ChatCommand(StrEnum):
    """Commands supported by the investigation chat composer."""

    NEW = "/NEW"
    SAVE = "/SAVE"
    STATS = "/STATS"
    INFO = "/INFO"


class ChatCommandError(ValueError):
    """Raised when composer text looks like an unsupported slash command."""


def parse_chat_command(text: str) -> ChatCommand | None:
    """Return a supported command, ordinary prompt, or a safe validation error."""
    normalized = text.strip()
    if not normalized.startswith("/"):
        return None
    candidate = normalized.upper()
    try:
        return ChatCommand(candidate)
    except ValueError as error:
        supported = " · ".join(command.value for command in ChatCommand)
        raise ChatCommandError(f"Unknown command. Available: {supported}") from error
