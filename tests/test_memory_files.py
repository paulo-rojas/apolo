import json


def test_memory_files_create_and_remember_note(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr("core.memory_files.memory_dir", lambda: tmp_path / "memory")

    from core.memory_files import ensure_memory_files, read_memory_context, remember_note

    base = ensure_memory_files()
    result = remember_note("prefiero respuestas cortas", source="test")
    context = read_memory_context()

    assert (base / "apolo_profile.md").exists()
    assert result["text"] == "prefiero respuestas cortas"
    assert "prefiero respuestas cortas" in context["profile"]


def test_voice_corrections_are_file_backed(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr("core.memory_files.memory_dir", lambda: tmp_path / "memory")

    from core.memory_files import add_voice_correction, apply_voice_corrections

    add_voice_correction("hache te te pe ese", "https")

    assert apply_voice_corrections("protocolo hache te te pe ese") == "protocolo https"


def test_learned_route_is_written_to_memory_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr("core.memory_files.memory_dir", lambda: tmp_path / "memory")

    from core.memory_files import record_learned_route

    record_learned_route(
        "define protocolo http",
        {"parsed": {"kind": "answer", "text": "HTTP es un protocolo."}},
        350,
    )

    learned = json.loads((tmp_path / "memory" / "learned_routes.json").read_text(encoding="utf-8"))
    assert learned["define protocolo http"]["count"] == 1
    assert learned["define protocolo http"]["lastElapsedMs"] == 350


def test_repetitive_answer_is_saved_after_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr("core.memory_files.memory_dir", lambda: tmp_path / "memory")
    config = tmp_path / "config.json"
    config.write_text('{"memory":{"repetitive_threshold":2}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    from core.memory_files import cached_repetitive_answer, maybe_remember_repetitive_answer

    below = maybe_remember_repetitive_answer(
        "define protocolo tls",
        {"parsed": {"kind": "answer", "text": "TLS cifra la comunicacion."}},
        {"count": 1},
    )
    saved = maybe_remember_repetitive_answer(
        "define protocolo tls",
        {"parsed": {"kind": "answer", "text": "TLS cifra la comunicacion."}},
        {"count": 2},
    )

    assert below["saved"] is False
    assert saved["saved"] is True
    assert cached_repetitive_answer("define protocolo tls")["answer"] == "TLS cifra la comunicacion."
