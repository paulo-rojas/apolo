def test_listener_rest_flag_roundtrip(tmp_path, monkeypatch):
    import core.listener_control as control

    monkeypatch.setattr(control, "_REST_PATH", tmp_path / "rest.flag")

    assert control.listener_is_resting() is False
    control.rest_listener()
    assert control.listener_is_resting() is True
    control.resume_listener()
    assert control.listener_is_resting() is False


def test_listener_shutdown_flag_roundtrip(tmp_path, monkeypatch):
    import core.listener_control as control

    monkeypatch.setattr(control, "_SHUTDOWN_PATH", tmp_path / "shutdown.flag")

    assert control.shutdown_requested() is False
    control.request_shutdown()
    assert control.shutdown_requested() is True
    control.clear_shutdown()
    assert control.shutdown_requested() is False
