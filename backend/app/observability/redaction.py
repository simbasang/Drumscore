"""Keeping secrets and host details out of logs and API responses."""

import re

_URL_PASSWORD = re.compile(r"(?P<prefix>[A-Za-z][A-Za-z0-9+.\-]*://[^:/@\s]*:)[^@\s/]+@")
_KEYWORD_PASSWORD = re.compile(r"(?i)(?P<prefix>\bpassword\s*=\s*)[^\s'\"&;]+")


def redact(text: str) -> str:
    """Replaces the password in `scheme://user:password@host` URLs and in
    libpq-style `password=...` pairs with `***`."""
    text = _URL_PASSWORD.sub(r"\g<prefix>***@", text)
    return _KEYWORD_PASSWORD.sub(r"\g<prefix>***", text)
