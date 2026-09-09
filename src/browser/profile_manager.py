
from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.core.paths import APP_BASE_DIR, PROFILES_DIR

ACCEPT_LANGUAGE = "ja,en-US;q=0.9,en;q=0.7"

ProfileStatus = Literal["ready_canonical", "ready_legacy", "missing"]

@dataclass(frozen=True)
class ProfileLocation:

    status: ProfileStatus
    path: Path | None
    reason: str = ""

def _ensure_webengine_process_path() -> None:
    import os
    import sys

    if not getattr(sys, "frozen", False):
        return
    current = (os.environ.get("QTWEBENGINEPROCESS_PATH") or "").strip()
    if current and Path(current).is_file():
        return
    base = Path(sys.executable).resolve().parent
    for cand in (
        base / "QtWebEngineProcess.exe",
        base / "_internal" / "QtWebEngineProcess.exe",
        base / "PySide6" / "QtWebEngineProcess.exe",
        base / "_internal" / "PySide6" / "QtWebEngineProcess.exe",
    ):
        if cand.is_file():
            os.environ["QTWEBENGINEPROCESS_PATH"] = str(cand)
            return

def _storage_name_for(account_id: str) -> str:
    raw = (account_id or "").strip() or "default"
    cleaned = "".join(ch for ch in raw if ch.isalnum())
    return cleaned or "default"

def resolve_profile_path(account_id: str) -> Path:
    aid = (account_id or "").strip() or "default"
    return PROFILES_DIR / aid

