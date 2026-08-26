import json


def test_open_system_app_discovers_launches_and_remembers(tmp_path, monkeypatch):
    import core.system_apps as apps

    launched = []
    shortcut = tmp_path / "Programs" / "Editor Pro.lnk"
    shortcut.parent.mkdir()
    shortcut.write_text("", encoding="utf-8")

    monkeypatch.setattr(apps, "memory_dir", lambda: tmp_path / "memory")
    monkeypatch.setattr(
        apps,
        "discover_system_apps",
        lambda: [
            {
                "label": "Editor Pro",
                "normalized": "editor pro",
                "source": "test",
                "launch": {"type": "path", "value": str(shortcut)},
            }
        ],
    )

    result = apps.open_system_app("editor", launcher=launched.append)
    second = apps.open_system_app("editor pro", launcher=launched.append)

    registry = json.loads((tmp_path / "memory" / "system_apps.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert second["source"] == "memory"
    assert launched == [{"type": "path", "value": str(shortcut)}, {"type": "path", "value": str(shortcut)}]
    assert registry["aliases"]["editor"]["timesOpened"] == 2


def test_remember_system_app_adds_alias(tmp_path, monkeypatch):
    import core.system_apps as apps

    monkeypatch.setattr(apps, "memory_dir", lambda: tmp_path / "memory")

    result = apps.remember_system_app(
        "mi editor",
        {"type": "path", "value": "C:\\Tools\\editor.exe"},
        label="Editor",
    )

    assert result["ok"] is True
    assert apps.known_app_alias("mi editor") is True


def test_close_system_app_uses_memory_alias_and_remembers(tmp_path, monkeypatch):
    import subprocess
    import core.system_apps as apps

    monkeypatch.setattr(apps, "memory_dir", lambda: tmp_path / "memory")
    apps.remember_system_app(
        "mi editor",
        {"type": "path", "value": "C:\\Tools\\editor.exe"},
        label="Editor",
    )

    def fake_runner(cmd, **kwargs):
        assert "powershell.exe" in cmd[0]
        assert "editor" in cmd[-1]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"id":10,"name":"editor","title":"Editor"}',
            stderr="",
        )

    result = apps.close_system_app("mi editor", runner=fake_runner)
    registry = json.loads((tmp_path / "memory" / "system_apps.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["closed"] == 1
    assert result["processes"][0]["name"] == "editor"
    assert registry["aliases"]["mi editor"]["timesClosed"] == 1
    assert registry["aliases"]["editor"]["timesClosed"] == 1


def test_close_system_app_raises_when_no_window_matches(tmp_path, monkeypatch):
    import subprocess
    import pytest
    import core.system_apps as apps

    monkeypatch.setattr(apps, "memory_dir", lambda: tmp_path / "memory")

    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(apps.SystemAppNotFound):
        apps.close_system_app("editor fantasma", runner=fake_runner)


def test_close_system_app_ignores_browser_titles(tmp_path, monkeypatch):
    import subprocess
    import core.system_apps as apps

    monkeypatch.setattr(apps, "memory_dir", lambda: tmp_path / "memory")

    captured = {}

    def fake_runner(cmd, **kwargs):
        captured["script"] = cmd[-1]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"id":18152,"name":"Discord","title":"Amigos - Discord"}',
            stderr="",
        )

    result = apps.close_system_app("discord", runner=fake_runner)

    assert result["closed"] == 1
    assert "$browserNames -contains $name" in captured["script"]


def test_best_app_match_uses_token_overlap():
    from core.system_apps import best_app_match

    match = best_app_match(
        "visual studio",
        [
            {"label": "Calculator", "normalized": "calculator"},
            {"label": "Visual Studio Code", "normalized": "visual studio code"},
        ],
    )

    assert match["label"] == "Visual Studio Code"
