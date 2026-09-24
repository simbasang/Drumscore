import copy
import dataclasses
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from app.persistence.models import (
    TERMINAL_STATUSES,
    Analysis,
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    LeaseLostError,
    NewAnalysis,
    NewArtifact,
    Project,
    ProjectSummary,
    ScoreVersion,
    ScoreVersionConflictError,
    Stage,
    new_id,
)


class InMemoryStore:
    """Thread-safe in-process Store used by unit tests. Honours exactly the
    same contract as PostgresStore (tests/test_store_contract.py runs
    against both)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._maintenance = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._jobs: dict[str, Job] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._analyses: dict[str, Analysis] = {}
        self._scores: list[ScoreVersion] = []
        self._cache: dict[tuple[str, Stage, str], CacheEntry] = {}

    # --- projects -------------------------------------------------------
    def create_project_with_job(self, *, source_kind, source_url, source_key, title, max_attempts, now):
        with self._lock:
            project = Project(
                id=new_id(),
                title=title,
                source_kind=source_kind,
                source_url=source_url,
                source_key=source_key,
                created_at=now,
                updated_at=now,
            )
            job = Job(
                id=new_id(),
                project_id=project.id,
                status=JobStatus.QUEUED,
                attempts=0,
                max_attempts=max_attempts,
                available_at=now,
                correlation_id=new_id(),
                created_at=now,
                updated_at=now,
            )
            self._projects[project.id] = project
            self._jobs[job.id] = job
            return project, job

    def get_project(self, project_id):
        with self._lock:
            return self._projects.get(project_id)

    def find_live_project_by_source_key(self, source_key):
        with self._lock:
            matches = [p for p in self._projects.values() if p.source_key == source_key and p.deleted_at is None]
            return max(matches, key=lambda p: p.created_at, default=None)

    def list_live_projects(self):
        with self._lock:
            live = [p for p in self._projects.values() if p.deleted_at is None]
            live.sort(key=lambda p: (p.updated_at, p.created_at), reverse=True)
            summaries = []
            for project in live:
                job = self.latest_job(project.id)
                summaries.append(
                    ProjectSummary(
                        project=project,
                        latest_job_status=job.status if job else None,
                        has_edits=any(s.project_id == project.id for s in self._scores),
                    )
                )
            return summaries

    def set_project_title(self, project_id, title, now):
        with self._lock:
            self._touch_project(project_id, now, title=title)

    def soft_delete_project(self, project_id, now):
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.deleted_at is not None:
                return False
            self._projects[project_id] = dataclasses.replace(project, deleted_at=now, updated_at=now)
            return True

    def _touch_project(self, project_id: str, now: datetime, **changes: Any) -> None:
        project = self._projects[project_id]
        self._projects[project_id] = dataclasses.replace(project, updated_at=now, **changes)

    # --- jobs / queue -----------------------------------------------------
    def get_job(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def latest_job(self, project_id):
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.project_id == project_id]
            return max(jobs, key=lambda j: j.created_at, default=None)

    def claim_next_job(self, owner, lease_seconds, now):
        with self._lock:
            candidates = [
                j
                for j in self._jobs.values()
                if j.status not in TERMINAL_STATUSES
                and j.available_at <= now
                and (j.lease_expires_at is None or j.lease_expires_at < now)
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda j: j.created_at)
            claimed = dataclasses.replace(
                job,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempts=job.attempts + 1,
                updated_at=now,
            )
            self._jobs[job.id] = claimed
            return claimed

    def _owned(self, job_id: str, owner: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None or job.lease_owner != owner:
            raise LeaseLostError(job_id)
        return job

    def extend_lease(self, job_id, owner, lease_seconds, now):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.lease_owner != owner:
                return False
            self._jobs[job_id] = dataclasses.replace(
                job, lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now
            )
            return True

    def release_lease(self, job_id, owner, now):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.lease_owner != owner:
                return
            self._jobs[job_id] = dataclasses.replace(
                job,
                lease_owner=None,
                lease_expires_at=None,
                available_at=now,
                attempts=max(job.attempts - 1, 0),
                updated_at=now,
            )

    def set_job_status(self, job_id, owner, status, now):
        with self._lock:
            job = self._owned(job_id, owner)
            self._jobs[job_id] = dataclasses.replace(job, status=status, updated_at=now)

    def commit_stage(self, job_id, owner, status, artifacts: Sequence[NewArtifact], cache_entry, now):
        with self._lock:
            job = self._owned(job_id, owner)
            created = [
                Artifact(
                    id=new_id(),
                    project_id=job.project_id,
                    job_id=job.id,
                    kind=a.kind,
                    storage_key=a.storage_key,
                    size_bytes=a.size_bytes,
                    sha256=a.sha256,
                    created_at=now,
                )
                for a in artifacts
            ]
            for artifact in created:
                self._artifacts[artifact.id] = artifact
            if cache_entry is not None:
                self._cache[(cache_entry.source_key, cache_entry.stage, cache_entry.pipeline_version)] = cache_entry
            self._jobs[job_id] = dataclasses.replace(job, status=status, updated_at=now)
            return created

    def fail_job(self, job_id, owner, error, now):
        with self._lock:
            job = self._owned(job_id, owner)
            self._jobs[job_id] = dataclasses.replace(
                job,
                status=JobStatus.FAILED,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )

    def schedule_retry(self, job_id, owner, error, available_at, now):
        with self._lock:
            job = self._owned(job_id, owner)
            self._jobs[job_id] = dataclasses.replace(
                job, error=error, available_at=available_at, lease_owner=None, lease_expires_at=None, updated_at=now
            )

    def requeue_failed_job(self, job_id, now):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.FAILED:
                return None
            requeued = dataclasses.replace(
                job,
                status=JobStatus.QUEUED,
                attempts=0,
                error=None,
                available_at=now,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=None,
                updated_at=now,
            )
            self._jobs[job_id] = requeued
            return requeued

    # --- artifacts / cache ------------------------------------------------
    def artifacts_for_job(self, job_id):
        with self._lock:
            by_kind: dict[ArtifactKind, Artifact] = {}
            for artifact in sorted(self._artifacts.values(), key=lambda a: a.created_at):
                if artifact.job_id == job_id:
                    by_kind[artifact.kind] = artifact
            return by_kind

    def get_cache_entry(self, source_key, stage, pipeline_version):
        with self._lock:
            return self._cache.get((source_key, stage, pipeline_version))

    def complete_job(self, job_id, owner, analysis: NewAnalysis, now):
        with self._lock:
            job = self._owned(job_id, owner)
            stored = Analysis(
                id=new_id(),
                project_id=job.project_id,
                job_id=job.id,
                pipeline_version=analysis.pipeline_version,
                tempo_bpm=analysis.tempo_bpm,
                tempo_map=analysis.tempo_map,
                beats=list(analysis.beats),
                events=list(analysis.events),
                raw_events=list(analysis.raw_events),
                created_at=now,
            )
            self._analyses[stored.id] = stored
            self._jobs[job_id] = dataclasses.replace(
                job,
                status=JobStatus.COMPLETED,
                error=None,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            self._touch_project(job.project_id, now)
            return stored

    # --- analyses / scores ------------------------------------------------
    def latest_analysis(self, project_id):
        with self._lock:
            analyses = [a for a in self._analyses.values() if a.project_id == project_id]
            return max(analyses, key=lambda a: a.created_at, default=None)

    def latest_score(self, project_id):
        with self._lock:
            scores = [s for s in self._scores if s.project_id == project_id]
            return max(scores, key=lambda s: s.version, default=None)

    def save_score(self, project_id, analysis_id, score, base_version, now):
        with self._lock:
            latest = self.latest_score(project_id)
            latest_version = latest.version if latest else None
            if base_version != latest_version:
                raise ScoreVersionConflictError(latest_version)
            saved = ScoreVersion(
                id=new_id(),
                project_id=project_id,
                analysis_id=analysis_id,
                version=(latest_version or 0) + 1,
                score=copy.deepcopy(score),
                created_at=now,
            )
            self._scores.append(saved)
            self._touch_project(project_id, now)
            return saved

    # --- lifecycle ----------------------------------------------------------
    def _row_is_disposable(self, artifact: Artifact, failed_before: datetime) -> bool:
        project = self._projects[artifact.project_id]
        job = self._jobs[artifact.job_id]
        if project.deleted_at is not None:
            return True
        if job.status == JobStatus.FAILED and job.finished_at is not None and job.finished_at < failed_before:
            return True
        return artifact.kind == ArtifactKind.SOURCE_AUDIO and job.status == JobStatus.COMPLETED

    def disposable_storage_keys(self, failed_before):
        with self._lock:
            rows_by_key: dict[str, list[Artifact]] = {}
            for artifact in self._artifacts.values():
                if artifact.pruned_at is None:
                    rows_by_key.setdefault(artifact.storage_key, []).append(artifact)
            return {
                key
                for key, rows in rows_by_key.items()
                if all(self._row_is_disposable(row, failed_before) for row in rows)
            }

    def mark_storage_keys_pruned(self, keys, now):
        with self._lock:
            for artifact_id, artifact in list(self._artifacts.items()):
                if artifact.storage_key in keys and artifact.pruned_at is None:
                    self._artifacts[artifact_id] = dataclasses.replace(artifact, pruned_at=now)
            self._cache = {
                cache_key: entry
                for cache_key, entry in self._cache.items()
                if not any(a.storage_key in keys for a in entry.artifacts)
            }

    def purge_deleted_projects(self):
        with self._lock:
            doomed = {pid for pid, p in self._projects.items() if p.deleted_at is not None}
            self._projects = {pid: p for pid, p in self._projects.items() if pid not in doomed}
            self._jobs = {jid: j for jid, j in self._jobs.items() if j.project_id not in doomed}
            self._artifacts = {aid: a for aid, a in self._artifacts.items() if a.project_id not in doomed}
            self._analyses = {aid: a for aid, a in self._analyses.items() if a.project_id not in doomed}
            self._scores = [s for s in self._scores if s.project_id not in doomed]
            return len(doomed)

    @contextmanager
    def maintenance_lock(self) -> Iterator[bool]:
        acquired = self._maintenance.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._maintenance.release()
