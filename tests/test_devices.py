from datetime import datetime, timezone

from core.devices import DeviceRegistry


def test_device_registry_registers_devices():
    registry = DeviceRegistry()

    device = registry.register(
        id="laptop-paulo",
        name="Laptop",
        platform="windows",
        capabilities=["system.info", "system.open_app"],
    )

    assert device.connected is True
    assert registry.get("laptop-paulo") is device
    assert registry.supports("laptop-paulo", "system.info")


def test_device_registry_updates_capabilities():
    registry = DeviceRegistry()
    registry.register(id="node", name="Node", platform="windows", capabilities=["system.info"])

    registry.update_capabilities("node", ["system.info", "system.close_app"])

    assert registry.supports("node", "system.close_app")


def test_device_registry_marks_disconnected():
    registry = DeviceRegistry()
    registry.register(id="node", name="Node", platform="windows", capabilities=["system.info"])

    registry.mark_disconnected("node")

    assert registry.get("node").connected is False
    assert not registry.supports("node", "system.info")
    assert isinstance(registry.get("node").last_seen, datetime)
    assert registry.get("node").last_seen.tzinfo is timezone.utc
