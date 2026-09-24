from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

# Schema source of truth for PostgresStore. Alembic migrations in
# backend/migrations must keep the database identical to this metadata
# (tests/test_migrations.py compares them).
metadata = MetaData()


def _timestamp(name: str, nullable: bool = False) -> Column:
    return Column(name, DateTime(timezone=True), nullable=nullable)


projects = Table(
    "projects",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("title", Text, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("source_key", Text, nullable=False),
    _timestamp("created_at"),
    _timestamp("updated_at"),
    _timestamp("deleted_at", nullable=True),
    Index("ix_projects_source_key", "source_key"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    _timestamp("available_at"),
    Column("lease_owner", Text, nullable=True),
    _timestamp("lease_expires_at", nullable=True),
    Column("error", Text, nullable=True),
    Column("correlation_id", Uuid(as_uuid=False), nullable=False),
    _timestamp("created_at"),
    _timestamp("updated_at"),
    _timestamp("finished_at", nullable=True),
    Index("ix_jobs_project_id", "project_id"),
    Index("ix_jobs_claim", "status", "available_at"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Uuid(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    _timestamp("created_at"),
    _timestamp("pruned_at", nullable=True),
    Index("ix_artifacts_job_id", "job_id"),
    Index("ix_artifacts_storage_key", "storage_key"),
)

analyses = Table(
    "analyses",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Uuid(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("tempo_bpm", Double, nullable=False),
    Column("tempo_map", JSONB, nullable=False),
    Column("beats", JSONB, nullable=False),
    Column("events", JSONB, nullable=False),
    Column("raw_events", JSONB, nullable=False),
    _timestamp("created_at"),
    UniqueConstraint("job_id", name="uq_analyses_job_id"),
    Index("ix_analyses_project_id", "project_id"),
)

score_versions = Table(
    "score_versions",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("analysis_id", Uuid(as_uuid=False), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("score", JSONB, nullable=False),
    _timestamp("created_at"),
    UniqueConstraint("project_id", "version", name="uq_score_versions_project_version"),
)

stage_cache = Table(
    "stage_cache",
    metadata,
    Column("source_key", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("artifacts", JSONB, nullable=False),
    _timestamp("created_at"),
    PrimaryKeyConstraint("source_key", "stage", "pipeline_version", name="pk_stage_cache"),
)
