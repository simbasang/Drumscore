import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, bindparam, create_engine, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

from app.persistence import tables as t
from app.persistence.models import (
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
from app.persistence.serialization import (
    artifact_from_dict,
    artifact_to_dict,
    beat_from_dict,
    beat_to_dict,
    event_from_dict,
    event_to_dict,
    tempo_map_from_dict,
    tempo_map_to_dict,
)

# Arbitrary constant identifying the pruner's advisory lock.
_MAINTENANCE_LOCK_KEY = 6_021_001

_CLAIM_SQL = text(
    """
    UPDATE jobs
    SET lease_owner = :owner, lease_expires_at = :lease_expires_at,
        attempts = attempts + 1, updated_at = :now
    WHERE id = (
        SELECT id FROM jobs
        WHERE status NOT IN ('completed', 'failed')
          AND available_at <= :now
          AND (lease_expires_at IS NULL OR lease_expires_at < :now)
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1)
    RETURNING *
    """
)

_DISPOSABLE_SQL = text(
    """
    SELECT a.storage_key
    FROM artifacts a
    JOIN jobs j ON j.id = a.job_id
    JOIN projects p ON p.id = a.project_id
    WHERE a.pruned_at IS NULL
    GROUP BY a.storage_key
    HAVING bool_and(
        p.deleted_at IS NOT NULL
        OR (j.status = 'failed' AND j.finished_at < :failed_before)
        OR (a.kind = 'source_audio' AND j.status = 'completed'))
    """
)

_LIVE_BYTES_SQL = text(
    """
    SELECT COALESCE(SUM(size_bytes), 0) FROM (
        SELECT DISTINCT ON (storage_key) size_bytes
        FROM artifacts
        WHERE pruned_at IS NULL
        ORDER BY storage_key
    ) AS live
    """
)

_DROP_CACHE_SQL = text(
    """
    DELETE FROM stage_cache
    WHERE EXISTS (
        SELECT 1 FROM jsonb_array_elements(stage_cache.artifacts) AS element
        WHERE element->>'storage_key' = ANY(:keys))
    """
).bindparams(bindparam("keys", type_=ARRAY(Text)))


def _project(row) -> Project:
    return Project(
        id=str(row.id),
        title=row.title,
        source_kind=row.source_kind,
        source_url=row.source_url,
        source_key=row.source_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _job(row) -> Job:
    return Job(
        id=str(row.id),
        project_id=str(row.project_id),
        status=JobStatus(row.status),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        available_at=row.available_at,
        correlation_id=str(row.correlation_id),
        created_at=row.created_at,
        updated_at=row.updated_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        error=row.error,
        finished_at=row.finished_at,
    )


def _artifact(row) -> Artifact:
    return Artifact(
        id=str(row.id),
        project_id=str(row.project_id),
        job_id=str(row.job_id),
        kind=ArtifactKind(row.kind),
        storage_key=row.storage_key,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        created_at=row.created_at,
        pruned_at=row.pruned_at,
    )


def _analysis(row) -> Analysis:
    return Analysis(
        id=str(row.id),
        project_id=str(row.project_id),
        job_id=str(row.job_id),
        pipeline_version=row.pipeline_version,
        tempo_bpm=row.tempo_bpm,
        tempo_map=tempo_map_from_dict(row.tempo_map),
        beats=[beat_from_dict(b) for b in row.beats],
        events=[event_from_dict(e) for e in row.events],
        raw_events=[event_from_dict(e) for e in row.raw_events],
        created_at=row.created_at,
    )


def _score(row) -> ScoreVersion:
    return ScoreVersion(
        id=str(row.id),
        project_id=str(row.project_id),
        analysis_id=str(row.analysis_id),
        version=row.version,
        score=row.score,
        created_at=row.created_at,
    )


class PostgresStore:
    """Store backed by Postgres (schema: app.persistence.tables, owned by
    Alembic). Every public method is one transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- projects -------------------------------------------------------
    def create_project_with_job(self, *, source_kind, source_url, source_key, title, max_attempts, now):
        project_id, job_id = new_id(), new_id()
        with self.engine.begin() as c:
            c.execute(
                insert(t.projects).values(
                    id=project_id,
                    title=title,
                    source_kind=source_kind,
                    source_url=source_url,
                    source_key=source_key,
                    created_at=now,
                    updated_at=now,
                )
            )
            c.execute(
                insert(t.jobs).values(
                    id=job_id,
                    project_id=project_id,
                    status=JobStatus.QUEUED.value,
                    attempts=0,
                    max_attempts=max_attempts,
                    available_at=now,
                    correlation_id=new_id(),
                    created_at=now,
                    updated_at=now,
                )
            )
            project = _project(c.execute(select(t.projects).where(t.projects.c.id == project_id)).one())
            job = _job(c.execute(select(t.jobs).where(t.jobs.c.id == job_id)).one())
        return project, job

    def get_project(self, project_id):
        with self.engine.connect() as c:
            row = c.execute(select(t.projects).where(t.projects.c.id == project_id)).one_or_none()
        return _project(row) if row else None

    def find_live_project_by_source_key(self, source_key):
        query = (
            select(t.projects)
            .where(t.projects.c.source_key == source_key, t.projects.c.deleted_at.is_(None))
            .order_by(t.projects.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _project(row) if row else None

    def list_live_projects(self):
        latest_status = (
            select(t.jobs.c.status)
            .where(t.jobs.c.project_id == t.projects.c.id)
            .order_by(t.jobs.c.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        has_edits = (
            select(t.score_versions.c.id).where(t.score_versions.c.project_id == t.projects.c.id).exists()
        )
        query = (
            select(t.projects, latest_status.label("latest_status"), has_edits.label("has_edits"))
            .where(t.projects.c.deleted_at.is_(None))
            .order_by(t.projects.c.updated_at.desc(), t.projects.c.created_at.desc())
        )
        with self.engine.connect() as c:
            rows = c.execute(query).all()
        return [
            ProjectSummary(
                project=_project(row),
                latest_job_status=JobStatus(row.latest_status) if row.latest_status else None,
                has_edits=bool(row.has_edits),
            )
            for row in rows
        ]

    def set_project_title(self, project_id, title, now):
        with self.engine.begin() as c:
            c.execute(update(t.projects).where(t.projects.c.id == project_id).values(title=title, updated_at=now))

    def soft_delete_project(self, project_id, now):
        with self.engine.begin() as c:
            result = c.execute(
                update(t.projects)
                .where(t.projects.c.id == project_id, t.projects.c.deleted_at.is_(None))
                .values(deleted_at=now, updated_at=now)
            )
        return result.rowcount == 1

    # --- jobs / queue -----------------------------------------------------
    def get_job(self, job_id):
        with self.engine.connect() as c:
            row = c.execute(select(t.jobs).where(t.jobs.c.id == job_id)).one_or_none()
        return _job(row) if row else None

    def latest_job(self, project_id):
        query = select(t.jobs).where(t.jobs.c.project_id == project_id).order_by(t.jobs.c.created_at.desc()).limit(1)
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _job(row) if row else None

    def claim_next_job(self, owner, lease_seconds, now):
        with self.engine.begin() as c:
            row = c.execute(
                _CLAIM_SQL,
                {"owner": owner, "now": now, "lease_expires_at": now + timedelta(seconds=lease_seconds)},
            ).one_or_none()
        return _job(row) if row else None

    def _owned_update(self, c, job_id: str, owner: str, **values: Any) -> None:
        result = c.execute(
            update(t.jobs).where(t.jobs.c.id == job_id, t.jobs.c.lease_owner == owner).values(**values)
        )
        if result.rowcount != 1:
            raise LeaseLostError(job_id)

    def extend_lease(self, job_id, owner, lease_seconds, now):
        with self.engine.begin() as c:
            try:
                self._owned_update(
                    c, job_id, owner, lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now
                )
            except LeaseLostError:
                return False
        return True

    def release_lease(self, job_id, owner, now):
        with self.engine.begin() as c:
            c.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.lease_owner == owner)
                .values(
                    lease_owner=None,
                    lease_expires_at=None,
                    available_at=now,
                    attempts=func.greatest(t.jobs.c.attempts - 1, 0),
                    updated_at=now,
                )
            )

    def set_job_status(self, job_id, owner, status, now):
        with self.engine.begin() as c:
            self._owned_update(c, job_id, owner, status=status.value, updated_at=now)

    def commit_stage(self, job_id, owner, status, artifacts: Sequence[NewArtifact], cache_entry, now):
        with self.engine.begin() as c:
            self._owned_update(c, job_id, owner, status=status.value, updated_at=now)
            project_id = c.execute(select(t.jobs.c.project_id).where(t.jobs.c.id == job_id)).scalar_one()
            ids = [new_id() for _ in artifacts]
            if artifacts:
                c.execute(
                    insert(t.artifacts),
                    [
                        {
                            "id": artifact_id,
                            "project_id": project_id,
                            "job_id": job_id,
                            "kind": a.kind.value,
                            "storage_key": a.storage_key,
                            "size_bytes": a.size_bytes,
                            "sha256": a.sha256,
                            "created_at": now,
                        }
                        for artifact_id, a in zip(ids, artifacts)
                    ],
                )
            if cache_entry is not None:
                c.execute(
                    text(
                        """
                        INSERT INTO stage_cache (source_key, stage, pipeline_version, artifacts, created_at)
                        VALUES (:source_key, :stage, :pipeline_version, CAST(:artifacts AS JSONB), :now)
                        ON CONFLICT ON CONSTRAINT pk_stage_cache
                        DO UPDATE SET artifacts = EXCLUDED.artifacts, created_at = EXCLUDED.created_at
                        """
                    ),
                    {
                        "source_key": cache_entry.source_key,
                        "stage": cache_entry.stage.value,
                        "pipeline_version": cache_entry.pipeline_version,
                        "artifacts": _json([artifact_to_dict(a) for a in cache_entry.artifacts]),
                        "now": now,
                    },
                )
            rows = c.execute(select(t.artifacts).where(t.artifacts.c.id.in_(ids))).all() if ids else []
        return [_artifact(row) for row in rows]

    def complete_job(self, job_id, owner, analysis: NewAnalysis, now):
        analysis_id = new_id()
        with self.engine.begin() as c:
            self._owned_update(
                c,
                job_id,
                owner,
                status=JobStatus.COMPLETED.value,
                error=None,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            project_id = c.execute(select(t.jobs.c.project_id).where(t.jobs.c.id == job_id)).scalar_one()
            c.execute(
                insert(t.analyses).values(
                    id=analysis_id,
                    project_id=project_id,
                    job_id=job_id,
                    pipeline_version=analysis.pipeline_version,
                    tempo_bpm=analysis.tempo_bpm,
                    tempo_map=tempo_map_to_dict(analysis.tempo_map),
                    beats=[beat_to_dict(b) for b in analysis.beats],
                    events=[event_to_dict(e) for e in analysis.events],
                    raw_events=[event_to_dict(e) for e in analysis.raw_events],
                    created_at=now,
                )
            )
            c.execute(update(t.projects).where(t.projects.c.id == project_id).values(updated_at=now))
            row = c.execute(select(t.analyses).where(t.analyses.c.id == analysis_id)).one()
        return _analysis(row)

    def fail_job(self, job_id, owner, error, now):
        with self.engine.begin() as c:
            self._owned_update(
                c,
                job_id,
                owner,
                status=JobStatus.FAILED.value,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )

    def schedule_retry(self, job_id, owner, error, available_at, now):
        with self.engine.begin() as c:
            self._owned_update(
                c,
                job_id,
                owner,
                error=error,
                available_at=available_at,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
            )

    def requeue_failed_job(self, job_id, now):
        with self.engine.begin() as c:
            row = c.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.status == JobStatus.FAILED.value)
                .values(
                    status=JobStatus.QUEUED.value,
                    attempts=0,
                    error=None,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    finished_at=None,
                    updated_at=now,
                )
                .returning(t.jobs)
            ).one_or_none()
        return _job(row) if row else None

    # --- artifacts / cache ------------------------------------------------
    def artifacts_for_job(self, job_id):
        query = select(t.artifacts).where(t.artifacts.c.job_id == job_id).order_by(t.artifacts.c.created_at)
        with self.engine.connect() as c:
            rows = c.execute(query).all()
        return {ArtifactKind(row.kind): _artifact(row) for row in rows}

    def get_cache_entry(self, source_key, stage, pipeline_version):
        query = select(t.stage_cache).where(
            t.stage_cache.c.source_key == source_key,
            t.stage_cache.c.stage == stage.value,
            t.stage_cache.c.pipeline_version == pipeline_version,
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        if row is None:
            return None
        return CacheEntry(
            source_key=row.source_key,
            stage=Stage(row.stage),
            pipeline_version=row.pipeline_version,
            artifacts=tuple(artifact_from_dict(a) for a in row.artifacts),
        )

    # --- analyses / scores ------------------------------------------------
    def latest_analysis(self, project_id):
        query = (
            select(t.analyses)
            .where(t.analyses.c.project_id == project_id)
            .order_by(t.analyses.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _analysis(row) if row else None

    def latest_score(self, project_id):
        query = (
            select(t.score_versions)
            .where(t.score_versions.c.project_id == project_id)
            .order_by(t.score_versions.c.version.desc())
            .limit(1)
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _score(row) if row else None

    def save_score(self, project_id, analysis_id, score, base_version, now):
        score_id = new_id()
        with self.engine.begin() as c:
            # Row lock on the project serialises concurrent saves so the
            # version check below cannot race.
            c.execute(select(t.projects.c.id).where(t.projects.c.id == project_id).with_for_update())
            latest_version = c.execute(
                select(func.max(t.score_versions.c.version)).where(t.score_versions.c.project_id == project_id)
            ).scalar_one()
            if base_version != latest_version:
                raise ScoreVersionConflictError(latest_version)
            c.execute(
                insert(t.score_versions).values(
                    id=score_id,
                    project_id=project_id,
                    analysis_id=analysis_id,
                    version=(latest_version or 0) + 1,
                    score=score,
                    created_at=now,
                )
            )
            c.execute(update(t.projects).where(t.projects.c.id == project_id).values(updated_at=now))
            row = c.execute(select(t.score_versions).where(t.score_versions.c.id == score_id)).one()
        return _score(row)

    # --- admission ----------------------------------------------------------
    def count_active_jobs(self):
        query = (
            select(func.count())
            .select_from(t.jobs.join(t.projects, t.jobs.c.project_id == t.projects.c.id))
            .where(
                t.jobs.c.status.not_in([JobStatus.COMPLETED.value, JobStatus.FAILED.value]),
                t.projects.c.deleted_at.is_(None),
            )
        )
        with self.engine.connect() as c:
            return c.execute(query).scalar_one()

    def live_artifact_bytes(self):
        with self.engine.connect() as c:
            return int(c.execute(_LIVE_BYTES_SQL).scalar_one())

    # --- lifecycle ----------------------------------------------------------
    def disposable_storage_keys(self, failed_before):
        with self.engine.connect() as c:
            return set(c.execute(_DISPOSABLE_SQL, {"failed_before": failed_before}).scalars())

    def mark_storage_keys_pruned(self, keys, now):
        if not keys:
            return
        key_list = sorted(keys)
        with self.engine.begin() as c:
            c.execute(
                update(t.artifacts)
                .where(t.artifacts.c.storage_key.in_(key_list), t.artifacts.c.pruned_at.is_(None))
                .values(pruned_at=now)
            )
            c.execute(_DROP_CACHE_SQL, {"keys": key_list})

    def purge_deleted_projects(self):
        with self.engine.begin() as c:
            result = c.execute(delete(t.projects).where(t.projects.c.deleted_at.is_not(None)))
        return result.rowcount

    @contextmanager
    def maintenance_lock(self) -> Iterator[bool]:
        with self.engine.connect() as c:
            acquired = c.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _MAINTENANCE_LOCK_KEY}).scalar_one()
            c.commit()
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MAINTENANCE_LOCK_KEY})
                    c.commit()


def _json(value: Any) -> str:
    return json.dumps(value)


def create_postgres_store(database_url: str) -> PostgresStore:
    return PostgresStore(create_engine(database_url, pool_pre_ping=True))
