"""Ordered background persistence that never holds a UI-facing queue lock."""

import logging
from queue import Queue
from threading import Event, Thread
from typing import Protocol

from raven.models import BackgroundJob

logger = logging.getLogger(__name__)


class JobRecorder(Protocol):
    def save_background_job(self, job: BackgroundJob) -> None: ...


class BackgroundJobWriter:
    def __init__(self, recorder: JobRecorder | None) -> None:
        self.recorder = recorder
        self._queue: Queue[BackgroundJob | Event | None] = Queue()
        self._failed: dict[str, BackgroundJob] = {}
        self._thread = Thread(target=self._consume, name="raven-job-persistence", daemon=True)
        self._thread.start()

    def submit(self, job: BackgroundJob) -> None:
        self._queue.put(job)

    def flush(self, timeout: float = 10) -> bool:
        barrier = Event()
        self._queue.put(barrier)
        return barrier.wait(timeout) and not self._failed

    def close(self) -> None:
        self._queue.put(None)

    def _consume(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                if isinstance(item, Event):
                    for failed in tuple(self._failed.values()):
                        self._write(failed)
                    item.set()
                elif self.recorder is not None:
                    self._write(item)
            finally:
                self._queue.task_done()

    def _write(self, item: BackgroundJob) -> None:
        if self.recorder is None:
            return
        for attempt in range(3):
            try:
                self.recorder.save_background_job(item)
            except Exception as error:
                logger.warning(
                    "Job persistence failed. job_id=%s attempt=%d error_type=%s",
                    item.job_id,
                    attempt + 1,
                    type(error).__name__,
                )
            else:
                self._failed.pop(item.job_id, None)
                return
        self._failed[item.job_id] = item
