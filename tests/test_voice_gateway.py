from core.state import State
from voice.gateway import VoiceGateway


def test_apolo_pausa_routes_fast_path(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo pausa", confidence=0.9, duration_ms=900)

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.pause"


def test_apolo_siguiente_routes_fast_path(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo siguiente")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.next"


def test_apolo_pon_everlong_routes_music(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo pon Everlong")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "everlong"}


def test_apolo_pon_everlong_de_foo_fighters_routes_music(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo pon Everlong de Foo Fighters")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "everlong foo fighters"}


def test_open_ended_search_routes_to_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo busca qué significa HTTP 502")

    assert result["kind"] == "codex"
    assert result["reason"] == "open-ended search"


def test_browser_navigation_routes_to_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo abre GitHub y entra al repositorio que estaba viendo")

    assert result["kind"] == "codex"
    assert result["reason"] == "browser navigation requires reasoning"


def test_voice_session_allows_followups_without_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    wake = gateway.handle_transcript("Apolo")
    search = gateway.handle_transcript("pon Arctic Monkeys")
    second = gateway.handle_transcript("la segunda")
    reject = gateway.handle_transcript("esa no")

    assert wake["kind"] == "session"
    assert search["tool"] == "youtube_music.play"
    assert second["tool"] == "youtube_music.play_last_search_index"
    assert second["args"] == {"index": 1}
    assert reject["tool"] == "youtube_music.esa_no"


def test_ignores_transcript_without_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("ayer estaba escuchando música")

    assert result["kind"] == "ignore"
    assert result["reason"] == "wake word not detected"


def test_ignores_non_command_even_inside_active_session(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    gateway.handle_transcript("Apolo")
    result = gateway.handle_transcript("ayer estaba escuchando música")

    assert result["kind"] == "ignore"
    assert result["reason"] == "not a command"


def test_apollo_variant_detects_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("apollo pon música")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"


def test_hola_polo_variant_detects_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Polo, pon hablando huevadas en Youtube")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "hablando huevadas en youtube"}


def test_incomplete_music_command_keeps_session_without_execution(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo reproduce")

    assert result["kind"] == "session"
    assert result["reason"] == "missing command target"


def test_low_confidence_is_ignored(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo pausa", confidence=0.2)

    assert result["kind"] == "ignore"
    assert result["reason"] == "unsafe or empty input"
