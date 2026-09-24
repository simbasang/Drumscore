from app.observability.redaction import redact


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
