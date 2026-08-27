"""Investigation-chat failures exposed at the application boundary."""


class InvestigationChatError(Exception):
    """Base failure for RAG indexing, retrieval, or streamed answers."""


class InvestigationChatCancelledError(InvestigationChatError):
    """Raised when the operator cancels an active chat operation."""
