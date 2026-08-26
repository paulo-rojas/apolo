import re

from ui.process_cleanup import _PROCESS_PATTERN, _cleanup_command


def test_cleanup_pattern_ignores_codex_processes():
    command_lines = [
        r"C:\Users\paulo\AppData\Roaming\npm\codex.cmd exec --cd C:\apolo",
        r"node C:\Users\paulo\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js",
        r"python -m pytest tests\test_codex_bridge.py",
        r"C:\Windows\SystemApps\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\SearchHost.exe -ServerName:CortanaUI.AppXstm",
    ]

    for command_line in command_lines:
        assert re.search(_PROCESS_PATTERN, command_line) is None


def test_cleanup_pattern_matches_only_apolo_service_processes():
    command_lines = [
        r"C:\apolo\.venv\Scripts\python.exe -m ui.app",
        r"C:\apolo\.venv\Scripts\python.exe -m voice.local_listener --continuous",
        r"C:\apolo\.venv\Scripts\python.exe -m uvicorn mcp.server:app",
        r"C:\apolo\.venv\Scripts\pythonw.exe -m uvicorn mcp.server:app --host 127.0.0.1",
    ]

    for command_line in command_lines:
        assert re.search(_PROCESS_PATTERN, command_line) is not None


def test_cleanup_command_has_balanced_script_block():
    command = _cleanup_command(10, 20)

    assert "Where-Object {" in command
    assert "$null -ne $_.CommandLine" in command
    assert "$_.CommandLine -like '*C:\\apolo\\.venv\\Scripts\\python*.exe*'" in command
    assert "$_.CommandLine -like '*-m ui.app*'" in command
    assert command.count("{") == command.count("}")
