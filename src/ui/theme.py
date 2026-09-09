

from __future__ import annotations

BG = "#0f1117"
SURFACE = "#181c26"
SURFACE_RAISED = "#1d2230"
BORDER = "#2b3242"
BORDER_STRONG = "#394255"
BORDER_ACCENT = "#3d6aa8"
TEXT = "#f1f3f7"
TEXT_SECONDARY = "#aeb6c5"
TEXT_MUTED = "#7f899a"
ACCENT = "#4a7ec7"

RADIUS_SM = 6
RADIUS_MD = 8

def overlay_stylesheet() -> str:
    from pathlib import Path
    _assets = Path(__file__).resolve().parent / "assets"
    _plus = (_assets / "spin_plus.png").as_posix()
    _minus = (_assets / "spin_minus.png").as_posix()
    css = f"""
        QWidget#mayotter_settings_dialog, QWidget#download_overlay,
        QWidget#url_overlay, QWidget#text_prompt_overlay,
        QWidget#confirm_overlay, QWidget#column_add_overlay {{
            background-color: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD}px;
        }}
        QLabel {{ color: {TEXT}; background: transparent; }}
        QLabel#download_overlay_title, QLabel#settings_title {{
            color: {TEXT}; font-size: 13px; font-weight: 600;
        }}
        QLabel#download_item_name {{ color: {TEXT}; font-size: 12px; }}
        QLabel#download_item_status {{ color: {TEXT_SECONDARY}; font-size: 11px; }}
        QGroupBox {{
            color: {TEXT}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
            margin-top: 8px; padding-top: 6px; background-color: {SURFACE_RAISED};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: 8px; padding: 0 3px; color: {TEXT_SECONDARY};
        }}
        QCheckBox {{ color: {TEXT}; spacing: 6px; background: transparent; }}
        QCheckBox:disabled {{ color: {TEXT_MUTED}; }}
        QCheckBox::indicator {{
            width: 14px; height: 14px; border-radius: 3px;
            border: 1px solid {BORDER_STRONG}; background: {SURFACE};
        }}
        QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        QRadioButton {{ color: {TEXT}; spacing: 6px; background: transparent; }}
        QRadioButton:disabled {{ color: {TEXT_MUTED}; }}
        QRadioButton::indicator {{
            width: 14px; height: 14px; border-radius: 7px;
            border: 1px solid {BORDER_STRONG}; background: {SURFACE};
        }}
        QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        QSpinBox, QComboBox, QLineEdit {{
            background-color: {SURFACE}; border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px; color: {TEXT}; padding: 2px 6px;
            min-height: 22px; selection-background-color: {BORDER_ACCENT};
        }}
        QSpinBox {{
            padding-right: 18px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            subcontrol-origin: border;
            width: 16px;
            background-color: #252b38;
            border-left: 1px solid {BORDER};
        }}
        QSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: {RADIUS_SM}px;
            border-bottom: 1px solid {BORDER};
        }}
        QSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: {RADIUS_SM}px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: #323a4c;
        }}
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
            background-color: {BORDER_STRONG};
        }}
        QSpinBox::up-arrow {{
            image: url("__SPIN_PLUS__");
            width: 8px;
            height: 8px;
            margin: 1px;
        }}
        QSpinBox::down-arrow {{
            image: url("__SPIN_MINUS__");
            width: 8px;
            height: 8px;
            margin: 1px;
        }}
        QSpinBox:hover, QComboBox:hover, QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
        QPushButton {{
            background-color: {SURFACE_RAISED}; border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px; color: {TEXT}; padding: 3px 10px; min-height: 22px;
        }}
        QPushButton:hover {{ background-color: {BORDER}; border-color: {BORDER_STRONG}; }}
        QPushButton:pressed {{ background-color: {BORDER_STRONG}; }}
        QToolButton {{ background: transparent; border: none; border-radius: 4px; color: {TEXT_SECONDARY}; }}
        QToolButton:hover {{ background-color: rgba(148, 178, 230, 0.12); }}
        QToolButton#download_action_btn {{
            background-color: transparent; border: 1px solid transparent; border-radius: 5px;
        }}
        QToolButton#download_action_btn:hover {{
            background-color: rgba(148, 178, 230, 0.14); border: 1px solid transparent;
        }}
        QToolButton#download_action_btn_danger {{
            background-color: transparent; border: 1px solid transparent; border-radius: 5px;
        }}
        QToolButton#download_action_btn_danger:hover {{
            background-color: rgba(230, 100, 100, 0.16); border: 1px solid transparent;
        }}
        QListWidget {{ background-color: transparent; border: none; color: {TEXT}; outline: none; }}
        QListWidget::item {{
            background-color: {SURFACE_RAISED}; border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px; margin: 3px 2px; padding: 2px;
        }}
        QListWidget::item:selected {{ border-color: {BORDER_ACCENT}; background-color: #222836; }}
        QListWidget#download_overlay_list {{
            outline: none;
            show-decoration-selected: 0;
        }}
        QListWidget#download_overlay_list::item {{
            background-color: transparent;
            border: none;
            margin: 0px;
            padding: 0px;
            outline: none;
        }}
        QListWidget#download_overlay_list::item:selected {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QListWidget#download_overlay_list::item:hover {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QDialogButtonBox QPushButton {{ min-width: 56px; padding: 2px 8px; min-height: 22px; font-size: 11px; }}
        QToolTip {{
            background-color: {SURFACE_RAISED};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 11px;
        }}
        /* WA_NativeWindow overlay は親 QSS を継承しないことがあるため共通スクロールバーを明示 */
        QScrollBar:vertical {{
            background: #141820;
            background-color: #141820;
            width: 8px;
            border: none;
            margin: 0;
        }}
        QScrollBar::groove:vertical {{
            background: #141820;
            background-color: #141820;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: #3d4a5e;
            background-color: #3d4a5e;
            border-radius: 4px;
            min-height: 30px;
            border: none;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #5a6b84;
            background-color: #5a6b84;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; width: 0; background: transparent; border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: #141820;
            background-color: #141820;
        }}
        QScrollBar:horizontal {{
            background: #141820;
            background-color: #141820;
            height: 8px;
            border: none;
            margin: 0;
        }}
        QScrollBar::groove:horizontal {{
            background: #141820;
            background-color: #141820;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: #3d4a5e;
            background-color: #3d4a5e;
            border-radius: 4px;
            min-width: 30px;
            border: none;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: #5a6b84;
            background-color: #5a6b84;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0; height: 0; background: transparent; border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: #141820;
            background-color: #141820;
        }}
    """
    return css.replace("__SPIN_PLUS__", _plus).replace("__SPIN_MINUS__", _minus)

