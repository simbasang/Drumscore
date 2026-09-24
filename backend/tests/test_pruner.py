import logging
import os
from datetime import timedelta

import pytest

from app.config import Settings
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind, JobStatus, NewArtifact
from app.storage import LocalArtifactStorage
from app.worker.pruner import prune
from tests.fakes import FakeClock
from tests.test_store_contract import sample_analysis

OWNER = "w"


@pytest.fixture
def env(tmp_path):
    return InMemoryStore(), LocalArtifactStorage(tmp_path / "s"), FakeClock()


def settings(**overrides):
    return Settings(_env_file=None, **overrides)


def job_with_files(store, storage, clock):
    project, job = store.create_project_with_job(
        source_kind="youtube", source_url="u", source_key="youtube:a", title="t", max_attempts=3, now=clock()
    )
    store.claim_next_job(OWNER, 300, clock())
    descriptors = []
    for kind in (ArtifactKind.SOURCE_AUDIO, ArtifactKind.DRUMS_STEM):
        stored = storage.put_bytes(f"projects/{project.id}/{job.id}/{kind.value}", b"data")
        descriptors.append(NewArtifact(kind, stored.key, stored.size_bytes, stored.sha256))
    store.commit_stage(job.id, OWNER, JobStatus.STEMS_SEPARATED, descriptors, None, clock())
    return project, job


def test_removes_source_audio_after_completion_but_keeps_stems(env):
    store, storage, clock = env
    _, job = job_with_files(store, storage, clock)
    store.complete_job(job.id, OWNER, sample_analysis(), clock())

    report = prune(store, storage, clock(), settings())

    artifacts = store.artifacts_for_job(job.id)
    assert report.deleted_keys == 1
    assert not storage.exists(artifacts[ArtifactKind.SOURCE_AUDIO].storage_key)
    assert artifacts[ArtifactKind.SOURCE_AUDIO].pruned_at == clock()
    assert storage.exists(artifacts[ArtifactKind.DRUMS_STEM].storage_key)


def test_failed_job_files_removed_only_after_retention(env):
    store, storage, clock = env
    _, job = job_with_files(store, storage, clock)
    store.fail_job(job.id, OWNER, "boom", clock())

    early = prune(store, storage, clock() + timedelta(days=6), settings(failed_job_retention_days=7))
    late = prune(store, storage, clock() + timedelta(days=8), settings(failed_job_retention_days=7))

    assert early.deleted_keys == 0
    assert late.deleted_keys == 2


def test_soft_deleted_project_files_and_rows_are_purged(env):
    store, storage, clock = env
    project, job = job_with_files(store, storage, clock)
    keys = [a.storage_key for a in store.artifacts_for_job(job.id).values()]
    store.soft_delete_project(project.id, clock())

    report = prune(store, storage, clock(), settings())

    assert report.purged_projects == 1
    assert store.get_project(project.id) is None
    assert not any(storage.exists(key) for key in keys)


def test_skips_when_another_pruner_holds_the_lock(env):
    store, storage, clock = env

    with store.maintenance_lock():
        report = prune(store, storage, clock(), settings())

    assert report.skipped is True


def test_removes_stale_temp_entries(env, tmp_path):
    store, storage, clock = env
    stale = tmp_path / "s" / "tmp" / "old.part"
    stale.write_bytes(b"x")
    long_ago = (clock() - timedelta(days=2)).timestamp()
    os.utime(stale, (long_ago, long_ago))

    report = prune(store, storage, clock(), settings())

    assert report.removed_temp == 1
    assert not stale.exists()


def test_warns_when_storage_exceeds_threshold(env, caplog):
    store, storage, clock = env
    storage.put_bytes("k/big.bin", b"0123456789")

    with caplog.at_level(logging.WARNING, logger="app.worker.pruner"):
        report = prune(store, storage, clock(), settings(storage_warn_bytes=5))

    assert report.total_bytes == 10
    assert "above STORAGE_WARN_BYTES" in caplog.text
