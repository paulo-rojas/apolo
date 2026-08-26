from voice.faster_whisper import FasterWhisperTranscriber, _is_cuda_runtime_error


def test_cuda_runtime_error_detects_missing_cublas():
    assert _is_cuda_runtime_error(RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))


def test_cuda_runtime_error_ignores_regular_errors():
    assert not _is_cuda_runtime_error(RuntimeError("audio file not found"))


def test_dictation_mode_disables_prompt_and_hotwords(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text(
        '{"whisper": {"prompt": "Apolo comandos", "hotwords": "Apolo, pausa"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))
    monkeypatch.setenv("APOLO_VOICE_DICTATION", "1")

    transcriber = FasterWhisperTranscriber()

    assert transcriber.prompt is None
    assert transcriber.hotwords is None
