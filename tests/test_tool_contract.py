import pytest

from core.tool_contract import ToolContractError, validate_structured_tool_args


def test_tool_contract_rejects_raw_command_keys():
    with pytest.raises(ToolContractError):
        validate_structured_tool_args("youtube_music.play", {"command": "pon numb"})


def test_tool_contract_rejects_voice_transcript_as_query():
    with pytest.raises(ToolContractError):
        validate_structured_tool_args("youtube_music.play", {"query": "Apolo ehh ponme Numb de Linkin Park"})


def test_tool_contract_accepts_structured_music_args():
    validate_structured_tool_args(
        "youtube_music.play",
        {"query": "numb", "artist": "linkin park", "platform": "youtube"},
    )


def test_tool_contract_accepts_browser_button_name():
    validate_structured_tool_args("browser.smart_click", {"target": "reproducir"})
