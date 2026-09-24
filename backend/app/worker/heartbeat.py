import contextvars
import logging
import threading
from collections.abc import Callable
from datetime import datetime

from app.clock import utc_now
from app.persistence.store import Store

logger = logging.getLogger(__name__)


class LeaseHeartbeat:
    """Extends a claimed job's lease every `interval_seconds` on a daemon
    thread while the job runs. If an extension is refused (the lease
    expired and another worker reclaimed the job) `lost` becomes True and
    the runner abandons the job at its next stage checkpoint."""

    def __init__(
        self,
        store: Store,
        job_id: str,
        owner: str,
        lease_seconds: int,
        interval_seconds: float,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._job_id = job_id
        self._owner = owner
        self._lease_seconds = lease_seconds
        self._interval = interval_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = False

    def __enter__(self) -> "LeaseHeartbeat":
        # Run the thread inside a copy of the caller's context so its log
        # records carry the job's log context (job_id, correlation_id, ...).
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run, args=(self._run,), daemon=True, name=f"heartbeat-{self._job_id}"
        )
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                extended = self._store.extend_lease(self._job_id, self._owner, self._lease_seconds, self._clock())
            except Exception:  # noqa: BLE001 - a DB blip must not kill the heartbeat; the lease has slack
                logger.exception("Heartbeat for job %s failed; retrying", self._job_id)
                continue
            if not extended:
                logger.warning("Lease on job %s was lost", self._job_id)
                self.lost = True
                return
