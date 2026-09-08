

from __future__ import annotations

import os
from pathlib import Path
import re
import time
from collections.abc import Callable
from urllib.parse import quote_plus

from PySide6.QtCore import Qt, QUrl, Signal, QEvent, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMenu, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineContextMenuRequest,
    QWebEnginePage,
    QWebEngineProfile,
)
from src.browser.url_policy import (
    apply_webengine_security_settings,
    decide_navigation,
    should_open_in_new_tab,
    open_in_default_browser,
    is_google_click_redirector,
    extract_google_redirect_target,
    classify_url,
)

from src.browser.content_filter import install_filter

import time as _nav_time

_nav_recent: dict[str, float] = {}
_NAV_DEDUP_SEC = 0.75

def _nav_key(url) -> str:
    try:
        if hasattr(url, "toString"):
            text = str(url.toString() or "")
        else:
            text = str(url or "")
    except Exception:
        text = str(url or "")
    text = text.strip()
    if "#" in text:
        text = text.split("#", 1)[0]
    return text

def _nav_begin(url) -> bool:
    key = _nav_key(url)
    if not key or key.startswith("about:"):
        return True
    now = _nav_time.monotonic()
    stale = [k for k, ts in _nav_recent.items() if now - ts > _NAV_DEDUP_SEC]
    for k in stale:
        _nav_recent.pop(k, None)
    prev = _nav_recent.get(key)
    if prev is not None and (now - prev) < _NAV_DEDUP_SEC:
        return False
    _nav_recent[key] = now
    return True

def _nav_end(url) -> None:
    return

_GOOGLE_SEARCH_URL = "https://www.google.com/search?q="
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+(:\d+)?(/.*)?$"
)
_LOCALHOST_RE = re.compile(r"^localhost(:\d+)?(/.*)?$", re.IGNORECASE)

_PNG_CONVERTIBLE_MIME = {
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/png",
}
_NON_IMAGE_SUFFIXES = (".gif", ".svg")

def should_convert_to_png(mime_type: str, file_name: str) -> bool:
    name = (file_name or "").lower()
    if name.endswith(_NON_IMAGE_SUFFIXES):
        return False
    return (mime_type or "").lower() in _PNG_CONVERTIBLE_MIME

def convert_file_to_png(path: str) -> None:
    image = QImage(path)
    if image.isNull():
        return
    image.save(path, "PNG")

import weakref
_DOWNLOAD_VIEWS: dict[int, list[weakref.ref]] = {}

_OFFSCREEN_CAPTURE_HOLDER: QWidget | None = None
_CAPTURE_HOST_WINDOW: QWidget | None = None

_disable_x_keyboard_shortcuts = False

_X_SHORTCUT_INSTALL_JS = r"""
(function(){
  if (window.__mayotterXScOff === true) return;
  function isEditable(t){
    if (!t || t === document || t === window) return false;
    try {
      if (t.isContentEditable) return true;
      var tag = (t.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      if (t.closest) {
        if (t.closest(
          '[contenteditable="true"],[contenteditable=""],[role="textbox"],' +
          '[data-testid="tweetTextarea_0"],[data-testid="dmComposerTextInput"],' +
          '[data-testid="searchBox"],[data-testid="SearchBox_Search_Input"]'
        )) return true;
      }
    } catch (e) {}
    return false;
  }
  function onKey(e){
    if (isEditable(e.target)) return;
    // Keep browser/OS chords (copy, paste, select-all, refresh, etc.)
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    e.stopImmediatePropagation();
  }
  window.__mayotterXScHandler = onKey;
  window.__mayotterXScOff = true;
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("keypress", onKey, true);
})();
"""

_X_SHORTCUT_REMOVE_JS = r"""
(function(){
  var h = window.__mayotterXScHandler;
  if (h) {
    try { window.removeEventListener("keydown", h, true); } catch (e) {}
    try { window.removeEventListener("keypress", h, true); } catch (e) {}
  }
  window.__mayotterXScHandler = null;
  window.__mayotterXScOff = false;
})();
"""

def set_disable_x_keyboard_shortcuts(enabled: bool) -> None:
    global _disable_x_keyboard_shortcuts
    _disable_x_keyboard_shortcuts = bool(enabled)

def get_disable_x_keyboard_shortcuts() -> bool:
    return bool(_disable_x_keyboard_shortcuts)

def is_x_twitter_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        return False
    return (
        host == "x.com"
        or host.endswith(".x.com")
        or host == "twitter.com"
        or host.endswith(".twitter.com")
    )

def x_shortcut_script(enabled: bool) -> str:
    return _X_SHORTCUT_INSTALL_JS if enabled else _X_SHORTCUT_REMOVE_JS

def attach_capture_holder_parent(parent: QWidget | None) -> None:
    global _OFFSCREEN_CAPTURE_HOLDER, _CAPTURE_HOST_WINDOW
    if parent is None:
        return
    _CAPTURE_HOST_WINDOW = parent
    try:
        if _OFFSCREEN_CAPTURE_HOLDER is not None:
            w = _OFFSCREEN_CAPTURE_HOLDER
            if w.parent() is not parent:
                w.setParent(parent)
            w.setWindowFlags(Qt.WindowType.Widget)
            w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            w.setFixedSize(1, 1)
            w.move(0, 0)
            w.hide()
            print(
                f"[TransientWindow] holder attached parent={type(parent).__name__} "
                f"isWindow={w.isWindow()} visible={w.isVisible()}",
                flush=True,
            )
            return
        w = QWidget(parent)
        w.setObjectName("mayotter_offscreen_capture_holder")
        w.setWindowFlags(Qt.WindowType.Widget)
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        w.setFixedSize(1, 1)
        w.move(0, 0)
        w.hide()
        _OFFSCREEN_CAPTURE_HOLDER = w
        print(
            f"[TransientWindow] holder CREATE parent={type(parent).__name__} "
            f"isWindow={w.isWindow()} (no top-level)",
            flush=True,
        )
    except Exception as exc:
        print(f"[TransientWindow] holder attach failed: {exc!r}", flush=True)

