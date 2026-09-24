import logging
import time
from datetime import timedelta

from app.observability.logging import log_context
from app.persistence.memory import InMemoryStore
from app.worker.heartbeat import LeaseHeartbeat
from tests.fakes import FakeClock


def claimed_job(store, clock):
    store.create_project_with_job(source_kind="youtube", source_url="u", source_key="k", title="t", max_attempts=3, now=clock())
    return store.claim_next_job("w", 300, clock())


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    return condition()


def test_heartbeat_extends_the_lease_while_running():
    store, clock = InMemoryStore(), FakeClock()
    job = claimed_job(store, clock)
    clock.advance(100)

    with LeaseHeartbeat(store, job.id, "w", 300, 0.01, clock=clock) as heartbeat:
        extended = wait_for(lambda: store.get_job(job.id).lease_expires_at == clock() + timedelta(seconds=300))

    assert extended
    assert heartbeat.lost is False


def test_heartbeat_flags_a_lost_lease_and_stops():
    store, clock = InMemoryStore(), FakeClock()
    job = claimed_job(store, clock)
    clock.advance(301)
    store.claim_next_job("thief", 300, clock())

    with LeaseHeartbeat(store, job.id, "w", 300, 0.01, clock=clock) as heartbeat:
        lost = wait_for(lambda: heartbeat.lost)

    assert lost


class FlakyStore:
    def __init__(self):
        self.calls = 0

    def extend_lease(self, *args):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("db blip")
        return True


def test_heartbeat_survives_transient_store_errors():
    store = FlakyStore()

    with LeaseHeartbeat(store, "j", "w", 300, 0.01, clock=FakeClock()) as heartbeat:
        recovered = wait_for(lambda: store.calls >= 2)

    assert recovered
    assert heartbeat.lost is False


def test_heartbeat_thread_logs_with_the_callers_context(caplog):
    store, clock = InMemoryStore(), FakeClock()
    job = claimed_job(store, clock)
    clock.advance(301)
    store.claim_next_job("thief", 300, clock())

    with caplog.at_level(logging.WARNING, logger="app.worker.heartbeat"):
        with log_context(job_id=job.id):
            with LeaseHeartbeat(store, job.id, "w", 300, 0.01, clock=clock) as heartbeat:
                wait_for(lambda: heartbeat.lost)

    assert caplog.records[-1].context == {"job_id": job.id}
