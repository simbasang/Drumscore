"""Keeping secrets and host details out of logs and API responses."""

import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

_URL_PASSWORD = re.compile(r"(?P<prefix>[A-Za-z][A-Za-z0-9+.\-]*://[^:/@\s]*:)[^@\s/]+@")
_KEYWORD_PASSWORD = re.compile(r"(?i)(?P<prefix>\bpassword\s*=\s*)[^\s'\"&;]+")


def redact(text: str) -> str:
    """Replaces the password in `scheme://user:password@host` URLs and in
    libpq-style `password=...` pairs with `***`."""
    text = _URL_PASSWORD.sub(r"\g<prefix>***@", text)
    return _KEYWORD_PASSWORD.sub(r"\g<prefix>***", text)


BACKEND_DIR = Path(__file__).resolve().parents[2]

_MAX_ERROR_CHARS = 500
_HEAD_CHARS = 200
_WINDOWS_PATH = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s'\"<>|*?]*")
_POSIX_PATH = re.compile(r"(?<![\w/:.>~\-])/(?:[^\s'\"/<>]+/)*[^\s'\"/<>]+")


def default_error_roots(storage_root: Path) -> tuple[tuple[Path, str], ...]:
    return ((storage_root, "<storage>"), (Path(tempfile.gettempdir()), "<tmp>"), (BACKEND_DIR, "<app>"))


def sanitize_error_message(message: str, roots: Sequence[tuple[Path, str]] = ()) -> str:
    """Makes an engine/OS error safe to store and return from the API:
    known directories become placeholders, any other absolute path becomes
    `<path>`, passwords are redacted and the text is capped at 500
    characters (head and tail kept, since an engine's stderr ends with the
    actual error)."""
    text = redact(message)
    for root, placeholder in sorted(roots, key=lambda item: len(str(item[0])), reverse=True):
        for spelling in {str(root), root.as_posix()}:
            text = re.sub(re.escape(spelling), placeholder, text, flags=re.IGNORECASE)
    text = _WINDOWS_PATH.sub("<path>", text)
    text = _POSIX_PATH.sub("<path>", text)
    if len(text) > _MAX_ERROR_CHARS:
        tail = _MAX_ERROR_CHARS - _HEAD_CHARS - 1
        text = f"{text[:_HEAD_CHARS]}…{text[-tail:]}"
    return text
