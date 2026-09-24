from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol

from app.persistence.models import (
    Analysis,
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    NewAnalysis,
    NewArtifact,
    Project,
    ProjectSummary,
    ScoreVersion,
    Stage,
)


class Store(Protocol):
    """Durable state for projects, the job queue, artifacts, analyses,
    score versions and the stage cache. One object (rather than one
    repository per table) so a stage commit - artifact rows, cache entry
    and status transition - is a single transaction. Methods that mutate a
    leased job take the caller's `owner` and raise LeaseLostError if the
    job's lease has passed to someone else. See docs/PERSISTENCE.md."""

    # --- projects -------------------------------------------------------
    def create_project_with_job(
        self, *, source_kind: str, source_url: str, source_key: str, title: str, max_attempts: int, now: datetime
    ) -> tuple[Project, Job]: ...

    def get_project(self, project_id: str) -> Project | None: ...

    def find_live_project_by_source_key(self, source_key: str) -> Project | None: ...

    def list_live_projects(self) -> list[ProjectSummary]: ...

    def set_project_title(self, project_id: str, title: str, now: datetime) -> None: ...

    def soft_delete_project(self, project_id: str, now: datetime) -> bool: ...

    # --- jobs / queue -----------------------------------------------------
    def get_job(self, job_id: str) -> Job | None: ...

    def latest_job(self, project_id: str) -> Job | None: ...

    def claim_next_job(self, owner: str, lease_seconds: int, now: datetime) -> Job | None: ...

    def extend_lease(self, job_id: str, owner: str, lease_seconds: int, now: datetime) -> bool: ...

    def release_lease(self, job_id: str, owner: str, now: datetime) -> None: ...

    def set_job_status(self, job_id: str, owner: str, status: JobStatus, now: datetime) -> None: ...

    def commit_stage(
        self,
        job_id: str,
        owner: str,
        status: JobStatus,
        artifacts: Sequence[NewArtifact],
        cache_entry: CacheEntry | None,
        now: datetime,
    ) -> list[Artifact]: ...

    def complete_job(self, job_id: str, owner: str, analysis: NewAnalysis, now: datetime) -> Analysis: ...

    def fail_job(self, job_id: str, owner: str, error: str, now: datetime) -> None: ...

    def schedule_retry(self, job_id: str, owner: str, error: str, available_at: datetime, now: datetime) -> None: ...

    def requeue_failed_job(self, job_id: str, now: datetime) -> Job | None: ...

    # --- artifacts / cache ------------------------------------------------
    def artifacts_for_job(self, job_id: str) -> dict[ArtifactKind, Artifact]: ...

    def get_cache_entry(self, source_key: str, stage: Stage, pipeline_version: str) -> CacheEntry | None: ...

    # --- analyses / scores ------------------------------------------------
    def latest_analysis(self, project_id: str) -> Analysis | None: ...

    def latest_score(self, project_id: str) -> ScoreVersion | None: ...

    def save_score(
        self, project_id: str, analysis_id: str, score: dict[str, Any], base_version: int | None, now: datetime
    ) -> ScoreVersion: ...

    # --- lifecycle ----------------------------------------------------------
    def disposable_storage_keys(self, failed_before: datetime) -> set[str]: ...

    def mark_storage_keys_pruned(self, keys: set[str], now: datetime) -> None: ...

    def purge_deleted_projects(self) -> int: ...

    def maintenance_lock(self) -> AbstractContextManager[bool]: ...
