import io
import json
import sys

from voice.local_listener import (
    RealtimeSttTimeout,
    _is_realtime_stt_backend,
    _looks_like_prompt_echo,
    _maybe_save_training_sample,
    _parse_realtime_stt_result,
    _realtime_stt_command,
    _listen_with_realtime_stt,
    _should_save_training_sample,
)


class FakeRealtimeProcess:
    def __init__(self, output: str, returncode: int = 0):
        self.stdout = io.StringIO(output)
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def test_prompt_echo_is_discarded():
    assert _looks_like_prompt_echo("El usuario suele empezar con el usuario,")


def test_regular_transcript_is_not_prompt_echo():
    assert not _looks_like_prompt_echo("apolov2 sierra discord")


def test_realtime_stt_backend_aliases_are_supported():
    assert _is_realtime_stt_backend("realtime-stt")
    assert _is_realtime_stt_backend("realtimestt")
    assert _is_realtime_stt_backend("realtime_stt")
    assert not _is_realtime_stt_backend("faster-whisper")


def test_realtime_stt_command_uses_current_python(tmp_path):
    command = _realtime_stt_command(tmp_path / "sample.wav", "es")
    assert command[:3] == [sys.executable, "-m", "voice.realtime_stt_worker"]
    assert "--output" in command
    assert "--language" in command
    assert "--loop" not in command


def test_realtime_stt_command_can_run_in_loop_mode(tmp_path):
    command = _realtime_stt_command(tmp_path / "sample.wav", "es", loop=True)

    assert "--loop" in command


def test_parse_realtime_stt_result_uses_last_json_line():
    result = _parse_realtime_stt_result("loading\n{\"ok\": false}\n{\"ok\": true, \"text\": \"Apolo\"}\n")
    assert result == {"ok": True, "text": "Apolo"}


def test_listen_with_realtime_stt_returns_worker_json(tmp_path, monkeypatch, capsys):
    config = tmp_path / "apolo.json"
    config.write_text(json.dumps({"realtime_stt": {"timeout_seconds": 3}}), encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    monkeypatch.setattr(
        "voice.local_listener.subprocess.Popen",
        lambda *args, **kwargs: FakeRealtimeProcess(
            '{"event": "ready"}\n'
            '{"event": "partial", "text": "Apolo"}\n'
            '{"ok": true, "text": "Apolo pausa", "duration_ms": 900, "elapsed_ms": 1200, "backend": "realtime-stt small"}\n'
        ),
    )
    result = _listen_with_realtime_stt(tmp_path / "sample.wav", "es")

    assert result["text"] == "Apolo pausa"
    assert result["duration_ms"] == 900
    output = capsys.readouterr().out
    assert "voice listener: realtime-stt ready; speak now" in output
    assert "voice listener: partial: Apolo" in output


def test_listen_with_realtime_stt_raises_worker_error(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text(json.dumps({"realtime_stt": {"timeout_seconds": 3}}), encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    monkeypatch.setattr(
        "voice.local_listener.subprocess.Popen",
        lambda *args, **kwargs: FakeRealtimeProcess(
            '{"ok": false, "error": "RealtimeSTT unavailable"}\n',
            returncode=2,
        ),
    )

    try:
        _listen_with_realtime_stt(tmp_path / "sample.wav", "es")
    except RuntimeError as error:
        assert "RealtimeSTT unavailable" in str(error)
    else:
        raise AssertionError("expected RuntimeError")


def test_listen_with_realtime_stt_raises_clear_timeout(tmp_path, monkeypatch):
    import subprocess

    config = tmp_path / "apolo.json"
    config.write_text(json.dumps({"realtime_stt": {"timeout_seconds": 3}}), encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))
    process = FakeRealtimeProcess("")

    def timing_out_wait(timeout=None):
        raise subprocess.TimeoutExpired("realtime", timeout)

    process.wait = timing_out_wait
    monkeypatch.setattr("voice.local_listener.subprocess.Popen", lambda *args, **kwargs: process)

    try:
        _listen_with_realtime_stt(tmp_path / "sample.wav", "es")
    except RealtimeSttTimeout as error:
        assert "no final phrase was detected" in str(error)
    else:
        raise AssertionError("expected RealtimeSttTimeout")


def test_listen_with_realtime_stt_terminates_worker_on_keyboard_interrupt(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text(json.dumps({"realtime_stt": {"timeout_seconds": 3}}), encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))
    process = FakeRealtimeProcess("")
    process.returncode = None

    def interrupting_wait(timeout=None):
        raise KeyboardInterrupt

    process.wait = interrupting_wait
    monkeypatch.setattr("voice.local_listener.subprocess.Popen", lambda *args, **kwargs: process)

    try:
        _listen_with_realtime_stt(tmp_path / "sample.wav", "es")
    except KeyboardInterrupt:
        assert process.returncode == -15
    else:
        raise AssertionError("expected KeyboardInterrupt")


def test_training_sample_saved_for_repeat_wake_command(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr("voice.local_listener.memory_dir", lambda: tmp_path / "memory")
    wav_path = tmp_path / "command.wav"
    wav_path.write_bytes(b"RIFFfake")

    _maybe_save_training_sample(
        wav_path,
        transcript="Apolo de meldia",
        response_text=json.dumps({"ok": True, "kind": "repeat", "reason": "command not understood"}),
        duration_ms=1680,
        elapsed_ms=1884,
        backend_label="small cuda/float16",
    )

    samples = sorted((tmp_path / "memory" / "voice_samples").glob("*.json"))
    assert len(samples) == 1
    metadata = json.loads(samples[0].read_text(encoding="utf-8"))
    assert metadata["transcript"] == "Apolo de meldia"
    assert metadata["response"]["kind"] == "repeat"
    assert metadata["backend"] == "small cuda/float16"
    assert metadata["audio"]
    assert (tmp_path / "memory" / "voice_samples" / samples[0].name.replace(".json", ".wav")).exists()


def test_training_sample_can_be_disabled(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text(json.dumps({"voice": {"training": {"enabled": False}}}), encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert not _should_save_training_sample("Apolo siguiente", {"kind": "mcp"})