def _normalize_legacy_path(legacy_path: str) -> Path | None:
    raw = (legacy_path or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.anchor:
        path = APP_BASE_DIR / path
    try:
        return path.resolve()
    except Exception:
        return path

def resolve_storage_for_account(
    account_id: str,
    legacy_path: str | None = None,
) -> ProfileLocation:
    aid = (account_id or "").strip()
    if not aid:
        return ProfileLocation("missing", None, "empty_account_id")

    canonical = resolve_profile_path(aid)
    try:
        if canonical.is_dir():
            return ProfileLocation("ready_canonical", canonical.resolve(), "")
    except Exception:
        if canonical.exists() and canonical.is_dir():
            return ProfileLocation("ready_canonical", canonical, "")

    legacy = _normalize_legacy_path(legacy_path or "")
    if legacy is not None:
        try:
            exists = legacy.is_dir()
        except Exception:
            exists = False
        if exists:
            if legacy.name == aid:
                try:
                    return ProfileLocation("ready_legacy", legacy.resolve(), "")
                except Exception:
                    return ProfileLocation("ready_legacy", legacy, "")
            return ProfileLocation(
                "missing",
                None,
                f"legacy_name_mismatch name={legacy.name!r} expected={aid!r}",
            )
        return ProfileLocation(
            "missing",
            None,
            f"legacy_missing path={str(legacy)!r}",
        )

    return ProfileLocation("missing", None, "no_canonical_no_legacy")

class ProfileManager:

    def __init__(self) -> None:
        self._profiles: dict[str, object] = {}

    def get_cached(self, account_id: str):
        return self._profiles.get(account_id)

    def open_existing(
        self,
        account_id: str,
        legacy_path: str | None = None,
    ) :
        aid = (account_id or "").strip()
        if not aid:
            return None
        if aid in self._profiles:
            return self._profiles[aid]

        loc = resolve_storage_for_account(aid, legacy_path)
        if loc.status == "missing" or loc.path is None:
            self._ptrace(
                aid,
                "open_existing_missing",
                path="",
                reason=loc.reason,
            )
            return None

        return self._build_profile(aid, loc.path, mkdir=False)

    def create_new(self, account_id: str):
        aid = (account_id or "").strip()
        if not aid:
            raise ValueError("account_id required")
        if aid in self._profiles:
            return self._profiles[aid]

        storage_path = resolve_profile_path(aid)
        return self._build_profile(aid, storage_path, mkdir=True)

    def get_or_create(self, account_id: str, profile_path: str = ""):
        profile = self.open_existing(account_id, profile_path or None)
        if profile is not None:
            return profile
        raise RuntimeError(
            f"Profile missing for account_id={account_id!r}; "
            "refusing to create empty profile during open. "
            "Use create_new() only for explicit new accounts."
        )

    def _build_profile(
        self,
        account_id: str,
        storage_path: Path,
        *,
        mkdir: bool,
    ) -> QWebEngineProfile:
        if account_id in self._profiles:
            return self._profiles[account_id]

        storage_name = _storage_name_for(account_id)
        cache_path = storage_path / "Cache"
        storage = str(storage_path)

        def _ptrace(stage: str, **extra) -> None:
            self._ptrace(account_id, stage, path=storage, **extra)

        _ensure_webengine_process_path()
        import os as _os

        _ptrace(
            "build_enter",
            mkdir=mkdir,
            proc=_os.environ.get("QTWEBENGINEPROCESS_PATH", ""),
        )

        if mkdir:
            _ptrace("mkdir_enter")
            try:
                storage_path.mkdir(parents=True, exist_ok=True)
                cache_path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                raise RuntimeError(
                    f"プロフィール保存先を作成できません: {storage_path} ({exc})"
                ) from exc
            _ptrace("mkdir_done")
        else:
            if not storage_path.is_dir():
                raise RuntimeError(
                    f"Profile directory missing (open_existing): {storage_path}"
                )
            try:
                if not cache_path.is_dir():
                    cache_path.mkdir(parents=False, exist_ok=True)
            except Exception:
                pass

        from PySide6.QtWebEngineCore import QWebEngineProfile

        _ptrace("qwebengineprofile_ctor_enter", storage_name=storage_name)
        profile = QWebEngineProfile(storage_name, None)
        _ptrace("qwebengineprofile_ctor_done", storage_name=storage_name)

        _ptrace("set_storage_enter")
        profile.setPersistentStoragePath(storage)
        try:
            profile.setCachePath(str(cache_path))
        except Exception:
            pass
        _ptrace("set_storage_done")

        try:
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
            )
        except Exception:
            try:
                from PySide6.QtWebEngineCore import QWebEngineProfile as _P
                profile.setPersistentCookiesPolicy(
                    _P.PersistentCookiesPolicy.AllowPersistentCookies
                )
            except Exception:
                pass

        profile.setHttpAcceptLanguage(ACCEPT_LANGUAGE)
        self._profiles[account_id] = profile
        return profile

    @staticmethod
    def _ptrace(account_id: str, stage: str, path: str = "", **extra) -> None:
        try:
            import os
            from src.core.paths import LOGS_DIR

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            extra_s = " ".join(f"{k}={v!r}" for k, v in extra.items())
            with open(LOGS_DIR / "last_account_add.log", "a", encoding="utf-8") as f:
                f.write(
                    f"profile_mgr {stage} id={account_id!r} path={path!r}"
                    + (f" {extra_s}" if extra_s else "")
                    + "\n"
                )
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        except Exception:
            pass

    def prepare_shutdown(self, timeout_ms: int = 0) -> None:
        import time as _time

        def _ms() -> int:
            return int(_time.monotonic() * 1000)

        timeout_ms = max(0, min(int(timeout_ms or 0), 2000))
        n = len(self._profiles)
        t_all = _ms()
        try:
            from src.core.paths import LOGS_DIR

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            path_bits = []
            for aid, profile in list(self._profiles.items()):
                try:
                    sp = str(profile.persistentStoragePath() or "")
                except Exception:
                    sp = "?"
                path_bits.append(f"{aid}:{sp}")
            with open(LOGS_DIR / "shutdown.log", "a", encoding="utf-8") as f:
                f.write(
                    f"profile_cleanup_start count={n} timeout_ms={timeout_ms} "
                    f"mono_ms={_ms()} paths={path_bits!r}\n"
                )
                f.flush()
        except Exception:
            pass

        t0 = _ms()
        for aid, profile in list(self._profiles.items()):
            try:
                store = profile.cookieStore()
                if store is not None:
                    _ = store
            except Exception:
                pass
        cookie_ms = _ms() - t0
        try:
            from src.core.paths import LOGS_DIR
            with open(LOGS_DIR / "shutdown.log", "a", encoding="utf-8") as f:
                f.write(
                    f"profile_cookieStore_touch_done count={n} "
                    f"elapsed_ms={cookie_ms}\n"
                )
                f.flush()
        except Exception:
            pass

        wait_ms = 0
        wait_mode = "none"
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QEventLoop, QTimer

            app = QApplication.instance()
            t0 = _ms()
            if app is not None:
                for _ in range(3):
                    app.processEvents()
            if timeout_ms > 0:
                quiet = 0
                deadline = t0 + timeout_ms
                while _ms() < deadline:
                    t1 = _ms()
                    if app is not None:
                        app.processEvents()
                    spent = _ms() - t1
                    if spent <= 1:
                        quiet += 1
                        if quiet >= 3:
                            wait_mode = "early_idle"
                            break
                    else:
                        quiet = 0
                    loop = QEventLoop()
                    QTimer.singleShot(15, loop.quit)
                    loop.exec()
                else:
                    wait_mode = "timeout"
            else:
                wait_mode = "processEvents_only"
            wait_ms = _ms() - t0
        except Exception:
            wait_mode = "error"
        try:
            from src.core.paths import LOGS_DIR
            with open(LOGS_DIR / "shutdown.log", "a", encoding="utf-8") as f:
                f.write(
                    f"profile_cleanup_done count={n} wait_elapsed_ms={wait_ms} "
                    f"wait_mode={wait_mode} total_elapsed_ms={_ms() - t_all}\n"
                )
                f.flush()
        except Exception:
            pass

    def get(self, account_id: str):
        return self._profiles.get(account_id)

    def remove(self, account_id: str, cleanup_data: bool = False) -> None:
        self._profiles.pop(account_id, None)
        if cleanup_data:
            self.delete_profile_data(account_id)

    def delete_profile_data(self, account_id: str) -> None:
        aid = (account_id or "").strip()
        if not aid:
            return
        profile_dir = resolve_profile_path(aid)
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)

    def __iter__(self) -> Iterator[str]:
        return iter(self._profiles)

    def __len__(self) -> int:
        return len(self._profiles)

    def _cleanup_profile_data(self, account_id: str) -> None:
        self.delete_profile_data(account_id)
