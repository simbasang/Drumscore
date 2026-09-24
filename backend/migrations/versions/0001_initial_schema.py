"""initial schema: projects, jobs, artifacts, analyses, score_versions, stage_cache

Revision ID: 0001
Revises:
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_index("ix_projects_source_key", "projects", ["source_key"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        _ts("available_at"),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        _ts("lease_expires_at", nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(as_uuid=False), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("finished_at", nullable=True),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("pruned_at", nullable=True),
    )
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])
    op.create_index("ix_artifacts_storage_key", "artifacts", ["storage_key"])

    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("tempo_bpm", sa.Double(), nullable=False),
        sa.Column("tempo_map", postgresql.JSONB(), nullable=False),
        sa.Column("beats", postgresql.JSONB(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("raw_events", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("job_id", name="uq_analyses_job_id"),
    )
    op.create_index("ix_analyses_project_id", "analyses", ["project_id"])

    op.create_table(
        "score_versions",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(as_uuid=False), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("score", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("project_id", "version", name="uq_score_versions_project_version"),
    )

    op.create_table(
        "stage_cache",
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("source_key", "stage", "pipeline_version", name="pk_stage_cache"),
    )


def downgrade() -> None:
    op.drop_table("stage_cache")
    op.drop_table("score_versions")
    op.drop_table("analyses")
    op.drop_table("artifacts")
    op.drop_table("jobs")
    op.drop_table("projects")