def dark_palette():
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    text = QColor(TEXT)
    muted = QColor(TEXT_MUTED)
    surface = QColor(SURFACE)
    bg = QColor(BG)
    raised = QColor(SURFACE_RAISED)
    accent = QColor(ACCENT)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        c = muted if group == QPalette.ColorGroup.Disabled else text
        p.setColor(group, QPalette.ColorRole.WindowText, c)
        p.setColor(group, QPalette.ColorRole.Text, c)
        p.setColor(group, QPalette.ColorRole.ButtonText, c)
        p.setColor(group, QPalette.ColorRole.Window, surface)
        p.setColor(group, QPalette.ColorRole.Base, bg)
        p.setColor(group, QPalette.ColorRole.Button, raised)
        p.setColor(group, QPalette.ColorRole.Highlight, accent)
        p.setColor(group, QPalette.ColorRole.HighlightedText, text)
    return p

def apply_overlay_theme(widget) -> None:
    try:
        from PySide6.QtCore import Qt
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    except Exception:
        pass
    try:
        widget.setStyleSheet(overlay_stylesheet())
    except Exception:
        pass
    try:
        pal = dark_palette()
        widget.setPalette(pal)
        from PySide6.QtWidgets import QAbstractButton, QLabel, QGroupBox
        for child in widget.findChildren(QAbstractButton):
            child.setPalette(pal)
            child.setAutoFillBackground(False)
        for child in widget.findChildren(QLabel):
            child.setPalette(pal)
        for child in widget.findChildren(QGroupBox):
            child.setPalette(pal)
    except Exception:
        pass

POPOVER_OPEN_MS = 170
POPOVER_CLOSE_MS = 120


