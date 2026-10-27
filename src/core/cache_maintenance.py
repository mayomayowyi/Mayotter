from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from shiboken6 import isValid


def _safe_path(path: Path) -> None:
    for part in (path.absolute(), *path.absolute().parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError(f"Link/reparse point refused: {part}")


def _cache_roots(errors: list[str]) -> list[Path]:
    from src.core.paths import CACHE_DIR, PROFILES_DIR

    roots = [CACHE_DIR]
    try:
        _safe_path(PROFILES_DIR)
        if PROFILES_DIR.is_dir():
            for profile in PROFILES_DIR.iterdir():
                try:
                    _safe_path(profile)
                    if profile.is_dir():
                        roots.append(profile / "Cache")
                except OSError as exc:
                    errors.append(f"{profile}: {exc}")
    except OSError as exc:
        errors.append(f"{PROFILES_DIR}: {exc}")
    return roots


def _cache_files(root: Path, errors: list[str]):
    stack = [root]
    while stack:
        path = stack.pop()
        try:
            _safe_path(path)
            if not path.exists():
                continue
            with os.scandir(path) as entries:
                for entry in list(entries):
                    child = Path(entry.path)
                    try:
                        _safe_path(child)
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(child)
                        elif entry.is_file(follow_symlinks=False):
                            yield child, entry.stat(follow_symlinks=False).st_size
                    except OSError as exc:
                        errors.append(f"{child}: {exc}")
        except OSError as exc:
            errors.append(f"{path}: {exc}")


@dataclass
class CacheSnapshot:
    bytes: int = 0
    sizes: dict[Path, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def cache_snapshot() -> CacheSnapshot:
    result = CacheSnapshot()
    for root in _cache_roots(result.errors):
        size = sum(size for _, size in _cache_files(root, result.errors))
        result.sizes[root] = size
        result.bytes += size
    return result


def cache_size_bytes() -> int:
    return cache_snapshot().bytes


@dataclass
class DiskCacheResult:
    deleted_bytes: int = 0
    errors: list[str] = field(default_factory=list)


def clear_disk_cache(active_paths=()) -> DiskCacheResult:
    """使用中のCacheはQt APIに任せ、未使用の既知キャッシュだけを処理する。"""
    result = DiskCacheResult()
    active = {os.path.normcase(os.path.abspath(p)) for p in active_paths}
    for root in _cache_roots(result.errors):
        if os.path.normcase(os.path.abspath(root)) in active:
            continue
        for path, _ in _cache_files(root, result.errors):
            try:
                _safe_path(path)
                size = path.stat(follow_symlinks=False).st_size
                path.unlink()
                result.deleted_bytes += size
            except FileNotFoundError:
                continue
            except OSError as exc:
                result.errors.append(f"{path}: {exc}")
    return result


@dataclass
class CacheCleanupResult:
    before: CacheSnapshot
    after: CacheSnapshot
    deleted_bytes: int
    errors: list[str]


class CacheCleanup(QObject):
    measured = Signal(object)
    finished = Signal(object)
    idle = Signal()
    _io_done = Signal(str, int, object)

    def __init__(self, profile_manager, parent=None, *, timeout_ms=120000):
        super().__init__(parent)
        self._manager = profile_manager
        self.running = False
        self._measuring = False
        self._generation = 0
        self.last_snapshot = None
        self._pending = {}
        self._connections = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._timed_out)
        self._io_done.connect(self._io_ready)

    def _run_io(self, stage, operation):
        generation = self._generation

        def run():
            try:
                value = operation()
            except Exception as exc:
                value = CacheSnapshot(errors=[f"Cache {stage}: {type(exc).__name__}: {exc}"])
            if isValid(self):
                self._io_done.emit(stage, generation, value)

        QThreadPool.globalInstance().start(QRunnable.create(run))

    def measure(self):
        if not self.busy and not self._measuring:
            self._measuring = True
            self._run_io("measure", cache_snapshot)

    @property
    def busy(self) -> bool:
        return self.running or bool(self._pending)

    def start(self) -> bool:
        if self.busy:
            return False
        self.running = True
        self._generation += 1
        self._errors = []
        self._waiting_after_timeout = False
        self._active_paths = []
        self._run_io("before", cache_snapshot)
        return True

    def _io_ready(self, stage, generation, value):
        if stage == "measure":
            self._measuring = False
        if generation != self._generation:
            return
        if stage == "measure":
            self.last_snapshot = value
            self.measured.emit(value)
        elif stage == "before":
            self._before = value
            self._begin_http_clear()
        else:
            if isinstance(value, CacheSnapshot):
                value = CacheCleanupResult(self._before, value, 0, self._errors + value.errors)
            self.running = False
            self.last_snapshot = value.after
            self._profiles = ()
            for error in value.errors:
                logging.getLogger(__name__).warning("Cache cleanup: %s", error)
            self.finished.emit(value)
            if not self.busy:
                if self._waiting_after_timeout:
                    self.measure()
                self.idle.emit()

    def _begin_http_clear(self):
        self._pending = {}
        self._starting_http = True
        self._profiles = self._manager.cache_profiles() if self._manager is not None else ()
        allowed = {os.path.normcase(os.path.abspath(p)) for p in self._before.sizes}
        for profile in self._profiles:
            try:
                path = Path(profile.cachePath())
                self._active_paths.append(path)
                _safe_path(path)
                if os.path.normcase(os.path.abspath(path)) not in allowed:
                    raise OSError("Cache path is outside allowed cache directories")
                signal = getattr(profile, "clearHttpCacheCompleted", None)
                if signal is None:
                    raise RuntimeError("This Qt version has no clearHttpCacheCompleted signal")
                key = id(profile)
                self._pending[key] = (profile, path)
                done = lambda k=key: self._profile_done(k)
                destroyed = lambda _=None, k=key: self._profile_done(k, "Profile destroyed during cache cleanup")
                signal.connect(done)
                profile.destroyed.connect(destroyed)
                self._connections.extend(((signal, done), (profile.destroyed, destroyed)))
            except (OSError, RuntimeError) as exc:
                self._errors.append(str(exc))
        for key, (profile, path) in list(self._pending.items()):
            try:
                profile.clearHttpCache()
            except RuntimeError as exc:
                self._profile_done(key, f"{path}: {exc}")
        self._starting_http = False
        if self._pending:
            self._timer.start()
        else:
            self._begin_disk_clear()

    def _profile_done(self, key, error=None):
        if not isValid(self):
            return
        if key not in self._pending:
            return
        _, path = self._pending.pop(key)
        if error:
            self._errors.append(f"{path}: {error}")
        if not self._pending and not self._starting_http:
            if self._waiting_after_timeout:
                self._disconnect_http()
                if not self.running:
                    self.measure()
                    self.idle.emit()
            else:
                self._begin_disk_clear()

    def _timed_out(self):
        for _, path in self._pending.values():
            self._errors.append(f"{path}: clearHttpCacheCompleted timeout")
        self._waiting_after_timeout = True
        self._begin_disk_clear()

    def _disconnect_http(self):
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except RuntimeError:
                pass
        self._connections.clear()

    def _begin_disk_clear(self):
        self._timer.stop()
        if not self._pending:
            self._disconnect_http()
        if self._manager is not None:
            for profile in self._manager.cache_profiles():
                try:
                    path = Path(profile.cachePath())
                    if path not in self._active_paths:
                        self._active_paths.append(path)
                        self._errors.append(f"{path}: Profile opened during cleanup; cache retained")
                except RuntimeError as exc:
                    self._errors.append(str(exc))

        def clear_and_measure():
            disk = clear_disk_cache(self._active_paths)
            after = cache_snapshot()
            return CacheCleanupResult(self._before, after, disk.deleted_bytes,
                                      self._before.errors + self._errors + disk.errors + after.errors)

        self._run_io("after", clear_and_measure)


def format_bytes(num: int) -> str:
    try:
        n = max(0, int(num))
    except Exception:
        n = 0
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"
