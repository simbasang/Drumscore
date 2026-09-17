from app.jobs import JobStatus, JobStore


def test_create_assigns_unique_id_and_queued_status():
    store = JobStore()

    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    assert job.url == "https://youtu.be/dQw4w9WgXcQ"
    assert job.status == JobStatus.QUEUED
    assert job.id


def test_create_assigns_different_ids_to_different_jobs():
    store = JobStore()

    first = store.create(url="https://youtu.be/aaaaaaaaaaa")
    second = store.create(url="https://youtu.be/bbbbbbbbbbb")

    assert first.id != second.id


def test_get_returns_previously_created_job():
    store = JobStore()
    created = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    found = store.get(created.id)

    assert found == created


def test_get_returns_none_for_unknown_id():
    store = JobStore()

    found = store.get("does-not-exist")

    assert found is None
