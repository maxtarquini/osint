"""Serialize case operations and invalidate work before destructive mutations."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, RLock

from raven.exceptions import InvestigationCancelledError


@dataclass
class _CaseOperations:
    lock: RLock = field(default_factory=RLock)
    invalidated: Event = field(default_factory=Event)
    revision: int = 0
    mutations: int = 0


class InvestigationOperations:
    """One process-wide owner for each case's publication and mutation order.

    Waiting operations retain the event for the revision they requested. A mutation
    invalidates that revision before waiting for active I/O to drain, so old work
    cannot publish after the mutation completes.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._cases: dict[str, _CaseOperations] = {}

    def _case(self, investigation_id: str) -> _CaseOperations:
        with self._lock:
            return self._cases.setdefault(investigation_id, _CaseOperations())

    @contextmanager
    def operation(
        self, investigation_id: str, cancelled: Callable[[], bool] | None = None
    ) -> Iterator[Callable[[], bool]]:
        case = self._case(investigation_id)
        event = case.invalidated
        with case.lock:
            yield lambda: event.is_set() or bool(cancelled and cancelled())

    @contextmanager
    def mutation(
        self, investigation_id: str, cancelled: Callable[[], bool] | None = None
    ) -> Iterator[None]:
        case = self._case(investigation_id)
        with self._lock:
            case.mutations += 1
            case.invalidated.set()
        acquired = False
        try:
            while not acquired:
                if cancelled and cancelled():
                    raise InvestigationCancelledError("Evidence upload cancelled")
                acquired = case.lock.acquire(timeout=0.1)
            if cancelled and cancelled():
                raise InvestigationCancelledError("Evidence upload cancelled")
            yield
        finally:
            with self._lock:
                case.revision += 1
                case.mutations -= 1
                if case.mutations == 0:
                    case.invalidated = Event()
            if acquired:
                case.lock.release()
