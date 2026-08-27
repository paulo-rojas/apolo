import pytest

from core.apolo_protocol import (
    DeviceRegisterMessage,
    ProtocolError,
    ToolExecuteMessage,
    parse_protocol_message,
)


def test_protocol_accepts_device_register_message():
    message = parse_protocol_message(
        {
            "protocol_version": "0.1",
            "type": "device.register",
            "request_id": "uuid",
            "device": {
                "id": "laptop-paulo",
                "name": "Laptop",
                "platform": "windows",
                "capabilities": ["system.info"],
            },
        }
    )

    assert isinstance(message, DeviceRegisterMessage)
    assert message.device.capabilities == ["system.info"]


def test_protocol_rejects_unknown_version():
    with pytest.raises(ProtocolError):
        parse_protocol_message({"protocol_version": "9.9", "type": "hello", "request_id": "uuid"})


def test_protocol_rejects_invalid_messages():
    with pytest.raises(ProtocolError):
        parse_protocol_message({"protocol_version": "0.1", "type": "tool.execute", "request_id": "uuid"})


def test_protocol_rejects_unknown_message_type():
    with pytest.raises(ProtocolError):
        parse_protocol_message({"protocol_version": "0.1", "type": "browser.fly", "request_id": "uuid"})


def test_protocol_parses_tool_execute():
    message = parse_protocol_message(
        {
            "protocol_version": "0.1",
            "type": "tool.execute",
            "request_id": "uuid",
            "tool": "system.info",
            "args": {},
        }
    )

    assert isinstance(message, ToolExecuteMessage)
