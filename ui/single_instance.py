from __future__ import annotations

import ctypes
import os
import socket
import threading
from ctypes import wintypes
from typing import Callable


ERROR_ALREADY_EXISTS = 183
DEFAULT_LOCK_PORT = 49731


class SingleInstance:
    def __init__(self, name: str, port: int = DEFAULT_LOCK_PORT):
        self._handle = None
        self._socket = None
        self._listener_thread = None
        self.already_running = False
        self._port = port
        self._bind_socket(port)
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        self._handle = handle
        self.already_running = self.already_running or ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def _bind_socket(self, port: int) -> None:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            connection.bind(("127.0.0.1", port))
            connection.listen(1)
        except OSError:
            self.already_running = True
            connection.close()
            return
        self._socket = connection

    def notify_existing(self, message: str = "show") -> bool:
        if not self.already_running:
            return False
        try:
            with socket.create_connection(("127.0.0.1", self._port), timeout=0.25) as connection:
                connection.sendall(message.encode("utf-8"))
            return True
        except OSError:
            return False

    def listen(self, callback: Callable[[str], None]) -> None:
        if self._socket is None or self._listener_thread is not None:
            return

        def run() -> None:
            while self._socket is not None:
                try:
                    connection, _addr = self._socket.accept()
                except OSError:
                    return
                with connection:
                    try:
                        message = connection.recv(128).decode("utf-8", errors="replace").strip()
                    except OSError:
                        message = ""
                if message:
                    callback(message)

        self._listener_thread = threading.Thread(target=run, name="apolo-single-instance", daemon=True)
        self._listener_thread.start()

    def release(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._handle is None:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle(self._handle)
        self._handle = None
