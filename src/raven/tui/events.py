"""Application events emitted by background service boundaries."""

from textual.message import Message


class BackgroundJobsChanged(Message):
    def __init__(self, investigation_id: str) -> None:
        super().__init__()
        self.investigation_id = investigation_id
