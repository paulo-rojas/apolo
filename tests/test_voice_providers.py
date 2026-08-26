import pytest

from voice.providers import create_speech_to_text_provider, wav_path_for_voice_command


def test_wav_path_for_voice_command():
    assert wav_path_for_voice_command("C:/tmp").name == "apolo_voice_command.wav"


def test_unknown_speech_to_text_provider_fails_clearly():
    with pytest.raises(ValueError, match="unsupported speech-to-text provider"):
        create_speech_to_text_provider("misterio")
