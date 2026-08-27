import asyncio

import pytest

from core.apolo_protocol import ToolResultMessage
from core.device_router import DeviceCapabilityError, DeviceConnectionError, DeviceRouter
from core.devices import DeviceRegistry


class FakeTransport:
    def __init__(self, on_send=None):
        self.sent = []
        self.on_send = on_send

    async def send_json(self, data):
        self.sent.append(data)
        if self.on_send:
            await self.on_send(data)


def test_device_router_rejects_missing_capability():
    registry = DeviceRegistry()
    registry.register(id="node", name="Node", platform="windows", capabilities=["system.info"])
    router = DeviceRouter(registry)
    router.attach("node", FakeTransport())

    with pytest.raises(DeviceCapabilityError):
        asyncio.run(router.execute_remote("node", "system.open_app", {}))


def test_device_router_correlates_request_id():
    registry = DeviceRegistry()
    registry.register(id="node", name="Node", platform="windows", capabilities=["system.info"])
    router = DeviceRouter(registry)

    async def complete(data):
        router.complete_result(
            "node",
            ToolResultMessage(request_id=data["request_id"], ok=True, result={"ok": True, "host": "node"}),
        )

    transport = FakeTransport(complete)
    router.attach("node", transport)

    result = asyncio.run(router.execute_remote("node", "system.info", {}))

    assert result == {"ok": True, "host": "node"}
    assert transport.sent[0]["type"] == "tool.execute"


def test_device_router_fails_pending_call_when_runtime_disconnects():
    registry = DeviceRegistry()
    registry.register(id="node", name="Node", platform="windows", capabilities=["system.info"])
    router = DeviceRouter(registry)

    async def disconnect(_data):
        router.detach("node")

    router.attach("node", FakeTransport(disconnect))

    with pytest.raises(DeviceConnectionError):
        asyncio.run(router.execute_remote("node", "system.info", {}))


def test_device_router_requires_connected_runtime():
    registry = DeviceRegistry()
    registry.register(id="node", name="Node", platform="windows", capabilities=["system.info"])
    router = DeviceRouter(registry)

    with pytest.raises(DeviceConnectionError):
        asyncio.run(router.execute_remote("node", "system.info", {}))
