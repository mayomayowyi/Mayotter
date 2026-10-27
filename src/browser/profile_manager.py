
from __future__ import annotations
from src.core.i18n import tr

import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal
from uuid import UUID

from src.core.paths import APP_BASE_DIR, PROFILES_DIR

from src.core.i18n import LANGUAGES, accept_language, get_language

if TYPE_CHECKING:
    from PySide6.QtWebEngineCore import QWebEngineProfile

ProfileStatus = Literal["ready_canonical", "ready_legacy", "missing"]

def _storage_key(path) -> str:
    """保存先の同時開設判定用の比較キー。大小文字・区切り文字・ジャンクションを整える。"""
    raw = str(path or "")
    try:
        raw = str(Path(raw).resolve())
    except Exception:
        pass
    try:
        return os.path.normcase(raw)
    except Exception:
        return raw

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
        # 削除済みアカウントの wrapper。Shiboken 上 QWebEngineProfile は C++ 側の
        # 所有物で、Python 参照を捨てても ProfileAdapter はプロセス終了まで残る。
        # 残った adapter が同一保存先の再構築 (createProfile) を None (失敗) にするので、
        # 参照失失で再取り出せるように保持しておく。
        self._revoked: dict[str, object] = {}
        self._language = get_language()

    @staticmethod
    def _cpp_valid(profile: object) -> bool:
        """shiboken で実体が破棄された wrapper は保持し続けても例外になるため、未構築として扱う。"""
        try:
            from shiboken6 import isValid
            return bool(isValid(profile))
        except Exception:
            return True

    def set_language(self, language: str) -> None:
        self._language = language if language in LANGUAGES else 'ja'
        for profile in self._profiles.values():
            if not self._cpp_valid(profile):
                continue
            profile.setHttpAcceptLanguage(accept_language(language))

    def open_existing(
        self,
        account_id: str,
        legacy_path: str | None = None,
    ) :
        aid = (account_id or "").strip()
        if not aid:
            return None
        cached = self._profiles.get(aid)
        if cached is not None and self._cpp_valid(cached):
            return cached
        self._profiles.pop(aid, None)

        loc = resolve_storage_for_account(aid, legacy_path)
        if loc.status == "missing" or loc.path is None:
            self._ptrace(
                aid,
                "open_existing_missing",
                path="",
                reason=loc.reason,
            )
            return None

        return self._build_profile(aid, loc.path, mkdir=False, op="open_existing")

    def create_new(self, account_id: str):
        aid = (account_id or "").strip()
        if not aid:
            raise ValueError(tr('account_id required'))
        cached = self._profiles.get(aid)
        if cached is not None and self._cpp_valid(cached):
            return cached
        self._profiles.pop(aid, None)

        storage_path = resolve_profile_path(aid)
        return self._build_profile(aid, storage_path, mkdir=True, op="create_new")

    def _build_profile(
        self,
        account_id: str,
        storage_path: Path,
        *,
        mkdir: bool,
        op: str = "profile_open",
    ) -> QWebEngineProfile:
        cached = self._profiles.get(account_id)
        if cached is not None and self._cpp_valid(cached):
            return cached
        self._profiles.pop(account_id, None)

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
                    tr('プロフィール保存先を作成できません: {v0} ({v1})', v0=storage_path, v1=exc)
                ) from exc
            _ptrace("mkdir_done")
        else:
            if not storage_path.is_dir():
                raise RuntimeError(
                    tr('Profile directory missing (open_existing): {v0}', v0=storage_path)
                )
            try:
                if not cache_path.is_dir():
                    cache_path.mkdir(parents=False, exist_ok=True)
            except Exception:
                pass

        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWebEngineCore import QWebEngineProfile

        # ページ破棄で wrapper が無効になっても、生存実体をアプリから取得し直せるようにする。
        owner = QCoreApplication.instance()

        _ptrace("qwebengineprofile_ctor_enter", storage_name=storage_name)
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfileBuilder
        except ImportError:
            profile = QWebEngineProfile(storage_name, owner)
        else:
            # 名前付きコンストラクタは、保存先の指定前にQtの既定領域を開く。
            builder = QWebEngineProfileBuilder()
            builder.setPersistentStoragePath(storage)
            builder.setCachePath(str(cache_path))
            profile = builder.createProfile(storage_name, owner)
            if profile is None:
                # Qt 側で「同じ保存先を使う adapter が既に生きている」場合の返値。
                # 生存している profile 実体が見つかれば、再生成せずにそれを再登録する
                #（Cookie・ログイン・ストレージはそのまま引き継がれる）。
                recovered = self._recover_profile_for_storage(account_id, storage)
                self.log_open_failure(
                    account_id,
                    op,
                    "create_profile_same_path_exists",
                    recovered=recovered is not None,
                    storage=storage,
                )
                if recovered is not None:
                    _ptrace(
                        "profile_recovered",
                        location=storage,
                        recovered_id=id(recovered),
                    )
                    self._profiles[account_id] = recovered
                    return recovered
                raise RuntimeError(tr('保存カラムのプロファイルを開けませんでした。'))
        _ptrace("qwebengineprofile_ctor_done", storage_name=storage_name)

        # 以降の設定処理で例外が出ても、実体はプロセスが生きている限り残るため、
        # 先に登録しておく（未登録のまま漏れると同一保存先の再構築が永久に失敗する）。
        self._profiles[account_id] = profile

        _ptrace("set_storage_enter")
        try:
            profile.setPersistentStoragePath(storage)
        except Exception as exc:
            _ptrace("set_storage_failed", err=repr(exc))
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

        try:
            # ディスクキャッシュを広げ、画像・JS・動画の再取得を減らす（既定は自動で小さめ）。
            # 7 アカウント分あるので 1 プロファイル 512MB を上限にする
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            profile.setHttpCacheMaximumSize(512 * 1024 * 1024)
        except Exception:
            pass

        try:
            profile.setHttpAcceptLanguage(accept_language(self._language))
        except Exception:
            pass
        self._log_import_state(account_id, storage_path)
        return profile

    def _recover_profile_for_storage(self, account_id: str, storage: str):
        """同じ保存先の生存実体を取得し直す。見つからなければ None を返す。"""
        from shiboken6 import isValid as _valid

        want = _storage_key(storage)
        if not want:
            return None

        def _path_of(profile) -> str:
            try:
                return str(profile.persistentStoragePath() or "")
            except Exception:
                return ""

        def _matches(profile) -> bool:
            path = _path_of(profile)
            return bool(path) and _storage_key(path) == want

        # 削除済みアカウントとして保持している参照をまず確認する
        revoked = self._revoked.get(account_id)
        if revoked is not None and _valid(revoked) and _matches(revoked):
            self._revoked.pop(account_id, None)
            return revoked

        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWebEngineCore import QWebEngineProfile

        app = QCoreApplication.instance()
        if app is not None:
            for profile in app.findChildren(QWebEngineProfile):
                if _valid(profile) and _matches(profile):
                    return profile

        # 実ウィジェット（開いているカラム・タブ）が参照している profile から探す
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            return None
        try:
            widgets = list(QApplication.allWidgets())
        except Exception:
            return None
        for widget in widgets:
            if not isinstance(widget, QWebEngineView):
                continue
            try:
                page = widget.page()
                profile = page.profile() if page is not None else None
            except Exception:
                continue
            if profile is None or not _valid(profile):
                continue
            if _matches(profile):
                return profile
        return None

    @staticmethod
    def _log_import_state(account_id: str, storage_path: Path) -> None:
        """ZIP版から移行したSetup版だけ、開いたプロファイルの保存先とCookie DBのサイズを診断ログへ（内容は記録しない）。"""
        try:
            from src.core.paths import DATA_DIR, IS_INSTALLED
            if not (IS_INSTALLED and (DATA_DIR / '.portable-migration.json').exists()):
                return
            from src.core.portable_migration import diagnose
            sizes = {name: (storage_path / name).stat().st_size
                     for name in ('Cookies', 'Cookies-journal') if (storage_path / name).exists()}
            diagnose(DATA_DIR, 'profile_open', account=account_id[:8], path=storage_path, **sizes)
        except Exception:
            pass

    @staticmethod
    def _ptrace(account_id: str, stage: str, path: str = "", **extra) -> None:
        import os
        enabled = (
            (os.environ.get("MAYOTTER_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")
            or (os.environ.get("MAYOTTER_ACCOUNT_TRACE") or "").strip().lower() in ("1", "true", "yes", "on")
        )
        if not enabled:
            return
        try:
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

    @staticmethod
    def log_open_failure(
        account_id: str,
        op: str,
        stage: str,
        exc: BaseException | None = None,
        *,
        storage: str = "",
        alive: str = "unknown",
        recovered=None,
    ) -> None:
        """プロファイルの開始失敗と復旧結果をログへ残す。

        パスワード / Cookie / 認証トークンは記録しない。アカウントは ID 先頭 8 文字のみ。
        """
        try:
            import traceback as _tb
            from datetime import datetime

            from src.core.paths import LOGS_DIR

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            aid = (account_id or "").strip() or "default"
            lines = [
                f"[{datetime.now().isoformat(timespec='seconds')}] open_fail"
                f" op={op} account={aid[:8]} stage={stage}"
                f" storage={storage} profile_alive={alive} recovery={recovered}"
            ]
            if exc is not None:
                lines.append(
                    f"exception={type(exc).__name__}: {exc}"
                )
                try:
                    lines.append("".join(_tb.format_exception(exc)).rstrip())
                except Exception:
                    pass
            with open(LOGS_DIR / "profile_reopen.log", "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def prepare_shutdown(self, timeout_ms: int = 0) -> None:
        import time as _time

        def _ms() -> int:
            return int(_time.monotonic() * 1000)

        timeout_ms = max(0, min(int(timeout_ms or 0), 2000))
        alive_items = [
            (aid, profile)
            for aid, profile in list(self._profiles.items()) + list(self._revoked.items())
            if self._cpp_valid(profile)
        ]
        n = len(alive_items)
        t_all = _ms()
        try:
            from src.core.paths import LOGS_DIR

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            path_bits = []
            for aid, profile in alive_items:
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
        for aid, profile in alive_items:
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

    def cache_profiles(self) -> tuple:
        return tuple(profile for profile in self._profiles.values() if self._cpp_valid(profile))

    def get(self, account_id: str):
        profile = self._profiles.get(account_id)
        if profile is not None and not self._cpp_valid(profile):
            # 実体が破棄された古い wrapper は、未構築として返し次回 open_existing で
            # 同じディスク上の保存領域を再オープンする（Cookie・ログインは失われない）。
            self._profiles.pop(account_id, None)
            return None
        return profile

    def remove(self, account_id: str, cleanup_data: bool = False) -> None:
        aid = (account_id or "").strip()
        if not aid:
            return
        profile = self._profiles.pop(aid, None)
        if profile is not None and self._cpp_valid(profile) and aid not in self._revoked:
            # wrapper を捨てても C++ 側の実体 (ProfileAdapter) はプロセス終了まで破棄されない。
            # 実体が残ると同一保存先の再構築が None (失敗) になるため、参照を保持して
            # 後から復元できるようにする。実体が本当に破棄されたら get/_cpp_valid で外れる。
            self._revoked[aid] = profile
        if cleanup_data:
            self.delete_profile_data(aid)

    def delete_profile_data(self, account_id: str) -> bool:
        aid = (account_id or "").strip()
        if not aid:
            return False
        try:
            profiles_root = PROFILES_DIR.resolve()
            profile_dir = resolve_profile_path(aid).resolve()
        except OSError:
            return False
        if profile_dir.parent != profiles_root:
            return False
        if not profile_dir.exists():
            return True
        try:
            shutil.rmtree(profile_dir)
        except OSError:
            return False
        return not profile_dir.exists()

    def cleanup_orphaned_profile_data(self, registered_account_ids: set[str]) -> list[str]:
        registered = {
            str(account_id or "").strip().lower()
            for account_id in registered_account_ids
            if str(account_id or "").strip()
        }
        try:
            entries = list(PROFILES_DIR.iterdir())
        except OSError:
            return []

        removed: list[str] = []
        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue
            try:
                canonical = str(UUID(entry.name))
            except (ValueError, AttributeError):
                continue
            if entry.name.lower() != canonical or canonical in registered:
                continue
            if self.delete_profile_data(entry.name):
                removed.append(entry.name)
        return removed

    def __iter__(self) -> Iterator[str]:
        return iter(self._profiles)

    def __len__(self) -> int:
        return len(self._profiles)
