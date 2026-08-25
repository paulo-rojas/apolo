import json

from core.config import get_bool, get_int, get_str
from voice.whisper_cpp import whisper_model_name, whisper_model_path


def test_config_reads_json_and_env_overrides(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text(
        json.dumps(
            {
                "browser": {"headless": False, "timeout_ms": 9000},
                "whisper": {"model": "base", "model_path": "C:\\models\\ggml-base.bin"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert get_bool("browser.headless", True) is False
    assert get_int("browser.timeout_ms", 15000) == 9000
    assert whisper_model_name() == "base"
    assert str(whisper_model_path()) == "C:\\models\\ggml-base.bin"

    monkeypatch.setenv("APOLO_WHISPER_MODEL", "small")
    assert whisper_model_name() == "small"
