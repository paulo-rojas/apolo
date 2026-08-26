from voice.realtime_stt_worker import _append_audio_chunk, _input_device_index, _recorder_kwargs


class FakeAudioArray:
    def __init__(self, data: bytes):
        self.data = data

    def tobytes(self):
        return self.data


def test_append_audio_chunk_accepts_byte_like_values():
    chunks = []

    _append_audio_chunk(chunks, b"one")
    _append_audio_chunk(chunks, bytearray(b"two"))
    _append_audio_chunk(chunks, memoryview(b"three"))
    _append_audio_chunk(chunks, FakeAudioArray(b"four"))
    _append_audio_chunk(chunks, None)

    assert chunks == [b"one", b"two", b"three", b"four"]


def test_input_device_index_ignores_default(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text('{"audio": {"input_device": "default"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert _input_device_index() is None


def test_silero_auto_backend_does_not_force_legacy_onnx_flag(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text(
        '{"realtime_stt": {"silero_backend": "auto", "silero_use_onnx": true}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    kwargs = _recorder_kwargs("es", lambda chunk: None, lambda text: None)

    assert kwargs["silero_backend"] == "auto"
    assert kwargs["silero_use_onnx"] is None


def test_dictation_mode_disables_realtime_prompt(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text('{"whisper": {"prompt": "Apolo comandos"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))
    monkeypatch.setenv("APOLO_VOICE_DICTATION", "1")

    kwargs = _recorder_kwargs("es", lambda chunk: None, lambda text: None)

    assert kwargs["initial_prompt"] is None


def test_short_command_turn_detection_options_are_configurable(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text(
        """
        {
          "realtime_stt": {
            "silero_deactivity_detection": true,
            "post_speech_silence_duration": 0.35,
            "min_length_of_recording": 0.25,
            "early_transcription_on_silence": 0.15
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    kwargs = _recorder_kwargs("es", lambda chunk: None, lambda text: None)

    assert kwargs["silero_deactivity_detection"] is True
    assert kwargs["post_speech_silence_duration"] == 0.35
    assert kwargs["min_length_of_recording"] == 0.25
    assert kwargs["early_transcription_on_silence"] == 0.15
