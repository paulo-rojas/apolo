import json

from core.config import core_host, core_port, core_url, core_ws_url, get_bool, get_int, get_str
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


def test_core_config_defaults_preserve_localhost(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing.json"))

    assert core_host() == "127.0.0.1"
    assert core_port() == 8000
    assert core_url() == "http://127.0.0.1:8000"
    assert core_ws_url() == "ws://127.0.0.1:8000/ws/runtime"


def test_core_config_can_override_endpoint(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text(
        json.dumps({"core": {"host": "0.0.0.0", "port": 8010, "url": "http://apolo-core.local:8010"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert core_host() == "0.0.0.0"
    assert core_port() == 8010
    assert core_url() == "http://apolo-core.local:8010"
    assert core_ws_url() == "ws://apolo-core.local:8010/ws/runtime"
