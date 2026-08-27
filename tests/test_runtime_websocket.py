import pytest

pytest.importorskip("fastapi", reason="fastapi not installed; skipping server websocket tests")
pytest.importorskip("fastapi.testclient", reason="fastapi test client not installed")

from fastapi.testclient import TestClient


def test_runtime_websocket_requires_initial_register():
    import mcp.server as server

    with TestClient(server.app).websocket_connect("/ws/runtime") as websocket:
        websocket.send_json({"protocol_version": "0.1", "type": "device.heartbeat", "request_id": "hb-1"})
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert "register" in response["error"]


def test_runtime_websocket_registers_heartbeats_and_disconnects():
    import mcp.server as server

    server.device_registry.remove("ws-node")
    with TestClient(server.app).websocket_connect("/ws/runtime") as websocket:
        websocket.send_json(
            {
                "protocol_version": "0.1",
                "type": "device.register",
                "request_id": "register-1",
                "device": {
                    "id": "ws-node",
                    "name": "WS Node",
                    "platform": "windows",
                    "capabilities": ["system.info"],
                },
            }
        )
        response = websocket.receive_json()
        websocket.send_json(
            {
                "protocol_version": "0.1",
                "type": "device.heartbeat",
                "request_id": "hb-1",
                "device_id": "ws-node",
            }
        )
        assert response["type"] == "device.registered"
        assert server.device_registry.supports("ws-node", "system.info")

    assert server.device_registry.get("ws-node").connected is False
