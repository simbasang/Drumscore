from pathlib import Path

from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
OPERATIONS = BACKEND_DIR.parent / "docs" / "OPERATIONS.md"


def env_example_keys():
    lines = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    return {line.split("=", 1)[0].strip() for line in lines if line.strip() and not line.startswith("#")}


def test_every_setting_is_documented_in_operations_md():
    text = OPERATIONS.read_text(encoding="utf-8")

    missing = [name.upper() for name in Settings.model_fields if f"`{name.upper()}`" not in text]

    assert missing == []


def test_env_file_is_git_ignored():
    patterns = (BACKEND_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in [pattern.strip() for pattern in patterns]


def test_env_example_only_uses_known_settings():
    known = {name.upper() for name in Settings.model_fields}

    assert env_example_keys() <= known


def test_env_example_database_url_is_the_development_placeholder():
    lines = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    url = next(line.split("=", 1)[1] for line in lines if line.startswith("DATABASE_URL="))

    assert url == "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
