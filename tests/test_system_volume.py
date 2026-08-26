import subprocess

import pytest


def test_set_exact_volume_uses_nircmd_when_available(monkeypatch):
    import core.system_volume as volume

    calls = []
    monkeypatch.setattr(volume.shutil, "which", lambda name: "nircmd.exe" if name == "nircmd.exe" else None)
    monkeypatch.setattr(volume.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))

    result = volume.set_system_volume(level=50)

    assert result == {"ok": True, "level": 50, "method": "nircmd"}
    assert calls == [["nircmd.exe", "setsysvolume", "32768"]]


def test_set_exact_volume_reports_missing_backend(monkeypatch):
    import core.system_volume as volume

    monkeypatch.setattr(volume.shutil, "which", lambda name: None)

    with pytest.raises(volume.SystemVolumeUnavailable):
        volume.set_system_volume(level=50)


def test_nudge_volume_uses_windows_media_keys(monkeypatch):
    import core.system_volume as volume

    calls = []
    monkeypatch.setattr(volume.os, "name", "nt")
    monkeypatch.setattr(volume.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))

    result = volume.set_system_volume(direction="up", step=1)

    assert result == {"ok": True, "direction": "up", "step": 1, "method": "media_keys"}
    assert "keybd_event(0xAF" in calls[0][-1]
    assert "SendKeys" not in calls[0][-1]
    assert "VolumeUp" not in calls[0][-1]