def menu_dropdown_show(widget, *, duration_ms: int = POPOVER_OPEN_MS) -> None:
    try:
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Qt as _Qt
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        for attr in (
            "_mayotter_hide_anim",
            "_mayotter_show_anim",
            "_mayotter_show_group",
            "_mayotter_hide_group",
        ):
            old = getattr(widget, attr, None)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass

        # effect を外す
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            widget.setAttribute(_Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            widget.setAutoFillBackground(False)
        except Exception:
            pass
        try:
            widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        except Exception:
            pass

        flags = int(widget.windowFlags())
        is_top = bool(widget.isWindow()) or bool(
            flags & int(_Qt.WindowType.Popup | _Qt.WindowType.Tool | _Qt.WindowType.Window)
        )
        is_native_child = (not is_top) and bool(
            widget.testAttribute(_Qt.WidgetAttribute.WA_NativeWindow)
        )

        # native 子では effect 禁止
        if is_native_child:
            try:
                widget.setWindowOpacity(1.0)
            except Exception:
                pass
            widget.show()
            widget.raise_()
            try:
                widget._mayotter_fading_out = False
            except Exception:
                pass
            return

        if is_top:
            widget.setWindowOpacity(0.0)
            widget.show()
            widget.raise_()
            opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
            opacity.setDuration(int(duration_ms))
            opacity.setStartValue(0.0)
            opacity.setEndValue(1.0)
            opacity.setEasingCurve(QEasingCurve.Type.OutCubic)

            def _after():
                try:
                    widget.setWindowOpacity(1.0)
                except Exception:
                    pass
                try:
                    widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                except Exception:
                    pass
                try:
                    widget._mayotter_fading_out = False
                except Exception:
                    pass

            opacity.finished.connect(_after)
            opacity.start()
            widget._mayotter_show_anim = opacity
            widget._mayotter_show_group = opacity
            try:
                from PySide6.QtCore import QTimer as _QT
                def _ensure_opaque(w=widget):
                    try:
                        if w.isVisible() and float(w.windowOpacity()) < 0.85:
                            w.setWindowOpacity(1.0)
                    except Exception:
                        pass
                _QT.singleShot(int(duration_ms) + 40, _ensure_opaque)
            except Exception:
                pass
            return

        widget.show()
        widget.raise_()
        try:
            widget._mayotter_fading_out = False
        except Exception:
            pass
    except Exception:
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            widget.setWindowOpacity(1.0)
            widget.show()
            widget.raise_()
        except Exception:
            pass

def menu_dropdown_hide(widget, *, duration_ms: int = POPOVER_CLOSE_MS, on_finished=None) -> None:
    try:
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Qt as _Qt

        if not widget.isVisible():
            if callable(on_finished):
                try:
                    on_finished()
                except Exception:
                    pass
            return

        def _done():
            try:
                try:
                    widget.setGraphicsEffect(None)
                except Exception:
                    pass
                try:
                    widget._mayotter_allow_hide = True
                except Exception:
                    pass
                widget.hide()
                try:
                    widget.setWindowOpacity(1.0)
                except Exception:
                    pass
                try:
                    widget._mayotter_allow_hide = False
                except Exception:
                    pass
                try:
                    widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                    widget.setAttribute(_Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
                    widget.setAutoFillBackground(False)
                except Exception:
                    pass
            except Exception:
                pass
            try:
                widget._mayotter_fading_out = False
            except Exception:
                pass
            if callable(on_finished):
                try:
                    on_finished()
                except Exception:
                    pass

        for attr in (
            "_mayotter_hide_anim",
            "_mayotter_show_anim",
            "_mayotter_show_group",
            "_mayotter_hide_group",
        ):
            old = getattr(widget, attr, None)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass

        try:
            widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        try:
            widget.clearFocus()
        except Exception:
            pass

        flags = int(widget.windowFlags())
        is_top = bool(widget.isWindow()) or bool(
            flags & int(_Qt.WindowType.Popup | _Qt.WindowType.Tool | _Qt.WindowType.Window)
        )
        is_native_child = (not is_top) and bool(
            widget.testAttribute(_Qt.WidgetAttribute.WA_NativeWindow)
        )
        try:
            widget._mayotter_fading_out = True
        except Exception:
            pass

        # effect を外す
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass

        if is_native_child or not is_top:
            _done()
            return

        opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
        opacity.setDuration(int(duration_ms))
        try:
            start_op = float(widget.windowOpacity())
        except Exception:
            start_op = 1.0
        if start_op <= 0.0:
            start_op = 1.0
        opacity.setStartValue(start_op)
        opacity.setEndValue(0.0)
        opacity.setEasingCurve(QEasingCurve.Type.InCubic)
        opacity.finished.connect(_done)
        opacity.start()
        widget._mayotter_hide_anim = opacity
        widget._mayotter_hide_group = opacity
    except Exception:
        try:
            try:
                widget.setGraphicsEffect(None)
            except Exception:
                pass
            try:
                widget._mayotter_allow_hide = True
            except Exception:
                pass
            widget.hide()
            try:
                widget._mayotter_allow_hide = False
            except Exception:
                pass
        except Exception:
            pass
        if callable(on_finished):
            try:
                on_finished()
            except Exception:
                pass

def popover_show(widget, *, duration_ms: int = POPOVER_OPEN_MS) -> None:
    menu_dropdown_show(widget, duration_ms=duration_ms)

def popover_hide(widget, *, duration_ms: int = POPOVER_CLOSE_MS, on_finished=None) -> None:
    menu_dropdown_hide(widget, duration_ms=duration_ms, on_finished=on_finished)

