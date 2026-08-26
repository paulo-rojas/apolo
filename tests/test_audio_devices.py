import sys
import types

from voice.audio_devices import safe_default_input_device, selected_device


class FakeSoundDevice(types.SimpleNamespace):
    pass


def test_safe_default_input_keeps_normal_default(monkeypatch):
    fake = FakeSoundDevice()
    fake.default = types.SimpleNamespace(device=(0, 1))
    fake.query_devices = lambda *args, **kwargs: [
        {"name": "USB Microphone", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    assert safe_default_input_device() is None


def test_safe_default_input_avoids_loopback_default(monkeypatch):
    fake = FakeSoundDevice()
    fake.default = types.SimpleNamespace(device=(0, 2))
    fake.query_devices = lambda *args, **kwargs: [
        {"name": "Stereo Mix", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "USB Microphone", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    assert safe_default_input_device() == 1


def test_selected_device_respects_explicit_config(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text('{"audio":{"input_device":"3"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert selected_device("input") == 3
