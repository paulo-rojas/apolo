from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.config import get_str


DeviceKind = Literal["input", "output"]


@dataclass(frozen=True)
class AudioDevice:
    id: int
    name: str
    kind: DeviceKind
    channels: int
    is_default: bool = False

    @property
    def label(self) -> str:
        suffix = " (predeterminado)" if self.is_default else ""
        return f"{self.name}{suffix}"


def list_audio_devices(kind: DeviceKind) -> list[AudioDevice]:
    try:
        import sounddevice as sd
    except Exception:
        return []

    try:
        devices = sd.query_devices()
        default_input, default_output = sd.default.device
    except Exception:
        return []

    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    default_id = default_input if kind == "input" else default_output
    result: list[AudioDevice] = []
    for index, device in enumerate(devices):
        channels = int(device.get(channel_key, 0) or 0)
        if channels <= 0:
            continue
        result.append(
            AudioDevice(
                id=index,
                name=_clean_device_name(str(device.get("name", f"Device {index}"))),
                kind=kind,
                channels=channels,
                is_default=index == default_id,
            )
        )
    return result


def selected_device(kind: DeviceKind) -> int | str | None:
    value = get_str(f"audio.{kind}_device", None)
    if value is None or value.strip() in {"", "default"}:
        if kind == "input":
            return safe_default_input_device()
        return None
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        return value


def safe_default_input_device() -> int | None:
    devices = list_audio_devices("input")
    default = next((device for device in devices if device.is_default), None)
    if default and not _looks_like_computer_audio_input(default.name):
        return None
    fallback = next((device for device in devices if not _looks_like_computer_audio_input(device.name)), None)
    return fallback.id if fallback else None


def _looks_like_computer_audio_input(name: str) -> bool:
    normalized = _clean_device_name(name).lower()
    suspicious_terms = (
        "loopback",
        "stereo mix",
        "mezcla estereo",
        "mezcla estéreo",
        "what u hear",
        "wave out",
        "wasapi output",
        "monitor of",
        "altavoces",
        "speakers",
        "speaker",
        "output",
    )
    return any(term in normalized for term in suspicious_terms)


def _clean_device_name(name: str) -> str:
    return " ".join(name.split())
