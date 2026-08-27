import socket
import time
import uuid

from ui.single_instance import SingleInstance


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


def test_second_instance_notifies_existing_instance():
    port = _free_port()
    first = SingleInstance(f"Global\\Apolov2Test{uuid.uuid4().hex}", port=port)
    messages = []
    first.listen(messages.append)
    second = SingleInstance(f"Global\\Apolov2Test{uuid.uuid4().hex}", port=port)

    try:
        assert first.already_running is False
        assert second.already_running is True
        assert second.notify_existing("show") is True
        deadline = time.monotonic() + 1
        while not messages and time.monotonic() < deadline:
            time.sleep(0.01)
        assert messages == ["show"]
    finally:
        second.release()
        first.release()
