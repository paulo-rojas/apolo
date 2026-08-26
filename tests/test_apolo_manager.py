from manager import ApoloManager, ServiceState


def test_manager_lifecycle_emits_status_and_logs():
    manager = ApoloManager()
    events = []
    manager.on("status_changed", events.append)
    manager.on("log_received", lambda source, message: events.append((source, message)))

    manager.start()

    assert manager.get_status() == "Activo"
    assert events == ["Activo", ("SYSTEM", "Apolo iniciado")]


def test_manager_exposes_service_states_and_updates_them():
    manager = ApoloManager()
    changed = []
    manager.on("service_changed", changed.append)

    manager.set_service_status("Browser", ServiceState.CONNECTED, "Connected via CDP")

    assert changed[-1].state is ServiceState.CONNECTED
    assert manager.get_services()[3].detail == "Connected via CDP"


def test_audio_level_emits_listening_state():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)
    manager.start()
    manager._listener_accepts_voice = True

    manager._audio_level(0.2)
    assert states[-1] == "Escuchando"

    manager._last_audio_at -= 1
    manager._audio_level(0.0)
    assert states[-1] == "Activo"
    manager.stop()


def test_audio_level_threshold_avoids_idle_listening():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)
    manager.start()

    manager._audio_level(0.02)

    assert states == ["Activo"]
    manager.stop()


def test_push_to_talk_hotkey_checks_all_keys(monkeypatch):
    from voice.local_listener import _hotkey_is_pressed

    class FakeKeyboard:
        @staticmethod
        def is_pressed(key):
            return key in pressed

    pressed = {"ctrl", "space"}

    assert _hotkey_is_pressed(FakeKeyboard, "ctrl+space")
    assert not _hotkey_is_pressed(FakeKeyboard, "ctrl+shift")


def test_voice_log_wake_detected_sets_attention_state():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)

    manager._handle_process_log("VOICE", "voice listener: wake detected")

    assert states[-1] == "Atento"


def test_voice_json_wake_feedback_sets_attention_state():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)

    manager._handle_process_log("VOICE", '{"ok":true,"kind":"session","feedback":"wake"}')

    assert states[-1] == "Atento"


def test_voice_json_repeat_feedback_sets_attention_state():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)

    manager._handle_process_log("VOICE", '{"ok":true,"kind":"repeat","feedback":"repeat"}')

    assert states[-1] == "Atento"


def test_open_mode_listening_is_idle_until_voice_or_wake():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)

    manager._handle_process_log("VOICE", "voice listener: listening")
    manager._handle_process_log("VOICE", "voice listener: recording")
    manager._handle_process_log("VOICE", "voice listener: wake detected")

    assert states == ["Activo", "Escuchando", "Atento"]


def test_voice_log_resting_sets_stopped_state():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)

    manager._handle_process_log("VOICE", "voice listener: resting")

    assert states[-1] == "Detenido"
    assert manager.get_services()[0].detail == "Descansando"


def test_voice_log_shutdown_sets_stopped_state():
    manager = ApoloManager()
    states = []
    manager.on("status_changed", states.append)

    manager._handle_process_log("VOICE", "voice listener: shutdown requested")

    assert states[-1] == "Detenido"
    assert manager.get_services()[0].detail == "Sesión terminada"


def test_voice_process_exit_after_shutdown_emits_shutdown_request(tmp_path, monkeypatch):
    import core.listener_control as control

    monkeypatch.setattr(control, "_SHUTDOWN_PATH", tmp_path / "shutdown.flag")
    control.request_shutdown()

    manager = ApoloManager()
    events = []
    manager.on("shutdown_requested", lambda: events.append("shutdown"))
    manager._running = True
    process = type("Process", (), {"poll": lambda self: 0})()
    manager._voice_process = process

    manager._handle_process_exit("VOICE", process)

    assert events == ["shutdown"]
    assert manager.get_status() == "Detenido"


def test_start_reactivates_resting_listener(tmp_path, monkeypatch):
    import core.listener_control as control

    monkeypatch.setattr(control, "_REST_PATH", tmp_path / "rest.flag")
    control.rest_listener()

    manager = ApoloManager()
    manager._running = True
    manager.start()

    assert control.listener_is_resting() is False
    assert manager.get_services()[0].detail == "Listener reactivado"


def test_speech_mute_duration_scales_with_text():
    from manager.apolo_manager import _speech_mute_seconds

    assert _speech_mute_seconds("hola") >= 2.0
    assert _speech_mute_seconds("uno dos tres cuatro cinco seis") > _speech_mute_seconds("hola")


def test_voice_listener_command_uses_configured_transcriber(tmp_path, monkeypatch):
    from manager.apolo_manager import _voice_listener_command

    config = tmp_path / "apolo.json"
    config.write_text('{"whisper": {"backend": "faster-whisper"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    command = _voice_listener_command("http://127.0.0.1:8000", "open", "ctrl+space")

    assert command[1:3] == ["-m", "voice.local_listener"]
    assert "--transcriber" in command
    assert command[command.index("--transcriber") + 1] == "faster-whisper"


def test_voice_listener_command_can_use_realtime_stt(tmp_path, monkeypatch):
    from manager.apolo_manager import _voice_listener_command

    config = tmp_path / "apolo.json"
    config.write_text('{"whisper": {"backend": "realtime-stt"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    command = _voice_listener_command("http://127.0.0.1:8000", "open", "ctrl+space")

    assert command[command.index("--transcriber") + 1] == "realtime-stt"
