import hashlib
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.storage import LocalArtifactStorage, artifact_key


def test_artifact_key_is_relative_and_scoped_by_project_and_job():
    assert artifact_key("p1", "j1", "drums.wav") == "projects/p1/j1/drums.wav"


def test_put_moves_file_into_place_and_reports_size_and_hash(tmp_path):
    storage = LocalArtifactStorage(tmp_path / "store")
    source = tmp_path / "input.wav"
    source.write_bytes(b"audio-bytes")

    stored = storage.put("projects/p/j/source.wav", source)

    assert stored.key == "projects/p/j/source.wav"
    assert stored.size_bytes == 11
    assert stored.sha256 == hashlib.sha256(b"audio-bytes").hexdigest()
    assert storage.read_bytes("projects/p/j/source.wav") == b"audio-bytes"
    assert storage.exists("projects/p/j/source.wav")
    assert list((tmp_path / "store" / "tmp").iterdir()) == []


def test_put_bytes_writes_content(tmp_path):
    storage = LocalArtifactStorage(tmp_path)

    stored = storage.put_bytes("projects/p/j/raw.json", b"[]")

    assert stored.size_bytes == 2
    assert storage.read_bytes("projects/p/j/raw.json") == b"[]"


def test_put_replaces_an_existing_key_atomically(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    storage.put_bytes("k/a.bin", b"old")

    storage.put_bytes("k/a.bin", b"new")

    assert storage.read_bytes("k/a.bin") == b"new"


def test_failed_copy_leaves_no_committed_file(tmp_path, monkeypatch):
    storage = LocalArtifactStorage(tmp_path)
    source = tmp_path / "input.wav"
    source.write_bytes(b"x")

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        storage.put("k/source.wav", source)

    assert not storage.exists("k/source.wav")
    assert list((tmp_path / "tmp").iterdir()) == []


@pytest.mark.parametrize("bad_key", ["/etc/passwd", "../escape", "a/../../b", "a\\b", "", "C:/evil.txt", "Z:/x/y", "c:relative"])
def test_path_rejects_unsafe_keys(tmp_path, bad_key):
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.path(bad_key)


def test_delete_removes_file_and_tolerates_missing(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    storage.put_bytes("k/a.bin", b"x")

    storage.delete("k/a.bin")
    storage.delete("k/a.bin")

    assert not storage.exists("k/a.bin")


def test_staging_dir_is_created_under_tmp_and_removed(tmp_path):
    storage = LocalArtifactStorage(tmp_path)

    with storage.staging_dir() as staging:
        (staging / "nested").mkdir()
        (staging / "nested" / "f.wav").write_bytes(b"x")
        inside = staging.parent == tmp_path / "tmp"

    assert inside
    assert not staging.exists()


def test_delete_stale_temp_removes_only_old_entries(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    old = tmp_path / "tmp" / "old.part"
    old.write_bytes(b"x")
    old_dir = tmp_path / "tmp" / "olddir"
    old_dir.mkdir()
    (old_dir / "f").write_bytes(b"x")
    fresh = tmp_path / "tmp" / "fresh.part"
    fresh.write_bytes(b"x")
    long_ago = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(old, (long_ago, long_ago))
    os.utime(old_dir, (long_ago, long_ago))

    removed = storage.delete_stale_temp(datetime.now(UTC) - timedelta(days=1))

    assert removed == 2
    assert not old.exists()
    assert not old_dir.exists()
    assert fresh.exists()


def test_total_bytes_counts_stored_files_but_not_temp(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    storage.put_bytes("k/a.bin", b"12345")
    storage.put_bytes("k/b.bin", b"123")
    (tmp_path / "tmp" / "junk.part").write_bytes(b"xxxxxxxxxx")

    assert storage.total_bytes() == 8
