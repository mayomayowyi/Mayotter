
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile

class InstanceLock:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / ".mayotter.lock"
        self._lock = QLockFile(str(self._path))
        self._lock.setStaleLockTime(30_000)
        self._held = False

    @property
    def lock_path(self) -> Path:
        return self._path

    def try_acquire(self) -> bool:
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
