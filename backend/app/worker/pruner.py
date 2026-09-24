import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import Settings
from app.persistence.store import Store
from app.storage import ArtifactStorage

logger = logging.getLogger(__name__)

_TEMP_RETENTION = timedelta(hours=24)


@dataclass(frozen=True)
class PruneReport:
    skipped: bool
    deleted_keys: int = 0
    purged_projects: int = 0
    removed_temp: int = 0
    total_bytes: int = 0


def prune(store: Store, storage: ArtifactStorage, now: datetime, settings: Settings) -> PruneReport:
    """Applies the retention rules in docs/PERSISTENCE.md. Files are deleted
    before their rows are marked pruned, so a crash in between only means
    the next run re-deletes (missing files are fine) and then marks them."""
    with store.maintenance_lock() as acquired:
        if not acquired:
            return PruneReport(skipped=True)

        failed_before = now - timedelta(days=settings.failed_job_retention_days)
        keys = store.disposable_storage_keys(failed_before=failed_before)
        for key in sorted(keys):
            storage.delete(key)
        store.mark_storage_keys_pruned(keys, now)
        purged = store.purge_deleted_projects()
        removed_temp = storage.delete_stale_temp(now - _TEMP_RETENTION)
        total = storage.total_bytes()

    if total > settings.storage_warn_bytes:
        logger.warning("Artifact storage uses %d bytes, above STORAGE_WARN_BYTES=%d", total, settings.storage_warn_bytes)
    logger.info("Pruned %d storage keys, purged %d projects, removed %d temp entries", len(keys), purged, removed_temp)
    return PruneReport(skipped=False, deleted_keys=len(keys), purged_projects=purged, removed_temp=removed_temp, total_bytes=total)
