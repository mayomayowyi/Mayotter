

import sys

def create_window():
    from src.browser.profile_manager import ProfileManager
    from src.core.settings import SettingsManager
    from src.ui.main_window import MainWindow
    return MainWindow(ProfileManager(), SettingsManager())

def main() -> int:
    import os

    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    extra = "--disable-webgpu --disable-gpu-shader-disk-cache"
    if "--disable-webgpu" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " " + extra).strip()
    try:
        from src.browser.cdp_poc import ensure_remote_debugging_env, cdp_poc_enabled
        port = ensure_remote_debugging_env(9222)
        if cdp_poc_enabled() and port:
            print(f"[CDP_POC] remote debugging port={port} (opt-in)", flush=True)
    except Exception as exc:
        print(f"[CDP_POC] env setup skipped: {exc!r}", flush=True)

    from src.core.edition import get_edition
    from src.core.paths import DATA_DIR, ensure_directories
    from src.core.version import APP_VERSION

    ensure_directories()

    try:
        import os as _os
        if (_os.environ.get("MAYOTTER_DEBUG") or "").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            import faulthandler
            faulthandler.enable(all_threads=True)
            print("[Mayotter] faulthandler enabled (MAYOTTER_DEBUG)", flush=True)
    except Exception:
        pass

    try:
        from src.media.debug_log import media_debug, media_debug_enabled, media_log_path
        if media_debug_enabled():
            media_debug(
                "APP",
                f"startup edition={get_edition()} data={DATA_DIR} ver={APP_VERSION} log={media_log_path()}",
            )
    except Exception:
        pass

    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QToolButton,
    )
    from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize, QRectF
    from PySide6.QtGui import QPainterPath, QRegion

    from src.browser.profile_manager import ProfileManager
    from src.core.settings import SettingsManager
    from src.core.single_instance import InstanceLock
    from src.ui.main_window import MainWindow

    APP_NAME = "Mayotter"

    app = QApplication(sys.argv)

    lock = InstanceLock(DATA_DIR)
    if not lock.try_acquire():
        try:
            from src.ui.theme import apply_overlay_theme, POPOVER_OPEN_MS, POPOVER_CLOSE_MS
        except Exception:
            apply_overlay_theme = None
            POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
        try:
            from src.ui.icons import make_close_icon
        except Exception:
            make_close_icon = None
        try:
            dlg = QDialog(None)
            dlg.setObjectName("mayotter_settings_dialog")
            dlg.setWindowTitle("Mayotter")
            dlg.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
            )
            dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            dlg.setMinimumWidth(360)
            if apply_overlay_theme is not None:
                try:
                    apply_overlay_theme(dlg)
                except Exception:
                    pass

            root = QVBoxLayout(dlg)
            root.setContentsMargins(10, 8, 10, 8)
            root.setSpacing(8)
            title_row = QHBoxLayout()
            title_lbl = QLabel("Mayotter")
            title_lbl.setStyleSheet("color:#f1f3f7; font-size:14px; font-weight:600;")
            title_row.addWidget(title_lbl)
            title_row.addStretch(1)
            close_tb = QToolButton()
            if make_close_icon is not None:
                try:
                    close_tb.setIcon(make_close_icon("#93a5c4", 12))
                    close_tb.setIconSize(QSize(12, 12))
                except Exception:
                    pass
            close_tb.setFixedSize(24, 24)
            close_tb.setStyleSheet(
                "QToolButton { background:transparent; border:none; border-radius:4px; }"
                "QToolButton:hover { background:#1a2740; }"
            )
            title_row.addWidget(close_tb)
            root.addLayout(title_row)

            msg = QLabel(
                "すでに同じデータ領域でMayotterが起動しています。\n"
                f"（{DATA_DIR}）"
            )
            msg.setWordWrap(True)
            msg.setStyleSheet("color:#eaf1fb; font-size:12px;")
            root.addWidget(msg)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            ok_btn = QPushButton("OK")
            ok_btn.setMinimumWidth(56)
            btn_row.addWidget(ok_btn)
            root.addLayout(btn_row)

            def _apply_round_mask():
                try:
                    path = QPainterPath()
                    path.addRoundedRect(QRectF(0, 0, max(1, dlg.width()), max(1, dlg.height())), 10, 10)
                    dlg.setMask(QRegion(path.toFillPolygon().toPolygon()))
                except Exception:
                    pass

            dlg.adjustSize()
            _apply_round_mask()

            finished = {"done": False}

            def _finish(code=0):
                if finished["done"]:
                    return
                finished["done"] = True
                try:
                    anim = getattr(dlg, "_mayotter_fade_anim", None)
                    if anim is not None:
                        try:
                            anim.stop()
                        except Exception:
                            pass
                        dlg._mayotter_fade_anim = None
                except Exception:
                    pass
                try:
                    dlg.done(int(code))
                except Exception:
                    try:
                        dlg.close()
                    except Exception:
                        pass

            def _fade_close():
                if getattr(dlg, "_mayotter_fading_out", False):
                    return
                dlg._mayotter_fading_out = True
                try:
                    anim = QPropertyAnimation(dlg, b"windowOpacity", dlg)
                    anim.setDuration(int(POPOVER_CLOSE_MS))
                    anim.setStartValue(float(dlg.windowOpacity() or 1.0))
                    anim.setEndValue(0.0)
                    anim.setEasingCurve(QEasingCurve.Type.InCubic)
                    anim.finished.connect(lambda: _finish(0))
                    anim.start()
                    dlg._mayotter_fade_anim = anim
                    QTimer.singleShot(int(POPOVER_CLOSE_MS) + 120, lambda: _finish(0))
                except Exception:
                    _finish(0)

            ok_btn.clicked.connect(_fade_close)
            close_tb.clicked.connect(_fade_close)

            try:
                dlg.setWindowOpacity(0.0)
            except Exception:
                pass
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            try:
                anim_in = QPropertyAnimation(dlg, b"windowOpacity", dlg)
                anim_in.setDuration(int(POPOVER_OPEN_MS))
                anim_in.setStartValue(0.0)
                anim_in.setEndValue(1.0)
                anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim_in.start()
                dlg._mayotter_fade_anim = anim_in
            except Exception:
                pass
            # アニメ失敗・非対応環境でも必ず見えるようにする
            QTimer.singleShot(0, lambda: dlg.setWindowOpacity(1.0) if not getattr(dlg, "_mayotter_fading_out", False) else None)
            QTimer.singleShot(int(POPOVER_OPEN_MS) + 50, lambda: dlg.setWindowOpacity(1.0) if not getattr(dlg, "_mayotter_fading_out", False) else None)
            dlg.exec()
        except Exception as exc:
            print(f"[Mayotter] already running for data={DATA_DIR} ({exc!r})", flush=True)
        return 1
    app._mayotter_instance_lock = lock


    try:
        app.setStyleSheet(
            app.styleSheet()
            + """
            QToolTip {
              background-color: #1d2230;
              color: #f1f3f7;
              border: 1px solid #2b3242;
              border-radius: 6px;
              padding: 4px 8px;
            }
            """
        )
    except Exception:
        pass
    app.setApplicationName(APP_NAME)
    try:
        app.setApplicationVersion(APP_VERSION)
    except Exception:
        pass
    try:
        app.setOrganizationName("Mayotter")
    except Exception:
        pass

    try:
        from pathlib import Path as _Path
        from PySide6.QtGui import QIcon
        from src.core.paths import APP_BASE_DIR

        icon = QIcon()
        candidates = [
            APP_BASE_DIR / "mayotter.ico",
            APP_BASE_DIR / "packaging" / "assets" / "mayotter.ico",
            _Path(__file__).resolve().parents[2] / "packaging" / "assets" / "mayotter.ico",
        ]
        for p in candidates:
            try:
                if p.is_file():
                    icon = QIcon(str(p))
                    if not icon.isNull():
                        break
            except Exception:
                continue
        if not icon.isNull():
            app.setWindowIcon(icon)
    except Exception:
        icon = None

    settings_manager = SettingsManager()
    profile_manager = ProfileManager()
    window = MainWindow(profile_manager, settings_manager)
    try:
        if icon is not None and not icon.isNull():
            window.setWindowIcon(icon)
    except Exception:
        pass
    window.show()

    try:
        _schedule_startup_update_check(app, window, settings_manager)
    except Exception:
        pass

    code = app.exec()
    try:
        lock.release()
    except Exception:
        pass
    return code