def _offscreen_capture_holder() -> QWidget | None:
    w = _OFFSCREEN_CAPTURE_HOLDER
    if w is None:
        host = _CAPTURE_HOST_WINDOW
        if host is not None:
            attach_capture_holder_parent(host)
            return _OFFSCREEN_CAPTURE_HOLDER
        print("[TransientWindow] holder missing (MainWindow not attached yet)", flush=True)
        return None
    return w

def _capture_parent_for(view_self: QWidget) -> QWidget:
    h = _offscreen_capture_holder()
    if h is not None:
        return h
    try:
        win = view_self.window()
        if win is not None:
            attach_capture_holder_parent(win)
            h = _offscreen_capture_holder()
            if h is not None:
                return h
            return win
    except Exception:
        pass
    return view_self

def attach_download_handler(profile: QWebEngineProfile) -> None:
    if profile.property("mayotter_download_connected"):
        return
    profile.setProperty("mayotter_download_connected", True)
    profile.downloadRequested.connect(handle_download_request)

def _resolve_download_directory() -> str:
    try:
        from src.core.settings import SettingsManager
        custom = str(SettingsManager().get_download_dir() or "").strip()
        if custom:
            p = Path(custom)
            p.mkdir(parents=True, exist_ok=True)
            return str(p)
    except Exception:
        pass
    try:
        from src.core.paths import default_downloads_dir
        p = default_downloads_dir()
        p.mkdir(parents=True, exist_ok=True)
        return str(p)
    except Exception:
        pass
    home = Path.home() / "Downloads"
    try:
        home.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return str(home)

def handle_download_request(download) -> None:
    suggested_name = download.downloadFileName() or "download"
    suggested_name = os.path.basename(str(suggested_name).replace('\\', "/")) or "download"
    to_png = should_convert_to_png(download.mimeType(), suggested_name)
    if to_png and not suggested_name.lower().endswith(".png"):
        base, _ = os.path.splitext(suggested_name)
        suggested_name = base + ".png"
    dest_dir = _resolve_download_directory()
    path = os.path.join(dest_dir, suggested_name)
    if os.path.exists(path):
        base, ext = os.path.splitext(suggested_name)
        n = 1
        while os.path.exists(path):
            path = os.path.join(dest_dir, f"{base} ({n}){ext}")
            n += 1
            if n > 999:
                break
    download.setDownloadDirectory(os.path.dirname(path))
    download.setDownloadFileName(os.path.basename(path))
    download.accept()

    _emit_download_progress(download, suggested_name, path, 0.0, "started")

    def _on_progress(bytes_received, bytes_total):
        if bytes_total > 0:
            progress = bytes_received / bytes_total
            _emit_download_progress(download, suggested_name, path, progress, "progress")

    if hasattr(download, "downloadProgress"):
        download.downloadProgress.connect(_on_progress)
    elif hasattr(download, "progress"):
        download.progress.connect(_on_progress)

    _done = {"v": False}

    def _on_finished(*_args):
        if _done["v"]:
            return
        if hasattr(download, "isFinished") and not download.isFinished():
            return
        state = getattr(download, "state", lambda: None)()
        completed_enum = getattr(getattr(download, "DownloadState", None), "Completed", None)
        is_completed = (
            (completed_enum is not None and state == completed_enum)
            or (hasattr(download, "isFinished") and download.isFinished()
                and state is not None and completed_enum is not None and state == completed_enum)
        )
        if not is_completed and hasattr(download, "isFinished") and download.isFinished():
            cancelled_enum = getattr(getattr(download, "DownloadState", None), "Cancelled", None)
            interrupted = getattr(getattr(download, "DownloadState", None), "Interrupted", None)
            if state in (cancelled_enum, interrupted):
                is_completed = False
            elif os.path.isfile(path):
                is_completed = True

        if not is_completed and state is None and os.path.isfile(path):
            is_completed = True

        _done["v"] = True
        for sig_name in ("downloadProgress", "progress"):
            if hasattr(download, sig_name):
                try:
                    getattr(download, sig_name).disconnect(_on_progress)
                except (TypeError, RuntimeError):
                    pass

        if is_completed:
            _emit_download_progress(download, suggested_name, path, 1.0, "completed")
            if to_png:
                convert_file_to_png(path)
        else:
            _emit_download_progress(download, suggested_name, path, 0.0, "failed")

    finished_signal = getattr(download, "finished", None)
    connected = False
    if finished_signal is not None:
        try:
            finished_signal.connect(_on_finished)
            connected = True
        except TypeError:
            pass
    if not connected and hasattr(download, "isFinishedChanged"):
        download.isFinishedChanged.connect(_on_finished)
        connected = True
    if not connected and hasattr(download, "stateChanged"):
        download.stateChanged.connect(_on_finished)

def _emit_download_progress(download, file_name: str, file_path: str, progress: float, status: str) -> None:
    download_id = str(id(download))
    profile = None
    if hasattr(download, "profile"):
        try:
            profile = download.profile()
        except Exception:
            profile = None
    if profile is None and hasattr(download, "page"):
        try:
            page = download.page()
            if page is not None and hasattr(page, "profile"):
                profile = page.profile()
        except Exception:
            profile = None
    if profile is None:
        keys = list(_DOWNLOAD_VIEWS.keys())
    else:
        keys = [id(profile)]
    emitted = False
    for key in keys:
        refs = _DOWNLOAD_VIEWS.get(key, [])
        alive = []
        for ref in refs:
            view = ref()
            if view is None:
                continue
            alive.append(ref)
            if hasattr(view, "download_progress"):
                view.download_progress.emit(download_id, file_name, file_path, progress, status)
                emitted = True
        _DOWNLOAD_VIEWS[key] = alive

