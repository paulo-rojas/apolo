from __future__ import annotations

import ctypes
import os
import socket
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183
DEFAULT_LOCK_PORT = 49731


class SingleInstance:
    def __init__(self, name: str, port: int = DEFAULT_LOCK_PORT):
        self._handle = None
        self._socket = None
        self.already_running = False
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

    def release(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._handle is None:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle(self._handle)
        self._handle = None
