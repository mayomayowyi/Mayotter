from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


def create_installer_mutex():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel.CreateMutexW(None, False, "Local\\Mayotter.Installed")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    # インストーラーはプロセス終了まで待つ。QLockFile の release 時には閉じない。
    return handle

class InstanceLock:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / ".mayotter.lock"
        self._lock = QLockFile(str(self._path))
        self._lock.setStaleLockTime(30_000)
        self._held = False

    def try_acquire(self) -> bool:
        from src.core.updater import update_in_progress
        if update_in_progress():
            return False
        if self._lock.tryLock(100):
            self._held = True
            return True
        return False

    def release(self) -> None:
        if self._held:
            try:
                self._lock.unlock()
            except Exception:
                pass
            self._held = False