def normalize_user_input_url(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    if _SCHEME_RE.match(value):
        return value
    if _LOCALHOST_RE.match(value):
        return "http://" + value
    if _DOMAIN_RE.match(value):
        return "https://" + value
    return _GOOGLE_SEARCH_URL + quote_plus(value)

def _norm_external_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "#" in u:
        u = u.split("#", 1)[0]
    return u.rstrip("/")

class MayotterPage(QWebEnginePage):

    ask_handler = None
    ask_handler_async = None
    pending_attach_files: list[str] | None = None
    media_status_handler = None
    _attach_auto_mode_global = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_attach_files: list[str] | None = None
        self._attach_choose_count = 0
        self._user_confirmed_external_url: str | None = None
        self._confirmed_in_app_external_chain: bool = False
        self._confirmed_bootstrap_pending: bool = False
        self._confirmed_in_app_generation: int = 0
        try:
            self.loadFinished.connect(self._on_confirmed_chain_load_finished)
        except Exception:
            pass
        self._attach_choose_served = False
        self._attach_auto_mode = False

    def chooseFiles(self, mode, old_files, accepted_mime_types):
        import os
        import sys

        def _log(msg: str) -> None:
            if os.environ.get("MAYOTTER_MEDIA_DEBUG") or os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                print(f"[ATTACH] {msg}", file=sys.stderr, flush=True)
            try:
                from src.media.debug_log import media_debug
                media_debug("ATTACH", msg)
            except Exception:
                pass

        pending = getattr(self, "pending_attach_files", None)
        if not pending:
            pending = getattr(MayotterPage, "pending_attach_files", None)
            used_class = True
        else:
            used_class = False

        if pending:
            self.pending_attach_files = None
            MayotterPage.pending_attach_files = None
            self._attach_choose_count = getattr(self, "_attach_choose_count", 0) + 1
            self._attach_choose_served = True
            paths = [str(p) for p in pending]
            _log(
                f"stage=F_chooseFiles_called chooseFiles_pending_count={len(paths)} "
                f"source={'class' if used_class else 'instance'} "
                f"stage=G_file_supplied chooseFiles_return={paths}"
            )
            try:
                import time as _t
                _log(f"T9_chooseFiles mono={_t.monotonic():.3f}")
            except Exception:
                pass
            return paths

        if getattr(self, "_attach_auto_mode", False) or getattr(
            MayotterPage, "_attach_auto_mode_global", False
        ):
            _log("chooseFiles auto_mode without pending → cancel (no native dialog)")
            return []

        _log("chooseFiles → native dialog")
        try:
            files = super().chooseFiles(mode, old_files, accepted_mime_types)
        except Exception:
            files = []
        if not files:
            return files

        try:
            from src.media.media_converter import is_audio_path, audio_file_to_mp4
        except Exception:
            return files

        out: list[str] = []
        notify = MayotterPage.media_status_handler
        for path in files:
            try:
                if is_audio_path(path):
                    if callable(notify):
                        try:
                            notify("音声をMP4に変換しています…")
                        except Exception:
                            pass
                    mp4 = audio_file_to_mp4(path, normalize=False)
                    out.append(str(mp4))
                    if callable(notify):
                        try:
                            notify("MP4の準備ができました")
                        except Exception:
                            pass
                else:
                    out.append(path)
            except Exception as exc:
                if callable(notify):
                    try:
                        notify(f"音声をMP4に変換できませんでした: {exc}")
                    except Exception:
                        pass
        return out

    def mark_user_confirmed_external(self, url: str) -> None:
        self._user_confirmed_external_url = _norm_external_url(url)
        self._confirmed_in_app_external_chain = True
        self._confirmed_bootstrap_pending = True
        self._confirmed_in_app_generation = int(
            getattr(self, "_confirmed_in_app_generation", 0) or 0
        ) + 1

    def clear_user_confirmed_external_chain(self) -> None:
        self._user_confirmed_external_url = None
        self._confirmed_in_app_external_chain = False
        self._confirmed_bootstrap_pending = False

    def _on_confirmed_chain_load_finished(self, ok: bool) -> None:
        if not getattr(self, "_confirmed_in_app_external_chain", False):
            return
        try:
            if self.isLoading():
                return
        except Exception:
            pass
        self.clear_user_confirmed_external_chain()

    def _is_redirect_like_navigation(self, navigation_type) -> bool:
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage as _QEP
            if navigation_type == _QEP.NavigationType.NavigationTypeRedirect:
                return True
            if navigation_type == _QEP.NavigationType.NavigationTypeOther:
                try:
                    if self.isLoading():
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def _is_user_initiated_navigation(self, navigation_type) -> bool:
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage as _QEP
            return navigation_type in (
                _QEP.NavigationType.NavigationTypeLinkClicked,
                _QEP.NavigationType.NavigationTypeTyped,
                _QEP.NavigationType.NavigationTypeFormSubmitted,
            )
        except Exception:
            return False

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame) -> bool:
        if not is_main_frame:
            return True
        url_str = url.toString() if hasattr(url, "toString") else str(url)
        url_str = (url_str or "").strip()
        try:
            extracted = extract_google_redirect_target(url_str) or ""
        except Exception:
            extracted = ""
        decision_url = extracted or url_str
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage as _QEP
            is_link = navigation_type == _QEP.NavigationType.NavigationTypeLinkClicked
        except Exception:
            is_link = False

        if not extracted and is_google_click_redirector(url_str):
            return True

        action = decide_navigation(decision_url)
        if action == "block":
            return False
        if action == "external_browser":
            if _nav_begin(decision_url):
                open_in_default_browser(decision_url)
            return False
        if action == "ask":
            try:
                from PySide6.QtWebEngineCore import QWebEnginePage as _QEP
                _nav = navigation_type
                is_history = _nav in (
                    _QEP.NavigationType.NavigationTypeBackForward,
                    _QEP.NavigationType.NavigationTypeReload,
                )
            except Exception:
                is_history = False
            if is_history:
                return True

            if getattr(self, "_confirmed_bootstrap_pending", False):
                self._confirmed_bootstrap_pending = False
                self._confirmed_in_app_external_chain = True
                return True

            if self._is_user_initiated_navigation(navigation_type):
                if getattr(self, "_confirmed_in_app_external_chain", False):
                    self.clear_user_confirmed_external_chain()
            elif getattr(self, "_confirmed_in_app_external_chain", False):
                if self._is_redirect_like_navigation(navigation_type):
                    return True
                self.clear_user_confirmed_external_chain()

            async_handler = MayotterPage.ask_handler_async
            if callable(async_handler):
                try:
                    async_handler(decision_url, self)
                except Exception:
                    pass
                return False
            handler = MayotterPage.ask_handler
            if callable(handler):
                try:
                    if handler(decision_url):
                        if is_link:
                            if _nav_begin(decision_url):
                                view = self.view() if hasattr(self, "view") else None
                                opener = getattr(view, "tab_opener", None) if view is not None else None
                                if callable(opener):
                                    opener(decision_url)
                                    return False
                        return True
                    return False
                except Exception:
                    return False
            if _nav_begin(decision_url):
                open_in_default_browser(decision_url)
            return False
        if is_link:
            try:
                use_tab = should_open_in_new_tab(decision_url, is_link_click=True)
            except Exception:
                use_tab = True
            if use_tab:
                if not _nav_begin(decision_url):
                    return False
                view = self.view() if hasattr(self, "view") else None
                opener = getattr(view, "tab_opener", None) if view is not None else None
                if callable(opener):
                    opener(decision_url)
                    return False
                return True
            return True
        return True

