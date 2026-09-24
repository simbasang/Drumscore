from pathlib import Path

from app.observability.redaction import BACKEND_DIR, default_error_roots, redact, sanitize_error_message


def test_redact_hides_the_password_in_a_database_url():
    text = "could not connect to postgresql+psycopg://drumscore:hunter2@db:5432/drumscore"

    result = redact(text)

    assert result == "could not connect to postgresql+psycopg://drumscore:***@db:5432/drumscore"


def test_redact_hides_a_libpq_password_keyword():
    result = redact("host=db user=u password=hunter2 dbname=x")

    assert result == "host=db user=u password=*** dbname=x"


def test_redact_leaves_urls_without_credentials_alone():
    text = "https://youtu.be/dQw4w9WgXcQ and http://localhost:8000/api"

    assert redact(text) == text


def test_sanitize_replaces_known_roots_longest_first(tmp_path):
    storage = tmp_path / "app" / "data"
    roots = ((storage, "<storage>"), (tmp_path / "app", "<app>"))
    message = f"Demucs failed: cannot open {storage / 'projects' / 'p' / 'source.wav'}"

    result = sanitize_error_message(message, roots)

    assert str(tmp_path) not in result
    assert result.startswith("Demucs failed: cannot open <storage>")
    assert "source.wav" in result


def test_sanitize_matches_roots_written_with_forward_slashes(tmp_path):
    roots = ((tmp_path, "<storage>"),)

    result = sanitize_error_message(f"missing {tmp_path.as_posix()}/x.wav", roots)

    assert result == "missing <storage>/x.wav"


def test_sanitize_replaces_unknown_absolute_paths():
    message = r"No such file: C:\Users\someone\secret.txt and /home/someone/.cache/model.th"

    result = sanitize_error_message(message)

    assert result == "No such file: <path> and <path>"


def test_sanitize_keeps_urls_and_ratios():
    message = "Failed to download https://youtu.be/dQw4w9WgXcQ at 3/4 speed"

    assert sanitize_error_message(message) == message


def test_sanitize_redacts_passwords():
    result = sanitize_error_message("postgresql://u:hunter2@db/x refused")

    assert "hunter2" not in result


def test_sanitize_caps_long_messages_keeping_head_and_tail():
    message = "H" * 300 + "M" * 1000 + "T" * 300

    result = sanitize_error_message(message)

    assert len(result) == 500
    assert result.startswith("H" * 200 + "…")
    assert result.endswith("T" * 299)


def test_default_error_roots_cover_storage_temp_and_backend(tmp_path):
    roots = dict((placeholder, root) for root, placeholder in default_error_roots(tmp_path))

    assert roots["<storage>"] == tmp_path
    assert roots["<app>"] == BACKEND_DIR
    assert roots["<tmp>"].is_dir()
    assert (BACKEND_DIR / "app" / "config.py").is_file()
