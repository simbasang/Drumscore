import json
from pathlib import Path

import pytest

import app.readiness as readiness
from app.config import Settings
from app.persistence.migrations import upgrade_to_head
from app.readiness import CheckResult, check_database, check_engines, check_storage, main


def test_check_storage_should_pass_for_a_writable_directory(tmp_path):
    result = check_storage(tmp_path)

    assert result == CheckResult("storage", True, "writable")
    assert list(tmp_path.iterdir()) == []


def test_check_storage_should_fail_for_a_missing_directory(tmp_path):
    result = check_storage(tmp_path / "missing")

    assert result.ok is False
    assert result.name == "storage"


def test_check_storage_should_fail_for_a_file_instead_of_a_directory(tmp_path):
    root = tmp_path / "file"
    root.write_text("x")

    result = check_storage(root)

    assert result.ok is False


def test_check_storage_should_not_leak_the_absolute_path(tmp_path):
    result = check_storage(tmp_path / "missing")

    assert str(tmp_path) not in result.detail


def test_check_engines_should_pass_when_ffmpeg_and_runner_exist(tmp_path, monkeypatch):
    runner = tmp_path / "python"
    runner.write_text("")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: f"/usr/bin/{name}")

    result = check_engines(runner)

    assert result == CheckResult("engines", True, "ffmpeg and DrumScript runner present")


def test_check_engines_should_fail_when_ffmpeg_is_missing(tmp_path, monkeypatch):
    runner = tmp_path / "python"
    runner.write_text("")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)

    result = check_engines(runner)

    assert result.ok is False
    assert "ffmpeg" in result.detail


def test_check_engines_should_fail_when_the_runner_python_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness.shutil, "which", lambda name: f"/usr/bin/{name}")

    result = check_engines(tmp_path / "missing-python")

    assert result.ok is False
    assert "DrumScript" in result.detail


def test_check_database_should_fail_without_leaking_the_password_for_an_unreachable_server():
    url = "postgresql+psycopg://drumscore:hunter2@127.0.0.1:1/drumscore?connect_timeout=1"

    result = check_database(url)

    assert result.ok is False
    assert result.name == "database"
    assert "hunter2" not in result.detail


@pytest.mark.integration
def test_check_database_should_pass_when_migrated_to_head(fresh_database_url):
    upgrade_to_head(fresh_database_url)

    result = check_database(fresh_database_url)

    assert result == CheckResult("database", True, "reachable, migrations at head")


@pytest.mark.integration
def test_check_database_should_fail_when_migrations_are_not_applied(fresh_database_url):
    result = check_database(fresh_database_url)

    assert result.ok is False
    assert "migrations" in result.detail


def settings_for(tmp_path: Path) -> Settings:
    return Settings(storage_root=tmp_path, _env_file=None)


def test_api_checks_should_cover_database_and_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "check_database", lambda url: CheckResult("database", True, "ok"))

    names = [result.name for result in readiness.api_checks(settings_for(tmp_path))]

    assert names == ["database", "storage"]


def test_worker_checks_should_also_cover_engines(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "check_database", lambda url: CheckResult("database", True, "ok"))

    names = [result.name for result in readiness.worker_checks(settings_for(tmp_path))]

    assert names == ["database", "storage", "engines"]


def fake_checks(monkeypatch, ok: bool) -> None:
    results = [CheckResult("database", True, "ok"), CheckResult("storage", ok, "detail")]
    monkeypatch.setattr(readiness, "worker_checks", lambda settings: results)
    monkeypatch.setattr(readiness, "api_checks", lambda settings: results)
    monkeypatch.setattr(readiness, "get_settings", lambda: None)


def test_main_should_exit_zero_and_print_the_checks_when_all_pass(monkeypatch, capsys):
    fake_checks(monkeypatch, ok=True)

    code = main(["worker"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_main_should_exit_nonzero_when_a_check_fails(monkeypatch, capsys):
    fake_checks(monkeypatch, ok=False)

    code = main(["api"])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_ready"


def test_main_should_reject_an_unknown_role(monkeypatch):
    fake_checks(monkeypatch, ok=True)

    with pytest.raises(SystemExit):
        main(["frontend"])


def test_check_storage_should_fail_when_the_directory_is_not_writable(tmp_path, monkeypatch):
    def refuse(**kwargs):
        raise PermissionError(13, "Permission denied", str(tmp_path / "x"))

    monkeypatch.setattr(readiness.tempfile, "NamedTemporaryFile", refuse)

    result = check_storage(tmp_path)

    assert result.ok is False
    assert "PermissionError" in result.detail
    assert str(tmp_path) not in result.detail