class XWebView(QWebEngineView):

    url_changed = Signal(str)
    loading_started = Signal()
    loading_finished = Signal(bool)
    pressed = Signal()
    download_progress = Signal(str, str, str, float, str)

    FREEZE_AFTER_SECONDS = 300

    tab_opener: "Callable[[str], None] | None" = None

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        def _vtrace(stage: str) -> None:
            try:
                import os
                from src.core.paths import LOGS_DIR
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                with open(LOGS_DIR / "last_account_add.log", "a", encoding="utf-8") as f:
                    f.write(f"webview {stage}\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            except Exception:
                pass

        _vtrace("super_enter")
        super().__init__(parent)
        _vtrace("super_done")
        self._profile = profile
        self._current_url = ""
        self._last_activity = time.time()
        self._last_user_gesture_mono: float | None = None
        self._suppress_user_gesture_mark = False
        self._media_wide_active = False
        _vtrace("create_page_enter")
        self.setPage(self._create_page(profile))
        _vtrace("create_page_done")
        _vtrace("install_filter_enter")
        install_filter(self.page())
        _vtrace("install_filter_done")
        _vtrace("attach_download_enter")
        attach_download_handler(profile)
        _vtrace("attach_download_done")

        key = id(profile)
        refs = _DOWNLOAD_VIEWS.setdefault(key, [])
        refs.append(weakref.ref(self))

        QTimer.singleShot(0, self._install_focus_proxy_filter)

        self._connect_signals()

    def _install_focus_proxy_filter(self) -> None:
        proxy = self.focusProxy()
        if proxy is not None:
            proxy.installEventFilter(self)

    def touch_activity(self) -> None:
        self._last_activity = time.time()
        page = self.page()
        if hasattr(page, "lifecycleState") and page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)

    def mark_user_gesture(self) -> None:
        try:
            self._last_user_gesture_mono = time.monotonic()
        except Exception:
            self._last_user_gesture_mono = None

    def seconds_since_user_gesture(self) -> float | None:
        try:
            t0 = self._last_user_gesture_mono
            if t0 is None:
                return None
            return max(0.0, time.monotonic() - float(t0))
        except Exception:
            return None

    def maybe_freeze(self, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        if current - self._last_activity < self.FREEZE_AFTER_SECONDS:
            return False
        return self.freeze_now()

    def freeze_now(self) -> bool:
        page = self.page()
        if not hasattr(page, "setLifecycleState"):
            return False
        if (
            hasattr(page, "lifecycleState")
            and page.lifecycleState() == QWebEnginePage.LifecycleState.Frozen
        ):
            return False
        accepted = page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        return bool(accepted)

    def mousePressEvent(self, event) -> None:
        self.touch_activity()
        if not getattr(self, "_suppress_user_gesture_mark", False):
            try:
                self._last_user_gesture_mono = time.monotonic()
            except Exception:
                pass
        self.pressed.emit()
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:
        self.touch_activity()
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        self.touch_activity()
        try:
            self._last_user_gesture_mono = time.monotonic()
        except Exception:
            pass
        super().keyPressEvent(event)

    def _local_paths_from_mime(self, md) -> list[str]:
        paths: list[str] = []
        try:
            if md is None or not md.hasUrls():
                return paths
            for url in md.urls():
                try:
                    if url.isLocalFile():
                        paths.append(str(url.toLocalFile()))
                except Exception:
                    continue
        except Exception:
            pass
        return paths

    def _mime_has_convertible_audio(self, md) -> bool:
        try:
            from src.media.media_converter import is_audio_path
            for p in self._local_paths_from_mime(md):
                if is_audio_path(p):
                    return True
        except Exception:
            pass
        return False

    def _media_status(self, msg: str) -> None:
        try:
            page = self.page()
            handler = getattr(page, "media_status_handler", None) if page is not None else None
            if callable(handler):
                handler(msg)
                return
        except Exception:
            pass
        try:
            print(f"[Mayotter] {msg}", flush=True)
        except Exception:
            pass

    def dragEnterEvent(self, event) -> None:
        try:
            if self._mime_has_convertible_audio(event.mimeData()):
                event.acceptProposedAction()
                return
        except Exception:
            pass
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        try:
            if self._mime_has_convertible_audio(event.mimeData()):
                event.acceptProposedAction()
                return
        except Exception:
            pass
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if getattr(self, "_dnd_passthrough", False):
            self._dnd_audio_log("dropEvent passthrough → Chromium")
            super().dropEvent(event)
            return
        if getattr(self, "_dnd_converting", False):
            self._dnd_audio_log(
                "dropEvent ignored reason=convert_in_progress "
                f"busy_src={getattr(self, '_dnd_busy_src', None)!r}"
            )
            try:
                event.acceptProposedAction()
            except Exception:
                try:
                    event.accept()
                except Exception:
                    pass
            return
        md = event.mimeData() if event is not None else None
        if not self._mime_has_convertible_audio(md):
            self._dnd_audio_log("dropEvent no-audio → Chromium super()")
            super().dropEvent(event)
            return
        try:
            event.acceptProposedAction()
        except Exception:
            try:
                event.accept()
            except Exception:
                pass
        paths = self._local_paths_from_mime(md)
        self._dnd_audio_log(f"dropEvent intercept paths={paths!r}")
        try:
            from src.media.media_converter import is_audio_path
        except Exception as exc:
            self._dnd_audio_log(f"is_audio_path import fail={exc!r}")
            self._media_status("音声変換モジュールを読み込めませんでした")
            return
        audio_paths = [p for p in paths if is_audio_path(p)]
        other_paths = [p for p in paths if not is_audio_path(p)]
        self._dnd_audio_log(
            f"classified audio={audio_paths!r} other={other_paths!r}"
        )
        if not audio_paths:
            super().dropEvent(event)
            return
        pos = None
        try:
            pos = event.position()
        except Exception:
            try:
                pos = event.posF()
            except Exception:
                pos = None
        self._convert_audio_drop_then_inject(audio_paths, other_paths, pos)

    def _dnd_audio_log(self, msg: str) -> None:
        import os
        import sys
        from datetime import datetime

        line = f"[DND_AUDIO] {msg}"
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:
            pass
        try:
            if os.environ.get("MAYOTTER_MEDIA_DEBUG") or os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                from src.media.debug_log import media_debug
                media_debug("DND_AUDIO", msg)
        except Exception:
            pass
        try:
            from src.core.paths import APP_BASE_DIR
            log_path = Path(APP_BASE_DIR) / "last_audio_dnd.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            try:
                import tempfile
                log_path = Path(tempfile.gettempdir()) / "Mayotter_last_audio_dnd.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().strftime('%H:%M:%S')} {msg}\n")
            except Exception:
                pass

    def _convert_audio_drop_then_inject(
        self, audio_paths: list[str], other_paths: list[str], pos
    ) -> None:
        from pathlib import Path as _P

        if getattr(self, "_dnd_converting", False):
            self._dnd_audio_log(
                "convert_skip reason=already_converting "
                f"busy_src={getattr(self, '_dnd_busy_src', None)!r} "
                f"ignored={audio_paths!r}"
            )
            self._media_status("音声を変換中です…")
            return

        audio_paths = [p for p in audio_paths if p and _P(p).is_file()]
        if not audio_paths:
            self._dnd_audio_log("convert_skip reason=no_audio_files")
            return

        primary = audio_paths[0]
        extras = audio_paths[1:]
        if extras:
            self._dnd_audio_log(f"extra_audio_ignored={extras!r}")

        self._dnd_converting = True
        self._dnd_busy_src = primary
        self._media_status("音声を変換しています…")
        self._dnd_audio_log(f"handoff_to_mainwindow src={primary!r} other={other_paths!r}")

        if other_paths:
            self._dnd_audio_log(f"other_paths deferred_to_chromium={other_paths!r}")

        win = None
        try:
            win = self.window()
        except Exception:
            win = None
        fn = getattr(win, "_process_audio_source_for_post", None) if win is not None else None
        if not callable(fn):
            self._dnd_converting = False
            self._dnd_busy_src = None
            self._dnd_audio_log("handoff_fail reason=no_process_audio_source_for_post")
            self._media_status("音声投稿処理を開始できませんでした")
            return

        def _clear_busy() -> None:
            self._dnd_converting = False
            self._dnd_busy_src = None

        try:
            page = self.page()
        except Exception:
            page = None

        try:
            fn(
                primary,
                normalize=False,
                is_recording=False,
                min_bytes=32,
                empty_msg="音声ファイルが空です",
                webview=self,
                page=page,
            )
            self._dnd_audio_log("process_audio_source_for_post called")
        except Exception as exc:
            _clear_busy()
            self._dnd_audio_log(f"process_audio_source_for_post exception={exc!r}")
            self._media_status(str(exc) or "音声変換を開始できませんでした")
            return

        worker = getattr(win, "_media_convert_worker", None)
        if worker is not None:
            try:
                worker.signals.finished.connect(lambda *_: _clear_busy())
                worker.signals.failed.connect(lambda *_: _clear_busy())
            except Exception as exc:
                self._dnd_audio_log(f"busy_clear_connect fail={exc!r}")
                _clear_busy()
        else:
            _clear_busy()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.focusProxy() and event.type() == QEvent.Type.FocusIn:
            try:
                self._last_user_gesture_mono = time.monotonic()
            except Exception:
                pass
            self.pressed.emit()
        return super().eventFilter(obj, event)

    def focusInEvent(self, event) -> None:
        self.pressed.emit()
        super().focusInEvent(event)

    def closeEvent(self, event) -> None:
        if self._media_wide_active:
            try:
                self._exit_media_wide(notify_page=False)
            except Exception:
                pass
        webviews = self._profile.property("mayotter_webviews")
        if webviews is not None:
            try:
                webviews.remove(self)
            except ValueError:
                pass
        super().closeEvent(event)

    def _create_page(self, profile: QWebEngineProfile) -> QWebEnginePage:
        page = MayotterPage(profile, self)
        apply_webengine_security_settings(page)
        return page

    def _connect_signals(self) -> None:
        self.urlChanged.connect(self._on_url_changed)
        self.loadStarted.connect(self._on_load_started)
        self.loadFinished.connect(self._on_load_finished)
        page = self.page()
        if page is not None and hasattr(page, "fullScreenRequested"):
            page.fullScreenRequested.connect(self._on_fullscreen_requested)

    def _on_fullscreen_requested(self, request) -> None:
        try:
            toggle_on = bool(request.toggleOn())
        except Exception:
            toggle_on = False
        try:
            request.accept()
        except Exception:
            return
        if toggle_on:
            self._enter_media_wide()
        else:
            self._exit_media_wide(notify_page=False)

    def _enter_media_wide(self) -> None:
        if self._media_wide_active:
            return
        win = self.window()
        enter = getattr(win, "enter_media_wide", None)
        if callable(enter):
            try:
                if enter(self):
                    self._media_wide_active = True
                    return
            except Exception:
                pass
        self._media_wide_active = True

    def _exit_media_wide(self, notify_page: bool = True) -> None:
        if not self._media_wide_active:
            return
        win = self.window()
        exit_fn = getattr(win, "exit_media_wide", None)
        if callable(exit_fn):
            try:
                exit_fn(self)
            except Exception:
                pass
        self._media_wide_active = False
        if notify_page:
            try:
                page = self.page()
                if page is not None:
                    page.runJavaScript(
                        "try{if(document.fullscreenElement){document.exitFullscreen();}}catch(e){}"
                    )
            except Exception:
                pass

    def is_html_fullscreen(self) -> bool:
        return bool(self._media_wide_active)

    def is_media_wide(self) -> bool:
        return bool(self._media_wide_active)

    def _on_url_changed(self, url: QUrl) -> None:
        url_str = url.toString()
        self._current_url = url_str
        self.url_changed.emit(url_str)

    def _on_load_started(self) -> None:
        self.loading_started.emit()

    def _on_load_finished(self, success: bool) -> None:
        self.loading_finished.emit(success)
        try:
            self._apply_x_shortcut_policy()
        except Exception:
            pass

    def _apply_x_shortcut_policy(self) -> None:
        try:
            url = ""
            try:
                url = self.url().toString() if self.url() else ""
            except Exception:
                url = getattr(self, "_current_url", "") or ""
            if not is_x_twitter_url(url):
                return
            page = self.page()
            if page is None:
                return
            enabled = get_disable_x_keyboard_shortcuts()
            page.runJavaScript(x_shortcut_script(enabled))
        except Exception:
            pass

    def contextMenuEvent(self, event) -> None:
        request = self.lastContextMenuRequest()
        menu, handlers = self._build_context_menu(request)
        self._extend_context_menu(menu, request)
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        handler = handlers.get(id(chosen))
        if handler is not None:
            handler()

    def _build_context_menu(self, request) -> tuple[QMenu, dict[int, "Callable[[], None]"]]:
        menu = QMenu(self)
        try:
            from src.ui.theme import SURFACE, BORDER, TEXT, TEXT_MUTED, RADIUS_SM, dark_palette
            menu.setStyleSheet(
                f"QMenu {{ background-color: {SURFACE}; color: {TEXT};"
                f" border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px; padding: 4px; }}"
                f"QMenu::item {{ color: {TEXT}; padding: 5px 18px 5px 12px; border-radius: 4px; }}"
                f"QMenu::item:selected {{ background-color: rgba(148,178,230,0.18); color: {TEXT}; }}"
                f"QMenu::item:disabled {{ color: {TEXT_MUTED}; }}"
            )
            menu.setPalette(dark_palette())
        except Exception:
            menu.setStyleSheet(
                "QMenu { background:#181c26; color:#f1f3f7; border:1px solid #2b3242; }"
                "QMenu::item { color:#f1f3f7; padding:5px 18px 5px 12px; }"
                "QMenu::item:selected { background:rgba(148,178,230,0.18); }"
            )
        handlers: dict[int, Callable[[], None]] = {}
        page_action = self.page().action

        def add(label: str, callback: "Callable[[], None]", enabled: bool = True):
            action = menu.addAction(label)
            action.setEnabled(enabled)
            handlers[id(action)] = callback
            return action

        back_action = page_action(QWebEnginePage.WebAction.Back)
        forward_action = page_action(QWebEnginePage.WebAction.Forward)
        add("戻る", lambda: self.page().triggerAction(QWebEnginePage.WebAction.Back), back_action.isEnabled())
        add("進む", lambda: self.page().triggerAction(QWebEnginePage.WebAction.Forward), forward_action.isEnabled())
        add("更新", lambda: self.reload_page())
        menu.addSeparator()

        has_link = bool(request is not None and request.linkUrl().isValid())
        media_type = (
            request.mediaType()
            if request is not None
            else QWebEngineContextMenuRequest.MediaType.MediaTypeNone
        )
        has_image = media_type == QWebEngineContextMenuRequest.MediaType.MediaTypeImage
        selection = (request.selectedText() if request is not None else "") or ""

        can_cut = False
        can_select_all = False
        try:
            if request is not None and hasattr(request, "editFlags"):
                flags = request.editFlags()
                EditFlag = QWebEngineContextMenuRequest.EditFlag
                can_cut = bool(flags & EditFlag.CanCut)
                can_select_all = bool(flags & EditFlag.CanSelectAll)
        except Exception:
            can_cut = False
            can_select_all = True

        if selection:
            if can_cut:
                cut_action = page_action(QWebEnginePage.WebAction.Cut)
                add(
                    "切り取り",
                    lambda: self.page().triggerAction(QWebEnginePage.WebAction.Cut),
                    cut_action.isEnabled() if cut_action is not None else True,
                )
            add(
                "コピー",
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.Copy),
            )
        paste_action = page_action(QWebEnginePage.WebAction.Paste)
        add(
            "貼り付け",
            lambda: self.page().triggerAction(QWebEnginePage.WebAction.Paste),
            paste_action.isEnabled(),
        )
        if can_select_all or True:
            sel_all = page_action(QWebEnginePage.WebAction.SelectAll)
            add(
                "すべて選択",
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.SelectAll),
                sel_all.isEnabled() if sel_all is not None else True,
            )

        if has_link:
            menu.addSeparator()
            link_url = request.linkUrl().toString()
            opener = self.tab_opener
            def _open_link_new_tab(url=link_url, open_fn=opener):
                try:
                    action = decide_navigation(url)
                except Exception:
                    action = "in_app"
                if action == "external_browser":
                    open_in_default_browser(url)
                    return
                if action == "block":
                    return
                if action == "ask":
                    page = self.page()
                    if isinstance(page, MayotterPage) and getattr(page, '_confirmed_bootstrap_pending', False):
                        allow = True
                    else:
                        async_handler = MayotterPage.ask_handler_async
                        if callable(async_handler) and isinstance(page, MayotterPage):
                            try:
                                async_handler(url, page)
                            except Exception:
                                pass
                            return
                        handler = MayotterPage.ask_handler
                        allow = False
                        if callable(handler):
                            try:
                                allow = bool(handler(url))
                            except Exception:
                                allow = False
                        if not allow:
                            if not callable(handler):
                                open_in_default_browser(url)
                            return
                if callable(open_fn):
                    open_fn(url)

            add(
                "新しいタブで開く",
                _open_link_new_tab if callable(opener) else (lambda: None),
                callable(opener),
            )
            add(
                "リンクのURLをコピー",
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.CopyLinkToClipboard),
            )
        if has_image:
            menu.addSeparator()
            add(
                "画像を保存...",
                lambda: self.page().triggerAction(
                    QWebEnginePage.WebAction.DownloadImageToDisk
                ),
            )
        if selection:
            menu.addSeparator()
            opener = self.tab_opener
            search_url = normalize_user_input_url(selection)
            add(
                f"「{selection[:20]}」をGoogle検索",
                (lambda url=search_url: opener(url)) if callable(opener) else (lambda: None),
                callable(opener),
            )
        return menu, handlers

    def _extend_context_menu(self, menu: QMenu, request) -> None:
        del menu, request

    def createWindow(self, kind) -> QWebEngineView:
        owner = self
        print(
            f"[CreateWindow] kind={kind!r} source={type(self).__name__}",
            flush=True,
        )

        class _CapturePage(QWebEnginePage):

            def __init__(self, profile, parent=None):
                super().__init__(profile, parent)
                self._routed = False
                self._last_url = ""

            def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
                if not is_main_frame:
                    return False
                text = url.toString() if hasattr(url, "toString") else str(url)
                text = (text or "").strip()
                if not text or text.startswith("about:") or text.startswith("data:"):
                    return True
                print(
                    f"[CapturePage] nav url={text[:160]!r} routed={self._routed}",
                    flush=True,
                )
                if self._routed:
                    return False
                self._last_url = text

                try:
                    extracted = extract_google_redirect_target(text) or ""
                except Exception:
                    extracted = ""
                if extracted:
                    self._route_final(extracted)
                    return False

                try:
                    if is_google_click_redirector(text):
                        return True
                except Exception:
                    pass

                self._route_final(text)
                return False

            def _route_final(self, final_url: str) -> None:
                if self._routed:
                    return
                final_url = (final_url or "").strip()
                if not final_url or final_url.startswith("about:"):
                    return
                self._routed = True
                print(
                    f"[CapturePage] final url={final_url[:160]!r}",
                    flush=True,
                )
                if not _nav_begin(final_url):
                    return
                try:
                    owner._open_from_new_window_request(final_url)
                finally:
                    _nav_end(final_url)

        class _CaptureView(QWebEngineView):

            def show(self) -> None:
                print("[TransientWindow] SHOW blocked CaptureView.show()", flush=True)
                return

            def showNormal(self) -> None:
                print("[TransientWindow] SHOW blocked CaptureView.showNormal()", flush=True)
                return

            def showFullScreen(self) -> None:
                return

            def showMaximized(self) -> None:
                return

            def showMinimized(self) -> None:
                return

            def setVisible(self, visible: bool) -> None:
                if visible:
                    print(
                        f"[TransientWindow] SHOW blocked CaptureView.setVisible(True) "
                        f"isWindow={self.isWindow()}",
                        flush=True,
                    )
                super().setVisible(False)

            def showEvent(self, event) -> None:
                try:
                    super().showEvent(event)
                except Exception:
                    pass
                try:
                    self.hide()
                    self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    self.setFixedSize(1, 1)
                except Exception:
                    pass
                print("[TransientWindow] SHOWEVENT CaptureView forced hide", flush=True)

            def raise_(self) -> None:
                return

            def activateWindow(self) -> None:
                return

            def setWindowState(self, state) -> None:
                return

        parent = _capture_parent_for(self)
        view = _CaptureView(parent)
        view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        view.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        view.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            view.setWindowFlags(Qt.WindowType.Widget)
        except Exception:
            pass
        view.setFixedSize(1, 1)
        view.move(0, 0)
        view.hide()
        print(
            f"[TransientWindow] CREATE CaptureView "
            f"parent={type(parent).__name__}/{parent.objectName()!r} "
            f"isWindow={view.isWindow()} visible={view.isVisible()} "
            f"flags=0x{int(view.windowFlags()):x} "
            f"dontShow={view.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)}",
            flush=True,
        )
        page = _CapturePage(self.page().profile(), view)
        view.setPage(page)

        def _on_capture_load(ok, pg=page, vw=view):
            try:
                if getattr(pg, "_routed", False):
                    return
                u = pg.url().toString() if pg.url() is not None else ""
                u = (u or "").strip()
                if not u or u.startswith("about:"):
                    return
                try:
                    if is_google_click_redirector(u):
                        return
                except Exception:
                    pass
                print(f"[CapturePage] loadFinished route url={u[:160]!r}", flush=True)
                pg._route_final(u)
            except Exception:
                pass

        try:
            page.loadFinished.connect(_on_capture_load)
        except Exception:
            pass
        view.hide()
        view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._pending_capture_views = getattr(self, "_pending_capture_views", [])
        self._pending_capture_views.append(view)

        def _drop():
            try:
                self._pending_capture_views.remove(view)
            except ValueError:
                pass
            try:
                view.hide()
            except Exception:
                pass
            view.deleteLater()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(15000, _drop)
        print(
            f"[CaptureView] ready parent=offscreen_holder "
            f"(no visible window / no taskbar / no focus)",
            flush=True,
        )
        return view

    def _open_from_new_window_request(self, text: str) -> None:
        text = (text or "").strip()
        if not text or text.startswith("about:") or text.startswith("data:"):
            return
        try:
            extracted = extract_google_redirect_target(text) or ""
            if extracted:
                text = extracted
        except Exception:
            pass
        try:
            if is_google_click_redirector(text):
                print(
                    f"[InternalNavigation] skip intermediate url={text[:120]!r}",
                    flush=True,
                )
                return
        except Exception:
            pass
        print(
            f"[InternalNavigation] classification begin url={text[:120]!r}",
            flush=True,
        )
        try:
            action = decide_navigation(text)
        except Exception:
            action = "in_app"
        print(
            f"[InternalNavigation] classification result={action} "
            f"(no visible window)",
            flush=True,
        )
        if action == "block":
            return
        if action == "external_browser":
            open_in_default_browser(text)
            return
        if action == "ask":
            page = self.page()
            if isinstance(page, MayotterPage) and (
                getattr(page, '_confirmed_bootstrap_pending', False)
                or getattr(page, '_confirmed_in_app_external_chain', False)
            ):
                allow = True
            else:
                async_handler = MayotterPage.ask_handler_async
                if callable(async_handler) and isinstance(page, MayotterPage):
                    try:
                        async_handler(text, page)
                    except Exception:
                        pass
                    return
                handler = MayotterPage.ask_handler
                allow = False
                if callable(handler):
                    try:
                        allow = bool(handler(text))
                    except Exception:
                        allow = False
                if not allow:
                    if not callable(handler):
                        open_in_default_browser(text)
                    return
        try:
            use_tab = should_open_in_new_tab(text, is_link_click=True)
        except Exception:
            use_tab = True
        if use_tab:
            opener = self.tab_opener
            if callable(opener):
                opener(text)
                return
        try:
            self.load_url(text)
        except Exception:
            opener = self.tab_opener
            if callable(opener):
                opener(text)

    def load_url(self, url: str, *, restore: bool = False) -> None:
        self.touch_activity()
        if restore:
            kind = classify_url(url)
            if kind == "unsupported":
                return
        else:
            action = decide_navigation(url)
            if action == "block":
                return
            if action == "external_browser":
                open_in_default_browser(url)
                return
            if action == "ask":
                page = self.page()
                if isinstance(page, MayotterPage) and getattr(page, '_confirmed_bootstrap_pending', False):
                    pass
                else:
                    async_handler = MayotterPage.ask_handler_async
                    if callable(async_handler) and isinstance(page, MayotterPage):
                        try:
                            async_handler(url, page)
                        except Exception:
                            pass
                        return
                    handler = MayotterPage.ask_handler
                    if callable(handler):
                        try:
                            if not handler(url):
                                return
                        except Exception:
                            return
                    else:
                        open_in_default_browser(url)
                        return
        try:
            def _norm(u: str) -> str:
                u = (u or "").strip().split("?")[0].split("#")[0].rstrip("/").lower()
                return u
            cur = ""
            try:
                cur = self.page().url().toString() if self.page() is not None else ""
            except Exception:
                cur = self._current_url or ""
            if cur and _norm(cur) == _norm(url):
                self._current_url = url
                return
        except Exception:
            pass
        self._current_url = url
        self.page().load(QUrl(url))

    def get_current_url(self) -> str:
        try:
            page = self.page()
            if page is not None:
                u = page.url()
                text = u.toString() if hasattr(u, "toString") else str(u)
                text = (text or "").strip()
                if text and not text.startswith("about:") and not text.startswith("data:"):
                    self._current_url = text
                    return text
        except Exception:
            pass
        return self._current_url or ""

    def go_back(self) -> bool:
        action = self.page().action(QWebEnginePage.WebAction.Back)
        if action.isEnabled():
            self.page().triggerAction(QWebEnginePage.WebAction.Back)
            return True
        return False

    def go_forward(self) -> bool:
        action = self.page().action(QWebEnginePage.WebAction.Forward)
        if action.isEnabled():
            self.page().triggerAction(QWebEnginePage.WebAction.Forward)
            return True
        return False

    def reload_page(self) -> None:
        self.touch_activity()
        self.page().triggerAction(QWebEnginePage.WebAction.Reload)
