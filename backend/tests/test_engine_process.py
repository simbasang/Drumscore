from app.engine_process import detached_process_kwargs


def test_windows_children_start_in_a_new_process_group(monkeypatch):
    monkeypatch.setattr("app.engine_process.sys.platform", "win32")

    kwargs = detached_process_kwargs()

    assert kwargs == {"creationflags": 0x00000200}


def test_posix_children_start_in_a_new_session(monkeypatch):
    monkeypatch.setattr("app.engine_process.sys.platform", "linux")

    kwargs = detached_process_kwargs()

    assert kwargs == {"start_new_session": True}
