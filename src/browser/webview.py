

from __future__ import annotations
from src.core.i18n import tr

import os
from pathlib import Path
import re
import time
from collections.abc import Callable
from urllib.parse import quote_plus

from PySide6.QtCore import Qt, QUrl, Signal, QEvent, QPoint, QTimer
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtWidgets import QApplication, QMenu, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineContextMenuRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineScript,
    QWebEngineDownloadRequest,
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
from src.browser.tls_security import enforce_certificate_error_rejection


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
    now = time.monotonic()
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
from src.ui.theme import themed_qcolor
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
    except Exception:
        pass

def _offscreen_capture_holder() -> QWidget | None:
    w = _OFFSCREEN_CAPTURE_HOLDER
    if w is None:
        host = _CAPTURE_HOST_WINDOW
        if host is not None:
            attach_capture_holder_parent(host)
            return _OFFSCREEN_CAPTURE_HOLDER
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


def needs_interactive_auth_window(url: str) -> bool:
    """OAuth / GIS / ログイン用 popup は URL 捕捉では成立しない。"""
    text = (url or "").strip()
    if not text or text.startswith("about:") or text.startswith("data:"):
        return False
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(text)
        host = (parsed.hostname or "").lower().rstrip(".")
        path = (parsed.path or "").lower()
    except Exception:
        return False
    if not host:
        return False
    # Google Identity Services / OAuth
    if host == "accounts.google.com" or host.endswith(".google.com"):
        if any(
            s in path
            for s in (
                "/gsi/",
                "/o/oauth2",
                "/signin",
                "/ServiceLogin",
                "/v3/signin",
                "/AddSession",
                "/InteractiveLogin",
                "/EmbeddedSetup",
            )
        ):
            return True
        if host == "accounts.google.com":
            return True
    if host in ("oauth2.googleapis.com", "www.googleapis.com"):
        return True
    # X / Twitter 認証ウィンドウ
    if host in (
        "api.twitter.com",
        "api.x.com",
        "accounts.x.com",
        "accounts.twitter.com",
    ):
        return True
    if host in ("x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.x.com", "mobile.twitter.com"):
        if any(s in path for s in ("/i/flow", "/oauth", "/account/login", "/login")):
            return True
    return False


# owner_window の id -> 認証ポップアップの弱参照
_AUTH_POPUPS: dict[int, list[weakref.ref]] = {}


def register_auth_popup(owner_window: QWidget | None, popup: QWidget) -> None:
    if owner_window is None or popup is None:
        return
    try:
        key = int(id(owner_window))
    except Exception:
        return
    refs = _AUTH_POPUPS.setdefault(key, [])
    refs.append(weakref.ref(popup))

    def _cleanup(*_args, k=key):
        lst = _AUTH_POPUPS.get(k)
        if not lst:
            return
        alive = [r for r in lst if r() is not None]
        if alive:
            _AUTH_POPUPS[k] = alive
        else:
            _AUTH_POPUPS.pop(k, None)

    try:
        popup.destroyed.connect(_cleanup)
    except Exception:
        pass


