from voice.local_listener import _looks_like_prompt_echo


def test_prompt_echo_is_discarded():
    assert _looks_like_prompt_echo("El usuario suele empezar con el usuario,")


def test_regular_transcript_is_not_prompt_echo():
    assert not _looks_like_prompt_echo("apolov2 sierra discord")
