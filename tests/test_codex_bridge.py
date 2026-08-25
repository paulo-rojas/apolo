import json
import subprocess

import pytest

from core.codex_bridge import (
    CodexBridge,
    CodexBridgeDisabled,
    _parse_json_object,
    build_codex_prompt,
    resolve_codex_executable,
)


def test_build_codex_prompt_contains_command_and_allowed_tools():
    prompt = build_codex_prompt("abre github", {"lastCommand": "abre github"})

    assert "abre github" in prompt
    assert "browser.open" in prompt
    assert "No pidas ni propongas browser.get_state" in prompt
    assert "Devuelve SOLO JSON valido" in prompt


def test_parse_json_object_extracts_json_from_text():
    parsed = _parse_json_object('texto {"kind":"mcp","tool":"browser.open","args":{}} fin')

    assert parsed == {"kind": "mcp", "tool": "browser.open", "args": {}}


def test_resolve_codex_executable_uses_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:\\bin\\codex.cmd" if name == "codex" else None)

    assert resolve_codex_executable("codex") == "C:\\bin\\codex.cmd"


def test_codex_bridge_disabled(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text(json.dumps({"codex": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    with pytest.raises(CodexBridgeDisabled):
        CodexBridge().run("abre github", {})


def test_codex_bridge_run_uses_exec_and_reads_last_message(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text(
        json.dumps(
            {
                "codex": {
                    "enabled": True,
                    "executable": "codex",
                    "timeout_seconds": 5,
                    "sandbox": "read-only",
                    "approval": "never",
                    "cwd": str(tmp_path),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    def fake_run(cmd, input, capture_output, text, encoding, errors, timeout, check):
        assert encoding == "utf-8"
        assert errors == "replace"
        output_path = cmd[cmd.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write('{"kind":"mcp","tool":"browser.open","args":{"url":"https://github.com"}}')
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CodexBridge().run("abre github", {})

    assert result["parsed"]["tool"] == "browser.open"
    assert result["parsed"]["args"] == {"url": "https://github.com"}
