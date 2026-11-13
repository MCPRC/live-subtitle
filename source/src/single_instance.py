"""Windows 单实例锁：避免重复启动导致多个字幕窗叠在一起。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = "LiveSubtitle_Instance"):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        self._last_error = ctypes.get_last_error()

    def already_running(self) -> bool:
        return self._last_error == ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
