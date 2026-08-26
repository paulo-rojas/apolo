from core.state import State
from voice.gateway import VoiceGateway


def test_apolo_pausa_routes_fast_path(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo pausa", confidence=0.9, duration_ms=900)

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.pause"


def test_apolov2_wake_word_routes_fast_path(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("apolov2 pausa", confidence=0.9, duration_ms=900)

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.pause"


def test_apolo_v2_wake_word_routes_fast_path(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo v2 pausa", confidence=0.9, duration_ms=900)

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
    assert result["args"] == {"query": "everlong", "artist": "foo fighters"}


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


def test_open_simple_site_routes_to_default_browser(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo abre GitHub")

    assert result["kind"] == "mcp"
    assert result["tool"] == "web.open"
    assert result["args"] == {"target": "github"}


def test_google_search_routes_to_default_browser(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo busca clima Lima en Google")

    assert result["kind"] == "mcp"
    assert result["tool"] == "web.search_google"
    assert result["args"] == {"query": "clima lima"}


def test_open_program_routes_to_system_app(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo abre la aplicación calculadora")

    assert result["kind"] == "mcp"
    assert result["tool"] == "system.open_app"
    assert result["args"] == {"name": "calculadora"}


def test_close_program_routes_to_system_app(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo cierra la aplicación calculadora")

    assert result["kind"] == "mcp"
    assert result["tool"] == "system.close_app"
    assert result["args"] == {"name": "calculadora"}


def test_close_program_formal_variant_routes_to_system_app(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo, cierre la aplicación discord.")

    assert result["kind"] == "mcp"
    assert result["tool"] == "system.close_app"
    assert result["args"] == {"name": "discord"}


def test_close_program_sierra_transcription_routes_to_system_app(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo, Sierra Discord.")

    assert result["kind"] == "mcp"
    assert result["tool"] == "system.close_app"
    assert result["args"] == {"name": "discord"}


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


def test_computer_audio_guard_blocks_followup_without_wake_word(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_COMPUTER_AUDIO_PATH", tmp_path / "computer.txt")
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    gateway.handle_transcript("apolov2")
    gate.mark_computer_audio_for(30)
    result = gateway.handle_transcript("pausa")

    assert result["kind"] == "ignore"
    assert result["reason"] == "computer audio guard active"


def test_computer_audio_guard_allows_explicit_wake_word(tmp_path, monkeypatch):
    import core.audio_gate as gate

    monkeypatch.setattr(gate, "_COMPUTER_AUDIO_PATH", tmp_path / "computer.txt")
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    gateway.handle_transcript("apolov2")
    gate.mark_computer_audio_for(30)
    result = gateway.handle_transcript("apolov2 pausa")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.pause"


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
    assert result["args"] == {"query": "hablando huevadas", "platform": "youtube"}


def test_hola_pola_variant_detects_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, pola, reproduce Numb de Link in Park en YouTube")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "numb", "artist": "linkin park", "platform": "youtube"}


def test_hola_capolo_unclear_command_requests_repeat(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, Capolo, tal y blé.")

    assert result["kind"] == "repeat"
    assert result["reason"] == "command not understood"


def test_hola_apollo_without_command_starts_session(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, Apollo.")

    assert result["kind"] == "session"
    assert result["feedback"] == "wake"


def test_short_garbled_wake_command_requests_repeat(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo de alble.")

    assert result["kind"] == "repeat"
    assert result["reason"] == "command not understood"


def test_single_garbled_wake_command_requests_repeat(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, polo, pumbly.")

    assert result["kind"] == "repeat"
    assert result["reason"] == "command not understood"


def test_hola_polvo_variant_detects_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola polvo me escuchas")

    assert result["kind"] == "local"
    assert result["command"] == "assistant_status"


def test_a_volo_variant_detects_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("a volo me escuchas")

    assert result["kind"] == "local"
    assert result["command"] == "assistant_status"


def test_repeated_a_polo_variant_detects_command(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, a polo, a polo, a polo, escucharse")

    assert result["kind"] == "local"
    assert result["command"] == "assistant_status"


def test_unclear_wake_attempt_requests_repeat(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, por lo muchas")

    assert result["kind"] == "repeat"
    assert result["feedback"] == "repeat"


def test_unknown_wake_command_falls_back_to_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo, blorpea el tablero azul")

    assert result["kind"] == "codex"
    assert result["command"] == "blorpea el tablero azul"
    assert result["reason"] == "local parser did not understand command"


def test_codex_status_question_routes_to_status(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo tiene esconexion con Codex")

    assert result["kind"] == "status"
    assert result["command"] == "codex"


def test_time_question_routes_to_local_fast_intent(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo dime la hora actual")

    assert result["kind"] == "local"
    assert result["command"] == "time"


def test_date_question_with_asr_plural_routes_local(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, polo que dias hoy.")

    assert result["kind"] == "local"
    assert result["command"] == "date"


def test_volume_asr_variant_routes_local(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola, Apollo, va a ser volumen.")

    assert result["kind"] == "mcp"
    assert result["tool"] == "system.set_volume"
    assert result["args"] == {"direction": "down"}


def test_browser_click_button_routes_without_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo, dale clic al botón de reproducir.")

    assert result["kind"] == "mcp"
    assert result["tool"] == "browser.smart_click"
    assert result["args"] == {"target": "reproducir"}


def test_browser_button_name_routes_without_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo, botón reproducir.")

    assert result["kind"] == "mcp"
    assert result["tool"] == "browser.smart_click"
    assert result["args"] == {"target": "reproducir"}


def test_common_button_name_routes_without_codex_inside_session(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    gateway.handle_transcript("Hola Apolo")
    result = gateway.handle_transcript("enviar")

    assert result["kind"] == "mcp"
    assert result["tool"] == "browser.smart_click"
    assert result["args"] == {"target": "enviar"}


def test_how_are_you_routes_local(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo, cómo estás?")

    assert result["kind"] == "local"
    assert result["command"] == "assistant_status"


def test_rest_command_routes_to_local_rest(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo descansa")

    assert result["kind"] == "local"
    assert result["command"] == "rest"


def test_shutdown_command_routes_to_local_shutdown(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo termina la sesión")

    assert result["kind"] == "local"
    assert result["command"] == "shutdown"


def test_define_http_routes_to_codex_despite_transcription_error(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo, define el protocolo HTTV")

    assert result["kind"] == "codex"
    assert result["command"] == "define el protocolo http"


def test_http_question_with_que_suena_noise_routes_to_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo, qué suena, protocolo, H and TTP")

    assert result["kind"] == "codex"
    assert result["command"] == "protocolo http"


def test_http_question_with_hace_3db_noise_routes_to_codex(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Apolo, qué suena, protocolo, hace 3db")

    assert result["kind"] == "codex"
    assert result["command"] == "protocolo http"


def test_hola_apolo_variant_detects_wake_word(tmp_path):
    gateway = VoiceGateway(State(str(tmp_path / "state.db")))

    result = gateway.handle_transcript("Hola Apolo, pausa")

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.pause"


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
