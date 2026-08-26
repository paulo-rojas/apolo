import pytest


@pytest.fixture(autouse=True)
def isolate_audio_gate_files(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_GATE_PATH", tmp_path / "listener_mute_until.txt")
    monkeypatch.setattr(gate, "_COMPUTER_AUDIO_PATH", tmp_path / "computer_audio_until.txt")
