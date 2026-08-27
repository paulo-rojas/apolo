from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

from core.apolo_protocol import ToolExecuteMessage, ToolResultMessage, model_dump
from core.devices import DeviceRegistry


class DeviceCapabilityError(RuntimeError):
    pass


class DeviceConnectionError(RuntimeError):
    pass


class RuntimeTransport(Protocol):
    async def send_json(self, data: dict[str, Any]) -> None:
        ...


class RuntimeConnection:
    def __init__(self, device_id: str, transport: RuntimeTransport) -> None:
        self.device_id = device_id
        self._transport = transport
        self._pending: dict[str, asyncio.Future] = {}

    async def execute(self, tool: str, args: dict[str, Any], *, timeout_seconds: float) -> Any:
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._transport.send_json(
                model_dump(ToolExecuteMessage(request_id=request_id, tool=tool, args=args))
            )
            result: ToolResultMessage = await asyncio.wait_for(future, timeout=timeout_seconds)
        finally:
            self._pending.pop(request_id, None)
        if not result.ok:
            raise DeviceConnectionError(result.error or "runtime tool execution failed")
        return result.result

    def complete(self, message: ToolResultMessage) -> bool:
        future = self._pending.get(message.request_id)
        if future is None or future.done():
            return False
        future.set_result(message)
        return True

    def disconnect(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(DeviceConnectionError("runtime disconnected during execution"))
        self._pending.clear()


class DeviceRouter:
    def __init__(self, registry: DeviceRegistry, *, timeout_seconds: float = 10.0) -> None:
        self.registry = registry
        self.timeout_seconds = timeout_seconds
        self._connections: dict[str, RuntimeConnection] = {}

    def attach(self, device_id: str, transport: RuntimeTransport) -> RuntimeConnection:
        connection = RuntimeConnection(device_id, transport)
        self._connections[device_id] = connection
        return connection

    def detach(self, device_id: str) -> None:
        connection = self._connections.pop(device_id, None)
        if connection is not None:
            connection.disconnect()
        try:
            self.registry.mark_disconnected(device_id)
        except KeyError:
            pass

    def complete_result(self, device_id: str, message: ToolResultMessage) -> bool:
        connection = self._connections.get(device_id)
        return bool(connection and connection.complete(message))

    async def execute_remote(self, device_id: str, tool: str, args: dict[str, Any]) -> Any:
        if not self.registry.supports(device_id, tool):
            raise DeviceCapabilityError(f"device {device_id} does not support {tool}")
        connection = self._connections.get(device_id)
        if connection is None:
            raise DeviceConnectionError(f"device {device_id} is not connected")
        return await connection.execute(tool, args, timeout_seconds=self.timeout_seconds)
