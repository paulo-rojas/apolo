import time


def test_audio_gate_mutes_until_deadline(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_GATE_PATH", tmp_path / "gate.txt")

    gate.mute_listener_for(1)
    assert gate.listener_is_muted() is True

    gate.clear_listener_mute()
    assert gate.listener_is_muted() is False


def test_audio_gate_clears_expired_deadline(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_GATE_PATH", tmp_path / "gate.txt")
    gate._GATE_PATH.write_text(str(time.time() - 1), encoding="utf-8")

    assert gate.listener_is_muted() is False
    assert not gate._GATE_PATH.exists()


def test_computer_audio_guard_mutes_until_deadline(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_COMPUTER_AUDIO_PATH", tmp_path / "computer.txt")

    gate.mark_computer_audio_for(1)
    assert gate.computer_audio_guard_active() is True

    gate.clear_computer_audio()
    assert gate.computer_audio_guard_active() is False


def test_computer_audio_guard_clears_expired_deadline(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_COMPUTER_AUDIO_PATH", tmp_path / "computer.txt")
    gate._COMPUTER_AUDIO_PATH.write_text(str(time.time() - 1), encoding="utf-8")

    assert gate.computer_audio_guard_active() is False
    assert not gate._COMPUTER_AUDIO_PATH.exists()