class AuthPopupWindow(QWidget):
    """Google / X 等の認証用 interactive popup。既存 overlay / 設定ダイアログと同一 chrome。"""

    _RADIUS = 8

    def __init__(self, web_view: QWebEngineView, owner_window: QWidget | None = None) -> None:
        super().__init__(None)
        self._web_view = web_view
        self._closing = False
        self._drag_pos = None

        from PySide6.QtWidgets import (
            QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame, QSizePolicy, QWidget,
        )
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QCursor

        try:
            from src.ui.theme import (
                SURFACE, BORDER, TEXT, RADIUS_MD,
            )
            bg = SURFACE
            border = BORDER
            text = TEXT
            radius = int(RADIUS_MD)
        except Exception:
            bg = "#181c26"
            border = "#2b3242"
            text = "#f1f3f7"
            radius = 8
        self._RADIUS = radius

        self.setObjectName("mayotter_auth_popup")
        self.setWindowTitle(tr('認証'))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        try:
            self.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            )
        except Exception:
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)

        try:
            from src.ui.window_polish import prepare_popup_chrome
            self._native_rounding = prepare_popup_chrome(
                self, background=bg, border_color=border, corner="round"
            )
        except Exception:
            self._native_rounding = False
        if not self._native_rounding:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setStyleSheet(
            f"QWidget#mayotter_auth_popup {{"
            f" background:{bg if self._native_rounding else 'transparent'}; border:none; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 内側 surface（既存ダイアログと同じ色・枠・角丸）
        surface = QWidget(self)
        surface.setObjectName("mayotter_auth_popup_surface")
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        surface.setStyleSheet(
            f"QWidget#mayotter_auth_popup_surface {{"
            f" background-color: {bg};"
            f" border: {'none' if self._native_rounding else f'1px solid {border}'};"
            f" border-radius: {0 if self._native_rounding else radius}px;"
            f"}}"
        )
        outer.addWidget(surface)
        self._surface = surface

        root = QVBoxLayout(surface)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # タイトルバー（設定 / ダウンロード overlay と同型）
        titlebar = QFrame(surface)
        titlebar.setObjectName("auth_popup_titlebar")
        titlebar.setFixedHeight(34)
        titlebar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        titlebar.setStyleSheet(
            "QFrame#auth_popup_titlebar { background: transparent; border: none; }"
        )
        title_l = QHBoxLayout(titlebar)
        title_l.setContentsMargins(12, 0, 8, 0)
        title_l.setSpacing(6)
        title_l.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_lbl = QLabel(tr('認証'))
        title_lbl.setObjectName("auth_popup_title")
        title_lbl.setStyleSheet(
            f"QLabel#auth_popup_title {{"
            f" color: {text}; font-size: 13px; font-weight: 600;"
            f" background: transparent; border: none;"
            f"}}"
        )
        title_l.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        title_l.addStretch(1)

        close_btn = QToolButton(titlebar)
        close_btn.setObjectName("auth_popup_close")
        close_btn.setToolTip(tr('閉じる'))
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            from src.ui.icons import make_close_icon
            close_btn.setText("")
            close_btn.setIcon(make_close_icon("#aeb6c5", 12))
            close_btn.setIconSize(QSize(12, 12))
        except Exception:
            close_btn.setText("×")
        # win_close_btn と同一の hover（赤系）
        close_btn.setStyleSheet(
            "QToolButton#auth_popup_close {"
            " background: transparent; border: none; border-radius: 4px;"
            " color: #aeb6c5; font-size: 14px; padding: 0;"
            "}"
            "QToolButton#auth_popup_close:hover {"
            " background-color: rgba(230, 100, 100, 0.3); color: #e66464;"
            "}"
            "QToolButton#auth_popup_close:pressed {"
            " background-color: rgba(230, 100, 100, 0.45); color: #e66464;"
            "}"
        )
        close_btn.clicked.connect(lambda: self.request_close())
        title_l.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._close_btn = close_btn
        root.addWidget(titlebar, 0)

        try:
            from src.ui.theme import install_hover_fade
            install_hover_fade(close_btn)
        except Exception:
            pass

        try:
            web_view.setParent(surface)
        except Exception:
            pass
        try:
            web_view.setMinimumSize(0, 0)
            web_view.setMaximumSize(16777215, 16777215)
        except Exception:
            pass
        web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        try:
            web_view.setMinimumSize(400, 480)
        except Exception:
            pass
        try:
            web_view.setVisible(True)
            web_view.show()
        except Exception:
            pass
        root.addWidget(web_view, 1)

        self.resize(520, 680)
        self.setMinimumSize(420, 520)
        self._apply_round_mask()

        try:
            page = web_view.page()
            if page is not None and hasattr(page, "windowCloseRequested"):
                page.windowCloseRequested.connect(self._on_window_close_requested)
        except Exception:
            pass

        titlebar.mousePressEvent = self._title_mouse_press  # type: ignore
        titlebar.mouseMoveEvent = self._title_mouse_move  # type: ignore
        titlebar.mouseReleaseEvent = self._title_mouse_release  # type: ignore

    def _apply_round_mask(self) -> None:
        # 角丸は半透明ウィンドウ + 内側 QSS で描く。
        # QRegion のマスクを掛けると角がギザギザになる。
        try:
            self.clearMask()
            surface = getattr(self, "_surface", None)
            if surface is not None:
                surface.clearMask()
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        self._apply_round_mask()

    def _title_mouse_press(self, event) -> None:
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        except Exception:
            pass
        try:
            event.ignore()
        except Exception:
            pass

    def _title_mouse_move(self, event) -> None:
        try:
            if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
                return
        except Exception:
            pass
        try:
            event.ignore()
        except Exception:
            pass

    def _title_mouse_release(self, event) -> None:
        self._drag_pos = None
        try:
            event.accept()
        except Exception:
            pass

    def _on_window_close_requested(self) -> None:
        self.request_close()

    def request_close(self, *, immediate: bool = False) -> None:
        if self._closing:
            return
        self._closing = True
        if immediate:
            self._finish_close()
            return
        try:
            from src.ui.theme import menu_dropdown_hide
            menu_dropdown_hide(self, on_finished=self._finish_close)
        except Exception:
            self._finish_close()

    def _finish_close(self) -> None:
        try:
            self.hide()
        except Exception:
            pass
        try:
            self.close()
        except Exception:
            pass
        try:
            self.deleteLater()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        if not self._closing:
            event.ignore()
            self.request_close()
            return
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()

    def show_animated(self) -> None:
        try:
            vw = self._web_view
            if vw is not None:
                try:
                    vw.setMinimumSize(0, 0)
                    vw.setMaximumSize(16777215, 16777215)
                    vw.setMinimumSize(400, 480)
                except Exception:
                    pass
                try:
                    vw.setVisible(True)
                    vw.show()
                except Exception:
                    pass
        except Exception:
            pass
        self._apply_round_mask()
        try:
            from src.ui.theme import menu_dropdown_show
            menu_dropdown_show(self)
        except Exception:
            self.show()
            self.raise_()
            try:
                self.activateWindow()
            except Exception:
                pass
        try:
            if self._web_view is not None:
                self._web_view.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass



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
        # Content-Length がある場合のみ 0..1 の確定進捗。
        # 不明サイズは -1 未満のセンチネル + 受信バイトを UI に渡し、
        # 偽パーセントや 0%→100% ジャンプを避ける。
        br = max(0, int(bytes_received or 0))
        if bytes_total and bytes_total > 0:
            progress = max(0.0, min(1.0, float(br) / float(bytes_total)))
        else:
            # progress < -1 は「不定形」。小数部に受信MBを埋め込む方式ではなく
            # 別引数が無い既存シグネチャを維持するため、
            # progress = -(1.0 + br) で受信バイトを運ぶ。
            progress = -(1.0 + float(br))
        _emit_download_progress(download, suggested_name, path, progress, "progress")

    # Qt6 の QWebEngineDownloadRequest に downloadProgress は無く、受信/総バイトの変更通知で進む。
    _last_emit = {"t": 0.0, "br": -1}

    def _on_bytes_changed(*_args):
        now = time.monotonic()
        br = int(download.receivedBytes() or 0)
        done = bool(hasattr(download, "isFinished") and download.isFinished())
        # 受信ごとの通知は多いので、約 60ms に1回へ間引く（最後の値は完了通知が確定させる）
        if not done and now - _last_emit["t"] < 0.06:
            return
        if br == _last_emit["br"]:
            return
        _last_emit["t"] = now
        _last_emit["br"] = br
        _on_progress(br, int(download.totalBytes() or 0))

    if hasattr(download, "receivedBytesChanged"):
        download.receivedBytesChanged.connect(_on_bytes_changed)
    if hasattr(download, "totalBytesChanged"):
        download.totalBytesChanged.connect(_on_bytes_changed)
    elif hasattr(download, "downloadProgress"):
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
        for sig_name, slot in (
            ("receivedBytesChanged", _on_bytes_changed),
            ("totalBytesChanged", _on_bytes_changed),
            ("downloadProgress", _on_progress),
            ("progress", _on_progress),
        ):
            if hasattr(download, sig_name):
                try:
                    getattr(download, sig_name).disconnect(slot)
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
        enforce_certificate_error_rejection(self)
        try:
            self.setBackgroundColor(themed_qcolor("#0b111f"))
        except Exception:
            pass
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
        try:
            # 新API(Qt 6.8+)を優先し、旧APIは古い環境用。二重処理を避けるため同時接続しない
            if hasattr(self, "permissionRequested"):
                self.permissionRequested.connect(self._on_permission_requested)
            elif hasattr(self, "featurePermissionRequested"):
                self.featurePermissionRequested.connect(self._on_feature_permission_requested)
        except Exception:
            pass

    def _on_permission_requested(self, permission) -> None:
        """マイク権限要求をユーザー確認のうえ grant/deny する（Qt 6.8+ の permissionRequested 用）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineCore import QWebEnginePermission
        from PySide6.QtWidgets import QMessageBox

        def _log(msg: str) -> None:
            try:
                from src.media.debug_log import media_debug
                media_debug("PERM", msg)
            except Exception:
                pass

        ptype = permission.permissionType()
        Type = QWebEnginePermission.PermissionType
        origin = permission.origin()
        host = (origin.host() or "").strip() if isinstance(origin, QUrl) else ""
        scheme = (origin.scheme() or "").strip().lower() if isinstance(origin, QUrl) else ""

        # マイク系以外（カメラ単独など）は拒否
        if ptype not in (Type.MediaAudioCapture, Type.MediaAudioVideoCapture):
            _log(f"api=permissionRequested type={ptype} origin={host} result=deny(not_audio)")
            permission.deny()
            return

        if not host or scheme in ("about", "data", "blob", "file"):
            _log(f"api=permissionRequested type={ptype} origin={origin.toString()!r} result=deny(invalid_origin)")
            permission.deny()
            return

        parent = None
        try:
            parent = self.view()
        except Exception:
            parent = None
        if parent is None:
            try:
                parent = self.parent()
            except Exception:
                parent = None

        reply = QMessageBox.question(
            parent,
            tr('マイクの使用'),
            tr('{v0} がマイクの使用を要求しています。許可しますか？', v0=host),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            _log(f"api=permissionRequested type={ptype} origin={host} result=grant")
            permission.grant()
        else:
            _log(f"api=permissionRequested type={ptype} origin={host} result=deny(user)")
            permission.deny()

    def _on_feature_permission_requested(self, origin, feature) -> None:
        """マイク等のメディア権限要求をユーザー確認のうえ Granted/Denied する。"""
        from PySide6.QtWidgets import QMessageBox

        try:
            Feature = QWebEnginePage.FeaturePermission
        except AttributeError:
            try:
                Feature = QWebEnginePage.Feature
            except AttributeError:
                Feature = None

        audio_features = set()
        if Feature is not None:
            for name in ("MediaAudioCapture", "MediaAudioVideoCapture"):
                val = getattr(Feature, name, None)
                if val is not None:
                    audio_features.add(val)

        is_audio = feature in audio_features if audio_features else False
        # マイク系以外（カメラ単独など）は拒否
        if not is_audio:
            try:
                Permission = QWebEnginePage.PermissionPolicy
                denied = getattr(Permission, "PermissionDeniedByUser", None)
                if denied is None:
                    denied = getattr(Permission, "DeniedByUser", None)
                if denied is not None:
                    self.setFeaturePermission(origin, feature, denied)
            except Exception:
                pass
            return

        host = ""
        try:
            if origin is not None and hasattr(origin, "host"):
                host = (origin.host() or "").strip()
            if not host and origin is not None and hasattr(origin, "toString"):
                host = (origin.toString() or "").strip()
        except Exception:
            host = ""

        scheme = ""
        try:
            if origin is not None and hasattr(origin, "scheme"):
                scheme = (origin.scheme() or "").strip().lower()
        except Exception:
            scheme = ""

        invalid = (
            not host
            or scheme in ("about", "data", "blob", "file")
            or (isinstance(host, str) and host.startswith("about:"))
        )

        Permission = QWebEnginePage.PermissionPolicy
        granted = getattr(Permission, "PermissionGrantedByUser", None)
        if granted is None:
            granted = getattr(Permission, "GrantedByUser", None)
        denied = getattr(Permission, "PermissionDeniedByUser", None)
        if denied is None:
            denied = getattr(Permission, "DeniedByUser", None)

        if invalid or granted is None or denied is None:
            try:
                if denied is not None:
                    self.setFeaturePermission(origin, feature, denied)
            except Exception:
                pass
            return

        label = host or tr('このサイト')
        parent = None
        try:
            parent = self.view()
        except Exception:
            parent = None
        if parent is None:
            try:
                parent = self.parent()
            except Exception:
                parent = None

        reply = QMessageBox.question(
            parent,
            tr('マイクの使用'),
            tr('{v0} がマイクの使用を要求しています。許可しますか？', v0=label),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        policy = granted if reply == QMessageBox.StandardButton.Yes else denied
        try:
            self.setFeaturePermission(origin, feature, policy)
        except Exception:
            pass

    def _js_dialog_parent(self):
        try:
            view = self.view()
            if view is not None:
                win = view.window()
                return win if win is not None else view
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication

            return QApplication.activeWindow()
        except Exception:
            return None

    def javaScriptAlert(self, origin, message) -> None:
        try:
            from src.ui.js_dialog import show_js_alert

            show_js_alert(self._js_dialog_parent(), str(message or ""))
        except Exception:
            pass

    def javaScriptConfirm(self, origin, message) -> bool:
        try:
            from src.ui.js_dialog import show_js_confirm

            return bool(show_js_confirm(self._js_dialog_parent(), str(message or "")))
        except Exception:
            return False

    def javaScriptPrompt(self, origin, message, defaultValue):
        try:
            from src.ui.js_dialog import show_js_prompt

            ok, text = show_js_prompt(
                self._js_dialog_parent(), str(message or ""), str(defaultValue or "")
            )
            return (bool(ok), str(text))
        except Exception:
            return (False, "")

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
                            notify(tr('音声をMP4に変換しています…'))
                        except Exception:
                            pass
                    mp4 = audio_file_to_mp4(path, normalize=False)
                    out.append(str(mp4))
                    if callable(notify):
                        try:
                            notify(tr('MP4の準備ができました'))
                        except Exception:
                            pass
                else:
                    out.append(path)
            except Exception as exc:
                if callable(notify):
                    try:
                        notify(tr('音声をMP4に変換できませんでした: {v0}', v0=exc))
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

# QtWebEngine はホイール1ノッチを「行数 x 20px」でスクロールする
# （web_event_factory.cpp: cDefaultQtScrollStep）。Chrome は「行数 x 100/3 px」
# （web_input_event_builders_win.cc: kScrollbarPixelsPerLine）で、常に 5/3 倍多い。
# Chrome 相当を 100% とし、ユーザー設定の倍率を掛けてスクロール量を決める。
_CHROME_WHEEL_BASE_SCALE = 5.0 / 3.0
_WHEEL_SCROLL_PERCENT = 200

# 後方互換用。旧定数を参照するコードがあっても有効な値を返す。
_WHEEL_DELTA_SCALE = _CHROME_WHEEL_BASE_SCALE * (_WHEEL_SCROLL_PERCENT / 100.0)


def set_wheel_scroll_percent(percent: int) -> None:
    """ホイールスクロール速度（%）を設定する。100 = Chrome 相当。"""
    global _WHEEL_SCROLL_PERCENT, _WHEEL_DELTA_SCALE
    try:
        v = int(percent)
    except (TypeError, ValueError):
        v = 200
    v = max(50, min(400, v))
    _WHEEL_SCROLL_PERCENT = v
    _WHEEL_DELTA_SCALE = _CHROME_WHEEL_BASE_SCALE * (v / 100.0)


def get_wheel_scroll_percent() -> int:
    return int(_WHEEL_SCROLL_PERCENT)


def _wheel_delta_to_chrome(value: int) -> int:
    if not value:
        return 0
    return int(round(value * _WHEEL_DELTA_SCALE))


def _wheel_pixel_to_scaled(value: int) -> int:
    if not value:
        return 0
    return int(round(value * (_WHEEL_SCROLL_PERCENT / 100.0)))


def _wheel_event_for_chrome(event: QWheelEvent) -> QWheelEvent | None:
    """設定倍率を掛けたスクロールイベントを返す（補正不要なら None）。"""
    angle = event.angleDelta()
    pixel = event.pixelDelta()
    if angle.isNull() and pixel.isNull():
        return None
    scaled_pixel = QPoint(
        _wheel_pixel_to_scaled(pixel.x()), _wheel_pixel_to_scaled(pixel.y())
    ) if not pixel.isNull() else pixel
    if angle.isNull():
        # 高精度タッチパッドは pixelDelta のみ。倍率だけ掛けて転送する。
        return QWheelEvent(
            event.position(),
            event.globalPosition(),
            scaled_pixel,
            angle,
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
        )
    return QWheelEvent(
        event.position(),
        event.globalPosition(),
        scaled_pixel,
        QPoint(_wheel_delta_to_chrome(angle.x()), _wheel_delta_to_chrome(angle.y())),
        event.buttons(),
        event.modifiers(),
        event.phase(),
        event.inverted(),
        event.source(),
    )


class XWebView(QWebEngineView):

    url_changed = Signal(str)
    loading_started = Signal()
    loading_finished = Signal(bool)
    pressed = Signal()
    download_progress = Signal(str, str, str, float, str)
    zoom_requested = Signal(int)
    zoom_changed = Signal(float)

    FREEZE_AFTER_SECONDS = 300
    HIDDEN_GRACE_SECONDS = 30
    DISCARD_AFTER_SECONDS = 120
    # 保護中・判定不能だったページを再判定するまでの間隔。
    MEMORY_RETRY_SECONDS = 60
    # 安全判定の応答を待つ上限。応答が無いまま判定中で止まり続けないようにする。
    PROBE_TIMEOUT_SECONDS = 30
    retain_hidden_pages = False
    _memory_views = weakref.WeakSet()
    # 診断用の累計（view の生成・破棄、ページ読込開始）。値は整数のみ保持する。
    memory_counters = {"created": 0, "destroyed": 0, "loads": 0, "probe_timeouts": 0}

    tab_opener: "Callable[[str], None] | None" = None

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._current_url = ""
        self._last_activity = time.time()
        self._last_user_gesture_mono: float | None = None
        self._suppress_user_gesture_mark = False
        self._wheel_scale_guard = False
        self._zoom_wheel_remainder = 0.0
        self._media_wide_active = False
        self._hidden_since = time.monotonic()
        self._memory_generation = 0
        self._memory_check_pending = False
        self._memory_discard_safe = False
        self._memory_last_probe = None
        self._memory_last_probe_at = None
        self._memory_check_started = 0.0
        self._memory_probe_timeouts = 0
        self._memory_timer = QTimer(self)
        self._memory_timer.setSingleShot(True)
        self._memory_timer.timeout.connect(self.maybe_freeze)
        self._memory_views.add(self)
        XWebView.memory_counters["created"] += 1
        self.destroyed.connect(XWebView._count_destroyed)
        self.setPage(self._create_page(profile))
        install_filter(self.page())
        attach_download_handler(profile)

        key = id(profile)
        refs = _DOWNLOAD_VIEWS.setdefault(key, [])
        refs.append(weakref.ref(self))

        self._focus_proxy_filter_target = None
        QTimer.singleShot(0, self, self._install_focus_proxy_filter)

        self._connect_signals()

    def setPage(self, page) -> None:
        super().setPage(page)
        if not hasattr(self, "_memory_timer"):
            return
        from src.browser.page_activity import ACTIVITY_SCRIPT
        script = QWebEngineScript()
        script.setName("mayotter-page-activity")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        script.setSourceCode(ACTIVITY_SCRIPT)
        page.scripts().insert(script)
        page.zoomFactorChanged.connect(self.zoom_changed.emit)
        page.loadStarted.connect(self._reset_memory_document)
        page.loadStarted.connect(XWebView._count_load)
        page.recommendedStateChanged.connect(self._schedule_memory_check)
        page.lifecycleStateChanged.connect(self._memory_state_changed)
        page.visibleChanged.connect(self._schedule_memory_check)
        page.loadFinished.connect(self._schedule_memory_check)
        self._reset_memory_document()

    @staticmethod
    def _count_destroyed(*_args) -> None:
        XWebView.memory_counters["destroyed"] += 1

    @staticmethod
    def _count_load(*_args) -> None:
        XWebView.memory_counters["loads"] += 1

    def _reset_memory_document(self) -> None:
        self._memory_generation += 1
        self._memory_check_pending = False
        self._memory_discard_safe = False
        self._memory_last_probe = None
        self._memory_last_probe_at = None
        self.page()._memory_upload_pending = False
        self.page()._memory_capture_active = False

    def _memory_state_changed(self, state) -> None:
        if state == QWebEnginePage.LifecycleState.Active:
            self._memory_discard_safe = False

    @classmethod
    def set_retain_hidden_pages(cls, enabled: bool) -> None:
        from shiboken6 import isValid
        cls.retain_hidden_pages = bool(enabled)
        for view in list(cls._memory_views):
            # Python 側の参照だけ残った削除済み view は対象外。
            if isValid(view):
                view._schedule_memory_check()

    def _schedule_memory_check(self, *_args) -> None:
        if self.isVisible() or self.page().isVisible():
            self._memory_timer.stop()
            return
        state = self.page().lifecycleState()
        if state == QWebEnginePage.LifecycleState.Discarded:
            return
        if (state == QWebEnginePage.LifecycleState.Frozen
                and self.page().recommendedState() == QWebEnginePage.LifecycleState.Active):
            self.resume_page()
            return
        if self._hidden_since is None:
            self._hidden_since = time.monotonic()
        delay = self.HIDDEN_GRACE_SECONDS
        if state == QWebEnginePage.LifecycleState.Frozen:
            if self.retain_hidden_pages:
                return
            delay = self.DISCARD_AFTER_SECONDS
        remaining = delay - (time.monotonic() - self._hidden_since)
        self._memory_timer.start(max(0, round(remaining * 1000)))

    def _install_focus_proxy_filter(self) -> None:
        """ホイール補正のため focusProxy（描画ウィジェット）へフィルタを設置する。

        ページ読込前に生成された WebView は focusProxy がまだ無く、生成直後の
        一度きりの設置では失敗したまま残る。読込開始/完了・表示・子ウィジェット
        追加のたびに呼び直し、実際に現れた focusProxy へ確実に設置する。
        """
        proxy = self.focusProxy()
        if proxy is None:
            return
        if proxy is getattr(self, "_focus_proxy_filter_target", None):
            return
        proxy.installEventFilter(self)
        self._focus_proxy_filter_target = proxy
        self._focus_proxy_filter_installed = True

    def touch_activity(self) -> None:
        self._last_activity = time.time()
        self.resume_page()

    def resume_page(self) -> None:
        self._memory_timer.stop()
        self._memory_generation += 1
        self._memory_check_pending = False
        self._hidden_since = None
        self._memory_discard_safe = False
        page = self.page()
        if page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)

    def seconds_since_user_gesture(self) -> float | None:
        try:
            t0 = self._last_user_gesture_mono
            if t0 is None:
                return None
            return max(0.0, time.monotonic() - float(t0))
        except Exception:
            return None

    def _retry_memory_check(self) -> None:
        if not self._memory_timer.isActive():
            self._memory_timer.start(self.MEMORY_RETRY_SECONDS * 1000)

    def _memory_in_use(self) -> bool:
        """表示中カラムの現在タブ（Dock 収納中を含む）か。owner 側の判定に委ねる。"""
        check = getattr(self.window(), "_memory_view_in_use", None)
        try:
            return bool(check(self)) if callable(check) else False
        except Exception:
            return True

    def maybe_freeze(self, now: float | None = None) -> bool:
        page = self.page()
        state = QWebEnginePage.LifecycleState
        if self.isVisible() or page.isVisible():
            if page.lifecycleState() == state.Frozen:
                self.resume_page()
            return False
        if self._memory_is_protected():
            # 非表示のまま凍結済みのページは、ワーク切替などの一時状態のために解凍しない。
            self._retry_memory_check()
            return False
        if self._memory_in_use():
            # Dock 収納中でも未読表示・即時展開のため、使用中のタブは動かしておく。
            if page.lifecycleState() == state.Frozen:
                self.resume_page()
            # 使用中でなくなった時点から猶予を数え直す。
            self._hidden_since = None
            return False
        if self._hidden_since is None:
            self._hidden_since = time.monotonic()
        age = time.monotonic() - self._hidden_since
        if age < self.HIDDEN_GRACE_SECONDS:
            self._schedule_memory_check()
            return False
        recommended = page.recommendedState()
        if recommended == state.Active:
            if page.lifecycleState() == state.Frozen:
                self.resume_page()
            return False
        if page.lifecycleState() == state.Discarded:
            return False
        if page.lifecycleState() == state.Frozen:
            if (not self.retain_hidden_pages and self._memory_discard_safe
                    and recommended == state.Discarded and age >= self.DISCARD_AFTER_SECONDS):
                page.setLifecycleState(state.Discarded)
                return page.lifecycleState() == state.Discarded
            if not self.retain_hidden_pages and age < self.DISCARD_AFTER_SECONDS:
                self._schedule_memory_check()
            return False
        from src.browser.page_activity import SAFETY_PROBE, probe_allows_freeze
        if self._memory_check_pending:
            waited = time.monotonic() - self._memory_check_started
            if waited < self.PROBE_TIMEOUT_SECONDS:
                # 応答待ち。応答が来なくても期限で戻ってこられるよう、必ず再確認を予約する。
                self._memory_timer.start(max(0, round((self.PROBE_TIMEOUT_SECONDS - waited) * 1000)))
                return False
            # 期限切れの判定は打ち切る（遅れて届いた結果は世代番号で無視する）。
            self._memory_generation += 1
            self._memory_check_pending = False
            self._memory_probe_timeouts += 1
            XWebView.memory_counters["probe_timeouts"] += 1
            fresh = (self._memory_last_probe_at is not None
                     and self._memory_last_probe_at >= self._hidden_since)
            if fresh and probe_allows_freeze(self._memory_last_probe):
                # 非表示になってからの判定で休止可能だったページだけ休止する（破棄はしない）。
                self._memory_discard_safe = False
                page.setLifecycleState(state.Frozen)
            else:
                self._retry_memory_check()
            return False
        generation = self._memory_generation
        self._memory_check_pending = True
        self._memory_check_started = time.monotonic()
        self._memory_timer.start(self.PROBE_TIMEOUT_SECONDS * 1000)

        def checked(result):
            from shiboken6 import isValid
            from src.browser.page_activity import probe_allows_discard
            if not isValid(self) or not isValid(page) or generation != self._memory_generation:
                return
            self._memory_check_pending = False
            self._memory_timer.stop()
            self._memory_last_probe = str(result or "unknown")[:80]
            self._memory_last_probe_at = time.monotonic()
            if self.isVisible() or page.isVisible():
                return
            if (not probe_allows_freeze(result) or self._memory_is_protected()
                    or self._memory_in_use()):
                # 再生中・アップロード中・判定不能などは休止せず、後で再判定する。
                self._retry_memory_check()
                return
            recommended = page.recommendedState()
            if recommended == state.Active:
                return
            # 休止は可能でも、破棄（再読み込み）は入力・送信・再生・判定不能が無いときだけ。
            discard_ok = probe_allows_discard(result)
            self._memory_discard_safe = discard_ok
            age = time.monotonic() - self._hidden_since if self._hidden_since is not None else 0
            target = state.Frozen
            if (not self.retain_hidden_pages and discard_ok and recommended == state.Discarded
                    and age >= self.DISCARD_AFTER_SECONDS):
                target = state.Discarded
            page.setLifecycleState(target)
            if target == state.Frozen and not self.retain_hidden_pages and discard_ok:
                self._schedule_memory_check()

        page.runJavaScript(SAFETY_PROBE, QWebEngineScript.ScriptWorldId.ApplicationWorld, checked)
        return False

    def freeze_now(self) -> bool:
        # 互換 caller からも安全条件と猶予を迂回しない。
        return self.maybe_freeze()

    def _memory_is_protected(self) -> bool:
        return self._memory_protection_reason() is not None

    def _memory_protection_reason(self) -> str | None:
        """休止を見送る理由（ページ自身の保護、またはワーク切替・Dock アニメーション中）。"""
        reason = self._memory_page_protection_reason()
        if reason is not None:
            return reason
        owner = self.window()
        gate = getattr(owner, "_transition_commit_gate", None)
        if getattr(owner, "_edge_dock_animating", False) or getattr(owner, "_edge_dock_switching", False):
            return "dock-transition"
        if getattr(owner, "_workspace_switching", False) or (gate is not None and gate.busy):
            return "workspace-switching"
        return None

    def _memory_page_protected(self) -> bool:
        """ページ自身または進行中の録音・添付・ダウンロードにより、休止・解放してはいけないか。"""
        return self._memory_page_protection_reason() is not None

    def _memory_page_protection_reason(self) -> str | None:
        page = self.page()
        checks = (
            ("loading", page.isLoading()),
            ("audible", page.recentlyAudible()),
            ("devtools", page.devToolsPage() is not None or page.inspectedPage() is not None),
            ("dnd-convert", getattr(self, "_dnd_converting", False)),
            ("media-wide", self._media_wide_active),
            ("attach", getattr(page, "pending_attach_files", None)
             or getattr(page, "_voice_attach_cleanup", None) is not None
             or getattr(page, "_attach_auto_mode", False)),
            ("upload", getattr(page, "_memory_upload_pending", False)),
            ("capture", getattr(page, "_memory_capture_active", False)),
        )
        for reason, hit in checks:
            if hit:
                return reason
        if any(not item.isFinished() for item in page.profile().findChildren(QWebEngineDownloadRequest)):
            return "download"
        owner = self.window()
        target = getattr(owner, "_recording_target", None)
        if target and (target.get("webview") is self or target.get("page") is page):
            return "recording-target"
        recorder = getattr(owner, "_audio_recorder", None)
        if not target and (getattr(owner, "_media_convert_worker", None) is not None
                           or (recorder is not None and recorder.is_recording)):
            return "recording"
        if MayotterPage.pending_attach_files or MayotterPage._attach_auto_mode_global:
            return "attach-global"
        return None

    _DIAG_HOSTS = ("x.com", "twitter.com", "grok.com")

    def memory_diagnostics(self) -> dict:
        """診断用の状態（状態を変更しない）。URL はホスト種別のみ、入力内容は含めない。

        hold は maybe_freeze と同じ順で「いま休止・破棄されない理由」を示す。
        """
        from src.browser.page_activity import probe_kind
        page = self.page()
        S = QWebEnginePage.LifecycleState
        state, recommended = page.lifecycleState(), page.recommendedState()
        visible = bool(self.isVisible() or page.isVisible())
        hidden_for = None
        if not visible and self._hidden_since is not None:
            hidden_for = int(time.monotonic() - self._hidden_since)
        try:
            reason = self._memory_protection_reason()
        except Exception:
            reason = "error"
        in_use = self._memory_in_use()
        probe = self._memory_last_probe
        if visible:
            hold = "visible"
        elif state == S.Discarded:
            hold = "discarded"
        elif reason is not None:
            hold = "protected:" + reason
        elif in_use:
            hold = "in-use"
        elif recommended == S.Active:
            hold = "recommended-active"
        elif state == S.Frozen:
            if self.retain_hidden_pages:
                hold = "frozen:retain-setting"
            elif self._memory_discard_safe:
                hold = "frozen:discard-pending"
            else:
                hold = "frozen:not-discard-safe"
        elif hidden_for is None or hidden_for < self.HIDDEN_GRACE_SECONDS:
            hold = "grace"
        elif self._memory_check_pending:
            hold = "probe-pending"
        elif probe is None:
            hold = "not-probed"
        else:
            hold = "probe:" + probe_kind(probe)
        host = (page.url().host() or "").lower()
        if host:
            host = next((h for h in self._DIAG_HOSTS if host == h or host.endswith("." + h)), "other")
        now = time.monotonic()
        return {
            "state": state.name, "recommended": recommended.name, "visible": visible,
            "hidden_s": hidden_for, "in_use": in_use, "protect": reason, "probe": probe,
            "probe_age_s": None if self._memory_last_probe_at is None else int(now - self._memory_last_probe_at),
            "pending_s": int(now - self._memory_check_started) if self._memory_check_pending else None,
            "probe_timeouts": self._memory_probe_timeouts,
            "discard_safe": bool(self._memory_discard_safe), "hold": hold, "host": host,
            "pid": int(page.renderProcessPid()),
        }

    def can_release_page(self) -> bool:
        """View ごと破棄しても失うものがないか（破棄済み・安全確認済みの凍結・未読込）。

        ワーク切替中にも呼ぶため、切替やアニメーションの一時状態は見ない。
        """
        if self._memory_page_protected():
            return False
        page = self.page()
        state = page.lifecycleState()
        if state == QWebEnginePage.LifecycleState.Discarded:
            return True
        if state == QWebEnginePage.LifecycleState.Frozen and self._memory_discard_safe:
            return True
        return page.renderProcessPid() == 0 and not page.isLoading() and page.url().isEmpty()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._hidden_since is None:
            self._hidden_since = time.monotonic()
        self._schedule_memory_check()

    def mousePressEvent(self, event) -> None:
        self.touch_activity()
        if not getattr(self, "_suppress_user_gesture_mark", False):
            try:
                self._last_user_gesture_mono = time.monotonic()
            except Exception:
                pass
        self.pressed.emit()
        super().mousePressEvent(event)

    def _handle_page_zoom_wheel(self, event) -> bool:
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._zoom_wheel_remainder = 0.0
            return False
        angle = event.angleDelta().y()
        pixel = event.pixelDelta().y()
        delta = float(angle) if angle else float(pixel) * 2.0
        if not delta:
            return False
        self.touch_activity()
        self._zoom_wheel_remainder += delta
        steps = int(self._zoom_wheel_remainder / 120.0)
        if steps:
            self._zoom_wheel_remainder -= steps * 120.0
            percent = max(50, min(150, round(self.zoomFactor() * 100) + 5 * steps))
            self.zoom_requested.emit(percent)
        event.accept()
        return True

    def wheelEvent(self, event) -> None:
        if self._handle_page_zoom_wheel(event):
            return
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
            self._media_status(tr('音声変換モジュールを読み込めませんでした'))
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
            from src.core.paths import APP_BASE_DIR, IS_INSTALLED, LOGS_DIR
            # Setup版は本体フォルダに書かず、保存先のlogsへ（アンインストール時に本体が残らないように）
            log_path = (Path(LOGS_DIR) if IS_INSTALLED else Path(APP_BASE_DIR)) / "last_audio_dnd.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
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
            self._media_status(tr('音声を変換中です…'))
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
        self._media_status(tr('音声を変換しています…'))
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
            self._media_status(tr('音声投稿処理を開始できませんでした'))
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
                empty_msg=tr('音声ファイルが空です'),
                webview=self,
                page=page,
            )
            self._dnd_audio_log("process_audio_source_for_post called")
        except Exception as exc:
            _clear_busy()
            self._dnd_audio_log(f"process_audio_source_for_post exception={exc!r}")
            self._media_status(str(exc) or tr('音声変換を開始できませんでした'))
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
        if obj is self.focusProxy():
            if event.type() == QEvent.Type.FocusIn:
                try:
                    self._last_user_gesture_mono = time.monotonic()
                except Exception:
                    pass
                self.pressed.emit()
            elif event.type() == QEvent.Type.Wheel and not self._wheel_scale_guard:
                if self._handle_page_zoom_wheel(event):
                    return True
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    return super().eventFilter(obj, event)
                # 実際のホイールは子の描画ウィジェット（focusProxy）が直接受けるため、
                # ここで Chrome 相当のデルタへ補正してから転送し直す
                scaled = _wheel_event_for_chrome(event)
                if scaled is not None:
                    self.touch_activity()
                    self._wheel_scale_guard = True
                    try:
                        QApplication.sendEvent(obj, scaled)
                    finally:
                        self._wheel_scale_guard = False
                    return True
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
        # QtWebEngine は既定でアニメーションスクロールが無効。通常ブラウザと同じ
        # スムーズな動きになるよう有効化する
        try:
            page.settings().setAttribute(
                QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True
            )
        except Exception:
            pass
        try:
            page.setBackgroundColor(themed_qcolor("#0b111f"))
        except Exception:
            pass
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

    def _on_url_changed(self, url: QUrl) -> None:
        url_str = url.toString()
        self._current_url = url_str
        self.url_changed.emit(url_str)

    def _on_load_started(self) -> None:
        self._install_focus_proxy_filter()
        self.loading_started.emit()

    def _on_load_finished(self, success: bool) -> None:
        self._install_focus_proxy_filter()
        self.loading_finished.emit(success)
        try:
            self._apply_x_shortcut_policy()
        except Exception:
            pass
        self._schedule_page_background()

    # 右端中央の要素から親をたどり、最初に不透明な背景色を返す（新しく出る領域は右端側）
    _PAGE_BG_JS = (
        "(function(){function bg(e){while(e){var c=getComputedStyle(e).backgroundColor;"
        r"if(c&&!/rgba\(.*,\s*0\)$/.test(c)&&c!=='transparent')return c;e=e.parentElement;}return '';}"
        "var e=document.elementFromPoint(Math.max(1,window.innerWidth-4),Math.floor(window.innerHeight/2));"
        "return bg(e)||bg(document.body)||'';})()"
    )

    # 最後に確認できたページ背景色（未取得なら None）
    page_background: QColor | None = None

    def _schedule_page_background(self) -> None:
        # 下地色は RenderWidgetHostView が安定してからでないと反映されないため、遅延を分けて掛け直す
        for ms in (0, 600, 1800):
            QTimer.singleShot(ms, self, self.apply_page_background)

    def apply_page_background(self) -> None:
        """ページの実背景色を WebEngine の下地色へ反映する。

        リサイズや再表示で新しく出る領域は下地色で塗られる。未設定だと黒になり、
        カラム境界の移動・収納の展開で黒い残像として見える。
        """
        if not self.isVisible():
            return
        try:
            self.page().runJavaScript(self._PAGE_BG_JS, self._on_page_background_probed)
        except Exception:
            pass

    def _on_page_background_probed(self, value) -> None:
        m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", str(value or ""))
        if not m:
            return
        r, g, b = (min(255, int(x)) for x in m.groups())
        self.page_background = QColor(r, g, b)
        page = self.page()
        try:
            # 同じ色の再設定は Qt に無視されることがあるため、一度ずらしてから設定する
            page.setBackgroundColor(QColor(r - 1 if r > 0 else r + 1, g, b))
            page.setBackgroundColor(QColor(r, g, b))
        except Exception:
            pass

    def childEvent(self, event) -> None:
        super().childEvent(event)
        if event.type() == QEvent.Type.ChildAdded:
            self._install_focus_proxy_filter()

    def showEvent(self, event) -> None:
        self.resume_page()
        super().showEvent(event)
        self._install_focus_proxy_filter()
        self._schedule_page_background()

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
        add(tr('戻る'), lambda: self.page().triggerAction(QWebEnginePage.WebAction.Back), back_action.isEnabled())
        add(tr('進む'), lambda: self.page().triggerAction(QWebEnginePage.WebAction.Forward), forward_action.isEnabled())
        add(tr('更新'), lambda: self.reload_page())
        menu.addSeparator()

        has_link = bool(request is not None and request.linkUrl().isValid())
        media_type = (
            request.mediaType()
            if request is not None
            else QWebEngineContextMenuRequest.MediaType.MediaTypeNone
        )
        has_image = media_type == QWebEngineContextMenuRequest.MediaType.MediaTypeImage
        has_video = (
            media_type == QWebEngineContextMenuRequest.MediaType.MediaTypeVideo
            and request is not None
            and request.mediaUrl().isValid()
        )
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
                    tr('切り取り'),
                    lambda: self.page().triggerAction(QWebEnginePage.WebAction.Cut),
                    cut_action.isEnabled() if cut_action is not None else True,
                )
            add(
                tr('コピー'),
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.Copy),
            )
        paste_action = page_action(QWebEnginePage.WebAction.Paste)
        add(
            tr('貼り付け'),
            lambda: self.page().triggerAction(QWebEnginePage.WebAction.Paste),
            paste_action.isEnabled(),
        )
        if can_select_all or True:
            sel_all = page_action(QWebEnginePage.WebAction.SelectAll)
            add(
                tr('すべて選択'),
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
                tr('新しいタブで開く'),
                _open_link_new_tab if callable(opener) else (lambda: None),
                callable(opener),
            )
            add(
                tr('リンクのURLをコピー'),
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.CopyLinkToClipboard),
            )
            add(tr('規定のブラウザで開く'), lambda url=link_url: open_in_default_browser(url))
            add(
                tr('リンク先を保存'),
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.DownloadLinkToDisk),
            )
        if not has_link:
            page_url = self.url().toString()
            if page_url:
                menu.addSeparator()
                add(tr('規定のブラウザで開く'), lambda url=page_url: open_in_default_browser(url))
        if has_image:
            menu.addSeparator()
            add(
                tr('画像をコピー'),
                lambda: self.page().triggerAction(
                    QWebEnginePage.WebAction.CopyImageToClipboard
                ),
            )
            add(
                tr('画像を保存...'),
                lambda: self.page().triggerAction(
                    QWebEnginePage.WebAction.DownloadImageToDisk
                ),
            )
        if has_video:
            menu.addSeparator()
            add(
                tr('動画を保存'),
                lambda: self.page().triggerAction(QWebEnginePage.WebAction.DownloadMediaToDisk),
            )
        if selection:
            menu.addSeparator()
            opener = self.tab_opener
            search_url = normalize_user_input_url(selection)
            add(
                tr('「{v0}」をGoogle検索', v0=selection[:20]),
                (lambda url=search_url: opener(url)) if callable(opener) else (lambda: None),
                callable(opener),
            )
        return menu, handlers

    def _extend_context_menu(self, menu: QMenu, request) -> None:
        del menu, request

    def createWindow(self, kind) -> QWebEngineView:
        owner = self
        owner_win = None
        try:
            owner_win = self.window()
        except Exception:
            owner_win = None

        class _CapturePage(QWebEnginePage):

            def __init__(self, profile, parent=None):
                super().__init__(profile, parent)
                enforce_certificate_error_rejection(self)
                self._routed = False
                self._interactive = False
                self._view_ref = None

            def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
                if not is_main_frame:
                    # 認証 popup 内の subframe は許可
                    return True if self._interactive else False
                text = url.toString() if hasattr(url, "toString") else str(url)
                text = (text or "").strip()
                if not text or text.startswith("about:") or text.startswith("data:"):
                    return True
                if self._interactive:
                    return True
                if self._routed:
                    return False

                try:
                    extracted = extract_google_redirect_target(text) or ""
                except Exception:
                    extracted = ""
                decision = extracted or text

                # 認証セッションは URL 捕捉せず実 window で継続
                try:
                    if needs_interactive_auth_window(decision) or needs_interactive_auth_window(text):
                        self._promote_interactive(text)
                        return True
                except Exception:
                    pass

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

            def _promote_interactive(self, url_text: str) -> None:
                if self._interactive or self._routed:
                    return
                self._interactive = True
                vw = self._view_ref
                if vw is None:
                    return
                try:
                    # capture 用の強制 hide / 1x1 固定を解除
                    vw._mayotter_interactive = True
                    try:
                        vw.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
                        vw.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
                    except Exception:
                        pass
                    vw.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                    try:
                        # capture 時の setFixedSize(1,1) を外す
                        vw.setMinimumSize(0, 0)
                        vw.setMaximumSize(16777215, 16777215)
                    except Exception:
                        pass
                    try:
                        vw.setWindowFlags(Qt.WindowType.Widget)
                    except Exception:
                        pass
                    try:
                        vw.setVisible(True)
                        vw.show()
                    except Exception:
                        pass
                    # Mayotter デザインのコンテナで包む
                    popup = AuthPopupWindow(vw, owner_win)
                    register_auth_popup(owner_win, popup)
                    popup.show_animated()
                except Exception:
                    # フォールバック: 従来の素の window 化
                    try:
                        vw.setMinimumSize(420, 520)
                        vw.setMaximumSize(16777215, 16777215)
                        vw.resize(520, 640)
                        vw.setWindowFlags(
                            Qt.WindowType.Window
                            | Qt.WindowType.WindowCloseButtonHint
                            | Qt.WindowType.WindowTitleHint
                        )
                        vw.setWindowTitle(tr('認証'))
                        vw.setParent(None)
                        vw.show()
                        vw.raise_()
                        vw.activateWindow()
                        register_auth_popup(owner_win, vw)
                    except Exception:
                        pass

            def _route_final(self, final_url: str) -> None:
                if self._routed or self._interactive:
                    return
                final_url = (final_url or "").strip()
                if not final_url or final_url.startswith("about:"):
                    return
                self._routed = True
                if not _nav_begin(final_url):
                    return
                try:
                    owner._open_from_new_window_request(final_url)
                finally:
                    _nav_end(final_url)

        class _CaptureView(QWebEngineView):

            def show(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().show()
                return

            def showNormal(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().showNormal()
                return

            def showFullScreen(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().showFullScreen()
                return

            def showMaximized(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().showMaximized()
                return

            def showMinimized(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().showMinimized()
                return

            def setVisible(self, visible: bool) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().setVisible(visible)
                super().setVisible(False)

            def showEvent(self, event) -> None:
                try:
                    super().showEvent(event)
                except Exception:
                    pass
                if getattr(self, "_mayotter_interactive", False):
                    return
                try:
                    self.hide()
                    self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    self.setFixedSize(1, 1)
                except Exception:
                    pass

            def raise_(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().raise_()
                return

            def activateWindow(self) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().activateWindow()
                return

            def setWindowState(self, state) -> None:
                if getattr(self, "_mayotter_interactive", False):
                    return super().setWindowState(state)
                return

            def closeEvent(self, event) -> None:
                try:
                    super().closeEvent(event)
                except Exception:
                    event.accept()

        parent = _capture_parent_for(self)
        view = _CaptureView(parent)
        view._mayotter_interactive = False
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
        page = _CapturePage(self.page().profile(), view)
        page._view_ref = view
        view.setPage(page)

        def _on_capture_load(ok, pg=page, vw=view):
            try:
                if getattr(pg, "_routed", False) or getattr(pg, "_interactive", False):
                    return
                u = pg.url().toString() if pg.url() is not None else ""
                u = (u or "").strip()
                if not u or u.startswith("about:"):
                    return
                try:
                    if needs_interactive_auth_window(u):
                        pg._promote_interactive(u)
                        return
                except Exception:
                    pass
                try:
                    if is_google_click_redirector(u):
                        return
                except Exception:
                    pass
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
                if getattr(page, "_interactive", False):
                    return
            except Exception:
                pass
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
                return
        except Exception:
            pass
        try:
            action = decide_navigation(text)
        except Exception:
            action = "in_app"
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
            # about:blank や空URLで本来の復元ロードを打ち切らない
            if cur and not cur.startswith("about:") and not cur.startswith("data:"):
                if _norm(cur) == _norm(url):
                    self._current_url = url
                    return
        except Exception:
            pass
        self._current_url = url
        try:
            page = self.page()
            if page is not None and hasattr(page, "setLifecycleState"):
                from PySide6.QtWebEngineCore import QWebEnginePage
                if hasattr(page, "lifecycleState"):
                    if page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
                        page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        except Exception:
            pass
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
