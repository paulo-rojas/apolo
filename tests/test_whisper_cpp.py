import pytest

from voice.whisper_cpp import _extract_transcript, whisper_model_name, whisper_prompt


def test_extract_transcript_removes_timestamps():
    output = """
    [00:00:00.000 --> 00:00:01.000] Apolo pon
    [00:00:01.000 --> 00:00:02.000] Everlong
    """

    assert _extract_transcript(output) == "Apolo pon Everlong"


def test_whisper_model_name_defaults_to_small(monkeypatch):
    monkeypatch.delenv("APOLO_WHISPER_MODEL", raising=False)
    monkeypatch.setenv("APOLO_CONFIG_FILE", "missing-apolo-config.json")

    assert whisper_model_name() == "small"


def test_whisper_model_name_rejects_unknown(monkeypatch):
    monkeypatch.setenv("APOLO_WHISPER_MODEL", "large")

    with pytest.raises(ValueError):
        whisper_model_name()


def test_whisper_prompt_reads_config(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text('{"whisper":{"prompt":"Apolo comandos"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert whisper_prompt() == "Apolo comandos"
