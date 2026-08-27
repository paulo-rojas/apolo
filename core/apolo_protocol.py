from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, ValidationError, field_validator


PROTOCOL_VERSION = "0.1"


class ProtocolError(ValueError):
    pass


class DeviceInfo(BaseModel):
    id: str
    name: str
    platform: str
    capabilities: list[str] = Field(default_factory=list)


class ProtocolMessage(BaseModel):
    protocol_version: Literal["0.1"] = PROTOCOL_VERSION
    type: str
    request_id: str

    @field_validator("request_id")
    @classmethod
    def request_id_required(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("request_id is required")
        return value


class HelloMessage(ProtocolMessage):
    type: Literal["hello"] = "hello"


class DeviceRegisterMessage(ProtocolMessage):
    type: Literal["device.register"] = "device.register"
    device: DeviceInfo


class DeviceRegisteredMessage(ProtocolMessage):
    type: Literal["device.registered"] = "device.registered"
    device_id: str
    ok: bool = True


class DeviceHeartbeatMessage(ProtocolMessage):
    type: Literal["device.heartbeat"] = "device.heartbeat"
    device_id: str | None = None


class ToolExecuteMessage(ProtocolMessage):
    type: Literal["tool.execute"] = "tool.execute"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResultMessage(ProtocolMessage):
    type: Literal["tool.result"] = "tool.result"
    ok: bool
    result: Any = None
    error: str | None = None


class ErrorMessage(ProtocolMessage):
    type: Literal["error"] = "error"
    error: str
    code: str | None = None


RuntimeMessage = Union[
    HelloMessage,
    DeviceRegisterMessage,
    DeviceRegisteredMessage,
    DeviceHeartbeatMessage,
    ToolExecuteMessage,
    ToolResultMessage,
    ErrorMessage,
]


_MESSAGE_TYPES = {
    "hello": HelloMessage,
    "device.register": DeviceRegisterMessage,
    "device.registered": DeviceRegisteredMessage,
    "device.heartbeat": DeviceHeartbeatMessage,
    "tool.execute": ToolExecuteMessage,
    "tool.result": ToolResultMessage,
    "error": ErrorMessage,
}


def parse_protocol_message(data: Any) -> RuntimeMessage:
    if not isinstance(data, dict):
        raise ProtocolError("message must be an object")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version: {data.get('protocol_version')}")
    message_type = data.get("type")
    model = _MESSAGE_TYPES.get(message_type)
    if model is None:
        raise ProtocolError(f"unsupported message type: {message_type}")
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ProtocolError(str(error)) from error


def model_dump(message: BaseModel) -> dict[str, Any]:
    return message.model_dump(exclude_none=True)
