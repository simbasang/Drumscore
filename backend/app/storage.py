import hashlib
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import ContextManager, Protocol

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StoredFile:
    key: str
    size_bytes: int
    sha256: str


def artifact_key(project_id: str, job_id: str, filename: str) -> str:
    return f"projects/{project_id}/{job_id}/{filename}"


class ArtifactStorage(Protocol):
    def staging_dir(self) -> ContextManager[Path]: ...
    def put(self, key: str, source: Path) -> StoredFile: ...
    def put_bytes(self, key: str, data: bytes) -> StoredFile: ...
    def path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def read_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def delete_stale_temp(self, older_than: datetime) -> int: ...
    def total_bytes(self) -> int: ...


class LocalArtifactStorage:
    """Artifacts on the local filesystem under `root`. Writes go to
    root/tmp first and are fsync'd and atomically renamed into place, so a
    key either holds a complete file or does not exist - never a partial
    file that looks finished."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._tmp = root / "tmp"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        pure = PurePosixPath(key)
        if not key or "\\" in key or pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe storage key: {key!r}")
        return self.root.joinpath(*pure.parts)

    @contextmanager
    def staging_dir(self) -> Iterator[Path]:
        directory = self._tmp / f"stage-{uuid.uuid4().hex}"
        directory.mkdir()
        try:
            yield directory
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def put(self, key: str, source: Path) -> StoredFile:
        destination = self.path(key)
        partial = self._tmp / f"{uuid.uuid4().hex}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as reader, partial.open("wb") as writer:
                while chunk := reader.read(_CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
        return StoredFile(key=key, size_bytes=size, sha256=digest.hexdigest())

    def put_bytes(self, key: str, data: bytes) -> StoredFile:
        with self.staging_dir() as staging:
            source = staging / "payload"
            source.write_bytes(data)
            return self.put(key, source)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def read_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def delete_stale_temp(self, older_than: datetime) -> int:
        cutoff = older_than.timestamp()
        removed = 0
        for entry in self._tmp.iterdir():
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
        return removed

    def total_bytes(self) -> int:
        return sum(
            f.stat().st_size for f in self.root.rglob("*") if f.is_file() and self._tmp not in f.parents
        )