def _show_startup_update_notice(parent, version: str) -> None:
    from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QRectF
    from PySide6.QtGui import QPainterPath, QRegion
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QWidget,
    )

    try:
        from src.ui.theme import (
            SURFACE,
            BORDER,
            TEXT,
            RADIUS_MD,
            POPOVER_OPEN_MS,
            POPOVER_CLOSE_MS,
        )
    except Exception:
        SURFACE, BORDER, TEXT = "#181c26", "#2b3242", "#f1f3f7"
        RADIUS_MD = 8
        POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120

    ver = (version or "").strip() or "?"
    dlg = QDialog(parent)
    dlg.setObjectName("mayotter_startup_update_notice")
    dlg.setModal(False)
    dlg.setWindowTitle("アップデート")
    dlg.setWindowFlags(
        Qt.WindowType.Dialog
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
    )
    dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.setStyleSheet(
        "QDialog#mayotter_startup_update_notice { background:transparent; border:none; }"
    )

    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    surface = QWidget(dlg)
    surface.setObjectName("mayotter_startup_update_surface")
    surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    surface.setStyleSheet(
        f"QWidget#mayotter_startup_update_surface {{"
        f" background:{SURFACE}; border:1px solid {BORDER};"
        f" border-radius:{RADIUS_MD}px; }}"
    )
    outer.addWidget(surface)
    v = QVBoxLayout(surface)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(10)

    title = QLabel("アップデート")
    title.setStyleSheet(
        f"color:{TEXT}; font-size:14px; font-weight:600; background:transparent;"
    )
    v.addWidget(title)

    body = QLabel(f"新しいバージョンがあります: {ver}")
    body.setWordWrap(True)
    body.setStyleSheet(f"color:{TEXT}; font-size:12px; background:transparent;")
    v.addWidget(body)

    _btn_ss = (
        "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
        " border-radius:6px; padding:6px 16px; }"
        "QToolButton:hover { background:#232a38; border:1px solid #394255; }"
        "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
    )
    row = QHBoxLayout()
    row.addStretch(1)
    check_btn = QToolButton()
    check_btn.setText("今すぐ確認")
    check_btn.setStyleSheet(_btn_ss)
    later_btn = QToolButton()
    later_btn.setText("あとで")
    later_btn.setStyleSheet(_btn_ss)
    row.addWidget(check_btn)
    row.addWidget(later_btn)
    v.addLayout(row)

    def _apply_round_mask():
        try:
            r = surface.rect()
            if r.width() <= 0 or r.height() <= 0:
                return
            path = QPainterPath()
            path.addRoundedRect(QRectF(r), float(RADIUS_MD), float(RADIUS_MD))
            surface.setMask(QRegion(path.toFillPolygon().toPolygon()))
        except Exception:
            pass

    def _finish_close(then=None):
        if getattr(dlg, "_mayotter_done", False):
            return
        dlg._mayotter_done = True
        try:
            anim = getattr(dlg, "_mayotter_fade_anim", None)
            if anim is not None:
                try:
                    anim.stop()
                except Exception:
                    pass
                dlg._mayotter_fade_anim = None
        except Exception:
            pass
        try:
            dlg.hide()
            dlg.deleteLater()
        except Exception:
            pass
        if then is not None:
            try:
                QTimer.singleShot(0, then)
            except Exception:
                pass

    def _fade_close(then=None):
        if getattr(dlg, "_mayotter_fading_out", False):
            return
        if getattr(dlg, "_mayotter_done", False):
            return
        dlg._mayotter_fading_out = True
        try:
            anim = QPropertyAnimation(dlg, b"windowOpacity", dlg)
            anim.setDuration(int(POPOVER_CLOSE_MS))
            anim.setStartValue(float(dlg.windowOpacity() or 1.0))
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.InCubic)
            anim.finished.connect(lambda: _finish_close(then))
            anim.start()
            dlg._mayotter_fade_anim = anim
            QTimer.singleShot(
                int(POPOVER_CLOSE_MS) + 80, lambda: _finish_close(then)
            )
        except Exception:
            _finish_close(then)

    def _on_later():
        _fade_close(None)

    def _on_check_now():
        def _open():
            try:
                if parent is not None and hasattr(parent, "open_update_check"):
                    parent.open_update_check()
            except Exception:
                pass

        _fade_close(_open)

    later_btn.clicked.connect(_on_later)
    check_btn.clicked.connect(_on_check_now)
    dlg.reject = lambda *a, **k: _fade_close(None)

    dlg.resize(380, 140)
    try:
        dlg.adjustSize()
    except Exception:
        pass
    _apply_round_mask()

    try:
        if parent is not None and hasattr(parent, "frameGeometry"):
            geo = parent.frameGeometry()
            dlg.adjustSize()
            dg = dlg.frameGeometry()
            dlg.move(
                geo.center().x() - dg.width() // 2,
                geo.center().y() - dg.height() // 2,
            )
    except Exception:
        pass

    try:
        dlg.setWindowOpacity(0.0)
    except Exception:
        pass
    dlg.show()
    dlg.raise_()
    try:
        anim_in = QPropertyAnimation(dlg, b"windowOpacity", dlg)
        anim_in.setDuration(int(POPOVER_OPEN_MS))
        anim_in.setStartValue(0.0)
        anim_in.setEndValue(1.0)
        anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_in.start()
        dlg._mayotter_fade_anim = anim_in
    except Exception:
        try:
            dlg.setWindowOpacity(1.0)
        except Exception:
            pass

    try:
        parent._mayotter_startup_update_dlg = dlg
    except Exception:
        pass

def _schedule_startup_update_check(app, window, settings_manager) -> None:
    from PySide6.QtCore import QTimer

    def _run():
        try:
            if settings_manager is None:
                return
            if not getattr(settings_manager, "get_auto_check_updates", lambda: False)():
                return
            from src.core.updater import check_for_update

            repo = ""
            if hasattr(settings_manager, "get_github_repo"):
                repo = settings_manager.get_github_repo()
            info = check_for_update(github_repo=repo)
            if info is None:
                return
            _show_startup_update_notice(window, getattr(info, "version", "") or "")
        except Exception:
            pass

    QTimer.singleShot(2500, _run)

if __name__ == "__main__":
    sys.exit(main())
