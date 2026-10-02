from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from src.ui.icons import make_close_icon, _COLOR_TEXT_SECONDARY


try:
    from src.ui.theme import (
        apply_overlay_theme,
        POPOVER_OPEN_MS,
        POPOVER_CLOSE_MS,
        SURFACE,
        BORDER,
        TEXT,
        TEXT_MUTED,
        TEXT_SECONDARY,
        RADIUS_MD,
    )
except Exception:
    POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
    SURFACE, BORDER, TEXT = "#181c26", "#2b3242", "#f1f3f7"
    TEXT_MUTED, TEXT_SECONDARY, RADIUS_MD = "#7f899a", "#aeb6c5", 8

    def apply_overlay_theme(w):
        pass


class ExternalSiteConfirmDialog(QDialog):
    choiceMade = Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = (url or "").strip()
        self._finished = False
        self._choice = "cancel"
        self._surface: QWidget | None = None
        self._mayotter_done = False
        self._mayotter_fading_out = False
        self._mayotter_fade_anim = None

        self.setObjectName("mayotter_external_confirm_dialog")
        self.setModal(True)
        self.setWindowTitle("外部サイト")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            from src.ui.window_polish import prepare_popup_chrome
            self._native_rounding = prepare_popup_chrome(
                self, background=SURFACE, border_color=BORDER, corner="round"
            )
        except Exception:
            self._native_rounding = False
        if not self._native_rounding:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        try:
            apply_overlay_theme(self)
        except Exception:
            pass
        self.setStyleSheet(
            f"QDialog#mayotter_external_confirm_dialog {{"
            f" background:{SURFACE if self._native_rounding else 'transparent'}; border:none; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        surface = QWidget(self)
        self._surface = surface
        surface.setObjectName("mayotter_external_confirm_surface")
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        surface.setStyleSheet(
            f"QWidget#mayotter_external_confirm_surface {{"
            f" background:{SURFACE};"
            f" border:{'none' if self._native_rounding else f'1px solid {BORDER}'};"
            f" border-radius:{0 if self._native_rounding else RADIUS_MD}px; }}"
        )
        outer.addWidget(surface)
        v = QVBoxLayout(surface)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel("外部サイト")
        title_lbl.setStyleSheet(
            f"color:{TEXT}; font-size:14px; font-weight:600; background:transparent;"
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        close_tb = QToolButton()
        try:
            close_tb.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 12))
            close_tb.setIconSize(QSize(12, 12))
        except Exception:
            close_tb.setText("×")
        close_tb.setFixedSize(24, 24)
        close_tb.setStyleSheet(
            "QToolButton { background:transparent; border:none; border-radius:4px; }"
            "QToolButton:hover { background:#1a2740; }"
        )
        title_row.addWidget(close_tb)
        v.addLayout(title_row)

        body = QLabel("外部サイトを開こうとしています")
        body.setStyleSheet(
            f"color:{TEXT}; font-size:12px; background:transparent;"
        )
        body.setWordWrap(True)
        v.addWidget(body)

        url_lbl = QLabel(self._url)
        url_lbl.setWordWrap(True)
        url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        url_lbl.setStyleSheet(
            f"color:{TEXT_SECONDARY}; font-size:11px; background:transparent;"
        )
        v.addWidget(url_lbl)

        note = QLabel("このサイトはXではありません。")
        note.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:11px; background:transparent;"
        )
        v.addWidget(note)

        _btn_ss = (
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:6px 12px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 6, 0, 0)
        btn_row.setSpacing(6)
        btn_row.addStretch(1)
        btn_cancel = QToolButton()
        btn_cancel.setText("キャンセル")
        btn_cancel.setStyleSheet(_btn_ss)
        btn_browser = QToolButton()
        btn_browser.setText("既定ブラウザで開く")
        btn_browser.setStyleSheet(_btn_ss)
        btn_app = QToolButton()
        btn_app.setText("Mayotter内で開く")
        btn_app.setStyleSheet(_btn_ss)
        btn_row.addWidget(btn_browser)
        btn_row.addWidget(btn_app)
        btn_row.addWidget(btn_cancel)
        v.addLayout(btn_row)

        close_tb.clicked.connect(lambda: self._fade_close("cancel"))
        btn_cancel.clicked.connect(lambda: self._fade_close("cancel"))
        btn_browser.clicked.connect(lambda: self._fade_close("browser"))
        btn_app.clicked.connect(lambda: self._fade_close("app"))

        self.resize(420, 200)
        try:
            self.adjustSize()
        except Exception:
            pass
        self._apply_round_mask()

    def show_with_fade(self) -> None:
        try:
            self.setWindowOpacity(0.0)
        except Exception:
            pass
        self.show()
        self.raise_()
        try:
            anim_in = QPropertyAnimation(self, b"windowOpacity", self)
            anim_in.setDuration(int(POPOVER_OPEN_MS))
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim_in.start()
            self._mayotter_fade_anim = anim_in
        except Exception:
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass

    def reject(self) -> None:
        self._fade_close("cancel")

    def accept(self) -> None:
        self._fade_close(self._choice or "cancel")

    def _apply_round_mask(self) -> None:
        # 角は QSS の描画に任せる。QRegion のマスクは 1bit で角がギザギザになる。
        try:
            surface = self._surface
            if surface is not None:
                surface.clearMask()
            self.clearMask()
        except Exception:
            pass

    def _finish_close(self) -> None:
        if self._mayotter_done:
            return
        self._mayotter_done = True
        try:
            anim = self._mayotter_fade_anim
            if anim is not None:
                try:
                    anim.stop()
                except Exception:
                    pass
                self._mayotter_fade_anim = None
        except Exception:
            pass
        try:
            self.hide()
            self.deleteLater()
        except Exception:
            pass

    def _apply_choice(self, choice: str) -> None:
        if self._finished:
            return
        self._finished = True
        self._choice = choice
        if choice in ("browser", "app"):
            self.choiceMade.emit(choice)

    def _fade_close(self, choice: str) -> None:
        if self._mayotter_fading_out:
            return
        if self._mayotter_done:
            return
        self._mayotter_fading_out = True
        self._apply_choice(choice)
        try:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(int(POPOVER_CLOSE_MS))
            anim.setStartValue(float(self.windowOpacity() or 1.0))
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.InCubic)
            anim.finished.connect(self._finish_close)
            anim.start()
            self._mayotter_fade_anim = anim
            QTimer.singleShot(int(POPOVER_CLOSE_MS) + 80, self._finish_close)
        except Exception:
            self._finish_close()

    def refresh_theme(self) -> None:
        try:
            from src.ui.theme import color
            for btn in self.findChildren(QToolButton):
                if btn.objectName() == "close_tb":
                    btn.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 12))
                    btn.setIconSize(QSize(12, 12))
                    break

            self.setStyleSheet(
                f"QDialog#mayotter_external_confirm_dialog {{"
                f" background:{color('SURFACE') if getattr(self, '_native_rounding', False) else 'transparent'}; border:none; }}"
            )
            if hasattr(self, '_surface') and self._surface:
                self._surface.setStyleSheet(
                    "QWidget#mayotter_external_confirm_surface {"
                    f" background:{color('SURFACE')};"
                    f" border:{'none' if getattr(self, '_native_rounding', False) else '1px solid ' + color('BORDER')};"
                    f" border-radius:{0 if getattr(self, '_native_rounding', False) else 8}px; }}"
                )
            for btn in self.findChildren(QToolButton):
                if btn.objectName() == "close_tb":
                    btn.setStyleSheet(
                        "QToolButton { background:transparent; border:none; border-radius:4px; }"
                        f"QToolButton:hover {{ background:{color('SURFACE_HOVER')}; }}"
                    )
                    btn.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 12))
                    btn.setIconSize(QSize(12, 12))
                    break
            for lbl in self.findChildren(QLabel):
                if lbl.text() == "外部サイト":
                    lbl.setStyleSheet(f"color:{color('TEXT')}; font-size:14px; font-weight:600; background:transparent;")
                elif lbl.text() == "外部サイトを開こうとしています":
                    lbl.setStyleSheet(f"color:{color('TEXT')}; font-size:12px; background:transparent;")
                elif lbl.text() == self._url:
                    lbl.setStyleSheet(f"color:{color('TEXT_SECONDARY')}; font-size:11px; background:transparent;")
                elif lbl.text() == "このサイトはXではありません。":
                    lbl.setStyleSheet(f"color:{color('TEXT_MUTED')}; font-size:11px; background:transparent;")
            for btn in self.findChildren(QToolButton):
                if btn.objectName() in ("btn_cancel", "btn_browser", "btn_app"):
                    btn.setStyleSheet(
                        f"QToolButton {{ color:{color('TEXT')}; background:{color('SURFACE_HOVER')}; border:1px solid {color('BORDER')};"
                        " border-radius:6px; padding:6px 12px; }"
                        f"QToolButton:hover {{ background:{color('SURFACE_HOVER')}; border:1px solid {color('BORDER_STRONG')}; }}"
                        f"QToolButton:pressed {{ background:{color('SURFACE_SUNKEN')}; border:1px solid {color('BORDER')}; }}"
                    )
            self.update()
        except Exception:
            pass
