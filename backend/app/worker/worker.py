import logging
import os
import random
import socket
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from app.clock import utc_now
from app.config import Settings
from app.observability.redaction import default_error_roots
from app.persistence.models import LeaseLostError
from app.persistence.store import Store
from app.pipeline.runner import JobAbandoned, JobContext, PipelineEngines, process_job
from app.storage import ArtifactStorage
from app.worker.heartbeat import LeaseHeartbeat
from app.worker.pruner import prune

logger = logging.getLogger(__name__)


def default_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class Worker:
    """Claims one job at a time from the Store queue and processes it. Run
    one Worker per OS process; WORKER_CONCURRENCY processes bound how many
    heavy pipelines run at once."""

    def __init__(
        self,
        *,
        store: Store,
        storage: ArtifactStorage,
        engines: PipelineEngines,
        settings: Settings,
        clock: Callable[[], datetime] = utc_now,
        owner: str | None = None,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.store = store
        self.storage = storage
        self.engines = engines
        self.settings = settings
        self.owner = owner or default_owner()
        self._clock = clock
        self._jitter = jitter
        self._stop = threading.Event()
        self._next_prune_at: datetime | None = None
        self._error_roots = default_error_roots(settings.storage_root)

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> bool:
        job = self.store.claim_next_job(self.owner, self.settings.lease_seconds, self._clock())
        if job is None:
            return False

        # attempts only exceeds max_attempts here when the previous attempt
        # died without recording anything (killed process -> lease expiry).
        if job.attempts > job.max_attempts:
            self.store.fail_job(job.id, self.owner, job.error or "Exceeded maximum attempts", self._clock())
            return True

        logger.info("Worker %s claimed job %s (attempt %d)", self.owner, job.id, job.attempts)
        with LeaseHeartbeat(
            self.store, job.id, self.owner, self.settings.lease_seconds, self.settings.heartbeat_seconds, self._clock
        ) as heartbeat:
            context = JobContext(
                store=self.store,
                storage=self.storage,
                engines=self.engines,
                owner=self.owner,
                retry_base_seconds=self.settings.retry_base_seconds,
                clock=self._clock,
                should_stop=lambda: self._stop.is_set() or heartbeat.lost,
                error_roots=self._error_roots,
            )
            try:
                process_job(job, context)
            except JobAbandoned:
                if not heartbeat.lost:
                    self.store.release_lease(job.id, self.owner, self._clock())
                logger.info("Worker %s abandoned job %s", self.owner, job.id)
            except LeaseLostError:
                logger.warning("Lost lease on job %s; another worker owns it now", job.id)
        return True

    def maybe_prune(self) -> None:
        now = self._clock()
        if self._next_prune_at is not None and now < self._next_prune_at:
            return
        self._next_prune_at = now + timedelta(seconds=self.settings.prune_interval_seconds)
        prune(self.store, self.storage, now, self.settings)

    def _wait_poll_interval(self) -> None:
        interval = self.settings.poll_interval_seconds
        self._stop.wait(interval + self._jitter(0.0, interval / 2))

    def run_forever(self) -> None:
        """Runs the claim loop until `stop()` is called. A plain Exception
        from `maybe_prune()` or `run_once()` (e.g. a transient DB outage in
        a store call) is logged and the loop keeps going after one poll
        interval; a claimed job recovers through its lease expiring.
        BaseException (KeyboardInterrupt, SystemExit, ...) still propagates
        and stops the worker."""
        logger.info("Worker %s started", self.owner)
        while not self._stop.is_set():
            try:
                self.maybe_prune()
            except Exception:  # noqa: BLE001 - a maintenance blip must not kill the worker
                logger.exception("Worker %s: prune failed", self.owner)
                self._wait_poll_interval()
                continue

            try:
                processed = self.run_once()
            except Exception:  # noqa: BLE001 - a claim/store blip must not kill the worker
                logger.exception("Worker %s: run_once failed", self.owner)
                self._wait_poll_interval()
                continue

            if not processed:
                self._wait_poll_interval()
        logger.info("Worker %s stopped", self.owner)
