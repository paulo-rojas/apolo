from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Device:
    id: str
    name: str
    platform: str
    capabilities: set[str] = field(default_factory=set)
    connected: bool = True
    last_seen: datetime = field(default_factory=_now)


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}

    def register(
        self,
        *,
        id: str,
        name: str,
        platform: str,
        capabilities: Iterable[str],
        connected: bool = True,
    ) -> Device:
        device = Device(
            id=str(id).strip(),
            name=str(name).strip(),
            platform=str(platform).strip(),
            capabilities={str(item).strip() for item in capabilities if str(item).strip()},
            connected=connected,
            last_seen=_now(),
        )
        if not device.id:
            raise ValueError("device id is required")
        self._devices[device.id] = device
        return device

    def update_capabilities(self, device_id: str, capabilities: Iterable[str]) -> Device:
        device = self.require(device_id)
        device.capabilities = {str(item).strip() for item in capabilities if str(item).strip()}
        device.last_seen = _now()
        return device

    def mark_seen(self, device_id: str) -> Device:
        device = self.require(device_id)
        device.connected = True
        device.last_seen = _now()
        return device

    def mark_disconnected(self, device_id: str) -> Device:
        device = self.require(device_id)
        device.connected = False
        device.last_seen = _now()
        return device

    def remove(self, device_id: str) -> Device | None:
        return self._devices.pop(device_id, None)

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def require(self, device_id: str) -> Device:
        device = self.get(device_id)
        if device is None:
            raise KeyError(device_id)
        return device

    def list(self) -> list[Device]:
        return list(self._devices.values())

    def supports(self, device_id: str, capability: str) -> bool:
        device = self.get(device_id)
        return bool(device and device.connected and capability in device.capabilities)
