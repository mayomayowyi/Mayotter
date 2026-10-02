

from __future__ import annotations

import re

import ctypes
import sys
import time

from PySide6.QtWidgets import (
    QSpinBox,
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QToolButton,
    QLabel,
    QMenu,
)
from PySide6.QtCore import (
    Qt,
    QEvent,
    QTimer,
    QPropertyAnimation,
    QVariantAnimation,
    QEasingCurve,
    QPoint,
    QRect,
    QSize,
    Signal,
    QAbstractNativeEventFilter,
)
from PySide6.QtGui import (
    QCursor,
    QAction,
    QGuiApplication,
    QRegion,
    QColor,
    QPainter,
    QPixmap,
    QKeySequence,
    QShortcut,
)

from src.browser.profile_manager import ProfileManager
from src.ui.account_column import AccountColumn
from src.browser.webview import XWebView
from src.ui.url_overlay import UrlOverlay, TextPromptOverlay, ConfirmOverlay, DownloadIconButton, DownloadOverlay, ColumnAddOverlay, AccountComboBox
from src.ui.icons import (
    make_settings_icon,
    make_close_icon, make_edit_icon, install_close_icon,
    make_edge_dock_icon,
    make_minimize_icon,
    make_maximize_icon,
    make_restore_icon,
    make_stop_icon,
    make_mic_icon,
    make_chevron_left_icon,
    make_plus_icon,
    _COLOR_SECONDARY,
    _COLOR_TEXT,
    _COLOR_ACCENT_SOFT,
    _COLOR_DANGER,
    _COLOR_TEXT_SECONDARY,
)
from src.core.models import GROK_HOME_URL, Column
from src.ui.edge_dock import EdgeDetector, EdgeAnimator, PanelState
from src.ui.transition_commit_gate import TransitionCommitGate
from src.ui.theme import themed_qcolor, color as theme_color, get_theme_id

_WM_NCHITTEST = 0x0084
_WM_NCLBUTTONDBLCLK = 0x00A3
_WM_WINDOWPOSCHANGING = 0x0046
_SWP_NOMOVE = 0x0002
_WM_ENTERSIZEMOVE = 0x0231
_WM_EXITSIZEMOVE = 0x0232
_HTLEFT = 10
_HTTRANSPARENT = -1
_HTRIGHT = 11
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17
_HTCLIENT = 1

_RESIZE_MARGIN = 6
_RESIZE_CORNER = 12

_QT_EDGES_FOR_HT_CODE: dict[int, "Qt.Edges"] = {
    _HTLEFT: Qt.Edge.LeftEdge,
    _HTRIGHT: Qt.Edge.RightEdge,
    _HTTOP: Qt.Edge.TopEdge,
    _HTBOTTOM: Qt.Edge.BottomEdge,
    _HTTOPLEFT: Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
    _HTTOPRIGHT: Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    _HTBOTTOMLEFT: Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    _HTBOTTOMRIGHT: Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
}

_TAB_TITLE_ELIDE_PX = 72

class NoWheelSpinBox(QSpinBox):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QAbstractSpinBox
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)

    def wheelEvent(self, event) -> None:
        event.ignore()

def _dispose_widget_no_toplevel(w) -> None:
    if w is None:
        return
    try:
        w.hide()
    except Exception:
        pass
    try:
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    except Exception:
        pass
    try:
        w.deleteLater()
    except Exception:
        pass

class _ServiceMenu(QFrame):

    rename_requested = Signal(dict)
    delete_requested = Signal(dict)
    new_account_requested = Signal()

    def __init__(self, parent=None) -> None:

        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("service_menu")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            from src.ui.theme import overlay_stylesheet, SURFACE, BORDER, TEXT, RADIUS_MD
            self.setStyleSheet(
                overlay_stylesheet()
                + f"""
                QFrame#service_menu {{
                    background-color: {SURFACE};
                    border: 1px solid {BORDER};
                    border-radius: {RADIUS_MD}px;
                }}
                QFrame#service_menu[mayotterNativeRounded="true"] {{
                    border-radius: 0px;
                }}
                QLabel#service_menu_label {{ color: {TEXT}; }}
                QPushButton#service_menu_add_btn {{
                    color: {TEXT};
                    text-align: left;
                    padding: 4px 8px;
                    border: none;
                    border-radius: 4px;
                    background: transparent;
                    font-size: 12px;
                    min-height: 22px;
                }}
                QPushButton#service_menu_add_btn:hover {{
                    background: rgba(148,178,230,0.12);
                    color: {TEXT};
                }}
                """
            )
        except Exception:
            pass
        self._corner_radius = 8

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        add_btn = QPushButton("+ 新規追加")
        add_btn.setObjectName("service_menu_add_btn")
        add_btn.clicked.connect(lambda *_: self.new_account_requested.emit())
        layout.addWidget(add_btn)

        self._profile_layout = QVBoxLayout()
        self._profile_layout.setSpacing(0)
        self._profile_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._profile_layout)

        self._rows: list[QWidget] = []
        self._profile_accounts: list[dict] = []

    def setVisible(self, visible: bool) -> None:
        if (not visible) and self.isVisible() and not getattr(self, "_mayotter_allow_hide", False):
            if getattr(self, "_mayotter_fading_out", False):
                return
            self._mayotter_fading_out = True
            try:
                from src.ui.theme import menu_dropdown_hide

                def _after():
                    self._mayotter_fading_out = False
                    self._mayotter_allow_hide = True
                    try:
                        super(_ServiceMenu, self).setVisible(False)
                    finally:
                        self._mayotter_allow_hide = False

                menu_dropdown_hide(self, on_finished=_after)
            except Exception:
                self._mayotter_fading_out = False
                self._mayotter_allow_hide = True
                try:
                    super().setVisible(False)
                finally:
                    self._mayotter_allow_hide = False
            return
        super().setVisible(visible)

    def hide(self) -> None:
        self.setVisible(False)

    def hideEvent(self, event) -> None:
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        cb = getattr(self, "_on_auto_closed", None)
        if callable(cb):
            try:
                cb()
            except Exception:
                pass
        try:
            super().hideEvent(event)
        except Exception:
            pass

    def eventFilter(self, obj, event) -> bool:
        et = event.type()
        if not self.isVisible() or getattr(self, "_mayotter_fading_out", False):
            return False
        if et == QEvent.Type.KeyPress:
            try:
                if event.key() == Qt.Key.Key_Escape:
                    self.setVisible(False)
                    return True
            except Exception:
                pass
        elif et == QEvent.Type.MouseButtonPress:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    gp = event.globalPosition().toPoint()
                    if not self.rect().contains(self.mapFromGlobal(gp)):

                        self.setVisible(False)
            except Exception:
                pass
        return False

    def _apply_service_menu_mask(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        try:
            from src.ui.window_polish import prepare_popup_chrome, native_rounding_available
            if native_rounding_available():
                self.clearMask()
                if prepare_popup_chrome(self, corner="round"):
                    return
        except Exception:
            pass
        try:
            from src.ui.url_overlay import rounded_overlay_mask
            self.setMask(rounded_overlay_mask(w, h, self._corner_radius))
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_service_menu_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_service_menu_mask()

    def add_profile(self, account: dict) -> None:
        row = QWidget()
        row.setObjectName("service_menu_row")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 3, 4, 3)
        row_layout.setSpacing(2)

        name = account.get("display_name") or account.get("account_id", "")[:8]
        label = QLabel(name)
        label.setObjectName("service_menu_label")
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row_layout.addWidget(label)

        edit_btn = QToolButton()
        edit_btn.setObjectName("service_menu_edit_btn")
        edit_btn.setText("")
        edit_btn.setIcon(make_edit_icon(_COLOR_TEXT_SECONDARY, 12))
        edit_btn.setIconSize(QSize(12, 12))
        edit_btn.setFixedSize(20, 20)
        edit_btn.setToolTip("名前を変更")
        edit_btn.clicked.connect(lambda checked=False, a=account: self.rename_requested.emit(a))
        row_layout.addWidget(edit_btn)

        del_btn = QToolButton()
        del_btn.setObjectName("service_menu_del_btn")
        del_btn.setText("")
        del_btn.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 10))
        del_btn.setIconSize(QSize(10, 10))
        del_btn.setFixedSize(20, 20)
        del_btn.setToolTip("削除")
        del_btn.clicked.connect(lambda checked=False, a=account: self.delete_requested.emit(a))
        row_layout.addWidget(del_btn)

        row.mousePressEvent = lambda e, a=account: (
            self._on_row_clicked(a) if e.button() == Qt.MouseButton.LeftButton else
            self._on_row_right_click(e, a) if e.button() == Qt.MouseButton.RightButton else None
        )

        self._rows.append(row)
        self._profile_accounts.append(account)
        self._profile_layout.addWidget(row)

    def refresh_theme(self) -> None:
        for btn in self.findChildren(QToolButton):
            try:
                if btn.objectName() == "service_menu_edit_btn":
                    btn.setIcon(make_edit_icon(_COLOR_TEXT_SECONDARY, 12))
                elif btn.objectName() == "service_menu_del_btn":
                    btn.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 10))
            except Exception:
                pass
        self.update()

    def _on_row_clicked(self, account: dict) -> None:
        self.hide()
        parent = self.parentWidget()
        if parent and hasattr(parent, '_restore_account'):
            parent._restore_account(account["account_id"], account.get("grok", False))

    def _on_row_right_click(self, event, account: dict) -> None:
        ctx = QMenu(self)
        try:
            parent = self.parentWidget()
            while parent is not None and not hasattr(parent, "_style_mayotter_menu"):
                parent = parent.parentWidget()
            if parent is not None:
                parent._style_mayotter_menu(ctx)
            else:
                ctx.setStyleSheet(
                    "QMenu { background:#0d1524; color:#eaf1fb; border:1px solid #2f517d; border-radius:8px; }"
                    "QMenu::item { color:#eaf1fb; padding:6px 28px 6px 14px; }"
                    "QMenu::item:selected { background:rgba(148,178,230,0.18); color:#fff; }"
                )
        except Exception:
            pass
        rename_act = ctx.addAction("名前を変更")
        delete_act = ctx.addAction("削除")
        chosen = ctx.exec(self.mapToGlobal(event.pos()))
        if chosen == rename_act:
            self.rename_requested.emit(account)
        elif chosen == delete_act:
            self.delete_requested.emit(account)

class _TabChip(QWidget):

    selected = Signal()
    close_requested = Signal()
    context_requested = Signal(object)
    drag_started = Signal()
    drag_moving = Signal(float)
    drag_finished = Signal(float)

    DRAG_START_PX = 6

    def __init__(self, title: str, index: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tab_chip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._index = index
        self._is_active = False
        self._press_x = 0.0
        self._press_global_x = 0.0
        self._press_active = False
        self._dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(4)

        self.title_label = QLabel()
        self.title_label.setObjectName("tab_chip_title")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.title_label)
        self.set_title(title)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("tab_close_btn")
        self.close_btn.setFixedSize(16, 16)
        install_close_icon(self.close_btn, 10)
        self.close_btn.clicked.connect(self.close_requested)
        layout.addWidget(self.close_btn)

        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(_TAB_TITLE_ELIDE_PX + 40)
        self.setMinimumHeight(26)
        try:
            self.setWindowFlags(Qt.WindowType.Widget)
        except Exception:
            pass
        self._badge = QLabel(self)
        self._badge.setObjectName("tab_badge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.hide()

    def showEvent(self, event) -> None:
        if self.parent() is None or self.isWindow():
            try:
                self.hide()
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            except Exception:
                pass
            event.ignore()
            return
        super().showEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_x = event.globalPosition().x()
            self._press_global_x = event.globalPosition().x()
            self._press_active = True
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_active and not self._dragging:
            dx = abs(event.globalPosition().x() - self._press_x)
            if dx > self.DRAG_START_PX:
                self._dragging = True
                self.grabMouse()
                self.drag_started.emit()
        if self._dragging:
            self.drag_moving.emit(event.globalPosition().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                self._dragging = False
                self._press_active = False
                self.releaseMouse()
                self.drag_finished.emit(event.globalPosition().x())
            elif self._press_active:
                self._press_active = False
                self.selected.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.context_requested.emit(event.globalPos())
        event.accept()

    def set_active(self, active: bool) -> None:
        if active != self._is_active:
            self._is_active = active
            self.setProperty("checked", active)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def set_title(self, title: str) -> None:
        self._raw_title = title
        fm = self.title_label.fontMetrics()
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, _TAB_TITLE_ELIDE_PX)
        self.title_label.setText(elided)

    def set_badge(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self._badge.hide()
            return
        display = text if text != "•" else "●"
        self._badge.setText(display)
        self._badge.adjustSize()
        if display == "●":
            self._badge.setFixedSize(8, 8)
        else:
            self._badge.setFixedSize(max(12, self._badge.sizeHint().width() + 2), 12)
        self._position_badge()
        self._badge.show()
        self._badge.raise_()

    def _position_badge(self) -> None:
        if not hasattr(self, "_badge") or self._badge is None:
            return
        if self._badge.isHidden():
            return
        x = 3
        y = 2
        self._badge.move(x, y)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        try:
            self._position_badge()
        except Exception:
            pass

    def refresh_theme(self) -> None:
        self.setStyleSheet(
            f"QWidget#tab_chip {{"
            f" background-color: {theme_color('SURFACE')};"
            f" border: none;"
            f" border-right: 1px solid {theme_color('BORDER')};"
            f" border-top-left-radius: 7px;"
            f" border-top-right-radius: 7px;"
            f" color: {theme_color('TEXT_SECONDARY')};"
            f" padding: 4px 10px;"
            f" min-width: 60px;"
            f" max-width: 112px;"
            f"}}"
            f"QWidget#tab_chip QLabel#tab_chip_title {{"
            f" color: {theme_color('TEXT_SECONDARY')};"
            f" background: transparent;"
            f"}}"
            f"QWidget#tab_chip[checked=\"true\"] {{"
            f" background-color: {theme_color('SURFACE_HOVER')};"
            f" color: {theme_color('TEXT')};"
            f"}}"
            f"QWidget#tab_chip[checked=\"true\"] QLabel#tab_chip_title {{"
            f" color: {theme_color('TEXT')};"
            f"}}"
            f"QWidget#tab_chip:hover {{"
            f" background-color: {theme_color('SURFACE_HOVER')};"
            f"}}"
            f"QWidget#tab_chip:hover QLabel#tab_chip_title {{"
            f" color: {theme_color('TEXT')};"
            f"}}"
            f"#tab_close_btn {{"
            f" background-color: transparent;"
            f" border: none;"
            f" color: {theme_color('ICON')};"
            f" border-radius: 3px;"
            f" padding: 0;"
            f"}}"
            f"#tab_close_btn:hover {{"
            f" background-color: rgba(230, 100, 100, 0.2);"
            f" color: {theme_color('DANGER')};"
            f"}}"
        )
        self.update()

class _TabStrip(QWidget):

    tab_selected = Signal(int)
    tab_close_requested = Signal(int)
    tab_context_requested = Signal(int, object)
    tab_reorder_requested = Signal(int, int)
    new_tab_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tab_strip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self._chips: list[_TabChip] = []
        self._drag_source_index: int | None = None
        self._drag_armed = False
        self._drag_press_x = 0.0
        self._drag_placeholder: QWidget | None = None
        self._drag_insert_index: int | None = None
        self._drag_preview: QWidget | None = None
        self._drag_slots: dict[int, tuple[float, float]] | None = None

        self._add_gap = QWidget(self)
        self._add_gap.setFixedWidth(5)
        self._add_gap.setFixedHeight(1)
        self._add_gap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._add_btn = QToolButton(self)
        self._add_btn.setObjectName("tab_add_btn")
        self._add_btn.setText("")
        self._add_btn.setIcon(make_plus_icon(_COLOR_SECONDARY, 10))
        self._add_btn.setIconSize(QSize(10, 10))
        self._add_btn.setToolTip("新しいタブ")
        self._add_btn.setFixedSize(18, 18)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._add_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._add_btn.setAutoRaise(False)
        self._add_btn.setStyleSheet(
            "QToolButton#tab_add_btn {"
            " background-color:#181c26; border:1px solid #2b3242;"
            " border-radius:9px; padding:0; margin:0;"
            "}"
            "QToolButton#tab_add_btn:hover {"
            " background-color:#232a38; border:1px solid #3d6a9e;"
            "}"
            "QToolButton#tab_add_btn:pressed {"
            " background-color:#1a2030; border:1px solid #2b3242;"
            "}"
        )
        try:
            self._add_btn.clearMask()
        except Exception:
            pass
        self._add_btn.clicked.connect(self.new_tab_requested.emit)
        self._layout.addWidget(self._add_gap)
        self._layout.addWidget(self._add_btn)
        self._layout.addStretch(1)

        self._drop_line = QWidget(self)
        self._drop_line.setObjectName("tab_drop_line")
        self._drop_line.setFixedWidth(2)
        self._drop_line.hide()

    def refresh_theme(self) -> None:
        self._add_btn.setIcon(make_plus_icon(_COLOR_SECONDARY, 10))
        self._add_btn.setStyleSheet(
            "QToolButton#tab_add_btn {"
            f" background-color:{theme_color('SURFACE')}; border:1px solid {theme_color('BORDER')};"
            " border-radius:9px; padding:0; margin:0;"
            "}"
            f"QToolButton#tab_add_btn:hover {{"
            f" background-color:{theme_color('SURFACE_HOVER')}; border:1px solid {theme_color('BORDER_ACCENT')};"
            "}"
            f"QToolButton#tab_add_btn:pressed {{"
            f" background-color:{theme_color('SURFACE_SUNKEN')}; border:1px solid {theme_color('BORDER')};"
            "}"
        )
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 辺の切替などで幅が後から変わると、新しく出たチップが描かれないまま残ることがある
        for chip in self._chips:
            chip.update()
        self.update()

    def rebuild(self, tabs: list[str], current: int = 0, badges: list | None = None) -> None:
        badges = list(badges or [])
        while len(badges) < len(tabs):
            badges.append("")

        if len(self._chips) == len(tabs):
            all_match = True
            for i, (chip, title) in enumerate(zip(self._chips, tabs)):
                raw = getattr(chip, "_raw_title", None)
                if raw is None:
                    raw = chip.title_label.text()
                if raw != title or chip._index != i:
                    all_match = False
                    break
            if all_match:
                for i, chip in enumerate(self._chips):
                    chip.set_active(i == current)
                    try:
                        chip.set_badge(badges[i] if i < len(badges) else "")
                    except Exception:
                        pass
                self._normalize_add_btn()
                return

        for chip in self._chips:
            self._layout.removeWidget(chip)
            _dispose_widget_no_toplevel(chip)
        self._chips.clear()

        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is None:
                continue
            if w is self._add_btn:
                continue
            if w is getattr(self, "_drop_line", None):
                continue
            if w in self._chips:
                continue
            try:
                if w is not self._add_btn and w is not self._drop_line:
                    if w.objectName() in ("tab_drag_placeholder", "tab_drag_preview"):
                        _dispose_widget_no_toplevel(w)
            except Exception:
                pass

        for i, title in enumerate(tabs):
            chip = _TabChip(title, i, self)
            chip._raw_title = title
            chip.selected.connect(lambda idx=i: self._on_chip_selected(idx))
            chip.close_requested.connect(lambda idx=i: self._on_chip_close(idx))
            chip.context_requested.connect(
                lambda pos, idx=i: self.tab_context_requested.emit(idx, pos)
            )
            chip.drag_started.connect(lambda idx=i: self._on_drag_start(idx))
            chip.drag_moving.connect(self._on_drag_moving)
            chip.drag_finished.connect(self._on_chip_dropped)
            self._chips.append(chip)
            self._layout.addWidget(chip)

        gap = getattr(self, "_add_gap", None)
        if gap is not None:
            self._layout.addWidget(gap)
        self._layout.addWidget(self._add_btn)
        self._layout.addStretch(1)
        self._normalize_add_btn()

        for i, chip in enumerate(self._chips):
            chip.set_active(i == current)
            try:
                chip.set_badge(badges[i] if i < len(badges) else "")
            except Exception:
                pass

    def _normalize_add_btn(self) -> None:
        btn = getattr(self, "_add_btn", None)
        if btn is None:
            return
        try:
            btn.setFixedSize(18, 18)
            btn.setMinimumSize(18, 18)
            btn.setMaximumSize(18, 18)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            try:
                btn.clearMask()
            except Exception:
                pass
            btn.setVisible(True)
            btn.raise_()
        except Exception:
            pass

    def _on_chip_selected(self, index: int) -> None:
        self.tab_selected.emit(index)
        for i, chip in enumerate(self._chips):
            chip.set_active(i == index)

    def _on_chip_close(self, index: int) -> None:
        self.tab_close_requested.emit(index)

    def _on_drag_start(self, index: int) -> None:
        self._drag_source_index = index
        self._drag_insert_index = index
        chip = self._chips[index]

        slots: dict[int, tuple[float, float]] = {}
        for i, item in enumerate(self._chips):
            try:
                slots[i] = (
                    float(item.mapToGlobal(item.rect().topLeft()).x()),
                    float(max(1, item.width())),
                )
            except Exception:
                continue
        self._drag_slots = slots

        layout_index = self._layout.indexOf(chip)
        if layout_index >= 0:
            self._layout.removeWidget(chip)
        chip.setVisible(False)
        chip.move(-10000, -10000)

        sz = chip.size()
        if sz.width() < 8 or sz.height() < 8:
            sz = chip.sizeHint()

        self._clear_drag_placeholder()
        ph = QWidget(self)
        ph.setObjectName("tab_drag_placeholder")
        ph.setFixedSize(sz)
        ph.setStyleSheet(
            "QWidget#tab_drag_placeholder {"
            "  background: #0f1117;"
            "  border: none;"
            "  border-left: 2px solid #2f517d;"
            "}"
        )
        self._drag_placeholder = ph
        if layout_index >= 0:
            self._layout.insertWidget(layout_index, ph)
        else:
            self._layout.insertWidget(max(0, self._layout.count() - 1), ph)

        self._clear_drag_preview()
        from PySide6.QtWidgets import QLabel
        prev = QLabel(chip.title_label.text(), self)
        prev.setObjectName("tab_drag_preview")
        prev.setFixedSize(sz)
        prev.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        prev.setStyleSheet(
            "QLabel#tab_drag_preview {"
            "  background: rgba(26, 39, 64, 200);"
            "  border: 1px solid #5a7aa8;"
            "  border-radius: 6px;"
            "  color: #e8eef8;"
            "  padding-left: 8px;"
            "}"
        )
        prev.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        fx = QGraphicsOpacityEffect(prev)
        fx.setOpacity(0.72)
        prev.setGraphicsEffect(fx)
        self._drag_preview = prev
        from PySide6.QtGui import QCursor
        gpos = QCursor.pos()
        local = self.mapFromGlobal(gpos)
        prev.move(local.x() - sz.width() // 2, max(0, (self.height() - sz.height()) // 2))
        prev.show()
        prev.raise_()

        self._drop_line.show()
        self._drop_line.raise_()
        self._position_drop_line(index)

    def _clear_drag_placeholder(self) -> None:
        ph = self._drag_placeholder
        self._drag_placeholder = None
        if ph is None:
            return
        self._layout.removeWidget(ph)
        _dispose_widget_no_toplevel(ph)

    def _clear_drag_preview(self) -> None:
        prev = self._drag_preview
        self._drag_preview = None
        if prev is None:
            return
        _dispose_widget_no_toplevel(prev)

    def _on_drag_moving(self, global_x: float) -> None:
        if self._drag_source_index is None or not self._chips:
            return
        prev = self._drag_preview
        if prev is not None:
            from PySide6.QtGui import QCursor
            g = QCursor.pos()
            local = self.mapFromGlobal(g)
            prev.move(local.x() - prev.width() // 2, max(0, (self.height() - prev.height()) // 2))
            prev.raise_()
        to_index = self._compute_drop_index(global_x)
        if to_index != self._drag_insert_index:
            self._drag_insert_index = to_index
            self._relayout_placeholder(to_index)
        self._position_drop_line(to_index)

    def _relayout_placeholder(self, insert_index: int) -> None:
        ph = self._drag_placeholder
        src = self._drag_source_index
        if ph is None or src is None:
            return
        others = [c for i, c in enumerate(self._chips) if i != src]
        insert_index = max(0, min(insert_index, len(others)))
        while self._layout.count():
            self._layout.takeAt(0)
        for i, c in enumerate(others):
            if i == insert_index:
                self._layout.addWidget(ph)
            self._layout.addWidget(c)
        if insert_index >= len(others):
            self._layout.addWidget(ph)
        self._layout.addWidget(self._add_gap)
        self._layout.addWidget(self._add_btn)
        self._layout.addStretch(1)
        self._normalize_add_btn()
        src_chip = self._chips[src]
        if src_chip.isVisible() or src_chip.x() > -1000:
            src_chip.setVisible(False)
            src_chip.move(-10000, -10000)
        self._drop_line.raise_()

    def _compute_drop_index(self, global_x: float) -> int:
        src = self._drag_source_index
        if src is None:
            return 0
        slots = dict(self._drag_slots or {})
        count = 0
        for i, other in enumerate(self._chips):
            if i == src:
                continue
            try:
                left, width = slots[i]
            except Exception:
                try:
                    left = float(other.mapToGlobal(other.rect().topLeft()).x())
                    width = float(max(1, other.width()))
                except Exception:
                    continue
            # 左へ跨ぐ相手は右1/3境界(2/3地点)、右へ跨ぐ相手は
            # 左1/3境界を越えた時だけ入れ替える。判定座標はdrag開始時に固定。
            fraction = 2.0 / 3.0 if i < src else 1.0 / 3.0
            threshold = float(left) + float(width) * fraction
            if float(global_x) > threshold:
                count += 1
        return count

    def _position_drop_line(self, insert_index: int) -> None:
        ph = self._drag_placeholder
        if ph is not None and ph.isVisible():
            x = ph.geometry().left() - 1
        elif self._chips:
            src = self._drag_source_index
            others = [c for i, c in enumerate(self._chips) if i != src]
            insert_index = max(0, min(insert_index, len(others)))
            if insert_index < len(others):
                x = others[insert_index].geometry().left() - 1
            elif others:
                x = others[-1].geometry().right() + 1
            else:
                x = 0
        else:
            self._drop_line.hide()
            return
        self._drop_line.setFixedHeight(max(1, self.height()))
        self._drop_line.move(x, 0)
        self._drop_line.show()
        self._drop_line.raise_()

    def _on_chip_dropped(self, source_chip_or_global_x, global_x: float | None = None) -> None:
        if global_x is None:
            gx = float(source_chip_or_global_x)
        else:
            gx = global_x
        self._drop_line.hide()
        self._clear_drag_preview()
        self._clear_drag_placeholder()
        if self._drag_source_index is None:
            return
        from_index = self._drag_source_index
        if from_index < len(self._chips):
            chip = self._chips[from_index]
            chip.setGraphicsEffect(None)
            chip.title_label.setStyleSheet("")
        to_index = self._compute_drop_index(gx)
        self._drag_slots = None
        self._drag_source_index = None
        self._drag_insert_index = None

        self._restore_chip_layout()
        if to_index != from_index:
            self.tab_reorder_requested.emit(from_index, to_index)

    def _restore_chip_layout(self) -> None:
        while self._layout.count():
            self._layout.takeAt(0)
        for chip in self._chips:
            chip.move(0, 0)
            chip.setVisible(True)
            self._layout.addWidget(chip)
        self._layout.addWidget(self._add_gap)
        self._layout.addWidget(self._add_btn)
        self._layout.addStretch(1)
        self._normalize_add_btn()

class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_ulonglong),
        ("lParam", ctypes.c_longlong),
        ("time", ctypes.c_ulong),
        ("pt", ctypes.c_long * 2),
    ]

class _WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("hwndInsertAfter", ctypes.c_void_p),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", ctypes.c_uint),
    ]


class _ShrinkableScrollArea(QScrollArea):

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(0, 0)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(400, 300)

class _RootHitTestFilter(QAbstractNativeEventFilter):

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._alive = True
        self._cached_win_id: int | None = None
        self._in_filter = False
        window.destroyed.connect(self._on_window_destroyed)

    def _on_window_destroyed(self) -> None:
        self._alive = False
        self._window = None
        self._cached_win_id = None

    @staticmethod
    def _root_of_hwnd(hwnd: int) -> int:
        if sys.platform != "win32" or hwnd == 0:
            return 0
        user32 = ctypes.windll.user32
        root = user32.GetAncestor(hwnd, 2)
        return root

    def _local_from_physical(self, gx: int, gy: int) -> QPoint:
        return self._window._local_from_physical(gx, gy)

    def nativeEventFilter(self, event_type: bytes, message) -> tuple[bool, int]:
        if self._in_filter or not self._alive:
            return False, 0
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg_ptr = ctypes.cast(int(message), ctypes.POINTER(_MSG))
            msg = msg_ptr.contents
        except (OSError, ValueError, TypeError):
            return False, 0

        self._in_filter = True
        try:
            return self._handle_native_message(msg)
        finally:
            self._in_filter = False

    def _handle_native_message(self, msg) -> tuple[bool, int]:
        hwnd_val = msg.hwnd
        if hwnd_val is None or hwnd_val == 0 or self._cached_win_id is None:
            return False, 0
        hwnd = int(hwnd_val)

        try:
            root = self._root_of_hwnd(hwnd)
        except (OSError, ValueError):
            return False, 0
        if root != self._cached_win_id:
            return False, 0

        is_main_hwnd = (hwnd == self._cached_win_id)

        if msg.message == _WM_WINDOWPOSCHANGING and is_main_hwnd:
            w = self._window
            if w is not None:
                try:
                    wp = ctypes.cast(msg.lParam, ctypes.POINTER(_WINDOWPOS)).contents
                    if not (wp.flags & _SWP_NOMOVE):
                        w._sync_floating_popups_to(wp.x, wp.y)
                except Exception:
                    pass
            return False, 0

        if msg.message == _WM_ENTERSIZEMOVE:
            w = self._window
            if w is not None:
                w._os_sizing = True
                try:
                    w._os_sizing_start_size = QSize(w.size())
                except Exception:
                    w._os_sizing_start_size = None
            return False, 0
        if msg.message == _WM_EXITSIZEMOVE:
            w = self._window
            if w is not None and getattr(w, "_os_sizing", False):
                w._os_sizing = False
                start_size = getattr(w, "_os_sizing_start_size", None)
                w._os_sizing_start_size = None
                size_changed = start_size is None or w.size() != start_size
                if size_changed:
                    try:
                        if getattr(w, "_edge_dock_enabled", False):
                            w._sync_dock_after_os_resize()
                    except Exception:
                        pass
                try:
                    if not getattr(w, "_edge_dock_enabled", False):
                        w._window_mask_pending = False
                        w._window_mask_key = None
                        w._update_window_mask()
                        if size_changed and hasattr(w, "_fit_columns"):
                            w._fit_columns()
                except Exception:
                    pass
            return False, 0

        if msg.message == _WM_NCLBUTTONDBLCLK:
            if not is_main_hwnd:
                return False, 0
            gx = msg.lParam & 0xFFFF
            gy = (msg.lParam >> 16) & 0xFFFF
            if gx >= 0x8000:
                gx -= 0x10000
            if gy >= 0x8000:
                gy -= 0x10000
            local = self._local_from_physical(gx, gy)
            if is_main_hwnd and local.y() < 44:
                self._window._toggle_maximized()
                return True, 0
            return False, 0

        if msg.message != _WM_NCHITTEST:
            return False, 0

        gx = msg.lParam & 0xFFFF
        gy = (msg.lParam >> 16) & 0xFFFF
        if gx >= 0x8000:
            gx -= 0x10000
        if gy >= 0x8000:
            gy -= 0x10000

        local = self._local_from_physical(gx, gy)

        resize_code = self._window._resize_hit_code(local.x(), local.y())
        if resize_code != 0:
            if not is_main_hwnd:
                return True, _HTTRANSPARENT
            w = self._window
            if getattr(w, "_edge_dock_enabled", False) and getattr(
                w, "_edge_dock_revealed", False
            ):
                return True, _HTCLIENT
            # 左右端の個別収納帯（10px）は外枠の6pxリサイズ域と重なる。帯の上は帯のホバー/クリックを優先する
            if resize_code in (_HTLEFT, _HTRIGHT) and w._stowed_column_at_local(local) is not None:
                return True, _HTCLIENT
            return True, resize_code

        return False, 0

class _TitleLogo(QLabel):
    """タイトルバー左端のロゴ。文字色に合わせて現在テーマで塗り直す。"""

    _HEIGHT = 18

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from pathlib import Path
        self._source = QPixmap(str(Path(__file__).resolve().parent / "assets" / "mayotter_cat.png"))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if not self._source.isNull():
            self.setFixedSize(
                max(1, round(self._HEIGHT * self._source.width() / self._source.height())),
                self._HEIGHT,
            )
        self.refresh_theme()

    def refresh_theme(self) -> None:
        if self._source.isNull():
            return
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 元画像は大きいので、先に滑らかに縮小してから描く（直接縮小するとギザギザになる）
        small = self._source.scaled(
            pm.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        small.setDevicePixelRatio(dpr)
        p.drawPixmap(0, 0, small)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(QRect(0, 0, self.width(), self.height()), QColor(theme_color("TEXT")))
        p.end()
        self.setPixmap(pm)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_theme()


class _EmptyStateLogo(QWidget):
    """カラムが1つも無いときだけ、中央にロゴを静かに表示する。

    色はテーマの控えめな文字色（低い不透明度）、大きさは表示領域に比例する。
    出入りはフェードで行う。
    """

    def __init__(self, parent) -> None:
        super().__init__(parent)
        from pathlib import Path
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # NoSystemBackground にすると、リサイズ中に古いフレームのロゴが残って分身して見える
        parent.installEventFilter(self)
        self._source = QPixmap(str(Path(__file__).resolve().parent / "assets" / "mayotter_cat.png"))
        self._alpha = 0.0
        self._want = False
        self._cache: tuple | None = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_alpha)
        self._anim.finished.connect(self._on_done)
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        # 親（表示領域）のリサイズに同じフレームで追従する（定期更新を待たない）
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
            self.update()
        return False

    def set_insets(self, left: int, right: int) -> None:
        """個別収納帯が左右に占める幅。残りの背景部分の中央にロゴを描く（リサイズに追従できるよう幅ではなく余白で持つ）。"""
        if (left, right) != getattr(self, "_insets", (0, 0)):
            self._insets = (left, right)
            self.update()

    def set_visible_animated(self, show: bool, instant: bool = False) -> None:
        if show == self._want:
            return
        self._want = show
        if instant:
            # Dock の展開/収納・切替中は、描画される瞬間（フェード）を見せない
            self._anim.stop()
            self._alpha = 1.0 if show else 0.0
            if show:
                self.show()
                self.raise_()
            else:
                self.hide()
            self.update()
            return
        if show:
            self.show()
            self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._alpha)
        self._anim.setEndValue(1.0 if show else 0.0)
        self._anim.start()

    def _on_alpha(self, v) -> None:
        self._alpha = float(v)
        self.update()

    def _on_done(self) -> None:
        if not self._want:
            self.hide()

    def refresh_theme(self) -> None:
        self._cache = None
        self.update()

    def paintEvent(self, event) -> None:
        if self._source.isNull() or self._alpha <= 0.001:
            return
        p = QPainter(self)
        self.draw(p, self.rect(), self._alpha)
        p.end()

    def draw(self, p: QPainter, bounds: QRect, alpha: float) -> None:
        """bounds（この部品が覆う範囲）の中央へ描く。Dock の展開/収納中は本体の paintEvent からも呼ぶ。"""
        if self._source.isNull() or alpha <= 0.001:
            return
        il, ir = getattr(self, "_insets", (0, 0))
        area = QRect(bounds.x() + il, bounds.y(), max(1, bounds.width() - il - ir), bounds.height())
        if area.width() < 20:
            area = bounds
        w, h = area.width(), area.height()
        # 高さ基準。大きすぎず小さすぎず
        th = int(max(56, min(h * 0.30, w * 0.42, 280)))
        tw = int(th * self._source.width() / self._source.height())
        col = QColor(theme_color("TEXT_MUTED"))
        # 色付けは元解像度で一度だけ行い、サイズ変更ごとの作り直しをしない（リサイズ中のちらつき防止）
        if self._cache is None or self._cache[0] != col.name():
            pm = QPixmap(self._source.size())
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.drawPixmap(0, 0, self._source)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            q.fillRect(pm.rect(), col)
            q.end()
            self._cache = (col.name(), pm)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setOpacity(0.5 * alpha)
        p.drawPixmap(
            QRect(area.x() + (w - tw) // 2, area.y() + (h - th) // 2, tw, th),
            self._cache[1],
        )
        p.restore()


# アニメ中の region/外周線の角半径。展開後の DWM 角丸(Win11 は 8px)に合わせ、
# 終了時に形が変わって見えないようにする。
_DOCK_REVEAL_RADIUS = 8


class _DockRevealOutline(QWidget):
    """Dock 展開/収納アニメ中の外周線。region が DWM 枠を切るため子ウィジェットで描く。

    clip/root が全面を塗るので MainWindow.paintEvent では上に出せない。
    """

    def __init__(self, window, host) -> None:
        super().__init__(host)
        self._mw = window
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def _vis_rect(self) -> QRect:
        """region と同じ矩形を、この widget（central 内）の座標へ直したもの。"""
        mw = self._mw
        vis = getattr(mw, "_dock_reveal_rect", None)
        if vis is None:
            return QRect(0, 0, max(1, self.width()), max(1, self.height()))
        origin = self.parentWidget().pos() if self.parentWidget() is not None else QPoint(0, 0)
        return vis.translated(-origin.x(), -origin.y())

    def refresh(self) -> None:
        """前フレームの線の跡を下の clip/root ごと塗り直させてから再描画する。"""
        vis = self._vis_rect()
        last = getattr(self, "_last_vis", None)
        if last is not None and last != vis:
            parent = self.parentWidget()
            if parent is not None:
                parent.update(last.adjusted(-2, -2, 2, 2))
        self._last_vis = QRect(vis)
        self.update()

    def paintEvent(self, event) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPen

        vis = self._vis_rect()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(theme_color("BORDER")), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # MainWindow.paintEvent と同じ経路（窓座標を central 座標へ平行移動しただけ）。
        # 窓の縁に接する辺は central の外側なのでここでは出ず、paintEvent 側が描く。
        r = float(_DOCK_REVEAL_RADIUS)
        p.drawRoundedRect(QRectF(vis).adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        p.end()


class _DockNotifySphereWidget(QWidget):

    def __init__(self, diameter: int = 20, color: str = "#5b8fd6", parent=None):
        super().__init__(parent)
        self._d = max(12, int(diameter))
        self._color = str(color or "#5b8fd6")
        self._side = "left"
        self._phase = 0.0
        self.setObjectName("dock_notify_sphere")
        self.setFixedSize(self._d, self._d)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        try:
            flags |= Qt.WindowType.WindowTransparentForInput
        except Exception:
            pass
        self.setWindowFlags(flags)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        try:
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        except Exception:
            pass
        self._timer.timeout.connect(self._on_tick)

    def set_side(self, side: str) -> None:
        s = (side or "left").lower()
        if s not in ("left", "right", "top", "bottom"):
            s = "left"
        if s != self._side:
            self._side = s
            self.update()

    def set_color(self, color: str) -> None:
        self._color = str(color or "#5b8fd6")
        self.update()

    def refresh_theme(self) -> None:
        try:
            from src.ui.theme import color as theme_color
            self._color = theme_color("ACCENT_STRONG")
        except Exception:
            pass
        self.update()

    def start_anim(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            self._on_tick()

    def stop_anim(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self._phase = 0.0

    def _on_tick(self) -> None:
        self._phase = (float(self._phase) + 0.05) % 3600.0
        self.update()

    @staticmethod
    def _smooth(a: float, b: float, x: float) -> float:
        if b <= a:
            return 0.0 if x < a else 1.0
        t = max(0.0, min(1.0, (x - a) / (b - a)))
        return t * t * (3.0 - 2.0 * t)

    def paintEvent(self, event) -> None:
        from math import cos, sin, pi, atan2
        from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QRadialGradient
        from PySide6.QtCore import QRectF, QPointF

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        d = float(self._d)
        cx, cy = d * 0.5, d * 0.5
        R = d * 0.42
        side = self._side
        t = float(self._phase)

        cycle = 12.0 + 1.5 * sin(t * 2.0 * pi / 37.0)
        cycle = max(10.0, min(14.0, cycle))
        local = t % cycle
        seed = sin(t * 2.0 * pi / 29.0)

        rise = self._smooth(0.22 * cycle, 0.40 * cycle, local)
        peak = self._smooth(0.40 * cycle, 0.55 * cycle, local) * (1.0 - self._smooth(0.55 * cycle, 0.70 * cycle, local))
        flow = self._smooth(0.38 * cycle, 0.58 * cycle, local)
        recover = self._smooth(0.62 * cycle, 0.82 * cycle, local)
        settle = self._smooth(0.82 * cycle, 0.96 * cycle, local)
        env = max(rise * (1.0 - recover * 0.85), peak) * (1.0 - settle * 0.9)
        env = max(0.0, min(1.0, env))
        breath = 0.015 * sin(t * 2.0 * pi / 5.0) * (1.0 - env)

        if side == "left":
            ox, oy, tx, ty = -1.0, 0.0, 0.0, 1.0
        elif side == "right":
            ox, oy, tx, ty = 1.0, 0.0, 0.0, 1.0
        elif side == "top":
            ox, oy, tx, ty = 0.0, -1.0, 1.0, 0.0
        else:
            ox, oy, tx, ty = 0.0, 1.0, 1.0, 0.0

        N = 16
        pts = []
        for i in range(N):
            ang = 2.0 * pi * i / N - pi * 0.5
            ux, uy = cos(ang), sin(ang)
            face = atan2(oy, ox)
            da = ang - face
            while da > pi:
                da -= 2 * pi
            while da < -pi:
                da += 2 * pi
            facing = max(0.0, cos(da)) ** 1.5
            lobe = env * (0.14 * facing + 0.06 * cos(da * 2.0 + flow * pi))
            shear = env * 0.10 * sin(da + flow * pi) * (0.8 + 0.2 * seed)
            pinch = env * (-0.08) * max(0.0, -cos(da)) ** 1.2
            rad = R * (1.0 + breath + lobe + pinch)
            px = cx + ux * rad + tx * shear * R
            py = cy + uy * rad + ty * shear * R
            lag = env * 0.04 * sin(ang * 2.0 - flow * pi * 1.3)
            px += ox * lag * R
            py += oy * lag * R
            pts.append((px, py))

        body = QPainterPath()
        tau = 0.22

        def _pt(i):
            return pts[i % N]

        body.moveTo(pts[0][0], pts[0][1])
        for i in range(N):
            p0, p1, p2, p3 = _pt(i - 1), _pt(i), _pt(i + 1), _pt(i + 2)
            body.cubicTo(
                p1[0] + (p2[0] - p0[0]) * tau,
                p1[1] + (p2[1] - p0[1]) * tau,
                p2[0] - (p3[0] - p1[0]) * tau,
                p2[1] - (p3[1] - p1[1]) * tau,
                p2[0], p2[1],
            )
        body.closeSubpath()

        half = QPainterPath()
        if side == "left":
            half.addRect(QRectF(-1, -1, cx + 1, d + 2))
        elif side == "right":
            half.addRect(QRectF(cx - 1, -1, d - cx + 2, d + 2))
        elif side == "top":
            half.addRect(QRectF(-1, -1, d + 2, cy + 1))
        else:
            half.addRect(QRectF(-1, cy - 1, d + 2, d - cy + 2))
        p.setClipPath(half)

        base = QColor(self._color)
        dark = QColor(base).darker(145)
        light = QColor(base).lighter(145)
        bright = QColor(base).lighter(165)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dark))
        p.drawPath(body)

        def mass(u, v, rw, rh, col, alpha):
            mx = cx + (tx * u + ox * v) * R
            my = cy + (ty * u + oy * v) * R
            g = QRadialGradient(QPointF(mx, my), max(rw, rh) * R)
            c0 = QColor(col)
            c0.setAlpha(alpha)
            c1 = QColor(col)
            c1.setAlpha(0)
            g.setColorAt(0.0, c0)
            g.setColorAt(0.55, c0)
            g.setColorAt(1.0, c1)
            p.setBrush(QBrush(g))
            p.drawEllipse(QRectF(mx - rw * R, my - rh * R, 2 * rw * R, 2 * rh * R))

        u_main = 0.55 * env * sin(flow * pi) + 0.08 * seed
        mass(u_main, 0.25 + 0.35 * env, 0.70, 0.85, base, 220)
        mass(u_main * 0.7 + 0.2, 0.15 + 0.40 * env, 0.50, 0.55, bright, 210)
        mass(-u_main * 0.8, 0.20, 0.45, 0.50, dark, 190)

        rim = QColor(light)
        rim.setAlpha(100)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(rim, max(1.0, d * 0.04)))
        p.drawPath(body)
        p.end()

class MainWindow(QMainWindow):
    # 通常ウィンドウの最小サイズ: top_bar(32) + 2カラム(AccountColumn.MIN_WIDTH=200×2) + chrome の余裕
    _NORMAL_MIN_SIZE = (560, 480)

    def __init__(self, profile_manager: ProfileManager, settings_manager=None) -> None:
        super().__init__()
        self._profile_manager = profile_manager
        self._settings_manager = settings_manager
        self._disable_x_keyboard_shortcuts = False
        try:
            if self._settings_manager is not None and hasattr(
                self._settings_manager, "get_disable_x_keyboard_shortcuts"
            ):
                self._disable_x_keyboard_shortcuts = bool(
                    self._settings_manager.get_disable_x_keyboard_shortcuts()
                )
            from src.browser.webview import set_disable_x_keyboard_shortcuts
            set_disable_x_keyboard_shortcuts(self._disable_x_keyboard_shortcuts)
        except Exception:
            self._disable_x_keyboard_shortcuts = False

        self._twitter_packs: dict[str, list] = {"normal": [], "lr": [], "tb": []}
        self._grok_packs: dict[str, list] = {"normal": [], "lr": [], "tb": []}
        self._mode_active: dict[str, object] = {"normal": None, "lr": None, "tb": None}

        self._columns: list[AccountColumn] = self._twitter_packs["normal"]

        self._active_column: AccountColumn | None = None

        self._tab_strip: QWidget | None = None
        self._tab_strip_layout: QHBoxLayout | None = None

        self._url_overlay: UrlOverlay | None = None
        self._name_overlay: TextPromptOverlay | None = None
        self._confirm_overlay: ConfirmOverlay | None = None
        self._download_overlay: DownloadOverlay | None = None
        self._download_icon_btn: DownloadIconButton | None = None
        self._column_add_overlay: ColumnAddOverlay | None = None

        self._media_wide_view: XWebView | None = None
        self._media_wide_column: AccountColumn | None = None
        self._media_wide_hidden_columns: list[AccountColumn] = []
        self._media_wide_nav_was_visible: bool = True
        self._media_wide_top_bar_was_visible: bool = True
        self._media_wide_saved_widths: dict[str, int] = {}
        self._media_wide_esc: QShortcut | None = None
        self._media_wide_last_vw: int = 0

        self._grok_mode = False
        self._grok_columns: list[AccountColumn] = self._grok_packs["normal"]
        self._twitter_columns: list[AccountColumn] = self._twitter_packs["normal"]

        self._known_accounts: dict[str, dict] = {}

        self._column_configs: list[Column] = []

        self.EDGE_DOCK_ANIMATION_DURATION = 260
        self.EDGE_DOCK_HOVER_LEAVE_DELAY = 200
        self.EDGE_DOCK_TRIGGER_WIDTH = 8
        self.EDGE_DOCK_ON_ANIMATION_DURATION = 200
        self.EDGE_DOCK_INDICATOR_WIDTH = 4
        self.EDGE_DOCK_KEEP_OPEN_MARGIN = 40
        self.EDGE_SWITCH_HYSTERESIS_PX = 40

        self._edge_dock_enabled = False
        self._edge_dock_direction = "right"
        self._edge_dock_edge_offsets = {
            "left": 0.5,
            "right": 0.5,
            "top": 0.5,
            "bottom": 0.5,
        }
        self._edge_dock_edge_offset = 0.5
        self._edge_dock_revealed = False
        self._edge_dock_column_count = 1
        self._edge_dock_column_count_lr = 1
        self._edge_dock_column_count_tb = 2
        self._normal_column_count = 2
        self._restoring_session = False
        self._edge_dock_zoom_percent = 90
        self._edge_dock_always_on_top = True
        self._edge_dock_disable_on_fullscreen = True
        self._edge_dock_fs_yielded = False
        self._edge_dock_fs_timer: QTimer | None = None
        self._dock_has_unread = False
        self._dock_notify_timer: QTimer | None = None
        self._dock_notify_icon = None
        self._dock_unread_indicator_enabled = True
        self._dock_notify_sphere_d = 20
        self._edge_dock_profile_lock = False
        self._edge_dock_dir_transitioning = False
        self._edge_dir_anim: QVariantAnimation | None = None

        self._edge_dock_width_lr = 0
        self._edge_dock_height_lr = 0
        self._edge_dock_width_tb = 0
        self._edge_dock_height_tb = 0
        self._edge_dock_panel_height_ratio = 0.78

        self._edge_dock_reveal_progress = 0.0
        self._edge_dock_animating = False
        # 方向切替 / Dock ON/OFF の離散 state 置換中。
        # True の間は resizeEvent が mask/fit を走らせない（表示中 morph を禁止する）。
        self._edge_dock_switching = False
        self._dock_geom_reenter = False
        self._dock_slide_proxy: QLabel | None = None
        self._edge_dock_anim_cw = 0
        self._edge_dock_anim_ch = 0
        self._edge_dock_opaque_fill = False

        self._edge_dock_clip: QWidget | None = None
        self._edge_dock_root: QWidget | None = None
        self._transition_commit_gate = TransitionCommitGate(self)

        self._edge_dock_normal_geometry: QRect | None = None
        self._scroll_layout: QHBoxLayout | None = None
        self._current_service_menu: _ServiceMenu | None = None
        self._suspended_dock_popups: list[str] = []

        self._edge_dock_dragging = False
        self._edge_dock_drag_anchor: QPoint | None = None
        self._edge_dock_drag_start_direction: str | None = None
        self._edge_dock_drag_last_global_pos: QPoint | None = None
        self._edge_dock_drag_offset: float | None = None
        self._edge_dock_resizing = False
        self._os_sizing = False
        self._os_sizing_start_size: QSize | None = None
        self._edge_dock_resize_edges = ""
        self._edge_dock_resize_origin: QPoint | None = None
        self._edge_dock_resize_geom: QRect | None = None
        self._edge_cursor_forced = False
        self._mode_stowed_columns: dict[str, list] = {"normal": [], "lr": [], "tb": []}
        self._mode_stow_saved_widths: dict[str, dict] = {"normal": {}, "lr": {}, "tb": {}}
        self._stowed_columns: list = []
        self._stow_saved_widths: dict = {}
        self._bound_mode_key: str = "normal"
        self._pending_stow_ids: list = []
        self._stow_restore_rail = None
        self._stow_restore_rail_left = None
        self._stow_restore_knob_class = None
        self._boundary_hand_cursor = False

        self._edge_detector: EdgeDetector | None = None
        self._edge_animator: EdgeAnimator | None = None

        self._download_seen_ids: set[str] = set()

        self._resize_filter = _RootHitTestFilter(self)
        QGuiApplication.instance().installNativeEventFilter(self._resize_filter)

        self.setWindowTitle("Mayotter")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        )

        try:
            from src.browser.webview import attach_capture_holder_parent
            attach_capture_holder_parent(self)
        except Exception:
            pass
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setContentsMargins(1, 1, 1, 1)
        # MainWindow 最小サイズ: top_bar(32) + margins + 典型2カラム相当(AccountColumn.MIN_WIDTH=200×2)
        # + スクロール/chrome 余裕。560x480 は既存 UI 要素から算出し、UI 破綻を防ぐ。
        # Dock 手動リサイズ下限(240x200)とは独立（Dock 中は setMinimumSize(1,1) に一時切替）。
        self.setMinimumSize(*self._NORMAL_MIN_SIZE)

        self.resize(1280, 800)
        try:
            if self._settings_manager is not None:
                geom = None
                if hasattr(self._settings_manager, "get_window_geometry_normal"):
                    geom = self._settings_manager.get_window_geometry_normal()
                if not geom:
                    geom = self._settings_manager.get_window_geometry()
                if geom:
                    self.restoreGeometry(geom)
                    # 起動時に最大化状態のまま復元すると、フレームレスの位置がタスクバーぶんずれて
                    # タイトルバーが埋もれる。最大化ボタンと同じ経路で表示後に最大化する。
                    if self.windowState() & Qt.WindowState.WindowMaximized:
                        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMaximized)
                        self._start_maximized = True
        except Exception:
            pass

        self._setup_ui()
        self._apply_theme()
        self._load_accounts()
        self._download_history_restored = False
        self._install_url_policy_handlers()
        self._update_edge_dock_ui()

        if self._edge_dock_enabled:
            QTimer.singleShot(0, self._restore_edge_dock_on_startup)

        self._resize_filter._cached_win_id = int(self.winId())

        QApplication.instance().installEventFilter(self)

        self._hibernation_timer = QTimer(self)
        self._hibernation_timer.setInterval(60_000)
        self._hibernation_timer.timeout.connect(self._check_hibernation)
        self._hibernation_timer.start()

        self._stowed_hover_timer = QTimer(self)
        self._stowed_hover_timer.setInterval(60)
        self._stowed_hover_timer.timeout.connect(self._poll_stowed_hover)
        self._stowed_hover_timer.start()

        # Dock 切替・展開の途中は fit が走らないので、ロゴの状態と位置は定期的に整える
        self._empty_state_timer = QTimer(self)
        self._empty_state_timer.setInterval(120)
        self._empty_state_timer.timeout.connect(self._update_empty_state)
        self._empty_state_timer.start()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._top_bar = QFrame()
        self._top_bar.setObjectName("top_bar")
        self._top_bar.setFixedHeight(32)
        def _top_bar_mouse_press(event):
            if event.button() == Qt.MouseButton.LeftButton:
                local = self._top_bar.mapTo(self, event.position().toPoint())
                code = self._resize_hit_code(local.x(), local.y())
                edges = _QT_EDGES_FOR_HT_CODE.get(code)
                # 角の斜めリサイズは +カラム 等のボタンより優先
                corner = code in (
                    _HTTOPLEFT,
                    _HTTOPRIGHT,
                    _HTBOTTOMLEFT,
                    _HTBOTTOMRIGHT,
                )
                if (
                    edges is not None
                    and corner
                    and not self.isMaximized()
                    and not self.isFullScreen()
                ):
                    wh = self.windowHandle()
                    if wh is not None:
                        if self._edge_dock_enabled and self._edge_dock_revealed:
                            estr = self._edges_str_from_ht_code(code)
                            if estr and self._begin_dock_manual_resize(
                                estr, event.globalPosition().toPoint()
                            ):
                                return
                        else:
                            wh.startSystemResize(edges)
                            return
                try:
                    child = self._top_bar.childAt(event.position().toPoint())
                except Exception:
                    child = None
                w = child
                while w is not None and w is not self._top_bar:
                    if self._widget_is_interactive_control(w):
                        from PySide6.QtWidgets import QFrame as _QF
                        _QF.mousePressEvent(self._top_bar, event)
                        return
                    try:
                        w = w.parentWidget()
                    except Exception:
                        break
                code = self._resize_hit_code(local.x(), local.y())
                edges = _QT_EDGES_FOR_HT_CODE.get(code)
                if edges is not None and not self.isMaximized() and not self.isFullScreen():
                    wh = self.windowHandle()
                    if wh is not None:
                        if self._edge_dock_enabled and self._edge_dock_revealed:
                            estr = self._edges_str_from_ht_code(code)
                            if estr and self._begin_dock_manual_resize(
                                estr, event.globalPosition().toPoint()
                            ):
                                return
                        else:
                            wh.startSystemResize(edges)
                            return
                if self._edge_dock_enabled:
                    try:
                        from PySide6.QtGui import QMouseEvent as _QME
                        from PySide6.QtCore import QPointF as _QPF
                        gp = event.globalPosition()
                        lp = self.mapFromGlobal(gp.toPoint())
                        mapped = _QME(
                            event.type(),
                            _QPF(lp),
                            gp,
                            event.button(),
                            event.buttons(),
                            event.modifiers(),
                        )
                        self.mousePressEvent(mapped)
                    except Exception:
                        self.mousePressEvent(event)
                    return
                wh = self.windowHandle()
                if wh:
                    wh.startSystemMove()
        self._top_bar.mousePressEvent = _top_bar_mouse_press

        def _top_bar_mouse_double_click(event) -> None:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    if not getattr(self, "_edge_dock_enabled", False):
                        self._toggle_maximized()
            except Exception:
                pass

        self._top_bar.mouseDoubleClickEvent = _top_bar_mouse_double_click
        top_bar_layout = QHBoxLayout(self._top_bar)
        top_bar_layout.setContentsMargins(6, 2, 6, 2)
        top_bar_layout.setSpacing(4)
        self._top_bar_layout = top_bar_layout

        self._title_logo = _TitleLogo()
        top_bar_layout.addWidget(self._title_logo)

        self._add_twitter_btn = QPushButton("+ X")
        self._add_twitter_btn.setObjectName("add_twitter_btn")
        self._add_twitter_btn.setMinimumWidth(40)
        self._add_twitter_btn.setToolTip("アカウントを追加")
        self._add_twitter_btn.clicked.connect(lambda: self._open_service_menu(False))
        top_bar_layout.addWidget(self._add_twitter_btn)

        self._add_column_btn = QPushButton("+ カラム")
        self._add_column_btn.setObjectName("add_column_btn")
        self._add_column_btn.setMinimumWidth(56)
        self._add_column_btn.setToolTip("カラムを追加")
        self._add_column_btn.clicked.connect(self._open_column_add_overlay)
        top_bar_layout.addWidget(self._add_column_btn)

        self._multi_post_btn = QPushButton("投稿")
        self._multi_post_btn.setObjectName("add_column_btn")
        self._multi_post_btn.setMinimumWidth(40)
        self._multi_post_btn.setToolTip("複数アカウントへまとめて投稿")
        self._multi_post_btn.clicked.connect(self._open_multi_post_dialog)
        top_bar_layout.addWidget(self._multi_post_btn)

        self._tab_strip = _TabStrip()
        self._tab_strip_layout = self._tab_strip._layout
        self._tab_strip.tab_selected.connect(self._on_tab_chip_selected)
        self._tab_strip.tab_close_requested.connect(self._on_tab_chip_close)
        self._tab_strip.tab_context_requested.connect(self._show_tab_context_menu)
        self._tab_strip.tab_reorder_requested.connect(self._on_tab_reorder)
        self._tab_strip.new_tab_requested.connect(self._on_tab_strip_new_tab)
        self._tab_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_bar_layout.addWidget(self._tab_strip, 1)

        self._download_icon_btn = DownloadIconButton()
        self._download_icon_btn.clicked.connect(self._toggle_download_history)
        top_bar_layout.addWidget(self._download_icon_btn)

        self._record_btn = QToolButton()
        self._record_btn.setObjectName("record_btn")
        self._record_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._record_btn.setIcon(make_mic_icon(_COLOR_ACCENT_SOFT, 14))
        self._record_btn.setIconSize(QSize(14, 14))
        self._record_btn.setText("")
        self._record_btn.setFixedSize(24, 24)
        self._record_btn.setToolTip("音声投稿")
        self._record_btn.clicked.connect(self._toggle_recording)
        top_bar_layout.addWidget(self._record_btn)
        self._audio_recorder = None
        self._media_convert_worker = None
        self._media_convert_is_recording = False
        self._recording_elapsed_sec = 0
        self._recording_target = None
        self._recording_overlay = None
        try:
            from src.browser.webview import MayotterPage
            MayotterPage.media_status_handler = self._on_media_status
        except Exception:
            pass

        self._edge_dock_toggle_btn = QPushButton("Dock")
        self._edge_dock_toggle_btn.setObjectName("edge_dock_toggle_btn")
        self._edge_dock_toggle_btn.setMinimumWidth(88)
        self._edge_dock_toggle_btn.setMaximumWidth(140)
        self._edge_dock_toggle_btn.setIcon(make_edge_dock_icon(_COLOR_SECONDARY, 12))
        self._edge_dock_toggle_btn.setIconSize(QSize(12, 12))
        self._edge_dock_toggle_btn.setToolTip("Dock を有効にする / 右クリックで収納位置")
        self._edge_dock_toggle_btn.clicked.connect(self._toggle_edge_dock)
        self._edge_dock_toggle_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._edge_dock_toggle_btn.customContextMenuRequested.connect(self._show_edge_dock_menu)
        top_bar_layout.addWidget(self._edge_dock_toggle_btn)

        self._dock_chrome_chevron = QToolButton()
        self._dock_chrome_chevron.setObjectName("dock_chrome_chevron")
        self._dock_chrome_chevron.setIcon(make_chevron_left_icon(_COLOR_SECONDARY, 12))
        self._dock_chrome_chevron.setIconSize(QSize(12, 12))
        self._dock_chrome_chevron.setFixedSize(24, 24)
        self._dock_chrome_chevron.setToolTip("操作ボタンを表示")
        self._dock_chrome_chevron.setVisible(False)
        self._dock_chrome_chevron.clicked.connect(lambda: self._set_dock_chrome_expanded(True))
        top_bar_layout.addWidget(self._dock_chrome_chevron)

        self._dock_chrome_tray = QWidget()
        self._dock_chrome_tray.setObjectName("dock_chrome_tray")
        tray_l = QHBoxLayout(self._dock_chrome_tray)
        tray_l.setContentsMargins(0, 0, 0, 0)
        tray_l.setSpacing(2)
        self._dock_chrome_tray_layout = tray_l

        self._settings_btn = QToolButton()
        self._settings_btn.setObjectName("settings_btn")
        self._settings_btn.setText("")
        self._settings_btn.setIcon(make_settings_icon(_COLOR_TEXT_SECONDARY, 14))
        self._settings_btn.setIconSize(QSize(14, 14))
        self._settings_btn.setFixedSize(24, 24)
        self._settings_btn.setToolTip("設定")
        self._settings_btn.clicked.connect(self._open_settings_dialog)
        tray_l.addWidget(self._settings_btn)

        top_bar_layout.addWidget(self._dock_chrome_tray)

        self._win_min_btn = QToolButton()
        self._win_min_btn.setObjectName("win_min_btn")
        self._win_min_btn.setText("")
        self._win_min_btn.setIcon(make_minimize_icon(_COLOR_SECONDARY, 12))
        self._win_min_btn.setIconSize(QSize(12, 12))
        self._win_min_btn.setFixedSize(24, 24)
        self._win_min_btn.setToolTip("最小化")
        self._win_min_btn.clicked.connect(self._minimize_window)
        top_bar_layout.addWidget(self._win_min_btn)

        self._win_max_btn = QToolButton()
        self._win_max_btn.setObjectName("win_max_btn")
        self._win_max_btn.setText("")
        self._win_max_btn.setIcon(make_maximize_icon(_COLOR_SECONDARY, 12))
        self._win_max_btn.setIconSize(QSize(12, 12))
        self._win_max_btn.setFixedSize(24, 24)
        self._win_max_btn.setToolTip("最大化")
        self._win_max_btn.clicked.connect(self._toggle_maximized)
        top_bar_layout.addWidget(self._win_max_btn)

        self._win_close_btn = QToolButton()
        self._win_close_btn.setObjectName("win_close_btn")
        self._win_close_btn.setText("")
        self._win_close_btn.setIcon(make_close_icon(_COLOR_SECONDARY, 12))
        self._win_close_btn.setIconSize(QSize(12, 12))
        self._win_close_btn.setFixedSize(24, 24)
        self._win_close_btn.setToolTip("閉じる")
        self._win_close_btn.clicked.connect(self.close)
        top_bar_layout.addWidget(self._win_close_btn)

        self._dock_chrome_expanded = True
        self._dock_chrome_chevron.installEventFilter(self)
        self._dock_chrome_tray.installEventFilter(self)
        self._top_bar.installEventFilter(self)
        for _b in (
            getattr(self, "_add_twitter_btn", None),
            getattr(self, "_add_column_btn", None),
            getattr(self, "_multi_post_btn", None),
            getattr(self, "_download_icon_btn", None),
            getattr(self, "_record_btn", None),
            getattr(self, "_settings_btn", None),
            getattr(self, "_edge_dock_toggle_btn", None),
        ):
            if _b is not None:
                try:
                    _b.installEventFilter(self)
                except Exception:
                    pass

        self._scroll = _ShrinkableScrollArea()
        self._scroll.setObjectName("scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        try:
            self._force_dark_scrollbars(self._scroll)
        except Exception:
            pass
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("scroll_content")
        self._scroll_content.setMinimumSize(0, 0)
        self._scroll_layout = QHBoxLayout(self._scroll_content)
        self._scroll_layout.setSpacing(0)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)

        self._scroll.setWidget(self._scroll_content)

        self._edge_dock_clip = QWidget()
        self._edge_dock_clip.setObjectName("edgeDockClip")
        self._edge_dock_clip.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._edge_dock_clip.setAutoFillBackground(True)
        _cp = self._edge_dock_clip.palette()
        _cp.setColor(self._edge_dock_clip.backgroundRole(), themed_qcolor("#0f1117"))
        self._edge_dock_clip.setPalette(_cp)
        self._edge_dock_root = QWidget(self._edge_dock_clip)
        self._edge_dock_root.setObjectName("edgeDockRoot")
        self._edge_dock_root.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._edge_dock_root.setAutoFillBackground(True)
        _rp = self._edge_dock_root.palette()
        _rp.setColor(self._edge_dock_root.backgroundRole(), themed_qcolor("#0f1117"))
        self._edge_dock_root.setPalette(_rp)
        edge_dock_root_layout = QVBoxLayout(self._edge_dock_root)
        edge_dock_root_layout.setContentsMargins(0, 0, 0, 0)
        edge_dock_root_layout.setSpacing(0)
        edge_dock_root_layout.addWidget(self._top_bar)
        edge_dock_root_layout.addWidget(self._scroll)
        self._edge_dock_root.setGeometry(0, 0, 1, 1)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(0)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(self._edge_dock_clip)
        layout.addLayout(body_layout)

        self._url_overlay = UrlOverlay(self)
        self._name_overlay = TextPromptOverlay(self)
        self._confirm_overlay = ConfirmOverlay(self)
        self._download_overlay = DownloadOverlay(self)
        try:
            self._download_overlay.history_changed.connect(self._persist_download_history)
        except Exception:
            pass
        self._column_add_overlay = ColumnAddOverlay(self)
        self._column_add_overlay.column_added.connect(self._on_column_added)
        self._column_add_overlay.closed.connect(self._on_column_add_overlay_closed)
        if self._settings_manager is not None and hasattr(self._settings_manager, "get_saved_searches"):
            self._column_add_overlay.set_saved_searches_store(
                self._settings_manager.get_saved_searches,
                self._settings_manager.save_saved_searches,
            )
        self._init_boundary_action_overlay()

        self._setup_shortcuts()

    def _apply_theme(self) -> None:
        from src.ui.theme import remap_stylesheet
        self.setStyleSheet(remap_stylesheet("""
            QMainWindow { background-color: #0f1117; }
            QMainWindow {
                background-color: #0f1117;
            }
            #top_bar {
                background-color: #0f1117;
                border-bottom: 1px solid #2b3242;
            }
            #scroll_content {
                background-color: #0f1117;
            }
            #scroll {
                background-color: #0f1117;
                border: none;
            }
            AccountColumn {
                background-color: transparent;
                border: none;
            }
            #column_nav {
                background-color: #0f1117;
                border-bottom: 1px solid #2b3242;
            }
            #column_resize_handle {
                background-color: transparent;
            }
            /* 境界線とhover色は _BoundaryHintBar.paintEvent が描く */
            #column_resize_handle[hint="true"] #boundary_hint_bar,
            #boundary_hint_bar {
                background-color: transparent;
                border: none;
            }
            #url_bar {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                padding: 0 8px;
                color: #f1f3f7;
                selection-background-color: #2f517d;
            }
            #back_btn, #forward_btn, #reload_btn, #home_btn, #stow_self_btn {
                background-color: transparent;
                border: none;
                color: #93a5c4;
                border-radius: 4px;
            }
            #back_btn:hover, #forward_btn:hover, #reload_btn:hover, #home_btn:hover, #stow_self_btn:hover {
                background-color: rgba(148, 178, 230, 0.1);
            }
            #close_btn {
                background-color: transparent;
                border: none;
                color: #93a5c4;
                border-radius: 4px;
                font-weight: bold;
            }
            #close_btn:hover {
                background-color: rgba(230, 100, 100, 0.2);
                color: #e66464;
            }
            QPushButton#add_twitter_btn {
                background-color: #181c26;
                border: 1px solid #2b3242;
                border-radius: 6px;
                color: #f1f3f7;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            }
            QPushButton#add_twitter_btn:hover {
                background-color: #1d2230;
                border-color: #394255;
                color: #f1f3f7;
            }
            QPushButton#add_twitter_btn:pressed {
                background-color: #2b3242;
            }
            QPushButton#add_twitter_btn::menu-indicator {
                image: none;
                width: 0;
            }
            QPushButton#add_column_btn {
                background-color: #181c26;
                border: 1px solid #2b3242;
                border-radius: 6px;
                color: #f1f3f7;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            }
            QPushButton#add_column_btn:hover {
                background-color: #1d2230;
                border-color: #394255;
                color: #f1f3f7;
            }
            QPushButton#add_column_btn:pressed {
                background-color: #2b3242;
            }
            #tab_strip {
                background-color: transparent;
            }
            QWidget#tab_chip {
                background-color: #181c26;
                border: none;
                border-right: 1px solid #232a38;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
                color: #aeb6c5;
                padding: 4px 10px;
                min-width: 60px;
                max-width: 112px;
            }
            QWidget#tab_chip QLabel#tab_chip_title {
                color: #aeb6c5;
                background: transparent;
            }
            QWidget#tab_chip[checked="true"] {
                background-color: #232a38;
                color: #eaf1fb;
            }
            QWidget#tab_chip[checked="true"] QLabel#tab_chip_title {
                color: #eaf1fb;
            }
            QWidget#tab_chip:hover {
                background-color: #232a38;
            }
            QWidget#tab_chip:hover QLabel#tab_chip_title {
                color: #f1f3f7;
            }
            #tab_close_btn {
                background-color: transparent;
                border: none;
                color: #93a5c4;
                border-radius: 3px;
                padding: 0;
            }
            #tab_close_btn:hover {
                background-color: rgba(230, 100, 100, 0.2);
                color: #e66464;
            }
            QToolButton#tab_add_btn {
                background-color: #181c26;
                border: 1px solid #2b3242;
                border-radius: 9px;
                color: #aeb6c5;
                padding: 0;
                margin: 0;
            }
            QToolButton#tab_add_btn:hover {
                background-color: #232a38;
                border: 1px solid #3d6a9e;
            }
            QToolButton#tab_add_btn:pressed {
                background-color: #1a2030;
                border: 1px solid #2b3242;
            }
            QLabel#tab_badge {
                background-color: #3d7eff;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-size: 9px;
                font-weight: 700;
                padding: 0 2px;
                min-width: 8px;
                min-height: 8px;
            }

            #tab_drop_line {
                background-color: #1d9bf0;
                border-radius: 1px;
            }
            #download_icon_btn {
                background-color: transparent;
                border: none;
                border-radius: 6px;
            }
            #download_icon_btn:hover {
                background-color: rgba(148, 178, 230, 0.1);
            }
            #record_btn {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: #eaf1fb;
                padding: 0 4px;
                font-size: 11px;
                font-weight: 600;
            }
            #record_btn:hover {
                background-color: rgba(230, 100, 100, 0.15);
            }
            #record_btn[recording="true"] {
                background-color: rgba(230, 100, 100, 0.25);
                border: 1px solid #e66464;
                color: #eaf1fb;
            }
            #win_min_btn, #win_max_btn, #win_close_btn {
                background-color: transparent;
                border: none;
                color: #93a5c4;
                border-radius: 4px;
                font-size: 12px;
            }
            #win_min_btn:hover, #win_max_btn:hover {
                background-color: rgba(148, 178, 230, 0.1);
            }
            #win_close_btn:hover {
                background-color: rgba(230, 100, 100, 0.3);
                color: #e66464;
            }
            #edge_dock_toggle_btn {
                background-color: #181c26;
                border: 1px solid #2b3242;
                border-radius: 6px;
                color: #f1f3f7;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            }
            #dock_chrome_chevron {
                background-color: #181c26;
                border: 1px solid #2b3242;
                border-radius: 6px;
            }
            #dock_chrome_chevron:hover {
                background-color: #232a38;
            }
            #edge_dock_toggle_btn:hover {
                background-color: #232a38;
                border-color: #2f517d;
            }
            #edge_dock_count_btn {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                color: #aeb6c5;
                font-size: 11px;
                padding: 2px 6px;
            }
            #edge_dock_count_btn:hover {
                background-color: #232a38;
                border-color: #2f517d;
            }
            #url_overlay, #text_prompt_overlay, #confirm_overlay, #download_overlay, #column_add_overlay {
                background-color: #181c26;
                border: 1px solid #2b3242;
                border-radius: 8px;
            }
            #url_overlay QLabel, #text_prompt_overlay QLabel, #confirm_overlay QLabel, #column_add_overlay QLabel {
                color: #f1f3f7;
            }
            #url_overlay_input, #text_prompt_input {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 0 10px;
                color: #eaf1fb;
                selection-background-color: #2f517d;
            }
            #url_overlay_input:focus, #text_prompt_input:focus {
                border-color: #33639f;
            }
            #confirm_message, #text_prompt_title {
                color: #f1f3f7;
            }
            QPushButton#text_prompt_ok, QPushButton#text_prompt_cancel,
            QPushButton#confirm_delete, QPushButton#confirm_cancel {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                color: #eaf1fb;
                padding: 3px 10px;
                min-width: 56px;
                min-height: 22px;
            }
            QPushButton#text_prompt_ok:hover, QPushButton#text_prompt_cancel:hover {
                background-color: #232a38;
            }
            QPushButton#confirm_delete {
                background-color: #3d1a1a;
                border-color: #5d2a2a;
            }
            QPushButton#confirm_delete:hover {
                background-color: #5d2a2a;
            }
            QComboBox#column_add_combo {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                padding: 4px 8px;
                color: #eaf1fb;
                min-height: 24px;
            }
            QComboBox#column_add_combo::drop-down {
                border: none;
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 24px;
            }
            QComboBox#column_add_combo::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #9fb4d8;
                margin-right: 8px;
            }
            QComboBox#column_add_combo QAbstractItemView {
                background-color: #181c26;
                border: 1px solid #232a38;
                color: #eaf1fb;
                selection-background-color: #2f517d;
            }
            #download_overlay_title {
                color: #f1f3f7;
                font-weight: bold;
                padding-bottom: 4px;
                border-bottom: 1px solid #232a38;
            }
            #download_overlay_list {
                background-color: transparent;
                border: none;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            #download_overlay_list::item {
                background-color: transparent;
            }
            #download_item_name {
                color: #f1f3f7;
            }
            QMenu {
                background-color: #0d1524;
                color: #eaf1fb;
                border: 1px solid #2f517d;
                border-radius: 8px;
                padding: 6px;
            }
            QMenu::item {
                background-color: transparent;
                border-radius: 4px;
                padding: 6px 28px 6px 14px;
                color: #eaf1fb;
            }
            QMenu::item:selected {
                background-color: rgba(148, 178, 230, 0.18);
                color: #ffffff;
            }
            QMenu::item:disabled {
                color: #6b7c96;
            }
            QMenu::separator {
                height: 1px;
                background-color: #232a38;
                margin: 4px 8px;
            }
                        #settings_btn {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 4px;
            }
            #settings_btn:hover {
                background-color: #1a2740;
                border-color: #2f517d;
            }
            #download_overlay_close {
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            #download_overlay_close:hover {
                background-color: #1a2740;
            }
            #service_menu {
                background-color: #0d1524;
                border: 1px solid #2f517d;
                border-radius: 6px;
            }
            #service_menu_add_btn {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                color: #aeb6c5;
                padding: 6px 12px;
                margin: 4px;
            }
            #service_menu_add_btn:hover {
                background-color: #232a38;
                border-color: #2f517d;
            }
            #service_menu_row {
                border-radius: 4px;
                padding: 2px 4px;
            }
            #service_menu_row:hover {
                background-color: rgba(148, 178, 230, 0.15);
            }
            #service_menu_label {
                color: #f1f3f7;
                padding: 4px 8px;
            }
            #service_menu_del_btn {
                background-color: transparent;
                border: none;
                border-radius: 3px;
                color: #93a5c4;
                font-size: 12px;
            }
            #service_menu_del_btn:hover {
                background-color: rgba(230, 100, 100, 0.2);
                color: #e66464;
            }
            QCheckBox#confirm_dont_show {
                color: #aeb6c5;
                spacing: 8px;
            }
            QCheckBox#confirm_dont_show::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #2f517d;
                border-radius: 3px;
                background-color: #181c26;
            }
            QCheckBox#confirm_dont_show::indicator:checked {
                background-color: #33639f;
                border-color: #33639f;
            }
            QToolTip {
                background-color: #1d2230;
                color: #f1f3f7;
                border: 1px solid #2b3242;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QScrollBar:vertical {
                background: #141820;
                background-color: #141820;
                width: 8px;
                border: none;
                margin: 0;
            }
            QScrollBar::groove:vertical {
                background: #141820;
                background-color: #141820;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #3d4a5e;
                background-color: #3d4a5e;
                border-radius: 4px;
                min-height: 30px;
                border: none;
            }
            QScrollBar::handle:vertical:hover {
                background: #5a6b84;
                background-color: #5a6b84;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0; width: 0; background: transparent; border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: #141820;
                background-color: #141820;
            }
            QScrollBar:horizontal, QScrollBar:horizontal:horizontal {
                background: #141820;
                background-color: #141820;
                height: 8px;
                border: none;
                margin: 0;
            }
            QScrollBar::groove:horizontal {
                background: #141820;
                background-color: #141820;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: #3d4a5e;
                background-color: #3d4a5e;
                border-radius: 4px;
                min-width: 30px;
                border: none;
            }
            QScrollBar::handle:horizontal:hover {
                background: #5a6b84;
                background-color: #5a6b84;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0; height: 0; background: transparent; border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: #141820;
                background-color: #141820;
            }
        """))

        QTimer.singleShot(0, self._update_window_mask)

    def _apply_runtime_theme(self, theme_id: str) -> None:
        from src.ui.theme import set_theme, apply_theme_to_application

        set_theme(theme_id)
        app = QApplication.instance()
        if app is not None:
            apply_theme_to_application(app)
        self._apply_theme()
        self._refresh_theme_icons()
        try:
            self._update_edge_dock_ui()
        except Exception:
            pass
        seen = set()
        for pack in getattr(self, "_mode_columns", {}).values():
            for column in pack or []:
                if id(column) in seen:
                    continue
                seen.add(id(column))
                try:
                    column.refresh_theme()
                except Exception:
                    pass
        # 1つの refresh_theme の失敗で残りの widget が旧テーマ色のまま残らないよう、個別に守る
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_theme", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    import traceback
                    traceback.print_exc()
        try:
            for host in (self._edge_dock_clip, self._edge_dock_root):
                pal = host.palette()
                pal.setColor(host.backgroundRole(), themed_qcolor("#0f1117"))
                host.setPalette(pal)
                host.update()
        except Exception:
            pass
        try:
            for host in (self._scroll, self._scroll.viewport(), self._scroll_content, self.centralWidget()):
                if host is not None:
                    pal = host.palette()
                    pal.setColor(host.backgroundRole(), themed_qcolor("#0f1117"))
                    host.setPalette(pal)
                    host.update()
        except Exception:
            pass
        try:
            self._transition_commit_gate.invalidate_theme_cache()
        except Exception:
            pass
        try:
            from src.ui.theme import apply_overlay_theme
            for name in (
                "_url_overlay",
                "_name_overlay",
                "_confirm_overlay",
                "_download_overlay",
                "_column_add_overlay",
            ):
                overlay = getattr(self, name, None)
                if overlay is not None:
                    apply_overlay_theme(overlay)
        except Exception:
            pass
        # 通知球は独立した Tool ウィンドウなので個別に更新する
        try:
            sphere = getattr(self, "_dock_notify_icon", None)
            if sphere is not None:
                refresh = getattr(sphere, "refresh_theme", None)
                if callable(refresh):
                    refresh()
        except Exception:
            pass
        try:
            self._window_mask_key = None
            self._dock_shape_mask_key = None
            if self._edge_dock_enabled:
                self._apply_dock_shape_mask(force=True)
            else:
                self._update_window_mask()
        except Exception:
            pass
        self._refresh_native_borders(force=True)
        # 収納中の細い本体は親の update() だけでは再描画されないことがあるため即時に塗り直す
        if self._edge_dock_enabled and not self._edge_dock_revealed:
            self.repaint()
        self.update()

    def _sync_dock_opaque_paint(self) -> None:
        """収納中だけ clip/root の WA_OpaquePaintEvent を外す。

        収納帯（幅数px）で opaque のままだと帯の内側が黒くなる。展開中は opaque のまま。
        """
        opaque = not (self._edge_dock_enabled and not self._edge_dock_revealed)
        attr = Qt.WidgetAttribute.WA_OpaquePaintEvent
        for host in (getattr(self, "_edge_dock_clip", None), getattr(self, "_edge_dock_root", None)):
            if host is not None and host.testAttribute(attr) != opaque:
                host.setAttribute(attr, opaque)
                host.update()

    def _native_border_state(self) -> tuple:
        # 収納中と展開/収納アニメ中は DWM 枠を消す。アニメ中の region は DWM 枠を切れず、
        # 元サイズの枠だけが残る/枠が二重になるため、その間は _DockRevealOutline が担当する。
        stowed = bool(
            self._edge_dock_enabled
            and (
                not self._edge_dock_revealed
                or getattr(self, "_edge_dock_animating", False)
            )
        )
        return (get_theme_id(), stowed)

    def _refresh_native_borders(self, *, force: bool = False) -> None:
        """DWM枠色を現在テーマへ合わせる。geometry keyとは別にテーマ単位で管理する。"""
        self._sync_dock_opaque_paint()
        outline = getattr(self, "_dock_reveal_outline", None)
        if outline is not None and outline.isVisible() and not self._edge_dock_animating:
            # 外周線と DWM 枠を同じ更新で受け渡す（二重に見えて太くならないように）
            outline.hide()
        state = self._native_border_state()
        if not force and getattr(self, "_native_border_theme", None) == state:
            return
        self._native_border_theme = state
        try:
            from src.ui.window_polish import apply_native_window_polish, set_window_border_hidden
            # 収納中は DWM 枠を出さない（元サイズの枠だけが残るため）。展開で現在テーマへ戻す
            if state[1]:
                set_window_border_hidden(self, True)
            else:
                apply_native_window_polish(self, corner=None)
            if not force:
                return
            for w in QApplication.topLevelWidgets():
                if w is self or not w.isVisible():
                    continue
                if w.windowFlags() & Qt.WindowType.ToolTip or w.testAttribute(
                    Qt.WidgetAttribute.WA_TranslucentBackground
                ):
                    continue
                apply_native_window_polish(w, corner=None)
        except Exception:
            pass

    def _refresh_theme_icons(self) -> None:
        try:
            self._settings_btn.setIcon(make_settings_icon(_COLOR_TEXT_SECONDARY, 14))
            self._win_min_btn.setIcon(make_minimize_icon(_COLOR_SECONDARY, 12))
            if self.isMaximized():
                self._win_max_btn.setIcon(make_restore_icon(_COLOR_SECONDARY, 12))
            else:
                self._win_max_btn.setIcon(make_maximize_icon(_COLOR_SECONDARY, 12))
            self._win_close_btn.setIcon(make_close_icon(_COLOR_SECONDARY, 12))
            self._dock_chrome_chevron.setIcon(make_chevron_left_icon(_COLOR_SECONDARY, 12))
            rec = getattr(self, "_audio_recorder", None)
            if rec is not None and bool(getattr(rec, "is_recording", False)):
                self._record_btn.setIcon(make_stop_icon(_COLOR_DANGER, 14))
            else:
                self._record_btn.setIcon(make_mic_icon(_COLOR_ACCENT_SOFT, 14))
        except Exception:
            pass
        try:
            if hasattr(self, "_edge_dock_toggle_btn") and self._edge_dock_toggle_btn:
                self._edge_dock_toggle_btn.setIcon(
                    make_edge_dock_icon(_COLOR_TEXT if self._edge_dock_enabled else _COLOR_SECONDARY,
                                       14 if self._edge_dock_enabled else 12)
                )
            if hasattr(self, "_download_icon_btn") and self._download_icon_btn:
                self._download_icon_btn.refresh_theme()
            if hasattr(self, "_tab_strip") and self._tab_strip:
                self._tab_strip.refresh_theme()
            if getattr(self, "_empty_logo", None) is not None:
                self._empty_logo.refresh_theme()
        except Exception:
            pass
        # スタイルシートを置き換えた後は、継承しているテキストボタンを再 polish する
        for btn in (
            getattr(self, "_add_twitter_btn", None),
            getattr(self, "_add_column_btn", None),
            getattr(self, "_multi_post_btn", None),
        ):
            if btn is not None:
                try:
                    btn.style().unpolish(btn)
                    btn.style().polish(btn)
                    btn.update()
                except Exception:
                    pass

    def _setup_shortcuts(self) -> None:
        add_twitter_action = QAction("Add Account", self)
        add_twitter_action.setShortcut("Ctrl+N")
        add_twitter_action.triggered.connect(lambda: self._open_service_menu(False))
        self.addAction(add_twitter_action)

        go_home_action = QAction("Go Home", self)
        go_home_action.setShortcut("Ctrl+H")
        go_home_action.triggered.connect(self._go_home_focused)
        self.addAction(go_home_action)

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.addAction(exit_action)

    def _get_screen_geometry(self) -> QRect:
        screens = QGuiApplication.screens()
        if self._edge_dock_enabled:
            idx = getattr(self, "_edge_dock_monitor_index", 0)
            if 0 <= idx < len(screens):
                return screens[idx].availableGeometry()
        screen = QGuiApplication.screenAt(self.pos())
        if not screen:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _store_live_size(self, w: int, h: int, edge: str | None = None) -> None:
        if getattr(self, "_edge_dock_profile_lock", False):
            return
        edge = edge or self._edge_dock_direction
        w, h = int(w), int(h)
        lim = self.EDGE_DOCK_INDICATOR_WIDTH * 4
        try:
            screen = self._get_screen_geometry()
            max_w = max(240, int(screen.width()))
            max_h = max(180, int(screen.height()))
        except Exception:
            max_w, max_h = 10000, 10000
        if edge in ("top", "bottom"):
            if h <= lim:
                return
            self._edge_dock_width_tb = min(max(240, w), max_w)
            self._edge_dock_height_tb = min(max(180, h), max_h)
        else:
            if w <= lim:
                return
            self._edge_dock_width_lr = min(max(240, w), max_w)
            self._edge_dock_height_lr = min(max(180, h), max_h)

    def _panel_size_for_edge(self, edge: str) -> QSize:
        screen = self._get_screen_geometry()
        if edge in ("top", "bottom"):
            w = self._edge_dock_width_tb
            h = self._edge_dock_height_tb

            if not w or w <= 0:
                w = max(640, min(int(screen.width() * 0.3516), screen.width() - 40))
            if not h or h <= 0:
                h = max(360, min(int(screen.height() * 0.4757), screen.height() - 40))
        else:
            w = self._edge_dock_width_lr
            h = self._edge_dock_height_lr
            if not w or w <= 0:
                w = max(360, min(520, int(screen.width() * 0.187)))
            if not h or h <= 0:
                h = max(560, min(screen.height() - 40, int(screen.height() * 0.596)))
        w = min(max(240, int(w)), screen.width())
        h = min(max(180, int(h)), screen.height())
        return QSize(w, h)

    def _get_edge_offset(self, edge: str | None = None) -> float:
        edge = edge or self._edge_dock_direction
        offsets = getattr(self, "_edge_dock_edge_offsets", None)
        if not isinstance(offsets, dict):
            offsets = {}
        try:
            v = float(offsets.get(edge, getattr(self, "_edge_dock_edge_offset", 0.5)))
        except (TypeError, ValueError):
            v = 0.5
        return max(0.0, min(1.0, v))

    def _set_edge_offset(self, offset: float, edge: str | None = None) -> None:
        edge = edge or self._edge_dock_direction
        try:
            offset = max(0.0, min(1.0, float(offset)))
        except (TypeError, ValueError):
            offset = 0.5
        if not isinstance(getattr(self, "_edge_dock_edge_offsets", None), dict):
            self._edge_dock_edge_offsets = {
                "left": 0.5, "right": 0.5, "top": 0.5, "bottom": 0.5,
            }
        self._edge_dock_edge_offsets[edge] = offset
        if edge == self._edge_dock_direction:
            self._edge_dock_edge_offset = offset

    def _expanded_geometry_for_edge(self, edge: str, size: QSize | None = None) -> QRect:
        screen = self._get_screen_geometry()
        size = size or self._panel_size_for_edge(edge)
        offset = self._get_edge_offset(edge)
        if edge in ("left", "right"):
            usable = max(0, screen.height() - size.height())
            y = screen.top() + int(usable * offset)
            if edge == "right":
                x = screen.right() - size.width() + 1
            else:
                x = screen.left()
            return QRect(x, y, size.width(), size.height())
        usable = max(0, screen.width() - size.width())
        x = screen.left() + int(usable * offset)
        if edge == "top":
            y = screen.top()
        else:
            y = screen.bottom() - size.height() + 1
        return QRect(x, y, size.width(), size.height())

    def _lerp_rect(self, a: QRect, b: QRect, t: float) -> QRect:
        t = max(0.0, min(1.0, float(t)))
        return QRect(
            int(round(a.x() + (b.x() - a.x()) * t)),
            int(round(a.y() + (b.y() - a.y()) * t)),
            max(1, int(round(a.width() + (b.width() - a.width()) * t))),
            max(1, int(round(a.height() + (b.height() - a.height()) * t))),
        )

    def _panel_size(self) -> QSize:
        return self._panel_size_for_edge(self._edge_dock_direction)

    def _expanded_geometry(self) -> QRect:
        return self._expanded_geometry_for_edge(self._edge_dock_direction)

    def _collapsed_geometry(self) -> QRect:
        screen = self._get_screen_geometry()
        size = self._panel_size()
        edge = self._edge_dock_direction
        offset = self._get_edge_offset(edge)
        ind = self.EDGE_DOCK_INDICATOR_WIDTH

        if edge in ("left", "right"):
            usable = max(0, screen.height() - size.height())
            y = screen.top() + int(usable * offset)
            if edge == "right":
                x = screen.right() - ind + 1
            else:
                x = screen.left()
            return QRect(x, y, ind, size.height())

        usable = max(0, screen.width() - size.width())
        x = screen.left() + int(usable * offset)
        if edge == "top":
            y = screen.top()
        else:
            y = screen.bottom() - ind + 1
        return QRect(x, y, size.width(), ind)

    def _local_strip_rect(
        self,
        edge: str | None = None,
        fw: int | None = None,
        fh: int | None = None,
    ) -> QRect:
        """収納帯の矩形（ウィンドウ内座標）。

        _dock_slide_strip_geom にスクリーン座標を入れないこと。mask 計算は常にウィンドウ内座標。
        """
        edge = edge or self._edge_dock_direction
        ind = max(1, int(self.EDGE_DOCK_INDICATOR_WIDTH))
        if fw is None:
            fw = max(1, int(self.width()))
        if fh is None:
            fh = max(1, int(self.height()))
        fw, fh = max(1, int(fw)), max(1, int(fh))
        if edge == "bottom":
            return QRect(0, max(0, fh - ind), fw, ind)
        if edge == "top":
            return QRect(0, 0, fw, ind)
        if edge == "right":
            return QRect(max(0, fw - ind), 0, ind, fh)
        return QRect(0, 0, ind, fh)


    def _panel_global_rect(self) -> QRect:
        full = self._expanded_geometry()
        edge = self._edge_dock_direction
        ind = self.EDGE_DOCK_INDICATOR_WIDTH
        t = self._edge_dock_reveal_progress
        if edge == "right":
            w = max(ind, int(round(ind + (full.width() - ind) * t)))
            return QRect(full.right() - w + 1, full.top(), w, full.height())
        if edge == "left":
            w = max(ind, int(round(ind + (full.width() - ind) * t)))
            return QRect(full.left(), full.top(), w, full.height())
        if edge == "top":
            h = max(ind, int(round(ind + (full.height() - ind) * t)))
            return QRect(full.left(), full.top(), full.width(), h)
        h = max(ind, int(round(ind + (full.height() - ind) * t)))
        return QRect(full.left(), full.bottom() - h + 1, full.width(), h)

    def _setup_edge_detector(self) -> None:
        prev_det = getattr(self, "_edge_detector", None)
        if prev_det is not None:
            try:
                prev_det.stop()
            except Exception:
                pass
            try:
                prev_det.should_expand.disconnect(self._expand_edge_dock)
            except (TypeError, RuntimeError):
                pass
            try:
                prev_det.should_collapse.disconnect(self._collapse_edge_dock)
            except (TypeError, RuntimeError):
                pass
            prev_det.deleteLater()
            self._edge_detector = None
        prev_anim = getattr(self, "_edge_animator", None)
        if prev_anim is not None:
            try:
                prev_anim.stop()
            except Exception:
                pass
            try:
                prev_anim.progress_changed.disconnect(self._apply_reveal_mask)
            except (TypeError, RuntimeError):
                pass
            try:
                prev_anim.finished_expand.disconnect(self._on_expand_finished)
            except (TypeError, RuntimeError):
                pass
            try:
                prev_anim.finished_collapse.disconnect(self._on_collapse_finished)
            except (TypeError, RuntimeError):
                pass
            prev_anim.deleteLater()
            self._edge_animator = None

        self._edge_detector = EdgeDetector(
            get_panel_rect=self._panel_global_rect,
            get_screen_geometry=self._get_screen_geometry,
            edge=self._edge_dock_direction,
            trigger_px=self.EDGE_DOCK_TRIGGER_WIDTH,
            keep_open_margin=self.EDGE_DOCK_KEEP_OPEN_MARGIN,
            hide_delay_ms=self.EDGE_DOCK_HOVER_LEAVE_DELAY,
            parent=self,
        )
        self._edge_detector.should_expand.connect(self._expand_edge_dock)
        self._edge_detector.should_collapse.connect(self._collapse_edge_dock)

        self._edge_animator = EdgeAnimator(self)
        self._edge_animator.set_durations(
            int(self.EDGE_DOCK_ANIMATION_DURATION),
            int(self.EDGE_DOCK_ANIMATION_DURATION),
        )
        self._edge_animator.set_easing("OutCubic")
        self._edge_animator.progress_changed.connect(self._apply_reveal_mask)
        self._edge_animator.finished_expand.connect(self._on_expand_finished)
        self._edge_animator.finished_collapse.connect(self._on_collapse_finished)

    def _restore_edge_dock_on_startup(self) -> None:
        if self._edge_dock_enabled and self._edge_detector is not None:
            return

        saved_direction = self._edge_dock_direction
        if saved_direction not in ("left", "right", "top", "bottom"):
            saved_direction = "right"
        saved_offset = self._get_edge_offset(saved_direction)
        saved_monitor = int(getattr(self, "_edge_dock_monitor_index", 0) or 0)

        g = self.geometry()
        self._edge_dock_normal_geometry = QRect(g.x(), g.y(), g.width(), g.height())
        self._edge_dock_enabled = True
        self._edge_dock_direction = saved_direction
        self._set_edge_offset(saved_offset, saved_direction)
        self._edge_dock_monitor_index = saved_monitor
        self._edge_dock_animating = False
        self._edge_dock_revealed = True
        self._edge_dock_reveal_progress = 1.0
        try:
            self._update_stow_restore_rail()
        except Exception:
            pass

        full = self._expanded_geometry()
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        self._dock_shape_mask_key = None
        full = self._apply_dock_toplevel_geometry(full)
        self._dock_slide_full_geom = QRect(full)
        try:
            self._dock_slide_strip_geom = self._local_strip_rect(
                self._edge_dock_direction, full.width(), full.height()
            )
        except Exception:
            self._dock_slide_strip_geom = QRect(self._collapsed_geometry())
        self._apply_dock_shape_mask(full.width(), full.height(), force=True)
        try:
            self._set_dock_content_updates(True)
            self.setUpdatesEnabled(True)
        except Exception:
            pass

        self._setup_edge_detector()
        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
            self._edge_detector.set_state(PanelState.EXPANDED)
            self._edge_detector.start()

        self._set_interactive(True)
        self._set_window_opaque(True)
        # 起動復元では viewport/layout が旧Main寸法のままなので、
        # Dock余白を先に確定し、保存済みDock packを最終幅・高さで組む。
        self._apply_dock_content_insets()
        self._prestage_layout_for_target(full, dock_mode=True)
        try:
            self._set_dock_webengines_visible(True)
        except Exception:
            pass
        self._apply_edge_dock_always_on_top()
        self._apply_edge_dock_zoom()
        QTimer.singleShot(1500, self._end_edge_dock_reveal_grace)
        try:
            self._ensure_edge_dock_fs_timer()
        except Exception:
            pass
        try:
            self._ensure_dock_notify_timer()
            self._schedule_dock_notify_refresh()
        except Exception:
            pass

        self._update_edge_dock_ui()
        # 起動復元は showEvent 後に走り、setGeometry 直後は viewport が旧寸法のことがある。
        # 次のイベントループで実寸に合わせ直す。
        QTimer.singleShot(0, self._resync_dock_after_show)


    def _prelayout_dock_root_for_target(self, target: QRect) -> None:
        """top-level HWND を変える前に、clip の内側で子階層だけ最終サイズへ組む。"""
        root = getattr(self, "_edge_dock_root", None)
        if root is None:
            return
        fw = max(1, int(target.width()))
        fh = max(1, int(target.height()))
        rg = QRect(0, 0, fw, fh)
        if root.geometry() != rg:
            root.setGeometry(rg)
        try:
            lay = root.layout()
            if lay is not None:
                lay.invalidate()
                lay.setGeometry(root.rect())
                lay.activate()
                top_h = max(0, int(self._top_bar.height() if self._top_bar is not None else 0))
                if self._top_bar is not None:
                    self._top_bar.setGeometry(0, 0, fw, top_h)
                if self._scroll is not None:
                    self._scroll.setGeometry(0, top_h, fw, max(1, fh - top_h))
        except Exception:
            pass

    def _prestage_layout_for_target(
        self, target: QRect, *, dock_mode: bool, bind_columns: bool = True
    ) -> None:
        """親 HWND は旧サイズのまま、次の pack/WebView を最終サイズで先に準備する。"""
        self._prelayout_dock_root_for_target(target)
        if bind_columns:
            try:
                if dock_mode:
                    self._update_edge_dock_column_visibility()
                else:
                    self._apply_mode_column_visibility()
            except Exception:
                pass
        try:
            root = getattr(self, "_edge_dock_root", None)
            if root is not None:
                lay = root.layout()
                if lay is not None:
                    lay.invalidate()
                    lay.activate()
        except Exception:
            pass
        try:
            if self._scroll is not None:
                slay = self._scroll.layout()
                if slay is not None:
                    slay.invalidate()
                    slay.activate()
        except Exception:
            pass
        try:
            layout_width = max(1, int(target.width()))
            if dock_mode and self._scroll is not None:
                margins = self._scroll.contentsMargins()
                layout_width = max(
                    1, layout_width - int(margins.left()) - int(margins.right())
                )
            layout_height = self._column_layout_target_height(int(target.height()))
            self._fit_columns(target_width=layout_width, target_height=layout_height)
        except Exception:
            pass
        try:
            self._sync_visible_webengine_geometries()
        except Exception:
            pass
        try:
            self._update_boundary_visibility()
        except Exception:
            pass
        try:
            self._set_dock_content_updates(True)
            self._set_dock_webengines_visible(True)
        except Exception:
            pass

    def _apply_dock_toplevel_geometry(self, target: QRect, *, sync_children: bool = True) -> QRect:
        """Dock の top-level geometry と clip/root を同時に揃える。

        MW だけ先に動かすと root が旧サイズのまま描画され、黒く残る。
        縮小は clip/root → MW、拡大は MW → clip/root の順。
        """
        target = QRect(target)
        fw = max(1, int(target.width()))
        fh = max(1, int(target.height()))
        target.setWidth(fw)
        target.setHeight(fh)
        cur = QRect(self.geometry())
        clip = getattr(self, "_edge_dock_clip", None)
        root = getattr(self, "_edge_dock_root", None)

        def _sync_clip_root() -> None:
            if not sync_children:
                return
            cg = QRect(0, 0, fw, fh)
            if clip is not None and clip.geometry() != cg:
                clip.setGeometry(cg)
            if root is not None:
                if not root.isVisible():
                    try:
                        root.show()
                    except Exception:
                        pass
                if root.geometry() != cg:
                    root.setGeometry(cg)

        shrinking = fw <= max(1, cur.width()) and fh <= max(1, cur.height())
        if shrinking:
            _sync_clip_root()
            if cur != target:
                self.setGeometry(target)
            # setGeometry 中の resizeEvent 副作用後も目標に戻す
            _sync_clip_root()
        else:
            # 子階層は親より大きくできる。HWND の拡張前に WebView 側を最終サイズへ寄せる。
            if sync_children:
                self._prelayout_dock_root_for_target(target)
            if cur != target:
                self.setGeometry(target)
            _sync_clip_root()
        return QRect(self.geometry())

    def _start_edge_dock(self) -> None:
        if self._edge_dock_enabled:
            return

        try:
            self._save_columns()
            self._save_column_widths()
            if self._settings_manager and hasattr(self._settings_manager, "save_window_geometry_normal"):
                self._settings_manager.save_window_geometry_normal(self.saveGeometry())
        except Exception:
            pass

        g = self.geometry()
        self._edge_dock_normal_geometry = QRect(g.x(), g.y(), g.width(), g.height())
        self._edge_dock_enabled = True
        self._edge_dock_animating = False
        # ON 時点から展開済み（収納 strip を経由しない）
        self._edge_dock_revealed = True
        self._edge_dock_reveal_progress = 1.0
        try:
            self._update_stow_restore_rail()
        except Exception:
            pass

        if self._edge_dock_direction not in ("left", "right", "top", "bottom"):
            self._edge_dock_direction = self._detect_edge_dock_direction()
        # 最後にドラッグで決めた方向別オフセットをそのまま使う（ウィンドウ中心から再計算しない）
        self._edge_dock_edge_offset = self._get_edge_offset(self._edge_dock_direction)

        full = self._expanded_geometry()
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        # Main→Dock isolation: hide/show ではなく opacity で旧 Main を消し、Dock 最終状態を commit
        self._edge_dock_switching = True
        self._transition_isolate_begin()
        self._begin_visual_commit_gate(full)
        self._prestage_layout_for_target(full, dock_mode=True)
        try:
            self._dock_shape_mask_key = None
            full = self._apply_dock_toplevel_geometry(full)
            self._dock_slide_full_geom = QRect(full)
            self._dock_slide_strip_geom = QRect(self._collapsed_geometry())
            fw, fh = max(1, full.width()), max(1, full.height())

            self._setup_edge_detector()
            if self._edge_detector:
                self._edge_detector.set_pinned_open(True)
                self._edge_detector.set_state(PanelState.EXPANDED)
                self._edge_detector.start()

            self._set_interactive(True)
            self._set_window_opaque(True)
            self._apply_dock_content_insets()
            try:
                self._apply_dock_shape_mask(fw, fh, force=True)
            except Exception:
                pass
            self._apply_edge_dock_always_on_top()
            self._apply_edge_dock_zoom()
        finally:
            self._edge_dock_switching = False
            self._transition_isolate_commit_visible(apply_mask=True)
        # Dock ON 完了時は、旧 Main の mask と止めた updates が残ることがあるので
        # 現在の Dock サイズで mask を強制適用し、updates を戻す。
        try:
            fw = max(1, int(self.width() or 0))
            fh = max(1, int(self.height() or 0))
            self._dock_shape_mask_key = None
            if self._visual_commit_gate_active():
                self._hold_visual_commit_gate()
            elif fw > 1 and fh > 1:
                self._apply_dock_shape_mask(fw, fh, force=True)
        except Exception:
            pass
        try:
            self._set_dock_content_updates(True)
        except Exception:
            pass
        try:
            self.setUpdatesEnabled(True)
        except Exception:
            pass
        self._arm_visual_commit_gate()
        QTimer.singleShot(1500, self._end_edge_dock_reveal_grace)
        try:
            self._ensure_edge_dock_fs_timer()
        except Exception:
            pass
        try:
            self._ensure_dock_notify_timer()
            self._schedule_dock_notify_refresh()
        except Exception:
            pass
        self._update_edge_dock_ui()
        try:
            self._save_edge_dock_settings()
        except Exception:
            pass

    def _end_edge_dock_reveal_grace(self) -> None:
        if not self._edge_dock_enabled or self._edge_detector is None:
            return
        # ドラッグ/リサイズ中に pin が外れると誤って自動収納されるので、pin を維持する。
        # unpin は mouseRelease 側で行う。
        if getattr(self, "_edge_dock_dragging", False) or getattr(
            self, "_edge_dock_resizing", False
        ):
            return
        ov = getattr(self, "_column_add_overlay", None)
        if ov is not None and (
            ov.isVisible() or bool(getattr(ov, "_mayotter_fading_out", False))
        ):
            return
        self._edge_detector.set_pinned_open(False)

    def _detect_edge_dock_direction(self) -> str:
        screen = QGuiApplication.screenAt(self.pos())
        if not screen:
            screen = QGuiApplication.primaryScreen()
        geom = screen.availableGeometry()
        center = self.geometry().center()

        dist_left = center.x() - geom.left()
        dist_right = geom.right() - center.x()
        dist_top = center.y() - geom.top()
        dist_bottom = geom.bottom() - center.y()

        distances = {
            "left": dist_left,
            "right": dist_right,
            "top": dist_top,
            "bottom": dist_bottom,
        }
        return min(distances, key=distances.get)

    def _stop_edge_dock(self) -> None:
        if not self._edge_dock_enabled:
            return


        try:
            if self._edge_dock_revealed and not self._edge_dock_animating:
                self._store_live_size(
                    self.width(), self.height(), self._edge_dock_direction
                )
        except Exception:
            pass

        try:
            self._save_columns()
            self._save_column_widths()
            if self._settings_manager and hasattr(self._settings_manager, "save_window_geometry_dock"):
                self._settings_manager.save_window_geometry_dock(self.saveGeometry())
        except Exception:
            pass

        try:
            ov = getattr(self, "_column_add_overlay", None)
            if ov is not None and (
                ov.isVisible() or bool(getattr(ov, "_mayotter_fading_out", False))
            ):
                ov.close_overlay(immediate=True)
        except Exception:
            pass
        self._edge_dock_dragging = False
        self._edge_dock_drag_anchor = None
        self._edge_dock_drag_last_global_pos = None
        self._edge_dock_drag_start_direction = None
        self._edge_dock_drag_offset = None
        self._edge_dock_resizing = False
        self._edge_dock_resize_edges = ""
        self._edge_dock_resize_origin = None
        self._edge_dock_resize_geom = None
        try:
            if self.mouseGrabber() is self:
                self.releaseMouse()
        except Exception:
            pass
        try:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self._edge_cursor_forced = False
        except Exception:
            pass

        self._edge_dock_enabled = False
        self._edge_dock_revealed = False
        self._edge_dock_animating = False
        self._dock_window_lerp = False

        if self._edge_detector:
            self._edge_detector.stop()
            try:
                self._ensure_edge_dock_fs_timer()
            except Exception:
                pass
            try:
                self._ensure_dock_notify_timer()
            except Exception:
                pass
        if self._edge_animator:
            self._edge_animator.stop()

        self._edge_dock_switching = True
        try:
            self.setUpdatesEnabled(False)
            self._set_dock_content_updates(False)
        except Exception:
            pass
        try:
            self._set_window_opaque(True)
            self._set_interactive(True)

            # Dock 中に 1x1 にした最小サイズを通常ウィンドウの下限へ戻す
            self.setMinimumSize(*self._NORMAL_MIN_SIZE)
            g = self._edge_dock_normal_geometry
            self._edge_dock_normal_geometry = None
            raw_normal = None
            if g is None and self._settings_manager and hasattr(self._settings_manager, "get_window_geometry_normal"):
                try:
                    raw_normal = self._settings_manager.get_window_geometry_normal()
                except Exception:
                    raw_normal = None

            # 先に normal pack/WebView を旧 Dock viewport の裏で最終サイズへ準備する。
            if g is not None:
                self._begin_visual_commit_gate(QRect(g))
                self._prelayout_dock_root_for_target(QRect(g))

            try:
                self._apply_mode_column_visibility()
            except Exception:
                pass
            if g is not None:
                self._prestage_layout_for_target(QRect(g), dock_mode=False, bind_columns=False)
            else:
                try:
                    # raw_normal がある場合は直下の restoreGeometry 後にもう一度
                    # fit する。ここで先に fit すると旧 Dock幅基準で全カラムを
                    # resize してから正しい幅へ戻す二重作業になる。
                    if not raw_normal:
                        self._fit_columns()
                    self._sync_visible_webengine_geometries()
                except Exception:
                    pass

            # 子の Chromium surface が目標 geometry を受け取った後で HWND を最後に拡張する。
            if g is not None:
                self._apply_dock_toplevel_geometry(QRect(g))
            elif raw_normal:
                try:
                    self.restoreGeometry(raw_normal)
                    self._fit_columns()
                    self._sync_visible_webengine_geometries()
                except Exception:
                    pass

            try:
                self._set_dock_content_updates(True)
            except Exception:
                pass
            try:
                self._set_dock_webengines_visible(True)
            except Exception:
                pass
            self._window_mask_key = None
            self._window_mask_pending = False
            if self._visual_commit_gate_active():
                self._hold_visual_commit_gate()
            else:
                self._update_window_mask()

            handle = self.windowHandle()
            if handle is not None and bool(handle.flags() & Qt.WindowType.WindowStaysOnTopHint):
                handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                if sys.platform == "win32":
                    try:
                        hwnd = int(self.winId())
                        if hwnd:
                            ctypes.windll.user32.SetWindowPos(
                                hwnd, -2, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010,
                            )
                    except Exception:
                        pass
            self._hold_visual_commit_gate()
        finally:
            try:
                self._set_dock_content_updates(True)
                self.setUpdatesEnabled(True)
            except Exception:
                pass
            self._edge_dock_switching = False

        self._arm_visual_commit_gate()
        if not self._visual_commit_gate_active():
            self._resync_normal_after_dock_off()
        self._update_edge_dock_ui()
        QTimer.singleShot(0, self._update_boundary_visibility)
        try:
            self._ensure_dock_notify_timer()
            self._update_dock_notify_visual()
        except Exception:
            pass
        try:
            bubble = getattr(self, "_dock_notify_bubble", None)
            if bubble is not None:
                bubble.hide()
            self._dock_notify_busy = False
        except Exception:
            pass
        try:
            self._update_stow_restore_rail()
        except Exception:
            pass

    @staticmethod
    def _mayotter_menu_stylesheet() -> str:
        return (
            "QMenu {"
            "  background-color: #0d1524;"
            "  color: #eaf1fb;"
            "  border: 1px solid #2f517d;"
            "  border-radius: 8px;"
            "  padding: 6px;"
            "}"
            "QMenu::item {"
            "  background-color: transparent;"
            "  color: #eaf1fb;"
            "  border-radius: 4px;"
            "  padding: 6px 28px 6px 14px;"
            "}"
            "QMenu::item:selected {"
            "  background-color: rgba(148, 178, 230, 0.18);"
            "  color: #ffffff;"
            "}"
            "QMenu::item:disabled {"
            "  color: #6b7c96;"
            "}"
            "QMenu::separator {"
            "  height: 1px;"
            "  background-color: #232a38;"
            "  margin: 4px 8px;"
            "}"
            "QMenu::icon { padding-left: 6px; }"
        )

    def _style_mayotter_menu(self, menu) -> None:
        try:
            menu.setStyleSheet(self._mayotter_menu_stylesheet())
        except Exception:
            pass
        try:
            from src.ui.theme import dark_palette
            menu.setPalette(dark_palette())
        except Exception:
            try:
                from PySide6.QtGui import QPalette
                pal = menu.palette()
                for role in (
                    QPalette.ColorRole.WindowText,
                    QPalette.ColorRole.Text,
                    QPalette.ColorRole.ButtonText,
                ):
                    pal.setColor(role, themed_qcolor("#f1f3f7"))
                pal.setColor(QPalette.ColorRole.Window, themed_qcolor("#181c26"))
                pal.setColor(QPalette.ColorRole.Base, themed_qcolor("#0f1117"))
                menu.setPalette(pal)
            except Exception:
                pass

    def _show_edge_dock_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        self._style_mayotter_menu(menu)
        act_on = menu.addAction("Dock: ON" if not self._edge_dock_enabled else "Dock: OFF")
        menu.addSeparator()
        directions = [("right", "右"), ("left", "左"), ("top", "上"), ("bottom", "下")]
        dir_actions = {}
        for key, label in directions:
            act = menu.addAction(f"収納位置: {label}")
            act.setCheckable(True)
            act.setChecked(self._edge_dock_direction == key)
            dir_actions[act] = key
        chosen = menu.exec(self._edge_dock_toggle_btn.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_on:
            self._toggle_edge_dock()
            return
        if chosen in dir_actions:
            self._set_edge_dock_direction(dir_actions[chosen])

    def _visual_commit_gate_active(self) -> bool:
        gate = getattr(self, "_transition_commit_gate", None)
        return bool(gate is not None and gate.active)

    def _begin_visual_commit_gate(self, target_geometry: QRect) -> None:
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is None:
            return
        try:
            timer = getattr(self, "_normal_mask_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
        except Exception:
            pass
        try:
            gate.begin(QRect(target_geometry), self._apply_visual_commit_final_mask)
        except Exception:
            try:
                gate.cancel(finalize=False)
            except Exception:
                pass

    def _hold_visual_commit_gate(self) -> None:
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is None:
            return
        try:
            gate.hold()
        except Exception:
            pass

    def _arm_visual_commit_gate(self) -> None:
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is None or not gate.active:
            return
        webviews = []
        try:
            for col in list(getattr(self, "_columns", None) or []):
                if not col.isVisible():
                    continue
                if getattr(col, "is_individually_stowed", lambda: False)():
                    continue
                try:
                    wv = col.current_webview()
                except Exception:
                    wv = None
                if wv is None:
                    continue
                try:
                    if not wv.isVisible():
                        continue
                except Exception:
                    pass
                webviews.append(wv)
            gate.arm(webviews)
        except Exception:
            try:
                gate.cancel(finalize=True)
            except Exception:
                pass

    def _apply_visual_commit_final_mask(self) -> None:
        try:
            if self._edge_dock_enabled:
                self._dock_shape_mask_key = None
                if self._edge_dock_revealed:
                    self._apply_dock_shape_mask(force=True)
                elif self._edge_dock_direction == "bottom":
                    self._apply_reveal_mask(0.0)
                else:
                    self._apply_dock_shape_mask(force=True)
            else:
                self._resync_normal_after_dock_off()
                self._window_mask_key = None
                self._window_mask_pending = False
                self._update_window_mask()
        except Exception:
            pass

    def _transition_isolate_begin(self) -> None:
        """切替 isolation 開始。updates だけ止め、geometry/mask を同一 HWND 上で確定する。

        hide/show・opacity=0・WebEngine の setVisible(False) は黒帯や描画抜けが出るので使わない。
        """
        self.setUpdatesEnabled(False)
        try:
            self._set_dock_content_updates(False)
        except Exception:
            pass

    def _transition_isolate_commit_visible(self, *, apply_mask: bool = True) -> None:
        """最終 layout を有効化する。切替中の mask は commit gate が所有する。"""
        try:
            self._set_dock_content_updates(True)
        except Exception:
            pass
        if apply_mask:
            try:
                if self._visual_commit_gate_active():
                    self._hold_visual_commit_gate()
                elif self._edge_dock_enabled:
                    if self._edge_dock_revealed:
                        self._apply_dock_shape_mask(force=True)
                    elif self._edge_dock_direction == "bottom":
                        self._apply_reveal_mask(0.0)
                    else:
                        self._apply_dock_shape_mask(force=True)
                else:
                    self._update_window_mask()
            except Exception:
                pass
        if not self.isVisible():
            try:
                self.show()
            except Exception:
                pass
            if apply_mask:
                try:
                    if self._visual_commit_gate_active():
                        self._hold_visual_commit_gate()
                    elif self._edge_dock_enabled:
                        if self._edge_dock_revealed:
                            self._apply_dock_shape_mask(force=True)
                        elif self._edge_dock_direction == "bottom":
                            self._apply_reveal_mask(0.0)
                        else:
                            self._apply_dock_shape_mask(force=True)
                    else:
                        self._update_window_mask()
                except Exception:
                    pass
        self.setUpdatesEnabled(True)
        try:
            if abs(float(self.windowOpacity()) - 1.0) > 0.01:
                self.setWindowOpacity(1.0)
        except Exception:
            pass
        try:
            self._sync_visible_webengine_geometries()
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def _sync_visible_webengine_geometries(self) -> None:
        """可視 WE の再描画を促す。geometry は layout / fit_columns に任せ、update のみ行う。"""
        for col in list(getattr(self, "_columns", None) or []):
            try:
                if not col.isVisible():
                    continue
            except Exception:
                continue
            if hasattr(col, "_enforce_single_visible_tab"):
                try:
                    col._enforce_single_visible_tab()
                except Exception:
                    pass
            for wv in getattr(col, "webviews", lambda: [])() or []:
                try:
                    if wv is None:
                        continue
                    if wv.isVisible():
                        wv.update()
                except Exception:
                    pass


    def _layout_safe_webview_geometry(self, wv) -> None:
        """WE を親に合わせる。resize handle を覆わないよう、handle が見えていればその幅を除く。"""
        if wv is None:
            return
        parent = wv.parentWidget()
        if parent is None or not parent.size().isValid():
            return
        handle_w = 0
        try:
            is_webview_host = parent.objectName() == "webview_host"
        except Exception:
            is_webview_host = False
        if not is_webview_host:
            # findChildren 探索はしない。既存の AccountColumn._resize_handle を直接参照。
            try:
                w = parent
                while w is not None:
                    if type(w).__name__ == "AccountColumn":
                        h = getattr(w, "_resize_handle", None)
                        if h is not None and h.isVisible():
                            handle_w = max(0, int(h.width() or 0))
                        break
                    w = w.parentWidget()
            except Exception:
                handle_w = 0
        pw = max(1, parent.width())
        ph = max(1, parent.height())
        ww = max(1, pw - max(0, handle_w))
        r = QRect(0, 0, ww, ph)
        if wv.geometry() != r:
            wv.setGeometry(r)


    def _commit_dock_container_geometry(
        self, full: QRect, *, revealed: bool, keep_updates_off: bool = False
    ) -> None:
        """方向切替・サイズ確定。updates を止めたまま目標 geometry へ setGeometry し、最終 mask を適用する。

        keep_updates_off=True のときは呼び出し側が updates を戻す。
        """
        self.setUpdatesEnabled(False)
        try:
            full = self._apply_dock_toplevel_geometry(QRect(full))
            fw, fh = max(1, full.width()), max(1, full.height())
            self._dock_slide_full_geom = QRect(full)
            self._dock_slide_strip_geom = self._local_strip_rect(
                self._edge_dock_direction, fw, fh
            )
            self._edge_dock_reveal_progress = 1.0 if revealed else 0.0
            self._dock_shape_mask_key = None
            edge = self._edge_dock_direction
            if self._visual_commit_gate_active():
                self._hold_visual_commit_gate()
            elif revealed:
                try:
                    self._apply_dock_shape_mask(fw, fh, force=True)
                except Exception:
                    pass
            elif edge == "bottom":
                self._apply_reveal_mask(0.0)
            else:
                try:
                    self._apply_dock_shape_mask(fw, fh, force=True)
                except Exception:
                    pass
        finally:
            if not keep_updates_off:
                self.setUpdatesEnabled(True)

    def _set_edge_dock_direction(self, direction: str) -> None:
        """方向切替。描画済み領域を portal 化してから最終状態へ atomic commit する。"""
        if direction not in ("left", "right", "top", "bottom"):
            return
        if direction == getattr(self, "_edge_dock_direction", None) and self._edge_dock_enabled:
            return
        old_direction = getattr(self, "_edge_dock_direction", None)
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is not None and gate.busy:
            return
        if self._edge_animator is not None:
            try:
                self._edge_animator.stop()
            except Exception:
                pass
        self._edge_dock_animating = False

        if not self._edge_dock_enabled:
            self._edge_dock_direction = direction
            self._edge_dock_edge_offset = self._get_edge_offset(direction)
            self._edge_dock_column_count = self._column_count_for_edge(direction)
            if self._edge_detector:
                self._edge_detector.set_params(edge=direction)
            self._save_edge_dock_settings()
            self._update_edge_dock_ui()
            return

        try:
            size = self._panel_size_for_edge(direction)
            target = self._expanded_geometry_for_edge(direction, size)
        except Exception:
            target = QRect()

        def _commit() -> None:
            self._clear_collapse_slide_proxy()
            self._apply_edge_direction_discrete(
                direction, target_geom=target if target.isValid() else None
            )

        if gate is not None and target.isValid():
            gate.contract(
                target,
                _commit,
                source_edge=old_direction,
                target_edge=direction,
            )
        else:
            _commit()

    def _toggle_edge_dock(self) -> None:
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is not None and gate.busy:
            return

        enabled = bool(self._edge_dock_enabled)
        if enabled:
            target = QRect(self._edge_dock_normal_geometry) if self._edge_dock_normal_geometry else QRect()
        else:
            # ON 後の実際の置き場所（保存済みの Dock モニター）で目標を出す。
            # enabled=False のままだと現在いるモニターで計算され、別モニターへ向かって動いてしまう
            self._edge_dock_enabled = True
            try:
                target = QRect(self._expanded_geometry())
            except Exception:
                target = QRect()
            finally:
                self._edge_dock_enabled = False

        def _commit() -> None:
            if enabled:
                self._stop_edge_dock()
            else:
                self._start_edge_dock()
            self._save_edge_dock_settings()

        if gate is not None and target.isValid():
            gate.contract(target, _commit)
        else:
            _commit()

    def _set_interactive(self, interactive: bool) -> None:
        if hasattr(self, '_edge_dock_root') and self._edge_dock_root:
            self._edge_dock_root.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, not interactive
            )

    def _set_window_opaque(self, opaque: bool) -> None:
        opaque = bool(opaque)
        if getattr(self, "_edge_dock_opaque_fill", None) is opaque:
            return
        self._edge_dock_opaque_fill = opaque
        self.update()

    def paintEvent(self, event) -> None:
        bg_color = themed_qcolor("#0f1117")
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        dirty = event.rect()
        if self._edge_dock_animating or getattr(self, "_dock_collapse_we_active", False):
            p.fillRect(dirty, bg_color)
            self._paint_empty_logo_in_window(p)
            vis = getattr(self, "_dock_reveal_rect", None)
            if vis is not None and self._edge_dock_animating:
                # central より外側の 1px（窓の縁に接する辺）の枠。DWM 枠の代わり
                from PySide6.QtCore import QRectF
                from PySide6.QtGui import QPen
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setPen(QPen(QColor(theme_color("BORDER")), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = float(_DOCK_REVEAL_RADIUS)
                p.drawRoundedRect(QRectF(vis).adjusted(0.5, 0.5, -0.5, -0.5), r, r)
            p.end()
            return
        if getattr(self, "_edge_dock_opaque_fill", False) or self._edge_dock_revealed:
            p.fillRect(dirty, bg_color)
        else:
            ind = self.EDGE_DOCK_INDICATOR_WIDTH
            edge = self._edge_dock_direction
            fw, fh = self.width(), self.height()
            if edge == "right":
                r = QRect(fw - ind, 0, ind, fh)
            elif edge == "left":
                r = QRect(0, 0, ind, fh)
            elif edge == "bottom":
                r = QRect(0, fh - ind, fw, ind)
            else:
                r = QRect(0, 0, fw, ind)
            p.fillRect(r.intersected(dirty), bg_color)
        p.end()

    def _dock_peek_region(self, w: int, h: int, edge: str | None = None) -> QRegion:
        """収納帯/展開途中の形。大きな角丸ウィンドウの端がのぞいている見た目にする。

        帯そのものを丸めると U 字になるため、帯より大きな角丸矩形を作り、
        画面外側へ隠れる部分を切り落として「タイトルバーが少し見える」形にする。
        """
        radius = _DOCK_REVEAL_RADIUS
        edge = edge or getattr(self, "_edge_dock_direction", "right") or "right"
        w = max(1, int(w))
        h = max(1, int(h))
        ext = radius * 2
        if edge == "bottom":
            big = self._dock_outer_round_region(w, h + ext, radius, edge=edge, flags=(True, True, False, False))
            keep, shift = QRect(0, 0, w, h), (0, 0)
        elif edge == "top":
            big = self._dock_outer_round_region(w, h + ext, radius, edge=edge, flags=(False, False, True, True))
            keep, shift = QRect(0, ext, w, h), (0, -ext)
        elif edge == "left":
            big = self._dock_outer_round_region(w + ext, h, radius, edge=edge, flags=(False, True, True, False))
            keep, shift = QRect(ext, 0, w, h), (-ext, 0)
        else:
            big = self._dock_outer_round_region(w + ext, h, radius, edge=edge, flags=(True, False, False, True))
            keep, shift = QRect(0, 0, w, h), (0, 0)
        return big.intersected(QRegion(keep)).translated(*shift)

    def _mask_region_for_reveal_rect(self, r: QRect) -> QRegion:
        """見える矩形の region（ウィンドウ座標）。収納帯側は _dock_peek_region の形。"""
        if r.width() <= 0 or r.height() <= 0:
            return QRegion()
        region = self._dock_peek_region(r.width(), r.height()).translated(r.x(), r.y())
        thickness = r.height() if self._edge_dock_direction in ("top", "bottom") else r.width()
        if thickness > max(1, int(self.EDGE_DOCK_INDICATOR_WIDTH)):
            # 展開/収納の途中は接着面側の角も丸める（収納帯そのものは peek の形のまま）
            rr = max(1, min(_DOCK_REVEAL_RADIUS, r.width() // 2, r.height() // 2))
            full = self._dock_outer_round_region(
                r.width(), r.height(), rr, flags=(True, True, True, True)
            ).translated(r.x(), r.y())
            region = region.intersected(full)
        return region

    def _reveal_visible_rect(self, t: float, full: QRect, strip: QRect) -> QRect:
        edge = self._edge_dock_direction
        fw, fh = max(1, full.width()), max(1, full.height())
        t = max(0.0, min(1.0, float(t)))
        if edge in ("right", "left"):
            sw = max(1, min(strip.width(), fw))
            vis = max(1, int(sw + t * (fw - sw)))
            if edge == "right":
                return QRect(fw - vis, 0, vis, fh)
            return QRect(0, 0, vis, fh)
        sh = max(1, min(strip.height(), fh))
        vis = max(1, int(sh + t * (fh - sh)))
        if edge == "bottom":
            return QRect(0, fh - vis, fw, vis)
        return QRect(0, 0, fw, vis)

    def _apply_reveal_mask(self, t: float) -> None:
        t = max(0.0, min(1.0, float(t)))
        self._edge_dock_reveal_progress = t
        if self._visual_commit_gate_active():
            self._hold_visual_commit_gate()
            return

        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        if root is None or clip is None:
            return
        self._refresh_native_borders()
        outline = getattr(self, "_dock_reveal_outline", None)
        if outline is None:
            # central は native window なので、MainWindow 直下の子だと隠れる。central 内に置く
            host = self.centralWidget() or self
            outline = self._dock_reveal_outline = _DockRevealOutline(self, host)
        if self._edge_dock_animating:
            host = outline.parentWidget()
            outline.setGeometry(0, 0, host.width(), host.height())
            outline.show()
            outline.raise_()
            outline.refresh()
        elif outline.isVisible():
            outline.hide()

        # window_lerp: Right/Left/Top の position-slide（サイズ固定）
        # サイズは変わらないので角丸 shape mask を毎フレーム維持する。
        # clearMask は角を黒い四角に見せるため使わない
        if self._edge_dock_animating and getattr(self, "_dock_window_lerp", False):
            full = getattr(self, "_dock_slide_full_geom", None)
            strip = getattr(self, "_dock_slide_strip_geom", None)
            if full is not None and strip is not None:
                g = self._lerp_rect(strip, full, t)
                cg = self.geometry()
                if (
                    cg.x() != g.x()
                    or cg.y() != g.y()
                    or cg.width() != g.width()
                    or cg.height() != g.height()
                ):
                    if getattr(self, "_dock_geom_reenter", False):
                        return
                    self._dock_geom_reenter = True
                    try:
                        self.setGeometry(g)
                    finally:
                        self._dock_geom_reenter = False
                    try:
                        self._dock_anim_frame_n = int(getattr(self, "_dock_anim_frame_n", 0)) + 1
                    except Exception:
                        pass
                gw, gh = max(1, g.width()), max(1, g.height())
                if clip.geometry() != QRect(0, 0, gw, gh):
                    clip.setGeometry(0, 0, gw, gh)
                if not root.isVisible():
                    root.show()
                if root.geometry() != QRect(0, 0, gw, gh):
                    root.setGeometry(0, 0, gw, gh)
                # サイズ固定の position-slide: 角丸 mask を維持（clearMask 禁止）
                try:
                    self._apply_dock_shape_mask(gw, gh, force=True)
                except Exception:
                    pass
            return

        # mask reveal: Bottom（常時 full geometry + strip→full mask）
        # および非 animating 時のフォールバック
        fw = max(1, self.width())
        fh = max(1, self.height())
        if clip.geometry() != QRect(0, 0, fw, fh):
            clip.setGeometry(0, 0, fw, fh)
        if root.size() != QSize(fw, fh) or root.pos() != QPoint(0, 0):
            root.setGeometry(0, 0, fw, fh)
        if not root.isVisible():
            root.show()
        strip = getattr(self, "_dock_slide_strip_geom", None)
        if strip is None:
            ind = max(1, int(self.EDGE_DOCK_INDICATOR_WIDTH))
            edge = self._edge_dock_direction
            if edge == "bottom":
                strip = QRect(0, max(0, fh - ind), fw, ind)
            elif edge == "top":
                strip = QRect(0, 0, fw, ind)
            elif edge == "right":
                strip = QRect(max(0, fw - ind), 0, ind, fh)
            else:
                strip = QRect(0, 0, ind, fh)
        local_full = QRect(0, 0, fw, fh)
        local_strip = QRect(
            max(0, strip.x()), max(0, strip.y()),
            max(1, min(strip.width(), fw)), max(1, min(strip.height(), fh)),
        )
        r = self._reveal_visible_rect(t, local_full, local_strip)
        # 外周線は region と同じ矩形に描く（全方向。全体サイズの枠が残らないように）
        self._dock_reveal_rect = QRect(r)
        self.setMask(self._mask_region_for_reveal_rect(r))
        self._clip_floating_popups_to_reveal(r)
        outline = getattr(self, "_dock_reveal_outline", None)
        if outline is not None and outline.isVisible():
            outline.refresh()
        self.update()

    def _clip_floating_popups_to_reveal(self, reveal_local: QRect) -> None:
        """収納/展開の途中、浮遊ポップアップを本体と同じ見える矩形で切る（収納へ付いていく見た目にする）。"""
        if not self._edge_dock_animating:
            return
        reveal = reveal_local.translated(self.geometry().topLeft())
        for w in self._floating_popups():
            try:
                if not w.isVisible() or not w.isWindow():
                    continue
                if w is getattr(self, "_download_overlay", None) or w is getattr(self, "_current_service_menu", None):
                    continue  # この2つは収納開始時に畳まれ、展開後に開き直される
                vis = QRegion(w.rect()).intersected(QRegion(reveal.translated(-w.pos())))
                if not getattr(w, "_mayotter_reveal_clipped", False):
                    # DWM の枠は mask で切られず、矩形のまま取り残されるので切っている間は消す
                    from src.ui.window_polish import set_window_border_hidden
                    set_window_border_hidden(w, True)
                w.setMask(vis if not vis.isEmpty() else QRegion(0, 0, 1, 1))
                w._mayotter_reveal_clipped = True
            except Exception:
                pass

    def _unclip_floating_popups(self) -> None:
        for w in self._floating_popups():
            try:
                if getattr(w, "_mayotter_reveal_clipped", False):
                    w._mayotter_reveal_clipped = False
                    from src.ui.window_polish import set_window_border_hidden
                    set_window_border_hidden(w, False)
                    w.clearMask()
                    from src.ui.url_overlay import _apply_smooth_overlay_shape
                    if w.__class__.__module__.endswith("url_overlay"):
                        _apply_smooth_overlay_shape(w)
            except Exception:
                pass

    def _clear_collapse_slide_proxy(self) -> None:
        self._dock_window_lerp = False
        self._dock_anim_frame_n = 0
        self._dock_slide_full_geom = None
        self._dock_slide_strip_geom = None
        proxy = getattr(self, "_dock_slide_proxy", None)
        self._dock_slide_proxy = None
        if proxy is not None:
            _dispose_widget_no_toplevel(proxy)

    def _expand_edge_dock(self) -> None:
        if not self._edge_dock_enabled:
            return
        if self._edge_dock_revealed or self._edge_dock_animating:
            return
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is not None and gate.busy:
            return
        # 方向切替中は通常展開アニメを開始しない（経路分離）
        if getattr(self, "_edge_dock_switching", False) or getattr(
            self, "_edge_dock_dir_transitioning", False
        ):
            return

        if self._should_suppress_edge_expand():
            return
        self._edge_dock_animating = True
        self._edge_detector.set_state(PanelState.EXPANDING)
        self._set_interactive(True)
        try:
            if self.mouseGrabber() is self:
                self.releaseMouse()
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
        try:
            w = getattr(self, "_dock_notify_icon", None)
            if w is not None:
                w.stop_anim()
                w.hide()
        except Exception:
            pass
        self._clear_collapse_slide_proxy()

        full = self._expanded_geometry_for_edge(self._edge_dock_direction)
        edge = self._edge_dock_direction
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        self._dock_slide_full_geom = QRect(full)
        # 隣接 monitor へ HWND を出さないため、全方向で full geometry 固定 + local mask reveal を使う。
        self._dock_slide_strip_geom = self._local_strip_rect(edge, full.width(), full.height())
        self._dock_window_lerp = False
        self._edge_dock_anim_cw = max(1, full.width())
        self._edge_dock_anim_ch = max(1, full.height())
        self._edge_dock_reveal_progress = 0.0

        # 展開中は WE 非表示。finish で geometry 確定後に一度だけ表示。
        self._dock_collapse_we_active = False
        self._dock_anim_frame_n = 0
        self._set_window_opaque(True)
        try:
            self._set_dock_webengines_visible(False)
        except Exception:
            pass

        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        fw, fh = max(1, full.width()), max(1, full.height())
        full_c = QRect(0, 0, fw, fh)

        # 常時 full geometry。reveal は mask のみ。
        self.setUpdatesEnabled(False)
        try:
            # full geometry へ広げる前に full 座標系の strip mask を確立する。
            # setGeometry(full) が先だと、初回 frame だけ収納状態の内容が full 位置へ露出する。
            r0 = self._reveal_visible_rect(0.0, full_c, self._dock_slide_strip_geom)
            self.setMask(self._mask_region_for_reveal_rect(r0))
            if self.geometry() != full:
                self.setGeometry(full)
            if clip is not None and clip.geometry() != full_c:
                clip.setGeometry(full_c)
            if root is not None:
                if root.geometry() != full_c:
                    root.setGeometry(full_c)
                if not root.isVisible():
                    root.show()
        finally:
            self.setUpdatesEnabled(True)

        # count ベースで余分カラムを hide しない。
        # _edge_dock_column_count と packs 長さが一時的にずれると、
        # 既存 AccountColumn が hide されたまま「消えた」ように見える。
        # 表示可否は stowed / _bind_active_columns に任せる。
        stowed_set = set(getattr(self, "_stowed_columns", set()) or set())
        for col in self._columns:
            if col not in stowed_set:
                try:
                    if not col.isVisible():
                        col.show()
                except Exception:
                    pass
            else:
                try:
                    col.hide()
                except Exception:
                    pass
        self._update_edge_dock_column_visibility()
        try:
            self._apply_dock_content_insets()
        except Exception:
            pass
        try:
            if root is not None:
                lay = root.layout()
                if lay is not None:
                    lay.invalidate()
                    lay.activate()
            if self._scroll is not None:
                slay = self._scroll.layout()
                if slay is not None:
                    slay.invalidate()
                    slay.activate()
            self._fit_columns()
            for col in self._columns:
                if not col.isVisible():
                    continue
                for wv in getattr(col, "webviews", lambda: [])():
                    if wv is None:
                        continue
                    try:
                        self._layout_safe_webview_geometry(wv)
                    except Exception:
                        pass
                    try:
                        page = wv.page()
                        if page is not None:
                            page.setBackgroundColor(themed_qcolor("#0f1117"))
                    except Exception:
                        pass
        except Exception:
            pass
        self._set_dock_content_updates(True)
        # WE は finish まで非表示のまま（展開開始の黒四角・native surface 露出を防ぐ）
        self._edge_animator.animate_reveal(0.0, 1.0, self._edge_animator.expand_duration, True)

    def _set_dock_content_updates(self, enabled: bool) -> None:
        for w in (
            getattr(self, "_scroll", None),
            getattr(self, "_scroll_content", None),
            getattr(self, "_top_bar", None),
        ):
            if w is not None:
                try:
                    w.setUpdatesEnabled(enabled)
                except Exception:
                    pass
        for col in self._columns:
            try:
                col.setUpdatesEnabled(enabled)
            except Exception:
                pass
            for wv in getattr(col, "webviews", lambda: [])():
                try:
                    wv.setUpdatesEnabled(enabled)
                except Exception:
                    pass


    def _enforce_all_columns_single_tab(self) -> None:
        for col in self._columns:
            if hasattr(col, "_enforce_single_visible_tab"):
                try:
                    col._enforce_single_visible_tab()
                except Exception:
                    pass

    def _set_dock_webengines_visible(self, visible: bool) -> None:
        # 複数カラムを同時に起こすとき、中間フレームで index0 だけが
        # 未描画 surface として露出するのを避けるため root 単位で更新を止める。
        root = getattr(self, "_edge_dock_root", None)
        if root is not None:
            try:
                root.setUpdatesEnabled(False)
            except Exception:
                pass
        try:
            for col in self._columns:
                try:
                    if not visible:
                        for wv in getattr(col, "webviews", lambda: [])():
                            wv.setVisible(False)
                    else:
                        # 非表示 column は触らない（mode 切替で隠した列の surface を起こさない）
                        if not col.isVisible():
                            continue
                        tabs = list(getattr(col, "webviews", lambda: [])())
                        cur = int(getattr(col, "_current_tab", 0) or 0)
                        if tabs:
                            cur = max(0, min(cur, len(tabs) - 1))
                        for i, wv in enumerate(tabs):
                            if wv is None:
                                continue
                            if i == cur:
                                try:
                                    page = wv.page()
                                    if page is not None:
                                        page.setBackgroundColor(themed_qcolor("#0f1117"))
                                except Exception:
                                    pass
                        if hasattr(col, "_enforce_single_visible_tab"):
                            col._enforce_single_visible_tab()
                        else:
                            for i, wv in enumerate(tabs):
                                if wv is not None:
                                    wv.setVisible(i == cur)
                except Exception:
                    pass
        finally:
            if root is not None:
                try:
                    root.setUpdatesEnabled(True)
                except Exception:
                    pass

    def _collapse_edge_dock(self) -> None:
        if not self._edge_dock_enabled:
            return
        # 設定を開いている間は収納しない（開いたまま収納されて挙動が壊れるため）
        if getattr(self, "_settings_dialog_open", False):
            return
        # 録音中は収納しない
        rec = getattr(self, "_audio_recorder", None)
        if rec is not None and rec.is_recording:
            return
        if not self._edge_dock_revealed or self._edge_dock_animating:
            return
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is not None and gate.busy:
            return
        # 手動リサイズ中は収納しない（途中でカラムが消えるため）。
        if getattr(self, "_edge_dock_resizing", False):
            return
        # ウィンドウドラッグ中も同様。Dock ON 直後の grace 解除や keep-zone
        # 誤判定で移動中に strip 化しない（通常の自動収納自体は無効化しない）。
        if getattr(self, "_edge_dock_dragging", False):
            return
        # 方向切替中は通常収納アニメを開始しない（経路分離）
        if getattr(self, "_edge_dock_switching", False) or getattr(
            self, "_edge_dock_dir_transitioning", False
        ):
            return
        if hasattr(self, '_edge_cursor_forced') and self._edge_cursor_forced:
            from PySide6.QtWidgets import QApplication
            QApplication.restoreOverrideCursor()
            self._edge_cursor_forced = False

        self._edge_dock_animating = True
        self._edge_detector.set_state(PanelState.COLLAPSING)
        try:
            self._suspend_dock_popups()
        except Exception:
            pass
        if self._edge_animator is not None:
            self._edge_animator.stop()
        self._clear_collapse_slide_proxy()

        self._store_live_size(self.width(), self.height(), self._edge_dock_direction)
        self._snap_to_dock_edge()
        self._dock_anim_frame_n = 0
        self._set_window_opaque(True)
        self._dock_collapse_we_active = False
        self._set_dock_content_updates(False)

        edge = self._edge_dock_direction
        full = QRect(self.geometry())
        if full.width() <= self.EDGE_DOCK_INDICATOR_WIDTH * 2 or full.height() <= self.EDGE_DOCK_INDICATOR_WIDTH * 2:
            full = self._expanded_geometry_for_edge(edge)
        # 全方向で full HWND を owner screen 内に維持し、local mask だけで収納する。
        if self.geometry() != full:
            self.setGeometry(full)
        full = QRect(self.geometry())
        self._dock_slide_full_geom = QRect(full)
        self._dock_slide_strip_geom = self._local_strip_rect(
            edge, full.width(), full.height()
        )
        self._dock_window_lerp = False

        self._edge_dock_anim_cw = max(1, full.width())
        self._edge_dock_anim_ch = max(1, full.height())

        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        fw, fh = max(1, full.width()), max(1, full.height())
        if root is not None and not root.isVisible():
            root.show()
        if clip is not None:
            clip.setGeometry(0, 0, fw, fh)
        if root is not None:
            root.setGeometry(0, 0, fw, fh)
        if edge != "bottom":
            try:
                self._apply_dock_shape_mask(fw, fh, force=True)
            except Exception:
                pass

        self._edge_animator.animate_reveal(1.0, 0.0, self._edge_animator.collapse_duration, False)

    def _on_expand_finished(self) -> None:
        self._unclip_floating_popups()
        self._dock_window_lerp = False
        QTimer.singleShot(0, self._refresh_native_borders)
        self._clear_collapse_slide_proxy()
        self._edge_dock_animating = False
        self._edge_dock_anim_cw = self._edge_dock_anim_ch = 0
        self._edge_dock_revealed = True
        self._edge_detector.set_state(PanelState.EXPANDED)
        self._edge_dock_reveal_progress = 1.0
        self._set_interactive(True)
        full = self._expanded_geometry_for_edge(self._edge_dock_direction)
        if self.geometry() != full:
            self.setGeometry(full)
        fw = max(1, self.width())
        fh = max(1, self.height())
        clip = getattr(self, "_edge_dock_clip", None)
        root = getattr(self, "_edge_dock_root", None)
        if clip is not None:
            cg = QRect(0, 0, fw, fh)
            if clip.geometry() != cg:
                clip.setGeometry(cg)
        if root is not None:
            if root.size() != QSize(fw, fh) or root.pos() != QPoint(0, 0):
                root.setGeometry(0, 0, fw, fh)
            root.updateGeometry()
            lay = root.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
        # clearMask で矩形を一瞬出さない。最終角丸を直接適用する。
        try:
            self._apply_dock_shape_mask(fw, fh, force=True)
        except Exception:
            try:
                self._apply_reveal_mask(1.0)
            except Exception:
                pass
        self._snap_to_dock_edge()
        self._store_live_size(self.width(), self.height(), self._edge_dock_direction)
        self._set_window_opaque(True)
        self._set_interactive(True)
        # revealed=True 後に mode 切替 (normal→lr/tb) + stow 反映 + column show/hide
        self._update_edge_dock_column_visibility()
        # insets は fit より先。後から margin が変わると viewport 幅と column 幅がずれる
        self._apply_dock_content_insets()
        if root is not None:
            lay = root.layout()
            if lay is not None:
                lay.activate()
        # root layout activate で scroll viewport の resize が queue されるため、
        # scroll layout を明示 activate して viewport 幅を確定させる
        try:
            if self._scroll is not None:
                slay = self._scroll.layout()
                if slay is not None:
                    slay.invalidate()
                    slay.activate()
        except Exception:
            pass
        # WebEngine は geometry 確定後に再表示する（先に visible にすると黒画面が伸びる）
        if fw > self.EDGE_DOCK_INDICATOR_WIDTH * 4:
            self._fit_columns()
        try:
            for col in self._columns:
                if not col.isVisible():
                    continue
                for wv in getattr(col, "webviews", lambda: [])():
                    if wv is None:
                        continue
                    try:
                        self._layout_safe_webview_geometry(wv)
                    except Exception:
                        pass
        except Exception:
            pass
        # 最終外形確定後に root を出し、その後 WebEngine を一度だけ表示
        if root is not None and not root.isVisible():
            root.show()
        try:
            self._set_dock_content_updates(True)
        except Exception:
            pass
        try:
            self._set_dock_webengines_visible(True)
        except Exception:
            pass
        try:
            for col in self._columns:
                if not col.isVisible():
                    continue
                for wv in getattr(col, "webviews", lambda: [])():
                    if wv is None:
                        continue
                    try:
                        if not wv.updatesEnabled():
                            wv.setUpdatesEnabled(True)
                    except Exception:
                        pass
                    # native surface の再描画を促し、藍色背景が残るのを防ぐ
                    wv.update()
        except Exception:
            pass
        # fit / WebEngine geometry 確定後に境界を再同期（切替直後の 0 高さ handle を防ぐ）
        try:
            self._update_boundary_visibility()
        except Exception:
            pass
        self._apply_dock_shape_mask(force=True)
        try:
            self._resync_dock_after_show()
        except Exception:
            pass
        self._apply_edge_dock_always_on_top()
        self._apply_edge_dock_zoom()
        try:
            self._schedule_dock_notify_refresh()
        except Exception:
            pass
        try:
            self._restore_dock_popups()
        except Exception:
            pass

    def _is_foreign_fullscreen_active(self) -> bool:
        """同一モニター上の foreign fullscreen を検出する。

        Mayotter が一瞬 foreground になっても、直下のゲームを z-order で確認する。
        """
        try:
            if sys.platform != "win32":
                return False
            import ctypes
            import os
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            # 64bit では HWND/HMONITOR を c_int に切り詰めないよう型を明示する
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
            user32.GetWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = (
                wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
            )
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.IsWindowVisible.argtypes = (wintypes.HWND,)
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.IsIconic.argtypes = (wintypes.HWND,)
            user32.IsIconic.restype = wintypes.BOOL
            user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
            user32.MonitorFromWindow.restype = wintypes.HMONITOR
            try:
                dwmapi = ctypes.windll.dwmapi
            except Exception:
                dwmapi = None

            own_pid = int(os.getpid())
            fg = user32.GetForegroundWindow()
            if not fg:
                return False

            GW_HWNDNEXT = 2
            MONITOR_DEFAULTTONEAREST = 2
            DWMWA_CLOAKED = 14

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            def _pid(hwnd) -> int:
                value = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
                return int(value.value)

            def _class_name(hwnd) -> str:
                buf = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(hwnd, buf, len(buf))
                return str(buf.value or "")

            def _covers_monitor(hwnd) -> bool:
                if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                    return False
                if _pid(hwnd) == own_pid:
                    return False
                if _class_name(hwnd) in {
                    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"
                }:
                    return False
                if dwmapi is not None:
                    try:
                        cloaked = wintypes.DWORD()
                        result = dwmapi.DwmGetWindowAttribute(
                            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
                        )
                        if result == 0 and cloaked.value:
                            return False
                    except Exception:
                        pass
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return False
                ww = int(rect.right - rect.left)
                hh = int(rect.bottom - rect.top)
                if ww < 200 or hh < 200:
                    return False
                mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                    return False
                mw = int(mi.rcMonitor.right - mi.rcMonitor.left)
                mh = int(mi.rcMonitor.bottom - mi.rcMonitor.top)
                if mw <= 0 or mh <= 0:
                    return False
                tol = max(6, int(round(max(mw, mh) * 0.006)))
                return (
                    ww >= mw - tol
                    and hh >= mh - tol
                    and rect.left <= mi.rcMonitor.left + tol
                    and rect.top <= mi.rcMonitor.top + tol
                    and rect.right >= mi.rcMonitor.right - tol
                    and rect.bottom >= mi.rcMonitor.bottom - tol
                )

            if _pid(fg) != own_pid:
                return _covers_monitor(fg)

            hwnd = user32.GetWindow(fg, GW_HWNDNEXT)
            checked = 0
            while hwnd and checked < 48:
                checked += 1
                if _pid(hwnd) != own_pid and user32.IsWindowVisible(hwnd):
                    return _covers_monitor(hwnd)
                hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
            return False
        except Exception:
            return False

    def _should_suppress_edge_expand(self) -> bool:
        if not bool(getattr(self, "_edge_dock_disable_on_fullscreen", True)):
            return False
        return self._is_foreign_fullscreen_active()

    def _ensure_edge_dock_fs_timer(self) -> None:
        t = getattr(self, "_edge_dock_fs_timer", None)
        if t is None:
            t = QTimer(self)
            t.setInterval(400)
            t.timeout.connect(self._update_edge_dock_fullscreen_yield)
            self._edge_dock_fs_timer = t
        if self._edge_dock_enabled and bool(getattr(self, "_edge_dock_disable_on_fullscreen", True)):
            if not t.isActive():
                t.start()
                self._update_edge_dock_fullscreen_yield()
        else:
            t.stop()
            if getattr(self, "_edge_dock_fs_yielded", False):
                self._exit_edge_dock_fs_yield()

    def _update_edge_dock_fullscreen_yield(self) -> None:
        if not self._edge_dock_enabled or not bool(
            getattr(self, "_edge_dock_disable_on_fullscreen", True)
        ):
            if getattr(self, "_edge_dock_fs_yielded", False):
                self._exit_edge_dock_fs_yield()
            return
        fs = self._is_foreign_fullscreen_active()
        if fs and not getattr(self, "_edge_dock_fs_yielded", False):
            self._enter_edge_dock_fs_yield()
        elif (not fs) and getattr(self, "_edge_dock_fs_yielded", False):
            self._exit_edge_dock_fs_yield()

    def _enter_edge_dock_fs_yield(self) -> None:
        self._edge_dock_fs_yielded = True
        try:
            gate = getattr(self, "_transition_commit_gate", None)
            if gate is not None and gate.busy:
                gate.cancel(finalize=False)
        except Exception:
            pass

        # 先にtopmostを外す。collapse animationより先にゲームへz-orderを返す。
        try:
            handle = self.windowHandle()
            if handle is not None:
                if bool(handle.flags() & Qt.WindowType.WindowStaysOnTopHint):
                    handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                    if sys.platform == "win32":
                        try:
                            import ctypes
                            hwnd = int(self.winId())
                            if hwnd:
                                HWND_NOTOPMOST = -2
                                SWP_NOMOVE = 0x0002
                                SWP_NOSIZE = 0x0001
                                SWP_NOACTIVATE = 0x0010
                                ctypes.windll.user32.SetWindowPos(
                                    hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                                )
                        except Exception:
                            pass
            else:
                flags = self.windowFlags()
                if flags & Qt.WindowType.WindowStaysOnTopHint:
                    self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
                    if self.isVisible():
                        self.show()
        except Exception:
            pass

        try:
            if (
                self._edge_dock_revealed
                and not self._edge_dock_animating
                and not getattr(self, "_edge_dock_dragging", False)
                and not getattr(self, "_edge_dock_resizing", False)
            ):
                self._collapse_edge_dock()
        except Exception:
            pass
        try:
            self._update_dock_notify_visual()
        except Exception:
            pass

    def _exit_edge_dock_fs_yield(self) -> None:
        self._edge_dock_fs_yielded = False
        if not self._edge_dock_enabled:
            return
        try:
            self._apply_edge_dock_always_on_top()
        except Exception:
            pass
        try:
            if not self._edge_dock_revealed:
                full_c = self._expanded_geometry_for_edge(self._edge_dock_direction)
                if self.geometry() != full_c:
                    self.setGeometry(full_c)
                self._dock_slide_full_geom = QRect(full_c)
                self._dock_slide_strip_geom = QRect(self._collapsed_geometry())
                self._apply_reveal_mask(0.0)
        except Exception:
            pass
        try:
            self._update_dock_notify_visual()
        except Exception:
            pass

    def _on_collapse_finished(self) -> None:
        self._dock_window_lerp = False
        QTimer.singleShot(0, self._refresh_native_borders)
        self._dock_collapse_we_active = False
        self._clear_collapse_slide_proxy()
        self._edge_dock_animating = False
        self._edge_dock_anim_cw = self._edge_dock_anim_ch = 0
        self._edge_dock_revealed = False
        self._edge_detector.set_state(PanelState.COLLAPSED)
        self._edge_dock_reveal_progress = 0.0
        self._set_dock_content_updates(False)
        # 収納終了時点の Window は画面外にある。先に setGeometry(full) すると
        # mask 適用前に展開状態が1フレーム見えるので、内容を消してから strip サイズにする。
        try:
            self._set_dock_webengines_visible(False)
        except Exception:
            pass
        for col in self._columns:
            try:
                col.hide()
            except Exception:
                pass
        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        if root is not None:
            try:
                root.hide()
            except Exception:
                pass
        full = self._expanded_geometry_for_edge(self._edge_dock_direction)
        strip = self._collapsed_geometry()
        edge = self._edge_dock_direction
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        self.setUpdatesEnabled(False)
        try:
            if edge == "bottom":
                # Bottom: HWND は常時 full。strip mask だけ残す（次回 expand で resize 不要）。
                if self.geometry() != full:
                    self.setGeometry(full)
                fw, fh = max(1, full.width()), max(1, full.height())
                if clip is not None:
                    clip.setGeometry(0, 0, fw, fh)
                if root is not None:
                    root.setGeometry(0, 0, fw, fh)
                ind = max(1, int(self.EDGE_DOCK_INDICATOR_WIDTH))
                local_strip = QRect(0, max(0, fh - ind), fw, ind)
                self.setMask(self._mask_region_for_reveal_rect(local_strip))
                self._dock_slide_strip_geom = QRect(local_strip)
            else:
                # 他方向: indicator サイズへ直接確定。角丸は維持。
                if self.geometry() != strip:
                    self.setGeometry(strip)
                sw, sh = max(1, strip.width()), max(1, strip.height())
                if clip is not None:
                    clip.setGeometry(0, 0, sw, sh)
                if root is not None:
                    root.setGeometry(0, 0, sw, sh)
                self._dock_slide_strip_geom = QRect(strip)
                try:
                    self._apply_dock_shape_mask(sw, sh, force=True)
                except Exception:
                    pass
            self._dock_shape_mask_key = None
            self._dock_slide_full_geom = QRect(full)
            self._edge_dock_reveal_progress = 0.0
        finally:
            self.setUpdatesEnabled(True)
        self._set_window_opaque(True)
        self._set_interactive(False)
        try:
            self._schedule_dock_notify_refresh()
        except Exception:
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass
        # 収納完了後: pin解除と state 確定のうえ、トリガー上なら即展開判定
        try:
            det = self._edge_detector
            if det is not None:
                det.set_pinned_open(False)
                det._tick()
        except Exception:
            pass

    def _force_dark_scrollbars(self, area) -> None:
        from PySide6.QtGui import QPalette
        qss = (
            "QScrollBar:horizontal, QScrollBar:vertical {"
            " background: #141820; background-color: #141820; border: none; margin: 0; }"
            "QScrollBar:horizontal { height: 8px; }"
            "QScrollBar:vertical { width: 8px; }"
            "QScrollBar::groove:horizontal, QScrollBar::groove:vertical {"
            " background: #141820; background-color: #141820; border: none; }"
            "QScrollBar::handle:horizontal, QScrollBar::handle:vertical {"
            " background: #3d4a5e; background-color: #3d4a5e; border: none; border-radius: 4px; }"
            "QScrollBar::handle:horizontal { min-width: 30px; }"
            "QScrollBar::handle:vertical { min-height: 30px; }"
            "QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {"
            " background: #5a6b84; background-color: #5a6b84; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            " width: 0; height: 0; background: transparent; border: none; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            " background: #141820; background-color: #141820; }"
        )
        try:
            area.setStyleSheet((area.styleSheet() or "") + "\n" + qss)
        except Exception:
            pass
        for getter in ("horizontalScrollBar", "verticalScrollBar"):
            try:
                sb = getattr(area, getter)()
            except Exception:
                sb = None
            if sb is None:
                continue
            try:
                sb.setStyleSheet(qss)
                pal = sb.palette()
                dark = themed_qcolor("#141820")
                thumb = themed_qcolor("#3d4a5e")
                for role in (
                    QPalette.ColorRole.Window,
                    QPalette.ColorRole.Base,
                    QPalette.ColorRole.Button,
                    QPalette.ColorRole.Mid,
                    QPalette.ColorRole.Dark,
                ):
                    pal.setColor(role, dark)
                pal.setColor(QPalette.ColorRole.Button, thumb)
                pal.setColor(QPalette.ColorRole.Highlight, thumb)
                sb.setPalette(pal)
                sb.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            except Exception:
                pass

    _DOCK_UNREAD_JS = r"""
(function(){
  try {
    var t = String(document.title || '');
    if (/^\(\d+\)/.test(t)) return true;
    var sels = [
      'a[data-testid="AppTabBar_Notifications_Link"]',
      'a[href="/notifications"]',
      'a[data-testid="AppTabBar_DirectMessage_Link"]',
      'a[href="/messages"]',
      'a[data-testid="AppTabBar_Home_Link"]',
      'a[href="/home"]',
      'a[href*="/follower_requests"]',
      'a[href*="follower_requests"]',
      'a[href*="/followers"]',
      'a[data-testid*="follow"]'
    ];
    for (var s = 0; s < sels.length; s++) {
      var nodes = document.querySelectorAll(sels[s]);
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        var al = String(n.getAttribute('aria-label') || '');
        var tx = String(n.innerText || n.textContent || '');
        var blob = (al + ' ' + tx).toLowerCase();
        if (/(未読|unread)/.test(blob) && /\d/.test(blob)) return true;
        if (/\d+\s*(件|notification|message|repost|like|follow)/i.test(blob)) return true;
        if (/(フォローリクエスト|follower request|follow request|フォロワー)/.test(blob) && /\d/.test(blob)) return true;
        if (n.querySelector && n.querySelector('[data-testid$="Count"], [data-testid*="Badge"]')) {
          if (/\d/.test(tx)) return true;
        }
        var spans = n.querySelectorAll('span, div');
        for (var j = 0; j < spans.length; j++) {
          var st = String(spans[j].textContent || '').trim();
          if (/^\d+$/.test(st) && parseInt(st, 10) > 0) return true;
        }
      }
    }
    // Lightweight follow-request / new-follower cues outside nav (limited scan)
    var extra = document.querySelectorAll(
      'a[href*="follower_requests"], [data-testid*="followRequest"], [aria-label*="Follow request"], [aria-label*="フォローリクエスト"], [aria-label*="Follower request"]'
    );
    for (var k = 0; k < extra.length; k++) {
      var e = extra[k];
      var el = String(e.getAttribute('aria-label') || '') + ' ' + String(e.innerText || e.textContent || '');
      if (/\d/.test(el) || /(request|リクエスト|未読|unread)/i.test(el)) return true;
    }
  } catch (e) {}
  return false;
})()
"""

    def _ensure_dock_notify_timer(self) -> None:
        t = getattr(self, "_dock_notify_timer", None)
        if t is None:
            t = QTimer(self)
            t.setInterval(5000)
            t.timeout.connect(self._poll_dock_unread)
            self._dock_notify_timer = t
        if self._edge_dock_enabled and not getattr(self, "_edge_dock_fs_yielded", False):
            if not t.isActive():
                t.start()
                QTimer.singleShot(400, self._poll_dock_unread)
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass
        else:
            t.stop()
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass

    def _iter_x_webviews(self):
        cols = list(getattr(self, "_columns", None) or [])
        for col in cols:
            try:
                for wv in getattr(col, "webviews", lambda: [])() or []:
                    if wv is not None:
                        yield wv
            except Exception:
                continue

    def _poll_dock_unread(self) -> None:
        if not self._edge_dock_enabled or getattr(self, "_edge_dock_fs_yielded", False):
            return
        views = list(self._iter_x_webviews())
        if not views:
            if self._dock_has_unread:
                self._dock_has_unread = False
                self._update_dock_notify_visual()
            return
        state = {"pending": len(views), "any": False}

        def _one(result, st=state):
            try:
                if result is True or result == "true" or result == 1:
                    st["any"] = True
            except Exception:
                pass
            st["pending"] -= 1
            if st["pending"] <= 0:
                new_v = bool(st["any"])
                prev = bool(self._dock_has_unread)
                self._dock_has_unread = new_v
                if new_v != prev:
                    self._update_dock_notify_visual()
                elif new_v:
                    w = getattr(self, "_dock_notify_icon", None)
                    if w is None or (not w.isVisible()):
                        self._update_dock_notify_visual()

        for wv in views:
            try:
                page = wv.page()
                if page is None:
                    _one(False)
                    continue
                page.runJavaScript(self._DOCK_UNREAD_JS, _one)
            except Exception:
                _one(False)

    _DOCK_NOTIFY_COLOR = "#5b8fd6"

    def _dock_notify_visible_side(self) -> str:
        edge = str(getattr(self, "_edge_dock_direction", "right") or "right")
        if edge == "right":
            return "left"
        if edge == "left":
            return "right"
        if edge == "top":
            return "bottom"
        return "top"

    def _ensure_dock_notify_icon_widget(self):
        w = getattr(self, "_dock_notify_icon", None)
        if w is not None:
            return w
        d = int(getattr(self, "_dock_notify_sphere_d", 20) or 20)
        w = _DockNotifySphereWidget(diameter=d, color=getattr(self, "_DOCK_NOTIFY_COLOR", None) or theme_color("ACCENT_STRONG"))
        self._dock_notify_icon = w
        return w

    def _bind_dock_notify_transient(self, w) -> None:
        try:
            _ = self.winId()
            _ = w.winId()
            mh = self.windowHandle()
            wh = w.windowHandle()
            if mh is not None and wh is not None:
                if wh.transientParent() is not mh:
                    wh.setTransientParent(mh)
                on = bool(getattr(self, "_edge_dock_always_on_top", True))
                if bool(wh.flags() & Qt.WindowType.WindowStaysOnTopHint) != on:
                    wh.setFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        except Exception:
            pass

    def _dock_notify_global_pos(self, d: int) -> tuple[int, int]:
        edge = str(getattr(self, "_edge_dock_direction", "right") or "right")
        # 収納中も HWND は full のままなので self.geometry() だと位置がずれる。
        # 収納時は strip 相当の座標で置く。
        collapsed = (
            bool(self._edge_dock_enabled)
            and (not bool(self._edge_dock_revealed))
            and (not bool(getattr(self, "_edge_dock_animating", False)))
        )
        g = self._collapsed_geometry() if collapsed else self.geometry()
        half = max(1, d // 2)
        if edge == "right":
            x = g.x() - half
            y = g.y() + max(0, (g.height() - d) // 2)
        elif edge == "left":
            x = g.x() + g.width() - half
            y = g.y() + max(0, (g.height() - d) // 2)
        elif edge == "top":
            x = g.x() + max(0, (g.width() - d) // 2)
            y = g.y() + g.height() - half
        else:
            x = g.x() + max(0, (g.width() - d) // 2)
            y = g.y() - half
        return int(x), int(y)

    def _force_show_dock_notify_widget(self, w, d: int) -> None:
        self._bind_dock_notify_transient(w)
        gx, gy = self._dock_notify_global_pos(d)
        try:
            w.setWindowOpacity(1.0)
        except Exception:
            pass
        w.set_side(self._dock_notify_visible_side())
        w.set_color(getattr(self, "_DOCK_NOTIFY_COLOR", "#5b8fd6"))
        if w.width() != d or w.height() != d:
            w.setFixedSize(d, d)
        w.setGeometry(gx, gy, d, d)
        try:
            flags = w.windowFlags()
            if not (flags & Qt.WindowType.WindowTransparentForInput):
                flags |= Qt.WindowType.WindowTransparentForInput
                w.setWindowFlags(flags)
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        except Exception:
            pass
        if not w.isVisible():
            w.show()
        try:
            w.update()
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(w.winId())
                if hwnd:
                    user32 = ctypes.windll.user32
                    GWL_EXSTYLE = -20
                    WS_EX_TRANSPARENT = 0x00000020
                    WS_EX_NOACTIVATE = 0x08000000
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    SWP_NOACTIVATE = 0x0010
                    SWP_SHOWWINDOW = 0x0040
                    SWP_FRAMECHANGED = 0x0020
                    HWND_TOPMOST = -1
                    HWND_TOP = 0
                    try:
                        get_long = user32.GetWindowLongW
                        set_long = user32.SetWindowLongW
                        ex = int(get_long(hwnd, GWL_EXSTYLE))
                        ex |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
                        set_long(hwnd, GWL_EXSTYLE, ex)
                    except Exception:
                        pass
                    insert = HWND_TOPMOST if bool(getattr(self, "_edge_dock_always_on_top", True)) else HWND_TOP
                    user32.SetWindowPos(
                        hwnd, insert, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED,
                    )
            except Exception:
                pass

    def _update_dock_notify_visual(self) -> None:
        collapsed = (
            bool(self._edge_dock_enabled)
            and (not bool(self._edge_dock_revealed))
            and (not bool(getattr(self, "_edge_dock_animating", False)))
        )
        show = (
            collapsed
            and bool(self._dock_has_unread)
            and bool(getattr(self, "_dock_unread_indicator_enabled", True))
            and not bool(getattr(self, "_edge_dock_fs_yielded", False))
            and self.isVisible()
        )
        w = getattr(self, "_dock_notify_icon", None)
        if not show:
            if w is not None:
                try:
                    w.stop_anim()
                    w.hide()
                except Exception:
                    pass
            return
        d = int(getattr(self, "_dock_notify_sphere_d", 20) or 20)
        w = self._ensure_dock_notify_icon_widget()
        try:
            self._force_show_dock_notify_widget(w, d)
            w.start_anim()
        except Exception:
            import traceback
            traceback.print_exc()

    def _schedule_dock_notify_refresh(self) -> None:
        try:
            self._update_dock_notify_visual()
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._update_dock_notify_visual)
            QTimer.singleShot(50, self._update_dock_notify_visual)
        except Exception:
            pass


    def _layout_mode_key(self) -> str:
        # Dock 有効中は収納/展開に関わらず同一 pack を使う（追加が normal に逸れない）
        if self._edge_dock_enabled:
            if self._edge_dock_direction in ("top", "bottom"):
                return "tb"
            return "lr"
        return "normal"

    def _service_packs(self) -> dict:
        return self._grok_packs if self._grok_mode else self._twitter_packs


    def _bound_layout_mode_key(self) -> str:
        """現在 self._columns が実際に属している pack を返す。"""
        try:
            packs = self._service_packs()
            columns = getattr(self, "_columns", None)
            bound = getattr(self, "_bound_mode_key", None)
            if bound in ("normal", "lr", "tb") and columns is packs.get(bound):
                return bound
            for mode in ("normal", "lr", "tb"):
                if columns is packs.get(mode):
                    return mode
        except Exception:
            pass
        return self._layout_mode_key()

    def _sync_count_from_active_list(self) -> None:
        key = self._bound_layout_mode_key()
        n = max(0, len(self._columns))
        if key == "tb":
            self._edge_dock_column_count_tb = n
            self._edge_dock_column_count = self._edge_dock_column_count_tb
        elif key == "lr":
            self._edge_dock_column_count_lr = n
            self._edge_dock_column_count = self._edge_dock_column_count_lr
        else:
            self._normal_column_count = n
        self._save_edge_dock_settings()

    def _legacy_profile_path_for(self, account_id: str, *candidates: str) -> str:
        reg = self._known_accounts.get(account_id, {}) or {}
        for key in ("legacy_profile_path", "profile_path"):
            val = (reg.get(key) or "").strip()
            if val:
                return val
        for c in candidates:
            val = (c or "").strip()
            if val:
                return val
        return ""

    def _open_profile_for_account(
        self,
        account_id: str,
        *,
        legacy_path: str = "",
        create: bool = False,
    ):
        aid = (account_id or "").strip()
        if not aid:
            return None
        if create:
            return self._profile_manager.create_new(aid)
        leg = self._legacy_profile_path_for(aid, legacy_path)
        return self._profile_manager.open_existing(aid, leg or None)

    def _spawn_column_into_mode(self, mode: str, account_info: dict) -> None:
        from src.core.models import Account, Column as ColumnModel

        aid = account_info.get("account_id", "")
        if not aid:
            return
        account = Account(
            account_id=aid,
            display_name=account_info.get("display_name", ""),
            initial_url=account_info.get("initial_url", "https://x.com/"),
            profile_path="",
        )
        from src.core.models import resolve_source_url, default_column_title, migrate_column_type
        col_type = migrate_column_type(account_info.get("column_type", "home") or "home")
        source_url = resolve_source_url(col_type, account.initial_url, account_info.get("source_url", "") or "")
        if not source_url and col_type not in ("profile", "lists"):
            source_url = account.initial_url or "https://x.com/"
        title = account_info.get("title") or default_column_title(col_type, account.display_name, source_url)
        profile = self._open_profile_for_account(
            account.account_id,
            legacy_path=account_info.get("profile_path", "")
            or account_info.get("legacy_profile_path", ""),
            create=False,
        )
        if profile is None:
            self._account_add_trace(
                "profile_missing_skip_column",
                aid=account.account_id,
                mode=mode,
            )
            return
        webview = XWebView(profile)
        if source_url:
            webview._pending_restore_url = source_url
        saved_cid = (account_info.get("column_id") or "").strip()
        if saved_cid:
            column_config = ColumnModel(
                column_id=saved_cid,
                source_account_id=account.account_id,
                source_url=source_url,
                column_type=col_type,
                title=title,
                width=AccountColumn.DEFAULT_WIDTH,
            )
        else:
            column_config = ColumnModel(
                source_account_id=account.account_id,
                source_url=source_url,
                column_type=col_type,
                title=title,
                width=AccountColumn.DEFAULT_WIDTH,
            )
        column = AccountColumn(
            account_id=account.account_id,
            display_name=account.display_name,
            webview=webview,
            initial_url=source_url,
            width=column_config.width,
            column_id=column_config.column_id,
            column_type=column_config.column_type,
            title=column_config.title,
        )
        column.closed.connect(lambda cid=column.get_column_id(): self._remove_column(cid))
        column.activated.connect(lambda c=column: self._on_column_activated(c))
        column.url_edit_requested.connect(lambda c=column: self._open_url_overlay_for(c))
        column.new_tab_requested.connect(lambda url, c=column: self._on_new_tab_requested(url, c))
        column.tabs_changed.connect(self._save_columns)
        column.resized.connect(lambda w: self._save_column_widths())
        column.enabled_changed.connect(lambda e: self._save_accounts())
        column.boundary_dragged.connect(lambda delta, c=column: self._on_boundary_dragged(c, delta))
        column.boundary_drag_finished.connect(self._on_boundary_drag_finished)
        column.stow_right_requested.connect(self._stow_columns_right_of)
        column.stow_self_requested.connect(self._stow_single_column)
        column.restore_self_requested.connect(self._restore_single_column)
        column.reset_widths_requested.connect(self._reset_all_column_widths)
        column.reorder_requested.connect(
            lambda x, c=column: self._commit_column_reorder_at(c, x)
        )
        if hasattr(column, "reorder_drag_moved"):
            column.reorder_drag_moved.connect(
                lambda x, c=column: self._on_column_reorder_drag_moved(c, x)
            )
        if hasattr(column, "reorder_drag_finished"):
            column.reorder_drag_finished.connect(self._on_column_reorder_drag_finished)
        if hasattr(webview, "download_progress"):
            webview.download_progress.connect(self._on_download_progress)
        packs = self._service_packs()
        packs.setdefault(mode, []).append(column)
        try:
            host = getattr(self, "_scroll_content", None)
            if host is not None and column.parent() is not host:
                column.setParent(host)
        except Exception:
            pass
        column.hide()

    def _ensure_mode_columns(self, mode: str) -> None:
        if mode == "tb":
            target = max(0, int(self._edge_dock_column_count_tb))
        elif mode == "lr":
            target = max(0, int(self._edge_dock_column_count_lr))
        else:
            return
        packs = self._service_packs()
        lst = packs.setdefault(mode, [])
        # 既にある mode のカラムは設定のカラム数で水増ししない（+カラムで追加する）
        if lst:
            return
        try:
            if self._materialize_mode_pack_from_settings(mode):
                return
        except Exception:
            pass
        # 明示的に保存された []（ユーザーが全削除した状態）は尊重し、seed生成しない。
        # キー不存在（未初期化）のときだけ下のseed生成へ進む。
        try:
            _sm = getattr(self, "_settings_manager", None)
            if _sm is not None and hasattr(_sm, "has_columns_for_mode"):
                if bool(_sm.has_columns_for_mode(mode)):
                    return
        except Exception:
            pass
        if target <= 0:
            return
        seed = []
        for col in packs.get("normal", []):
            seed.append({
                "account_id": col.get_account_id(),
                "display_name": getattr(col, "_display_name", "") or "",
                "profile_path": "",
                "initial_url": getattr(col, "_initial_url", "https://x.com/") or "https://x.com/",
            })
        if not seed:
            seed = [a for a in self._known_accounts.values() if a.get("grok", False) == self._grok_mode]
        if not seed:
            return
        tb_types = ("home", "notifications")
        while len(lst) < target:
            info = dict(seed[0])
            if len(seed) > 1 and mode == "tb" and len(lst) >= 1:
                info = dict(seed[min(len(lst), len(seed) - 1) % len(seed)])
            reg = self._known_accounts.get(info.get("account_id", ""), {})
            if reg:
                info["legacy_profile_path"] = reg.get("legacy_profile_path", "") or reg.get("profile_path", "")
                info["initial_url"] = reg.get("initial_url", info.get("initial_url", "https://x.com/"))
                info["display_name"] = reg.get("display_name", info.get("display_name", ""))
            if mode == "tb" and len(lst) < len(tb_types):
                info["column_type"] = tb_types[len(lst)]
            elif mode == "lr" and "column_type" not in info:
                info["column_type"] = "home"
            elif mode == "normal" and "column_type" not in info:
                info["column_type"] = "home" if len(lst) == 0 else "notifications"
            self._spawn_column_into_mode(mode, info)


    def _ensure_mode_preferred_weights(self, mode: str, columns: list | None = None) -> None:
        if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
            self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
        mode = mode or "normal"
        dest = dict(self._mode_preferred_widths.get(mode) or {})
        cols = list(columns if columns is not None else (getattr(self, "_columns", None) or []))
        if not cols:
            self._preferred_widths = dict(dest)
            return

        min_w = AccountColumn.MIN_WIDTH
        default_w = float(AccountColumn.DEFAULT_WIDTH)

        # 他モード preferred を (account_id, column_type) で索引
        by_key: dict[tuple[str, str], float] = {}
        try:
            packs = self._service_packs()
        except Exception:
            packs = {}
        for m, pref in list(self._mode_preferred_widths.items()):
            if not pref:
                continue
            # 同一サービス pack のカラムで cid→account を解決
            for col in list((packs or {}).get(m) or []):
                try:
                    cid = col.get_column_id()
                    aid = str(col.get_account_id() or "")
                    try:
                        ctype = str(col.get_column_type() or "")
                    except Exception:
                        ctype = str(getattr(col, "_column_type", "") or "")
                    w = float((pref or {}).get(cid) or 0)
                    if not aid or w < min_w:
                        continue
                    by_key[(aid, ctype)] = w
                    if (aid, "") not in by_key:
                        by_key[(aid, "")] = w
                except Exception:
                    continue

        changed = False
        for col in cols:
            try:
                if getattr(col, "is_individually_stowed", lambda: False)():
                    continue
            except Exception:
                pass
            try:
                cid = col.get_column_id()
                aid = str(col.get_account_id() or "")
                try:
                    ctype = str(col.get_column_type() or "")
                except Exception:
                    ctype = str(getattr(col, "_column_type", "") or "")
            except Exception:
                continue
            if not cid:
                continue
            if float(dest.get(cid) or 0) >= min_w:
                continue
            w = float(by_key.get((aid, ctype)) or by_key.get((aid, "")) or 0)
            if w < min_w:
                try:
                    live = float(col.get_width() or 0)
                except Exception:
                    live = 0.0
                if live >= min_w:
                    w = live
                else:
                    w = default_w
            dest[cid] = w
            changed = True

        if changed or not self._mode_preferred_widths.get(mode):
            self._mode_preferred_widths[mode] = dict(dest)
        self._preferred_widths = dict(dest)

    def _hide_inactive_mode_columns(self, active_columns) -> None:
        active = set(active_columns or [])
        try:
            packs = self._service_packs()
        except Exception:
            return
        for columns in packs.values():
            for col in list(columns or []):
                if col in active:
                    continue
                try:
                    col.hide()
                except Exception:
                    pass
                self._pause_column_media(col)

    _PAUSE_MEDIA_JS = (
        "(function(){try{var ns=document.querySelectorAll('video,audio');"
        "for(var i=0;i<ns.length;i++){try{ns[i].pause();}catch(e){}}}catch(e){}})();"
    )

    def _pause_column_media(self, col) -> None:
        """非表示にしたカラムの動画・音声を止める。隠れても再生が続くのを防ぐ（Dock ON/OFF の切替など）。"""
        try:
            views = list(col.webviews() or []) if hasattr(col, "webviews") else []
        except Exception:
            views = []
        for wv in views:
            try:
                page = wv.page()
                if page is not None:
                    page.runJavaScript(self._PAUSE_MEDIA_JS)
            except Exception:
                pass

    def _bind_active_columns(self, *, skip_ensure: bool = False) -> None:
        if not hasattr(self, "_twitter_packs") or not hasattr(self, "_grok_packs"):
            self._twitter_packs = {"normal": [], "lr": [], "tb": []}
            self._grok_packs = {"normal": [], "lr": [], "tb": []}
        if not hasattr(self, "_mode_active") or self._mode_active is None:
            self._mode_active = {"normal": None, "lr": None, "tb": None}
        if self._scroll_layout is None:
            return
        key = self._layout_mode_key()
        if not skip_ensure:
            self._ensure_mode_columns(key)
        packs = self._service_packs()
        new_list = packs.setdefault(key, [])

        prev_key = getattr(self, "_bound_mode_key", None) or "normal"
        if not hasattr(self, "_mode_stowed_columns") or self._mode_stowed_columns is None:
            self._mode_stowed_columns = {"normal": [], "lr": [], "tb": []}
        if not hasattr(self, "_mode_stow_saved_widths") or self._mode_stow_saved_widths is None:
            self._mode_stow_saved_widths = {"normal": {}, "lr": {}, "tb": {}}
        try:
            cur_stowed = list(getattr(self, "_stowed_columns", None) or [])
            if cur_stowed:
                self._mode_stowed_columns[prev_key] = cur_stowed
                self._mode_stow_saved_widths[prev_key] = dict(getattr(self, "_stow_saved_widths", None) or {})
            else:
                kept = [
                    c for c in (self._mode_stowed_columns.get(prev_key) or [])
                    if c in (getattr(self, "_columns", None) or [])
                ]
                self._mode_stowed_columns[prev_key] = kept
        except Exception:
            pass

        mode_stowed = [
            c for c in (self._mode_stowed_columns.get(key) or [])
            if c in new_list
            and not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        stowed_set = set(mode_stowed)

        # 同一 mode / 同一リストなら layout の takeAt+hide+再追加を避け、WebEngine の再アタッチを防ぐ
        if (
            prev_key == key
            and getattr(self, "_columns", None) is new_list
            and getattr(self, "_bound_mode_key", None) == key
        ):
            # layout外へ残った別packのWidgetも必ず隠す。
            self._hide_inactive_mode_columns(new_list)
            self._stowed_columns = mode_stowed
            self._mode_stowed_columns[key] = list(mode_stowed)
            self._stow_saved_widths = dict(self._mode_stow_saved_widths.get(key) or {})
            if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._preferred_widths = dict(self._mode_preferred_widths.get(key) or {})
            try:
                self._ensure_mode_preferred_weights(key, self._columns)
            except Exception:
                pass
            for col in self._columns:
                if col in stowed_set:
                    col.hide()
                elif not col.isVisible():
                    col.show()

            # 起動時Dockでは空packを先にbindし、同じlistへ後からカラムが入る。
            # fast pathでもactive columnとタブ表示を同期する。
            visible = [c for c in self._columns if c not in stowed_set]
            active = getattr(self, "_active_column", None)
            if active not in visible:
                if visible:
                    self._set_active_column(visible[0])
                else:
                    self._active_column = None
                    self._clear_strip()
            else:
                self._rebuild_strip()

            # Dock切替中は top-level が旧幅のままなので fit しない。
            # 後続の _prestage_layout_for_target が正しい幅で fit する（二重 resize を避ける）。
            if not getattr(self, "_edge_dock_animating", False) and not getattr(
                self, "_edge_dock_switching", False
            ):
                self._fit_columns()
            self._update_boundary_visibility()
            self._apply_dock_content_insets()
            self._enforce_all_columns_single_tab()
            try:
                self._update_stow_restore_rail()
            except Exception:
                pass
            try:
                self._materialize_visible_pending_loads()
            except Exception:
                pass
            return

        prev_list = list(getattr(self, "_columns", None) or [])
        # pack切替ではlayoutに入っていない旧カラムも存在し得る。
        # 先に全inactive packを隠してからlayout所有を切り替える。
        self._hide_inactive_mode_columns(new_list)
        for col in prev_list:
            if col in new_list:
                continue
            try:
                col.hide()
            except Exception:
                pass

        if self._scroll_layout is not None:
            while self._scroll_layout.count():
                item = self._scroll_layout.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.hide()
                    w.setParent(self._scroll_content)

        self._columns = new_list
        if self._grok_mode:
            self._grok_columns = self._grok_packs["normal"]
        else:
            self._twitter_columns = self._twitter_packs["normal"]

        self._stowed_columns = mode_stowed
        self._mode_stowed_columns[key] = list(mode_stowed)
        self._stow_saved_widths = dict(self._mode_stow_saved_widths.get(key) or {})
        if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
            self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
        self._preferred_widths = dict(self._mode_preferred_widths.get(key) or {})
        try:
            self._ensure_mode_preferred_weights(key, self._columns)
        except Exception:
            pass

        for col in self._columns:
            self._scroll_layout.addWidget(col)
            if col in stowed_set:
                col.hide()
            else:
                col.show()

        self._hide_inactive_mode_columns(self._columns)
        self._bound_mode_key = key

        saved = self._mode_active.get(key)
        self._active_column = None
        if saved is not None and saved in self._columns and saved not in stowed_set:
            self._set_active_column(saved)
        else:
            visible = [c for c in self._columns if c not in stowed_set]
            if visible:
                self._set_active_column(visible[0])
            else:
                self._clear_strip()

        # Dock切替中の fit は上の fast path と同じ理由で省く。
        if not getattr(self, "_edge_dock_animating", False) and not getattr(
            self, "_edge_dock_switching", False
        ):
            self._fit_columns()
        self._update_boundary_visibility()
        self._apply_dock_content_insets()
        self._enforce_all_columns_single_tab()
        try:
            self._update_stow_restore_rail()
        except Exception:
            pass
        try:
            self._materialize_visible_pending_loads()
        except Exception:
            pass

    def _materialize_visible_pending_loads(self) -> None:
        for col in list(getattr(self, "_columns", None) or []):
            try:
                if not col.isVisible():
                    continue
            except Exception:
                continue
            try:
                wv = col.current_webview()
            except Exception:
                wv = None
            if wv is None:
                continue
            pending = getattr(wv, "_pending_restore_url", None)
            if not pending:
                continue
            try:
                wv._pending_restore_url = None
            except Exception:
                pass
            try:
                self._account_add_trace("nav_load_start", url=str(pending)[:80])
            except Exception:
                pass
            try:
                wv.load_url(str(pending), restore=True)
            except TypeError:
                try:
                    wv.load_url(str(pending))
                except Exception as exc:
                    try:
                        self._account_add_trace("nav_load_fail", err=repr(exc))
                    except Exception:
                        pass
            except Exception as exc:
                try:
                    self._account_add_trace("nav_load_fail", err=repr(exc))
                except Exception:
                    pass
            else:
                try:
                    self._account_add_trace("nav_load_ok", url=str(pending)[:80])
                except Exception:
                    pass

    def _apply_mode_column_visibility(self) -> None:
        self._bind_active_columns()

    def _apply_dock_content_insets(self) -> None:
        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        if not (self._edge_dock_enabled and self._edge_dock_revealed):
            scroll.setContentsMargins(0, 0, 0, 0)
            return
        rim = 1
        edge = self._edge_dock_direction
        l = t = r = b = rim
        if edge == "left":
            l = 0
        elif edge == "right":
            r = 0
        elif edge == "top":
            t = 0
        else:
            b = 0
        scroll.setContentsMargins(l, t, r, b)

    def _column_count_for_edge(self, edge: str | None = None) -> int:

        edge = edge or self._edge_dock_direction
        if edge in ("top", "bottom"):
            return max(1, int(self._edge_dock_column_count_tb))
        return max(1, int(self._edge_dock_column_count_lr))

    def _apply_edge_dock_always_on_top(self) -> None:
        if not self._edge_dock_enabled:
            return
        fullscreen_yield = bool(getattr(self, "_edge_dock_fs_yielded", False))
        if not fullscreen_yield and bool(getattr(self, "_edge_dock_disable_on_fullscreen", True)):
            fullscreen_yield = self._is_foreign_fullscreen_active()
        on = bool(self._edge_dock_always_on_top) and not fullscreen_yield
        handle = self.windowHandle()
        if handle is not None:
            has = bool(handle.flags() & Qt.WindowType.WindowStaysOnTopHint)
            if on == has:
                return
            handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, on)
            if sys.platform == "win32":
                try:
                    import ctypes
                    hwnd = int(self.winId())
                    if hwnd:
                        HWND_TOPMOST = -1
                        HWND_NOTOPMOST = -2
                        SWP_NOMOVE = 0x0002
                        SWP_NOSIZE = 0x0001
                        SWP_NOACTIVATE = 0x0010
                        insert = HWND_TOPMOST if on else HWND_NOTOPMOST
                        ctypes.windll.user32.SetWindowPos(
                            hwnd, insert, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                        )
                except Exception:
                    pass
            return

        flags = self.windowFlags()
        has = bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        if on == has:
            return
        if on:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        if self.isVisible():
            # setWindowFlags 後は再 show が必要
            self.show()
            if self._resize_filter is not None:
                try:
                    self._resize_filter._cached_win_id = int(self.winId())
                except Exception:
                    pass

    def _apply_edge_dock_zoom(self) -> None:
        if not self._edge_dock_enabled or not self._edge_dock_revealed:
            return
        factor = max(0.5, min(1.5, float(self._edge_dock_zoom_percent) / 100.0))
        for col in self._columns:
            if not col.isVisible():
                continue
            for wv in getattr(col, "webviews", lambda: [])():
                try:
                    if hasattr(wv, "setZoomFactor"):
                        wv.setZoomFactor(factor)
                    elif hasattr(wv, "page") and wv.page() is not None:
                        wv.page().setZoomFactor(factor)
                except Exception:
                    pass

    def _update_edge_dock_column_visibility(self) -> None:
        if not self._edge_dock_revealed:
            return
        self._edge_dock_column_count = self._column_count_for_edge()
        self._apply_mode_column_visibility()
        self._enforce_all_columns_single_tab()
        self._apply_edge_dock_zoom()

    def _update_resize_cursor(self, pos: QPoint) -> None:
        if not self._edge_dock_revealed or self._edge_dock_resizing:
            return
        from PySide6.QtWidgets import QApplication
        edges = self._hit_resize(pos)
        if edges:
            try:
                gp = self.mapToGlobal(pos)
            except Exception:
                gp = None
            if gp is not None and self._prefer_webview_scroll_over_resize(gp, pos, edges):
                edges = ""
        if edges:
            shape = self._cursor_for_edges(edges)
            if not getattr(self, "_edge_cursor_forced", False):
                QApplication.setOverrideCursor(shape)
                self._edge_cursor_forced = True
                self._edge_cursor_shape = shape
            elif getattr(self, "_edge_cursor_shape", None) != shape:
                QApplication.changeOverrideCursor(shape)
                self._edge_cursor_shape = shape
        else:
            if getattr(self, "_edge_cursor_forced", False):
                QApplication.restoreOverrideCursor()
                self._edge_cursor_forced = False
                self._edge_cursor_shape = None

    def _snap_to_dock_edge(self) -> None:
        g = self.geometry()
        screen = self._get_screen_geometry()
        dock = self._edge_dock_direction
        if dock == "right":
            g.moveRight(screen.right())
        elif dock == "left":
            g.moveLeft(screen.left())
        elif dock == "bottom":
            g.moveBottom(screen.bottom())
        elif dock == "top":
            g.moveTop(screen.top())
        if g != self.geometry():
            self.setGeometry(g)

    def _hit_resize(self, pos: QPoint) -> str:
        if not self._edge_dock_revealed:
            return ""
        r = self.rect()
        e = ""
        m = _RESIZE_MARGIN
        c = _RESIZE_CORNER
        dock = self._edge_dock_direction
        x, y = pos.x(), pos.y()
        w, h = r.width(), r.height()
        if x < c and y < c and dock not in ("left", "top"):
            return "LT"
        if x >= w - c and y < c and dock not in ("right", "top"):
            return "RT"
        if x < c and y >= h - c and dock not in ("left", "bottom"):
            return "LB"
        if x >= w - c and y >= h - c and dock not in ("right", "bottom"):
            return "RB"
        if x <= m and dock != "left":
            e += "L"
        elif x >= w - m and dock != "right":
            e += "R"
        if y <= m and dock != "top":
            e += "T"
        elif y >= h - m and dock != "bottom":
            e += "B"
        return e

    def _webview_scrollbar_region_at_global(self, gp) -> bool:
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            return False
        try:
            w = QApplication.widgetAt(gp)
        except Exception:
            return False
        view = None
        while w is not None:
            if isinstance(w, QWebEngineView):
                view = w
                break
            try:
                w = w.parentWidget()
            except Exception:
                break
        if view is None:
            return False
        try:
            local = view.mapFromGlobal(gp)
            vr = view.rect()
        except Exception:
            return False
        if not vr.contains(local):
            return False
        sb = 16
        if local.x() >= vr.width() - sb:
            return True
        if local.y() >= vr.height() - sb:
            return True
        return False

    def _prefer_webview_scroll_over_resize(self, gp, local, edges: str) -> bool:
        if not edges or gp is None:
            return False
        outer = 3
        near_outer = False
        if "L" in edges and local.x() <= outer:
            near_outer = True
        if "R" in edges and local.x() >= self.width() - 1 - outer:
            near_outer = True
        if "T" in edges and local.y() <= outer:
            near_outer = True
        if "B" in edges and local.y() >= self.height() - 1 - outer:
            near_outer = True
        if near_outer:
            return False
        return self._webview_scrollbar_region_at_global(gp)

    def _cursor_for_edges(self, edges: str):
        mapping = {
            "L": Qt.CursorShape.SizeHorCursor,
            "R": Qt.CursorShape.SizeHorCursor,
            "T": Qt.CursorShape.SizeVerCursor,
            "B": Qt.CursorShape.SizeVerCursor,
            "LT": Qt.CursorShape.SizeFDiagCursor,
            "RB": Qt.CursorShape.SizeFDiagCursor,
            "RT": Qt.CursorShape.SizeBDiagCursor,
            "LB": Qt.CursorShape.SizeBDiagCursor,
        }
        return mapping.get(edges, Qt.CursorShape.ArrowCursor)

    def _apply_edge_direction_discrete(
        self, direction: str, target_geom: QRect | None = None
    ) -> None:
        """方向切替（離散置換）。expand/collapse アニメは通らない。
        opacity=0 で隔離して commit → mask 維持 → opacity=1。
        """
        if direction not in ("left", "right", "top", "bottom"):
            return
        if self._edge_animator is not None:
            try:
                self._edge_animator.stop()
            except Exception:
                pass
        self._edge_dock_animating = False

        prev_anim = getattr(self, "_edge_dir_anim", None)
        if prev_anim is not None:
            try:
                prev_anim.stop()
            except Exception:
                pass
            self._edge_dir_anim = None

        self._edge_dock_dir_transitioning = True
        self._edge_dock_switching = True
        old_direction = self._edge_dock_direction

        # 切替前に「現在の展開サイズ」を旧方向プロファイルへ確定する。
        # これがないと左右系/上下系の独立記憶が、切替のたびに欠落・混線する。
        # profile_lock は store の後で立てる（lock 中は _store_live_size が no-op）。
        if (
            old_direction in ("left", "right", "top", "bottom")
            and old_direction != direction
            and self._edge_dock_revealed
            and not self._edge_dock_animating
        ):
            try:
                self._edge_dock_profile_lock = False
                self._store_live_size(self.width(), self.height(), old_direction)
            except Exception:
                pass
        self._edge_dock_profile_lock = True

        # isolation: 旧方向の絵を消してから方向を切り替える
        self._transition_isolate_begin()
        self._edge_dock_direction = direction
        self._edge_dock_edge_offset = self._get_edge_offset(direction)
        if self._edge_detector:
            self._edge_detector.set_params(edge=direction)

        try:
            root = getattr(self, "_edge_dock_root", None)
            if root is not None and not root.isVisible():
                root.show()

            self._edge_dock_column_count = self._column_count_for_edge(direction)

            if self._edge_dock_revealed:
                if target_geom is not None and target_geom.isValid():
                    full = QRect(target_geom)
                else:
                    size = self._panel_size_for_edge(direction)
                    full = self._expanded_geometry_for_edge(direction, size)
                self._begin_visual_commit_gate(full)
                self._prestage_layout_for_target(full, dock_mode=True)
                self._edge_dock_anim_cw = max(1, full.width())
                self._edge_dock_anim_ch = max(1, full.height())
                self._commit_dock_container_geometry(
                    full, revealed=True, keep_updates_off=True
                )
            else:
                full_c = self._expanded_geometry_for_edge(direction)
                self._dock_slide_full_geom = QRect(full_c)
                clip = getattr(self, "_edge_dock_clip", None)
                if direction == "bottom":
                    if self.geometry() != full_c:
                        self.setGeometry(full_c)
                    fw, fh = max(1, full_c.width()), max(1, full_c.height())
                    if clip is not None:
                        clip.setGeometry(0, 0, fw, fh)
                    if root is not None:
                        root.setGeometry(0, 0, fw, fh)
                    local_strip = self._local_strip_rect("bottom", fw, fh)
                    self._dock_slide_strip_geom = QRect(local_strip)
                    self._edge_dock_reveal_progress = 0.0
                    self.setMask(self._mask_region_for_reveal_rect(local_strip))
                else:
                    strip = self._collapsed_geometry()
                    if self.geometry() != strip:
                        self.setGeometry(strip)
                    sw, sh = max(1, strip.width()), max(1, strip.height())
                    if clip is not None:
                        clip.setGeometry(0, 0, sw, sh)
                    if root is not None:
                        root.setGeometry(0, 0, sw, sh)
                    self._dock_slide_strip_geom = self._local_strip_rect(
                        direction, sw, sh
                    )
                    self._edge_dock_reveal_progress = 0.0
                    try:
                        self._apply_dock_shape_mask(sw, sh, force=True)
                    except Exception:
                        pass
        finally:
            self._edge_dock_switching = False
            self._edge_dock_dir_transitioning = False
            self._transition_isolate_commit_visible(apply_mask=True)
            self._edge_dock_profile_lock = False

        self._save_edge_dock_settings()
        self._update_edge_dock_ui()
        # always_on_top は isolation 後に適用（setWindowFlags 再 show を避ける）
        self._apply_edge_dock_always_on_top()
        self._apply_edge_dock_zoom()
        self._arm_visual_commit_gate()

    def _resync_dock_after_show(self, *, _attempt: int = 0) -> None:
        """show 後の client 実寸で active pack / geometry / WebView を再確定する。

        起動時Dockは保存packのmaterializeとtop-level geometry確定が同じevent turnに
        重なる。viewport/rootの一時値を信じず、active packを先にbindした上で
        実Dock client寸法へ揃え、遅延layout後も不足があれば再同期する。
        """
        if not self._edge_dock_enabled or not self._edge_dock_revealed:
            return
        if getattr(self, "_edge_dock_animating", False) or getattr(self, "_edge_dock_switching", False):
            if _attempt < 6:
                QTimer.singleShot(0, lambda a=_attempt + 1: self._resync_dock_after_show(_attempt=a))
            return
        try:
            self._bind_active_columns()
        except Exception:
            pass
        fw = max(1, int(self.width() or 0))
        fh = max(1, int(self.height() or 0))
        if fw <= 1 or fh <= 1:
            if _attempt < 6:
                QTimer.singleShot(0, lambda a=_attempt + 1: self._resync_dock_after_show(_attempt=a))
            return
        clip = getattr(self, "_edge_dock_clip", None)
        root = getattr(self, "_edge_dock_root", None)
        target = QRect(0, 0, fw, fh)
        if clip is not None and clip.geometry() != target:
            clip.setGeometry(target)
        if root is not None:
            if root.geometry() != target:
                root.setGeometry(target)
            if not root.isVisible():
                root.show()
            try:
                rlay = root.layout()
                if rlay is not None:
                    rlay.invalidate()
                    rlay.setGeometry(root.rect())
                    rlay.activate()
                    top_h = max(0, int(self._top_bar.height() if self._top_bar is not None else 0))
                    if self._top_bar is not None:
                        self._top_bar.setGeometry(0, 0, fw, top_h)
                    if self._scroll is not None:
                        self._scroll.setGeometry(0, top_h, fw, max(1, fh - top_h))
            except Exception:
                pass
        try:
            if self._scroll is not None:
                slay = self._scroll.layout()
                if slay is not None:
                    slay.invalidate()
                    slay.setGeometry(self._scroll.rect())
                    slay.activate()
        except Exception:
            pass
        try:
            self._apply_dock_content_insets()
        except Exception:
            pass
        try:
            # 起動Dockではroot/viewportが旧Main幅を一瞬保持し得る。
            # ここでは確定済みtop-level Dock client幅を唯一の基準にする。
            margins = self._scroll.contentsMargins() if self._scroll is not None else None
            margin_w = (int(margins.left()) + int(margins.right())) if margins is not None else 0
            content_w = max(1, fw - margin_w)
            content_h = self._column_layout_target_height(fh)
            self._fit_columns(target_width=content_w, target_height=content_h)
            if self._scroll_content is not None:
                self._scroll_content.resize(content_w, content_h)
            if self._scroll_layout is not None and self._scroll_content is not None:
                self._scroll_layout.invalidate()
                self._scroll_layout.setGeometry(self._scroll_content.rect())
                self._scroll_layout.activate()
        except Exception:
            pass
        try:
            for col in self._layout_visible_columns():
                try:
                    clay = col.layout()
                    if clay is not None:
                        clay.invalidate()
                        clay.setGeometry(col.rect())
                        clay.activate()
                    body = getattr(col, "_body", None)
                    blay = body.layout() if body is not None else None
                    if blay is not None:
                        blay.invalidate()
                        blay.setGeometry(body.rect())
                        blay.activate()
                    host = getattr(col, "_webview_host", None)
                    if host is not None and hasattr(host, "sync_webview_geometry"):
                        host.sync_webview_geometry()
                except Exception:
                    pass
                for wv in getattr(col, "webviews", lambda: [])():
                    if wv is None:
                        continue
                    try:
                        self._layout_safe_webview_geometry(wv)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self._apply_dock_shape_mask(fw, fh, force=True)
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass
        if _attempt < 6:
            QTimer.singleShot(
                0,
                lambda a=_attempt + 1: (
                    self._resync_dock_after_show(_attempt=a)
                    if self._dock_startup_geometry_needs_resync()
                    else None
                ),
            )

    def _dock_startup_geometry_needs_resync(self) -> bool:
        """Qt の遅延 layout 処理後に Dock 内容が幅不足に戻っていないか確認する。"""
        if not self._edge_dock_enabled or not self._edge_dock_revealed:
            return False
        fw = max(1, int(self.width() or 0))
        fh = max(1, int(self.height() or 0))
        if fw <= 1 or fh <= 1:
            return True
        target = QSize(fw, fh)
        for widget in (getattr(self, "_edge_dock_clip", None), getattr(self, "_edge_dock_root", None)):
            if widget is not None and widget.size() != target:
                return True
        scroll = getattr(self, "_scroll", None)
        if scroll is None or int(scroll.width() or 0) < fw - 1:
            return True
        try:
            margins = scroll.contentsMargins()
            target_w = max(1, fw - int(margins.left()) - int(margins.right()))
        except Exception:
            target_w = fw
        visible = self._layout_visible_columns()
        if visible:
            total_w = sum(max(0, int(col.width() or 0)) for col in visible)
            if total_w < target_w - 1:
                return True
            for col in visible:
                try:
                    if getattr(col, "is_individually_stowed", lambda: False)():
                        continue
                    body = getattr(col, "_body", None)
                    host = getattr(col, "_webview_host", None)
                    cw = max(1, int(col.width() or 0))
                    if body is not None and int(body.width() or 0) < cw - 1:
                        return True
                    if body is not None and host is not None and int(host.width() or 0) < int(body.width() or 0) - 1:
                        return True
                except Exception:
                    return True
        return False

    def _resync_normal_after_dock_off(self) -> None:
        if self._edge_dock_enabled or self._edge_dock_switching:
            return
        fw = max(1, int(self.width() or 0))
        fh = max(1, int(self.height() or 0))
        if fw <= 1 or fh <= 1:
            return

        target = QRect(0, 0, fw, fh)
        clip = getattr(self, "_edge_dock_clip", None)
        root = getattr(self, "_edge_dock_root", None)
        if clip is not None and clip.geometry() != target:
            clip.setGeometry(target)
        if root is not None:
            if root.geometry() != target:
                root.setGeometry(target)
            if not root.isVisible():
                root.show()

        try:
            self._apply_mode_column_visibility()
        except Exception:
            pass

        layout = getattr(self, "_scroll_layout", None)
        expected = list(getattr(self, "_columns", None) or [])
        if layout is not None and expected:
            try:
                actual = [
                    layout.itemAt(i).widget()
                    for i in range(layout.count())
                    if layout.itemAt(i) is not None and layout.itemAt(i).widget() is not None
                ]
                if actual != expected:
                    while layout.count():
                        item = layout.takeAt(0)
                        widget = item.widget() if item is not None else None
                        if widget is not None and widget not in expected:
                            widget.hide()
                    for col in expected:
                        if col.parentWidget() is not self._scroll_content:
                            col.setParent(self._scroll_content)
                        layout.addWidget(col)
            except Exception:
                pass

        try:
            if root is not None and root.layout() is not None:
                root.layout().invalidate()
                root.layout().activate()
            if self._scroll is not None and self._scroll.layout() is not None:
                self._scroll.layout().invalidate()
                self._scroll.layout().activate()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        except Exception:
            pass
        try:
            target_width = int(self._column_layout_target_width() or 0)
            self._fit_columns(target_width=target_width if target_width > 0 else fw)
        except Exception:
            pass
        try:
            self._sync_visible_webengine_geometries()
            self._update_boundary_visibility()
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def _follow_drag(self, global_pos: QPoint) -> None:
        # 明示ドラッグ中だけ、カーソルが入った画面へDockのownerを移管する。
        # 通常の収納/展開判定では保存済みowner screen固定を維持する。
        screens = QGuiApplication.screens()
        target_screen = QGuiApplication.screenAt(global_pos)
        if target_screen is not None:
            screen = target_screen.availableGeometry()
            try:
                target_index = screens.index(target_screen)
            except ValueError:
                target_index = -1
            if target_index >= 0:
                self._edge_dock_monitor_index = target_index
        else:
            screen = self._get_screen_geometry()
        size = self.size()
        anchor = getattr(self, "_edge_dock_drag_anchor", None)
        if anchor is None:
            anchor = QPoint(size.width() // 2, min(24, max(0, size.height() - 1)))

        left = int(screen.left())
        right = int(screen.right())
        top = int(screen.top())
        bottom = int(screen.bottom())
        max_x = max(left, right - size.width() + 1)
        max_y = max(top, bottom - size.height() + 1)

        desired_x = int(global_pos.x() - anchor.x())
        desired_y = int(global_pos.y() - anchor.y())
        free_right = desired_x + size.width() - 1
        free_bottom = desired_y + size.height() - 1

        distances = {
            "left": max(0, desired_x - left),
            "right": max(0, right - free_right),
            "top": max(0, desired_y - top),
            "bottom": max(0, bottom - free_bottom),
        }

        prev = self._edge_dock_direction
        if prev not in distances:
            prev = "right"
        edge = prev
        current_distance = distances[prev]

        # 現在辺には小さな優先幅だけ与える。画面割合ベースの巨大な
        # ヒステリシスは使わず、角付近のチャタリングだけを抑える。
        switch_margin = 24
        edge_order = (prev, "left", "right", "top", "bottom")
        nearest = min(edge_order, key=lambda name: distances[name])
        if nearest != prev and distances[nearest] + switch_margin < current_distance:
            edge = nearest

        # 現在辺と隣接辺が同時に画面端へ接した角では距離が同値になる。
        # その場合だけポインタの進行方向で角を曲がる辺を決める。
        last_pos = getattr(self, "_edge_dock_drag_last_global_pos", None)
        if last_pos is not None:
            dx = int(global_pos.x() - last_pos.x())
            dy = int(global_pos.y() - last_pos.y())
            corner_slop = 6
            if current_distance <= corner_slop:
                if prev in ("top", "bottom") and abs(dx) >= abs(dy):
                    if dx < 0 and distances["left"] <= corner_slop:
                        edge = "left"
                    elif dx > 0 and distances["right"] <= corner_slop:
                        edge = "right"
                elif prev in ("left", "right") and abs(dy) >= abs(dx):
                    if dy < 0 and distances["top"] <= corner_slop:
                        edge = "top"
                    elif dy > 0 and distances["bottom"] <= corner_slop:
                        edge = "bottom"

        if edge == "left":
            x = left
            y = max(top, min(max_y, desired_y))
        elif edge == "right":
            x = max_x
            y = max(top, min(max_y, desired_y))
        elif edge == "top":
            x = max(left, min(max_x, desired_x))
            y = top
        else:
            x = max(left, min(max_x, desired_x))
            y = max_y

        self._edge_dock_profile_lock = True
        try:
            cur = self.geometry()
            if cur.x() != x or cur.y() != y:
                self.move(x, y)
        finally:
            self._edge_dock_profile_lock = False

        if edge != prev:
            self._edge_dock_direction = edge
            if self._edge_detector:
                self._edge_detector.set_params(edge=edge)
            # 接着面が変わった同じmouse-move内で外形も更新する。
            # releaseまで旧edgeのmaskを保持すると、left→bottom等で
            # 非接着側になった上角が尖ったまま追従してしまう。
            try:
                self._dock_shape_mask_key = None
                self._apply_dock_shape_mask(force=True)
            except Exception:
                pass

        if edge in ("left", "right"):
            usable = max(1, screen.height() - size.height())
            offset = (y - screen.top()) / usable
        else:
            usable = max(1, screen.width() - size.width())
            offset = (x - screen.left()) / usable
        self._edge_dock_drag_offset = max(0.0, min(1.0, float(offset)))
        self._edge_dock_drag_last_global_pos = QPoint(global_pos)

    def _update_edge_dock_ui(self) -> None:
        from PySide6.QtWidgets import QSizePolicy

        if hasattr(self, "_edge_dock_toggle_btn"):
            btn = self._edge_dock_toggle_btn
            if self._edge_dock_enabled:
                btn.setText("")
                btn.setIcon(make_edge_dock_icon(_COLOR_TEXT, 14))
                btn.setIconSize(QSize(14, 14))
                btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                btn.setMinimumSize(24, 24)
                btn.setMaximumSize(24, 24)
                btn.setFixedSize(24, 24)
                btn.setToolTip(
                    "Dock ON — クリックで無効化 / 右クリックで収納位置"
                )
                btn.setStyleSheet(
                    "QPushButton#edge_dock_toggle_btn {"
                    " background: #2a5f9e; color: #f1f3f7;"
                    " border: 1px solid #3d6aa8; border-radius: 8px;"
                    " padding: 0px; font-size: 10px; min-width: 24px; max-width: 24px;"
                    "}"
                    "QPushButton#edge_dock_toggle_btn:hover {"
                    " background: #336fba;"
                    "}"
                    "QPushButton#edge_dock_toggle_btn:pressed {"
                    " background: #1f4f88;"
                    "}"
                )
            else:

                btn.setStyleSheet("")
                btn.setMinimumSize(0, 0)
                btn.setMaximumSize(16777215, 16777215)
                btn.setSizePolicy(
                    QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
                )
                btn.setText("Dock")
                btn.setIcon(make_edge_dock_icon(_COLOR_SECONDARY, 12))
                btn.setIconSize(QSize(12, 12))
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
                btn.setToolTip(
                    "Dock を有効にする / 右クリックで収納位置"
                )

        self._sync_dock_chrome_mode()

        try:
            if self._record_btn is not None and getattr(
                self._record_btn, "property", lambda *_: None
            )("recording") == "true":
                if self._edge_dock_enabled:
                    self._record_btn.setToolButtonStyle(
                        Qt.ToolButtonStyle.ToolButtonIconOnly
                    )
                    self._record_btn.setText("")
                    self._record_btn.setFixedSize(24, 24)
                else:
                    self._record_btn.setToolButtonStyle(
                        Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                    )
                    sec = int(getattr(self, "_recording_elapsed_sec", 0) or 0)
                    m, s = divmod(sec, 60)
                    self._record_btn.setText(f"REC {m:02d}:{s:02d}")
                    self._record_btn.setFixedSize(96, 28)
        except Exception:
            pass

    def _apply_dock_chrome_layout(self) -> None:
        layout = getattr(self, "_top_bar_layout", None)
        tray = getattr(self, "_dock_chrome_tray", None)
        tray_l = getattr(self, "_dock_chrome_tray_layout", None)
        if layout is None or tray is None or tray_l is None:
            return

        docked = bool(getattr(self, "_edge_dock_enabled", False))
        narrow = self._chrome_width_stow()
        self._title_logo.setVisible(not docked and not narrow)

        dock_order = [
            getattr(self, "_add_twitter_btn", None),
            getattr(self, "_add_column_btn", None),
            getattr(self, "_multi_post_btn", None),
            getattr(self, "_download_icon_btn", None),
            getattr(self, "_record_btn", None),
            getattr(self, "_edge_dock_toggle_btn", None),
            getattr(self, "_settings_btn", None),
            getattr(self, "_win_close_btn", None),
        ]

        if docked or narrow:
            col = getattr(self, "_add_column_btn", None)
            if col is not None:
                col.setText("+C")
                col.setMinimumWidth(28)
                col.setMaximumWidth(40)
            tw = getattr(self, "_add_twitter_btn", None)
            if tw is not None:
                tw.setMinimumWidth(28)
                tw.setMaximumWidth(40)
            for w in dock_order:
                if w is None:
                    continue
                tray_l.addWidget(w)
                w.setVisible(True)
            chev = getattr(self, "_dock_chrome_chevron", None)
            if chev is not None and narrow:
                pass
            if docked:
                min_b = getattr(self, "_win_min_btn", None)
                max_b = getattr(self, "_win_max_btn", None)
                if min_b is not None:
                    min_b.setVisible(False)
                if max_b is not None:
                    max_b.setVisible(False)
            self._refresh_tab_strip_layout()
            return

        col = getattr(self, "_add_column_btn", None)
        if col is not None:
            col.setText("+ カラム")
            col.setMinimumWidth(56)
            col.setMaximumWidth(16777215)
        tw = getattr(self, "_add_twitter_btn", None)
        if tw is not None:
            tw.setMinimumWidth(40)
            tw.setMaximumWidth(16777215)

        def _put(w, stretch=0):
            if w is None:
                return
            layout.addWidget(w, stretch)
            w.setVisible(True)

        _put(getattr(self, "_add_twitter_btn", None))
        _put(getattr(self, "_add_column_btn", None))
        _put(getattr(self, "_multi_post_btn", None))
        _put(getattr(self, "_tab_strip", None), 1)
        _put(getattr(self, "_download_icon_btn", None))
        _put(getattr(self, "_record_btn", None))
        _put(getattr(self, "_edge_dock_toggle_btn", None))
        _put(getattr(self, "_dock_chrome_chevron", None))
        settings = getattr(self, "_settings_btn", None)
        if settings is not None and settings.parentWidget() is not tray:
            tray_l.addWidget(settings)
        _put(tray)
        _put(getattr(self, "_win_min_btn", None))
        _put(getattr(self, "_win_max_btn", None))
        _put(getattr(self, "_win_close_btn", None))
        chev = getattr(self, "_dock_chrome_chevron", None)
        if chev is not None:
            chev.setVisible(False)
        tray.setVisible(True)
        if settings is not None:
            settings.setVisible(True)
        self._dock_chrome_expanded = True
        self._refresh_tab_strip_layout()

    def _refresh_tab_strip_layout(self) -> None:
        """上下↔左右の切替でバーを組み直すと、タブチップの内側レイアウトと見た目が古いまま残るので作り直させる。"""
        def _refresh() -> None:
            strip = getattr(self, "_tab_strip", None)
            if strip is None:
                return
            for chip in list(getattr(strip, "_chips", None) or []):
                try:
                    chip.style().unpolish(chip)
                    chip.style().polish(chip)
                    lay = chip.layout()
                    if lay is not None:
                        lay.invalidate()
                        lay.activate()
                    chip.updateGeometry()
                    chip.repaint()
                except Exception:
                    pass
            lay = strip.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            strip.updateGeometry()
            strip.update()

        _refresh()
        # 切替直後はウィンドウ形状/マスクの更新が続くため、落ち着いた後にも描き直す
        for ms in (0, 150, 400, 900, 1500, 2200):
            QTimer.singleShot(ms, _refresh)

    def _maybe_collapse_dock_chrome(self) -> None:

        if not self._chrome_width_stow():
            return
        if getattr(self, "_edge_dock_dragging", False) or getattr(self, "_edge_dock_resizing", False):
            return
        chev = getattr(self, "_dock_chrome_chevron", None)
        tray = getattr(self, "_dock_chrome_tray", None)
        w = self.childAt(self.mapFromGlobal(QCursor.pos()))
        while w is not None:
            if w is chev or w is tray or (tray is not None and tray.isAncestorOf(w)):
                return
            w = w.parentWidget()
        self._set_dock_chrome_expanded(False)

    def _init_boundary_action_overlay(self) -> None:
        from src.ui.boundary_action_overlay import BoundaryActionOverlay

        self._boundary_action_col = None
        self._boundary_gap_active = None
        self._boundary_reset_btn = None
        self._boundary_stow_btn = None

        ov = BoundaryActionOverlay(self)
        ov.stowLeftRequested.connect(self._on_boundary_stow_left_clicked)
        ov.stowRightRequested.connect(self._on_boundary_stow_clicked)
        ov.resetRequested.connect(self._on_boundary_reset_clicked)
        ov.syncResizeCursorRequested.connect(self._sync_column_resize_cursor)
        ov.recheckHoverRequested.connect(self._recheck_boundary_hover)

        def _handoff_resize(press_x: float) -> None:
            col = getattr(self, "_boundary_action_col", None)
            self.hide_boundary_actions()
            if col is not None:
                handle = getattr(col, "_resize_handle", None)
                if handle is not None and hasattr(handle, "begin_external_drag"):
                    handle.begin_external_drag(float(press_x))

        ov.resizeHandoffRequested.connect(_handoff_resize)
        ov.hide()
        self._boundary_overlay = ov

    def _ensure_boundary_hover_poll(self) -> None:
        """hint/session 中は leave 欠落（native WebView 等）でも poll で終了できるようにする。"""
        timer = getattr(self, "_boundary_hover_poll", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(80)
            timer.timeout.connect(self._recheck_boundary_hover)
            self._boundary_hover_poll = timer
        if not timer.isActive():
            timer.start()

    def update_boundary_actions(self, cx: int, top: int, bot: int, expand: float, col) -> None:
        if getattr(self, "_boundary_dragging", False):
            self.hide_boundary_actions()
            return
        ov = getattr(self, "_boundary_overlay", None)
        if ov is None:
            return
        self._boundary_action_col = col
        t = max(0.0, min(1.0, float(expand)))
        if t > 0.02:
            self._ensure_boundary_hover_poll()

        fixed_w = 64
        if fixed_w % 2:
            fixed_w += 1
        h = max(40, int(bot) - int(top))
        x = int(cx) - fixed_w // 2
        y = int(top)
        ov.setGeometry(x, y, fixed_w, h)
        ov.set_state(int(cx), int(top), int(bot), t)
        if t > 0.02:
            ov.show()
            ov.raise_()
            try:
                ov.winId()
            except Exception:
                pass
        else:
            ov.hide()
            try:
                ov.clearMask()
                ov.setGeometry(-2000, -2000, 1, 1)
            except Exception:
                pass

    def hide_boundary_actions(self) -> None:
        self._boundary_action_col = None
        self._clear_boundary_hand_cursor()
        timer = getattr(self, "_boundary_hover_poll", None)
        if timer is not None and timer.isActive():
            timer.stop()
        ov = getattr(self, "_boundary_overlay", None)
        if ov is not None:
            ov.set_state(0, 0, 0, 0.0)
            try:
                ov.clearMask()
            except Exception:
                pass
            ov.hide()
            try:
                ov.setGeometry(-2000, -2000, 1, 1)
            except Exception:
                pass
        for b in (getattr(self, "_boundary_reset_btn", None), getattr(self, "_boundary_stow_btn", None)):
            if b is not None:
                try:
                    b.hide()
                    b.setGeometry(-2000, -2000, 1, 1)
                except Exception:
                    pass
        st = getattr(self, "_boundary_gap_active", None)
        if st:
            strip = st.get("strip")
            if strip is not None and self._scroll_layout is not None:
                try:
                    self._scroll_layout.removeWidget(strip)
                except Exception:
                    pass
                _dispose_widget_no_toplevel(strip)
            left, right = st.get("left"), st.get("right")
            if left is not None and "left_w" in st:
                try:
                    left.set_width(int(st["left_w"]), emit_signal=False)
                except Exception:
                    pass
            if right is not None and "right_w" in st:
                try:
                    right.set_width(int(st["right_w"]), emit_signal=False)
                except Exception:
                    pass
            self._boundary_gap_active = None
            try:
                self._fit_columns()
            except Exception:
                pass

    def _try_dispatch_boundary_action_from_global(self, event) -> bool:
        ov = getattr(self, "_boundary_overlay", None)
        if ov is None or not ov.isVisible() or float(getattr(ov, "_t", 0.0)) <= 0.02:
            return False
        try:
            gp = event.globalPosition().toPoint()
        except Exception:
            return False
        try:
            if hasattr(ov, "_refresh_action_rects"):
                ov._refresh_action_rects()
            local = ov.mapFromGlobal(gp)
            stow_left = getattr(ov, "_stow_left_rect", None)
            stow_right = getattr(ov, "_stow_right_rect", None) or getattr(ov, "_stow_rect", None)
            reset = getattr(ov, "_reset_rect", None)
            if stow_left is not None and stow_left.contains(local):
                self._on_boundary_stow_left_clicked()
                return True
            if stow_right is not None and stow_right.contains(local):
                self._on_boundary_stow_clicked()
                return True
            if reset is not None and reset.contains(local):
                self._on_boundary_reset_clicked()
                return True
        except Exception:
            return False
        return False

    def _update_boundary_action_cursor_from_global(self, event) -> None:
        ov = getattr(self, "_boundary_overlay", None)
        on_knob = False
        if ov is not None and ov.isVisible() and float(getattr(ov, "_t", 0.0)) > 0.02:
            try:
                gp = event.globalPosition().toPoint()
                if hasattr(ov, "_refresh_action_rects"):
                    ov._refresh_action_rects()
                local = ov.mapFromGlobal(gp)
                stow_left = getattr(ov, "_stow_left_rect", None)
                stow_right = getattr(ov, "_stow_right_rect", None) or getattr(ov, "_stow_rect", None)
                reset = getattr(ov, "_reset_rect", None)
                if stow_left is not None and stow_left.contains(local):
                    on_knob = True
                elif stow_right is not None and stow_right.contains(local):
                    on_knob = True
                elif reset is not None and reset.contains(local):
                    on_knob = True
            except Exception:
                on_knob = False
        forced = bool(getattr(self, "_boundary_hand_cursor", False))
        if on_knob and not forced:
            QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)
            self._boundary_hand_cursor = True
        elif not on_knob and forced:
            QApplication.restoreOverrideCursor()
            self._boundary_hand_cursor = False

    def _clear_boundary_hand_cursor(self) -> None:
        if getattr(self, "_boundary_hand_cursor", False):
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._boundary_hand_cursor = False

    def boundary_action_knobs_contain_global(self, global_pos) -> bool:
        """←→🔁 の実ボタン矩形上だけ。64px overlay 全体は含めない。"""
        ov = getattr(self, "_boundary_overlay", None)
        if ov is not None and ov.isVisible() and float(getattr(ov, "_t", 0.0)) > 0.02:
            try:
                if hasattr(ov, "_refresh_action_rects"):
                    ov._refresh_action_rects()
                local = ov.mapFromGlobal(global_pos)
                for attr in ("_stow_left_rect", "_stow_right_rect", "_stow_rect", "_reset_rect"):
                    r = getattr(ov, attr, None)
                    if r is not None and r.contains(local):
                        return True
            except Exception:
                pass
        for b in (getattr(self, "_boundary_reset_btn", None), getattr(self, "_boundary_stow_btn", None)):
            if b is not None and b.isVisible():
                try:
                    if b.rect().contains(b.mapFromGlobal(global_pos)):
                        return True
                except Exception:
                    pass
        return False

    def boundary_actions_contain_global(self, global_pos) -> bool:
        """Shared UI session 維持: ボタン矩形のみ（overlay 64px 全体では維持しない）。"""
        return self.boundary_action_knobs_contain_global(global_pos)

    def _cursor_over_column_resize_region(self, global_pos=None) -> bool:
        """実際の resize hit 上か。通常は中央 2px、収納はフル幅。共有UI hover 幅は含めない。"""
        from PySide6.QtGui import QCursor
        pos = global_pos if global_pos is not None else QCursor.pos()
        for col in getattr(self, "_columns", None) or []:
            h = getattr(col, "_resize_handle", None)
            if h is None or not h.isVisible():
                continue
            try:
                local = h.mapFromGlobal(pos)
                if not h.rect().contains(local):
                    continue
                stowed = getattr(col, "is_individually_stowed", lambda: False)()
                if stowed:
                    return True
                # 通常境界: 中央 2px のみ
                hit = getattr(h, "_local_in_resize_hit", None)
                if callable(hit):
                    return bool(hit(local.x()))
                cx = h.width() // 2
                return abs(int(local.x()) - cx) <= 1
            except Exception:
                continue
        return False

    def _sync_column_resize_cursor(self) -> None:
        """resize 可能座標では SizeHor を維持。Widget 跨ぎの一瞬 Arrow を防ぐ。

        子 leave → 隣接 enter の隙間で child が Arrow に戻しても、
        ウィンドウ側の cursor が SizeHor のままなので視覚的に途切れない。
        """
        if getattr(self, "_boundary_dragging", False):
            try:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            except Exception:
                pass
            return
        if self._cursor_over_column_resize_region():
            try:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            except Exception:
                pass
            return
        try:
            self.unsetCursor()
        except Exception:
            pass

    def _recheck_boundary_hover(self) -> None:
        """カーソルが handle / overlay session から完全に離れたときだけ閉じる。

        QWebEngineView（native）へ入ると leaveEvent が欠けることがあるため、
        poll からも同じ終了条件を適用する。resize/reset を待たずに青を消す。
        """
        if getattr(self, "_boundary_dragging", False):
            return
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        over_handle = None
        for col in getattr(self, "_columns", []) or []:
            h = getattr(col, "_resize_handle", None)
            if h is None or not h.isVisible():
                continue
            try:
                if h.rect().contains(h.mapFromGlobal(pos)):
                    over_handle = h
                    break
            except Exception:
                pass
            strip = getattr(col, "_shared_ui_hover_strip", None)
            if strip is not None and strip.isVisible():
                try:
                    if strip.rect().contains(strip.mapFromGlobal(pos)):
                        over_handle = h
                        if (
                            not getattr(h, "_actions_visible", False)
                            or float(getattr(h, "_expand", 0.0) or 0.0) < 0.99
                        ):
                            h._show_actions(True)
                        break
                except Exception:
                    pass
        over_actions = self.boundary_actions_contain_global(pos)
        if over_handle is not None or over_actions:
            try:
                self._sync_column_resize_cursor()
            except Exception:
                pass
            # session 継続。他ハンドルのローカル hint だけ掃除（overlay は触らない）
            for col in getattr(self, "_columns", []) or []:
                h = getattr(col, "_resize_handle", None)
                if h is None or h is over_handle:
                    continue
                try:
                    if getattr(h, "_hint", False) or getattr(h, "_actions_visible", False):
                        if getattr(h, "_expand_anim", None) is not None:
                            h._expand_anim.stop()
                        h._actions_visible = False
                        h._expand = 0.0
                        h.set_hint(False)
                except Exception:
                    pass
            return
        # session 終了: 共有 overlay と全ハンドルの青を確実に消す
        self.hide_boundary_actions()
        for col in getattr(self, "_columns", []) or []:
            h = getattr(col, "_resize_handle", None)
            if h is None:
                continue
            try:
                if getattr(h, "_expand_anim", None) is not None:
                    h._expand_anim.stop()
                h._actions_visible = False
                h._expand = 0.0
                h.set_hint(False)
            except Exception:
                pass
        try:
            self._sync_column_resize_cursor()
        except Exception:
            pass

    def _on_boundary_reset_clicked(self) -> None:
        self.hide_boundary_actions()
        self._reset_all_column_widths()

    def _on_boundary_stow_left_clicked(self) -> None:
        col = getattr(self, "_boundary_action_col", None)
        self.hide_boundary_actions()
        if col is not None:
            self._stow_columns_left_of(col)

    def _on_boundary_stow_clicked(self) -> None:
        col = getattr(self, "_boundary_action_col", None)
        self.hide_boundary_actions()
        if col is not None:
            self._stow_columns_right_of(col)

    def _chrome_width_stow(self) -> bool:
        return int(self.width()) <= 330

    def _set_dock_chrome_expanded(self, expanded: bool) -> None:
        narrow = self._chrome_width_stow()
        if not narrow:
            expanded = True
        was = getattr(self, "_dock_chrome_expanded", True)
        self._dock_chrome_expanded = bool(expanded)
        tray = getattr(self, "_dock_chrome_tray", None)
        chev = getattr(self, "_dock_chrome_chevron", None)
        if narrow:
            if tray is not None:
                tray.setVisible(self._dock_chrome_expanded)
            if chev is not None:
                chev.setVisible(not self._dock_chrome_expanded)
            if self._dock_chrome_expanded and not was:
                try:
                    self._apply_dock_chrome_layout()
                except Exception:
                    pass
        else:
            if tray is not None:
                tray.setVisible(True)
            if chev is not None:
                chev.setVisible(False)
        if getattr(self, "_edge_dock_enabled", False):
            min_b = getattr(self, "_win_min_btn", None)
            max_b = getattr(self, "_win_max_btn", None)
            if min_b is not None:
                min_b.setVisible(False)
            if max_b is not None:
                max_b.setVisible(False)

    def _sync_dock_chrome_mode(self) -> None:
        self._apply_dock_chrome_layout()
        if self._chrome_width_stow():
            self._set_dock_chrome_expanded(False)
        else:
            self._set_dock_chrome_expanded(True)

    def _update_chrome_by_window_width(self) -> None:
        narrow = self._chrome_width_stow()
        prev = getattr(self, "_chrome_narrow_prev", None)
        if prev is narrow:
            return
        self._chrome_narrow_prev = narrow
        self._sync_dock_chrome_mode()

    def _hold_edge_dock_for_ui(self, hold: bool) -> None:
        det = getattr(self, "_edge_detector", None)
        if det is not None:
            det.set_pinned_open(bool(hold))

    def _open_settings_dialog(self) -> None:
        self._settings_dialog_open = True
        self._hold_edge_dock_for_ui(True)
        try:
            self._open_settings_dialog_impl()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            try:
                self._show_settings_error_dialog(f"設定画面を開けませんでした:\n{exc}")
            except Exception:
                pass
        finally:
            self._settings_dialog_open = False
            self._hold_edge_dock_for_ui(False)

    def _show_settings_error_dialog(self, text: str) -> None:
        """設定オープン失敗時の通知を他ダイアログと統一した見た目で出す。

        ネイティブのタイトルバーを持たない角丸ダイアログにする。
        """
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget
        from src.ui.theme import apply_overlay_theme
        dlg = QDialog(self)
        dlg.setObjectName("mayotter_settings_error_dialog")
        dlg.setModal(True)
        dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            apply_overlay_theme(dlg)
        except Exception:
            pass
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        surface = QWidget(dlg)
        surface.setObjectName("mayotter_settings_error_surface")
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(surface)
        lay = QVBoxLayout(surface)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        title_lbl = QLabel("設定")
        title_lbl.setObjectName("settings_error_title")
        lay.addWidget(title_lbl)
        msg_lbl = QLabel(text)
        msg_lbl.setObjectName("settings_error_message")
        msg_lbl.setWordWrap(True)
        lay.addWidget(msg_lbl)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QToolButton()
        ok_btn.setText("閉じる")
        ok_btn.setObjectName("settings_error_ok_btn")
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)
        try:
            dlg.adjustSize()
        except Exception:
            pass
        dlg.exec()

    def _open_settings_dialog_impl(self) -> None:
        from PySide6.QtWidgets import (
            QDialog, QFormLayout, QDialogButtonBox, QCheckBox, QLineEdit, QVBoxLayout, QGroupBox, QRadioButton, QLabel, QHBoxLayout, QToolButton,
        )
        from PySide6.QtCore import QObject, QEvent
        dlg = QDialog(self)
        dlg.setObjectName("mayotter_settings_dialog")
        dlg.setWindowTitle("設定")
        dlg.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dlg.setMinimumWidth(720)
        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(dlg)
        except Exception:
            try:
                from src.ui.theme import overlay_stylesheet
                dlg.setStyleSheet(overlay_stylesheet())
            except Exception:
                pass

        root = QVBoxLayout(dlg)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        title_row = QHBoxLayout()
        title_lbl = QLabel("設定")
        title_lbl.setStyleSheet(f"color:{theme_color('TEXT')}; font-size:14px; font-weight:600;")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        close_tb = QToolButton()
        close_tb.setObjectName("settings_close_btn")
        close_tb.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 12))
        close_tb.setIconSize(QSize(12, 12))
        close_tb.setFixedSize(24, 24)
        close_tb.setStyleSheet(
            "QToolButton { background:transparent; border:none; border-radius:4px; }"
            f"QToolButton:hover {{ background:{theme_color('SURFACE_HOVER')}; }}"
        )
        close_tb.clicked.connect(dlg.reject)
        title_row.addWidget(close_tb)
        root.addLayout(title_row)

        appearance_box = QGroupBox("外観")
        appearance_form = QFormLayout(appearance_box)
        theme_combo = AccountComboBox(appearance_box)
        theme_combo.setMinimumWidth(180)
        try:
            from src.ui.theme import available_themes, get_theme_id
            for theme_id, label in available_themes():
                theme_combo.addItem(label, theme_id)
            current_theme = (
                self._settings_manager.get_ui_theme()
                if self._settings_manager is not None
                and hasattr(self._settings_manager, "get_ui_theme")
                else get_theme_id()
            )
            idx = theme_combo.findData(current_theme)
            if idx >= 0:
                theme_combo.setCurrentIndex(idx)
        except Exception:
            theme_combo.addItem("dark navy", "dark")
            theme_combo.addItem("milky pink", "nadeshiko")
            theme_combo.addItem("baby blue", "baby_blue")
            theme_combo.addItem("bordeaux", "bordeaux")
            theme_combo.addItem("pure purple", "pure_purple")
        appearance_form.addRow("テーマ", theme_combo)

        def _on_theme_changed(_index: int) -> None:
            selected_theme = str(theme_combo.currentData() or "dark")
            if self._settings_manager is not None and hasattr(
                self._settings_manager, "save_ui_theme"
            ):
                self._settings_manager.save_ui_theme(selected_theme)
            self._apply_runtime_theme(selected_theme)
            try:
                from src.ui.theme import apply_overlay_theme
                apply_overlay_theme(dlg)
            except Exception:
                pass
            try:
                from src.ui.window_polish import apply_native_window_polish
                apply_native_window_polish(dlg, corner="round")
            except Exception:
                pass
            try:
                from src.ui.icons import make_folder_icon, _COLOR_SECONDARY
                _folder_btn = dlg.findChild(QToolButton, "open_folder_btn")
                if _folder_btn is not None:
                    _folder_btn.setIcon(make_folder_icon(_COLOR_SECONDARY, 12))
                    _folder_btn.update()
            except Exception:
                pass

        theme_combo.currentIndexChanged.connect(_on_theme_changed)
        root.addWidget(appearance_box)

        dock_box = QGroupBox("Dock")
        dock_l = QVBoxLayout(dock_box)
        dock_l.setContentsMargins(8, 6, 8, 6)
        dock_l.setSpacing(2)
        dock_checks = QHBoxLayout()
        dock_checks.setContentsMargins(0, 0, 0, 0)
        dock_checks.setSpacing(14)
        aot = QCheckBox("Dockを常に最前面に表示")
        aot.setChecked(bool(self._edge_dock_always_on_top))
        dock_checks.addWidget(aot)
        fs_guard = QCheckBox("フルスクリーン中はDockを無効化")
        fs_guard.setChecked(bool(getattr(self, "_edge_dock_disable_on_fullscreen", True)))
        fs_guard.setToolTip("ゲーム・全画面動画などでDockを前面に残しません。")
        dock_checks.addWidget(fs_guard)
        unread_ind = QCheckBox("Dock未読通知インジケーター")
        unread_ind.setChecked(bool(getattr(self, "_dock_unread_indicator_enabled", True)))
        unread_ind.setToolTip("未読があるとき収納Dockに小さな通知アイコンを表示します。")
        dock_checks.addWidget(unread_ind)
        dock_checks.addStretch(1)
        dock_l.addLayout(dock_checks)

        lr_box = QGroupBox("左右 Dock")
        lr_form = QFormLayout(lr_box)
        lr_w = NoWheelSpinBox(); lr_w.setRange(240, 4000)
        lr_h = NoWheelSpinBox(); lr_h.setRange(180, 4000)
        lr_c = NoWheelSpinBox(); lr_c.setRange(1, 8)
        ps = self._panel_size_for_edge("right")
        lr_w.setValue(int(self._edge_dock_width_lr or ps.width()))
        lr_h.setValue(int(self._edge_dock_height_lr or ps.height()))
        lr_c.setValue(int(self._edge_dock_column_count_lr))
        lr_form.addRow("幅 (px)", lr_w)
        lr_form.addRow("高さ (px)", lr_h)
        lr_form.addRow("カラム数", lr_c)

        tb_box = QGroupBox("上下 Dock")
        tb_form = QFormLayout(tb_box)
        tb_w = NoWheelSpinBox(); tb_w.setRange(240, 4000)
        tb_h = NoWheelSpinBox(); tb_h.setRange(180, 4000)
        tb_c = NoWheelSpinBox(); tb_c.setRange(1, 8)
        ps2 = self._panel_size_for_edge("bottom")
        tb_w.setValue(int(self._edge_dock_width_tb or ps2.width()))
        tb_h.setValue(int(self._edge_dock_height_tb or ps2.height()))
        tb_c.setValue(int(self._edge_dock_column_count_tb))
        tb_form.addRow("幅 (px)", tb_w)
        tb_form.addRow("高さ (px)", tb_h)
        tb_form.addRow("カラム数", tb_c)

        dock_size_row = QHBoxLayout()
        dock_size_row.setContentsMargins(0, 0, 0, 0)
        dock_size_row.setSpacing(8)
        dock_size_row.addWidget(lr_box, 1)
        dock_size_row.addWidget(tb_box, 1)

        web_box = QGroupBox("表示")
        web_form = QFormLayout(web_box)
        zoom = NoWheelSpinBox(); zoom.setRange(50, 150); zoom.setSingleStep(5)
        zoom.setSuffix(" %")
        zoom.setValue(int(self._edge_dock_zoom_percent))
        x_sc_off = QCheckBox("Xのキーボードショートカットを無効にする")
        x_sc_off.setChecked(bool(getattr(self, "_disable_x_keyboard_shortcuts", False)))
        x_sc_off.setToolTip(
            "x.com 上の j/k/n 等のショートカットを止めます。"
            "投稿・検索・DM の文字入力はそのまま使えます。"
        )
        x_sc_off.toggled.connect(self._set_disable_x_keyboard_shortcuts)
        web_row = QHBoxLayout()
        web_row.setContentsMargins(0, 0, 0, 0)
        web_row.setSpacing(14)
        web_row.addWidget(QLabel("ページズーム"))
        web_row.addWidget(zoom)
        web_row.addWidget(x_sc_off)
        web_row.addStretch(1)
        web_form.addRow(web_row)

        root.addWidget(dock_box)
        root.addLayout(dock_size_row)
        root.addWidget(web_box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        sec = QGroupBox("Web / セキュリティ")
        sec_l = QVBoxLayout(sec)
        sec_l.addWidget(QLabel("外部サイトの扱い:"))
        from src.browser.url_policy import (
            POLICY_ASK,
            POLICY_DEFAULT_BROWSER,
            POLICY_IN_APP,
            get_external_site_policy,
        )
        pol = get_external_site_policy()
        if self._settings_manager and hasattr(self._settings_manager, "get_external_site_policy"):
            pol = self._settings_manager.get_external_site_policy()
        rb_browser = QRadioButton("外部リンクは既定ブラウザで開く")
        rb_in_app = QRadioButton("外部リンクをMayotter内の新規タブで開く")
        rb_ask = QRadioButton("外部リンクを開く前に確認")
        rb_browser.setChecked(pol == POLICY_DEFAULT_BROWSER or pol not in (POLICY_IN_APP, POLICY_ASK))
        rb_in_app.setChecked(pol == POLICY_IN_APP)
        rb_ask.setChecked(pol == POLICY_ASK)
        sec_l.addWidget(rb_browser)
        in_app_row = QHBoxLayout()
        in_app_row.setContentsMargins(0, 0, 0, 0)
        in_app_row.setSpacing(6)
        in_app_row.addWidget(rb_in_app, 0)
        in_app_note = QLabel("※セキュリティ上の理由から非推奨")
        in_app_note.setStyleSheet("color:#7f899a; font-size:10px; background:transparent;")
        in_app_row.addWidget(in_app_note, 0)
        in_app_row.addStretch(1)
        sec_l.addLayout(in_app_row)
        sec_l.addWidget(rb_ask)
        allowed_new_tab = QCheckBox("許可された外部リンクを新規タブで表示する")
        allowed_new_tab.setChecked(bool(getattr(self, "_allowed_external_new_tab", True)))
        allowed_row = QHBoxLayout()
        allowed_row.setContentsMargins(0, 0, 0, 0)
        allowed_row.setSpacing(6)
        allowed_row.addWidget(allowed_new_tab, 1)
        add_ext_btn = QToolButton()
        add_ext_btn.setText("追加")
        add_ext_btn.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        allowed_row.addWidget(add_ext_btn, 0)

        def _open_allowed_external_dialog():
            from PySide6.QtWidgets import (
                QDialog, QFormLayout, QLineEdit, QListWidget,
                QListWidgetItem, QAbstractItemView, QLabel, QHBoxLayout, QVBoxLayout,
            )
            from src.browser.url_policy import (
                builtin_allowed_external_groups,
                get_user_allowed_external,
                normalize_policy_domain,
                set_user_allowed_external,
            )
            user_entries = list(get_user_allowed_external())
            try:
                if self._settings_manager is not None and hasattr(
                    self._settings_manager, "get_user_allowed_external"
                ):
                    user_entries = list(self._settings_manager.get_user_allowed_external())
            except Exception:
                pass

            ad = QDialog(dlg)
            ad.setObjectName("mayotter_allowed_external_dialog")
            ad.setModal(True)
            ad.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
            )
            ad.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            ad.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            try:
                from src.ui.theme import apply_overlay_theme
                apply_overlay_theme(ad)
            except Exception:
                pass
            _ad_native = bool(ad.property("mayotterNativeRounded"))
            ad.setStyleSheet(
                "QDialog#mayotter_allowed_external_dialog {"
                f" background:{'#12151c' if _ad_native else 'transparent'}; border:none; }}"
            )
            ad.setMinimumWidth(300)
            ad.setMinimumHeight(280)
            outer = QVBoxLayout(ad)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            surface = QWidget(ad)
            surface.setObjectName("mayotter_allowed_ext_surface")
            surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            surface.setStyleSheet(
                "QWidget#mayotter_allowed_ext_surface {"
                f" background:#12151c; border:{'none' if _ad_native else '1px solid #2b3242'};"
                f" border-radius:{0 if _ad_native else 8}px; }}"
            )
            outer.addWidget(surface)
            v = QVBoxLayout(surface)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(6)

            def _apply_round_mask():
                try:
                    w, h = ad.width(), ad.height()
                    if w <= 0 or h <= 0:
                        return
                    ad.clearMask()
                except Exception:
                    pass

            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_lbl = QLabel("許可された外部リンク")
            title_lbl.setStyleSheet("color:#f1f3f7; font-size:12px; font-weight:600;")
            title_row.addWidget(title_lbl, 1)
            close_tb = QToolButton()
            install_close_icon(close_tb, 12)
            close_tb.setFixedSize(24, 24)
            close_tb.setCursor(Qt.CursorShape.PointingHandCursor)
            close_tb.setStyleSheet(
                "QToolButton { color:#aeb6c5; background:transparent; border:none;"
                " border-radius:6px; font-size:14px; }"
                "QToolButton:hover { background:#232a38; color:#f1f3f7; }"
            )
            close_tb.clicked.connect(ad.reject)
            title_row.addWidget(close_tb, 0)
            v.addLayout(title_row)

            lst = QListWidget()
            lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            lst.setUniformItemSizes(True)
            lst.setSpacing(0)
            lst.setStyleSheet(
                "QListWidget { background:#0f1117; color:#c5d4ea; border:1px solid #2b3242;"
                " border-radius:4px; font-size:11px; outline:none; padding:2px; }"
                "QListWidget::item { padding:2px 6px; min-height:18px; max-height:20px;"
                " border:none; border-radius:3px; }"
                "QListWidget::item:selected { background:#1d2230; color:#f1f3f7; }"
                "QListWidget::item:hover { background:#181c26; }"
            )

            def _rebuild_list():
                lst.clear()
                for _gl, domains in builtin_allowed_external_groups():
                    for d in domains:
                        it = QListWidgetItem(d)
                        it.setFlags(
                            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                        )
                        it.setData(
                            Qt.ItemDataRole.UserRole,
                            {"builtin": True, "domain": d},
                        )
                        lst.addItem(it)
                for i, entry in enumerate(user_entries):
                    domain = entry.get("domain") or ""
                    if not domain:
                        continue
                    it = QListWidgetItem(domain)
                    it.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    )
                    it.setData(
                        Qt.ItemDataRole.UserRole,
                        {"builtin": False, "index": i, "domain": domain},
                    )
                    lst.addItem(it)

            def _update_minus_enabled():
                item = lst.currentItem()
                data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
                can_del = isinstance(data, dict) and not data.get("builtin")
                minus_btn.setEnabled(bool(can_del))

            _rebuild_list()
            v.addWidget(lst, 1)
            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            plus_btn = QToolButton()
            plus_btn.setIcon(make_plus_icon(_COLOR_TEXT, 12))
            plus_btn.setIconSize(QSize(12, 12))
            plus_btn.setStyleSheet(
                "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
                " border-radius:6px; padding:3px 10px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
            )
            minus_btn = QToolButton()
            minus_btn.setIcon(make_minimize_icon(_COLOR_TEXT, 12))
            minus_btn.setIconSize(QSize(12, 12))
            minus_btn.setEnabled(False)
            minus_btn.setStyleSheet(
                "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
                " border-radius:6px; padding:3px 10px; }"
                "QToolButton:disabled { color:#5a6270; background:#151820; }"
            )
            btn_row.addWidget(plus_btn)
            btn_row.addWidget(minus_btn)
            v.addLayout(btn_row)
            lst.currentItemChanged.connect(lambda *_: _update_minus_enabled())

            def _persist():
                set_user_allowed_external(user_entries)
                try:
                    if self._settings_manager is not None:
                        self._settings_manager.save_user_allowed_external(user_entries)
                except Exception:
                    pass

            def _on_plus():
                form_dlg = QDialog(ad)
                form_dlg.setObjectName("mayotter_domain_add_dialog")
                form_dlg.setModal(True)
                form_dlg.setWindowFlags(
                    Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                )
                form_dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                form_dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                try:
                    from src.ui.theme import apply_overlay_theme
                    apply_overlay_theme(form_dlg)
                except Exception:
                    pass
                _form_native = bool(form_dlg.property("mayotterNativeRounded"))
                form_dlg.setStyleSheet(
                    "QDialog#mayotter_domain_add_dialog {"
                    f" background:{'#12151c' if _form_native else 'transparent'}; border:none; }}"
                )
                form_wrap = QVBoxLayout(form_dlg)
                form_wrap.setContentsMargins(0, 0, 0, 0)
                form_surface = QWidget(form_dlg)
                form_surface.setObjectName("mayotter_domain_add_surface")
                form_surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                form_surface.setStyleSheet(
                    "QWidget#mayotter_domain_add_surface {"
                    f" background:#12151c; border:{'none' if _form_native else '1px solid #2b3242'};"
                    f" border-radius:{0 if _form_native else 8}px; }}"
                )
                form_wrap.addWidget(form_surface)
                form = QFormLayout(form_surface)
                form.setContentsMargins(12, 12, 12, 12)
                name_ed = QLineEdit()
                name_ed.setPlaceholderText("例: X")
                domain_ed = QLineEdit()
                domain_ed.setPlaceholderText("例: x.com")
                try:
                    from src.ui.url_overlay import install_dark_lineedit_menu
                    install_dark_lineedit_menu(name_ed)
                    install_dark_lineedit_menu(domain_ed)
                except Exception:
                    pass
                form.addRow("サイト名", name_ed)
                form.addRow("ドメイン", domain_ed)
                row_b = QHBoxLayout()
                cancel_b = QToolButton()
                cancel_b.setText("キャンセル")
                cancel_b.setStyleSheet(
                    "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
                    " border-radius:6px; padding:4px 10px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
                )
                ok_b = QToolButton()
                ok_b.setText("追加")
                ok_b.setStyleSheet(
                    "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
                    " border-radius:6px; padding:4px 10px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
                )
                cancel_b.clicked.connect(form_dlg.reject)
                ok_b.clicked.connect(form_dlg.accept)
                row_b.addStretch(1)
                row_b.addWidget(cancel_b)
                row_b.addWidget(ok_b)
                form.addRow(row_b)
                form_dlg.adjustSize()
                try:
                    form_dlg.clearMask()
                except Exception:
                    pass
                try:
                    from src.ui.theme import POPOVER_OPEN_MS, POPOVER_CLOSE_MS
                except Exception:
                    POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
                from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
                form_result = {"code": int(QDialog.DialogCode.Rejected)}

                def _form_finish(code):
                    if getattr(form_dlg, "_mayotter_done", False):
                        return
                    form_dlg._mayotter_done = True
                    form_result["code"] = int(code)
                    try:
                        QDialog.done(form_dlg, int(code))
                    except Exception:
                        pass

                def _form_fade_close(code):
                    if getattr(form_dlg, "_mayotter_fading_out", False):
                        return
                    form_dlg._mayotter_fading_out = True
                    try:
                        anim = QPropertyAnimation(form_dlg, b"windowOpacity", form_dlg)
                        anim.setDuration(int(POPOVER_CLOSE_MS))
                        anim.setStartValue(float(form_dlg.windowOpacity() or 1.0))
                        anim.setEndValue(0.0)
                        anim.setEasingCurve(QEasingCurve.Type.InCubic)
                        anim.finished.connect(lambda: _form_finish(code))
                        anim.start()
                        QTimer.singleShot(int(POPOVER_CLOSE_MS) + 80, lambda: _form_finish(code))
                    except Exception:
                        _form_finish(code)

                form_dlg.reject = lambda *a, **k: _form_fade_close(QDialog.DialogCode.Rejected)
                form_dlg.accept = lambda *a, **k: _form_fade_close(QDialog.DialogCode.Accepted)
                try:
                    cancel_b.clicked.disconnect()
                except Exception:
                    pass
                try:
                    ok_b.clicked.disconnect()
                except Exception:
                    pass
                cancel_b.clicked.connect(lambda: form_dlg.reject())
                ok_b.clicked.connect(lambda: form_dlg.accept())
                try:
                    form_dlg.setWindowOpacity(0.0)
                except Exception:
                    pass
                form_dlg.show()
                form_dlg.raise_()
                try:
                    anim_in = QPropertyAnimation(form_dlg, b"windowOpacity", form_dlg)
                    anim_in.setDuration(int(POPOVER_OPEN_MS))
                    anim_in.setStartValue(0.0)
                    anim_in.setEndValue(1.0)
                    anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
                    anim_in.start()
                except Exception:
                    try:
                        form_dlg.setWindowOpacity(1.0)
                    except Exception:
                        pass
                form_dlg.exec()
                if int(form_dlg.result()) != int(QDialog.DialogCode.Accepted):
                    return
                domain = normalize_policy_domain(domain_ed.text())
                if not domain:
                    return
                name = (name_ed.text() or "").strip() or domain
                existing = {e.get("domain") for e in user_entries}
                for _gl, ds in builtin_allowed_external_groups():
                    existing.update(ds)
                if domain in existing:
                    return
                for base in existing:
                    if base and domain.endswith("." + base):
                        return
                user_entries.append({"name": name, "domain": domain})
                _persist()
                _rebuild_list()
                _update_minus_enabled()

            def _on_minus():
                item = lst.currentItem()
                if item is None:
                    return
                data = item.data(Qt.ItemDataRole.UserRole)
                if not isinstance(data, dict) or data.get("builtin"):
                    return
                domain = data.get("domain") or ""
                user_entries[:] = [
                    e for e in user_entries if (e.get("domain") or "") != domain
                ]
                _persist()
                _rebuild_list()
                _update_minus_enabled()

            plus_btn.clicked.connect(_on_plus)
            minus_btn.clicked.connect(_on_minus)
            ad.resize(320, 300)
            _apply_round_mask()

            def _fade_dialog_exec(dialog):
                from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
                try:
                    from src.ui.theme import POPOVER_OPEN_MS, POPOVER_CLOSE_MS
                except Exception:
                    POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
                result = {"code": int(QDialog.DialogCode.Rejected)}

                def _finish(code):
                    if getattr(dialog, "_mayotter_done", False):
                        return
                    dialog._mayotter_done = True
                    result["code"] = int(code)
                    try:
                        QDialog.done(dialog, int(code))
                    except Exception:
                        try:
                            dialog.close()
                        except Exception:
                            pass

                def _fade_close(code):
                    if getattr(dialog, "_mayotter_fading_out", False):
                        return
                    if getattr(dialog, "_mayotter_done", False):
                        return
                    dialog._mayotter_fading_out = True
                    try:
                        anim = QPropertyAnimation(dialog, b"windowOpacity", dialog)
                        anim.setDuration(int(POPOVER_CLOSE_MS))
                        anim.setStartValue(float(dialog.windowOpacity() or 1.0))
                        anim.setEndValue(0.0)
                        anim.setEasingCurve(QEasingCurve.Type.InCubic)
                        anim.finished.connect(lambda: _finish(code))
                        anim.start()
                        dialog._mayotter_fade_anim = anim
                        QTimer.singleShot(int(POPOVER_CLOSE_MS) + 80, lambda: _finish(code))
                    except Exception:
                        _finish(code)

                dialog.reject = lambda *a, **k: _fade_close(QDialog.DialogCode.Rejected)
                dialog.accept = lambda *a, **k: _fade_close(QDialog.DialogCode.Accepted)

                try:
                    dialog.setWindowOpacity(0.0)
                except Exception:
                    pass
                dialog.show()
                dialog.raise_()
                try:
                    anim_in = QPropertyAnimation(dialog, b"windowOpacity", dialog)
                    anim_in.setDuration(int(POPOVER_OPEN_MS))
                    anim_in.setStartValue(0.0)
                    anim_in.setEndValue(1.0)
                    anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
                    anim_in.start()
                    dialog._mayotter_fade_anim = anim_in
                except Exception:
                    try:
                        dialog.setWindowOpacity(1.0)
                    except Exception:
                        pass
                dialog.exec()
                return result["code"]

            _fade_dialog_exec(ad)

        add_ext_btn.clicked.connect(_open_allowed_external_dialog)
        sec_l.addLayout(allowed_row)
        root.addWidget(sec)

        dl_box = QGroupBox("ダウンロードファイルの保存先")
        dl_form = QFormLayout(dl_box)
        from src.core.paths import default_downloads_dir
        from pathlib import Path as _DlPath
        _dl_dir = default_downloads_dir()
        try:
            if self._settings_manager is not None:
                _dc = str(self._settings_manager.get_download_dir() or "").strip()
                if _dc:
                    _dl_dir = _DlPath(_dc)
        except Exception:
            pass
        try:
            _dl_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        dl_row = QHBoxLayout()
        dl_row.setSpacing(4)
        dl_lbl = QLabel("保存先")
        dl_lbl.setStyleSheet("color:#aeb6c5; font-size:11px;")
        dl_path_edit = QLineEdit(str(_dl_dir))
        dl_path_edit.setReadOnly(True)
        dl_path_edit.setToolTip(str(_dl_dir))
        dl_path_edit.setStyleSheet(
            "QLineEdit { color:#c5d4ea; background:#0f1117; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 6px; font-size:11px; }"
        )
        try:
            from src.ui.url_overlay import install_dark_lineedit_menu
            install_dark_lineedit_menu(dl_path_edit)
        except Exception:
            pass
        dl_browse = QToolButton()
        dl_browse.setText("参照")
        dl_browse.setToolTip("保存先を変更")
        dl_browse.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        from src.ui.icons import make_folder_icon as _mk_folder
        dl_open = QToolButton()
        dl_open.setObjectName("open_folder_btn")
        dl_open.setIcon(_mk_folder("#aeb6c5", 12))
        dl_open.setIconSize(QSize(12, 12))
        dl_open.setToolTip("フォルダを開く")
        dl_open.setFixedSize(24, 24)
        dl_open.setStyleSheet(
            "QToolButton { background:#1d2230; border:1px solid #2b3242; border-radius:6px; }"
        )

        def _browse_dl_dir():
            from PySide6.QtWidgets import QFileDialog
            start = dl_path_edit.text().strip() or str(default_downloads_dir())
            chosen = QFileDialog.getExistingDirectory(dlg, "ファイルの保存先", start)
            if chosen:
                dl_path_edit.setText(chosen)
                dl_path_edit.setToolTip(chosen)

        def _open_dl_dir():
            import os, sys, subprocess
            folder = dl_path_edit.text().strip() or str(default_downloads_dir())
            fp = _DlPath(folder)
            try:
                fp.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            try:
                if sys.platform == "win32":
                    os.startfile(str(fp))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(fp)])
                else:
                    subprocess.Popen(["xdg-open", str(fp)])
            except Exception:
                pass

        dl_browse.clicked.connect(_browse_dl_dir)
        dl_open.clicked.connect(_open_dl_dir)
        dl_row.addWidget(dl_lbl)
        dl_row.addWidget(dl_path_edit, 1)
        dl_row.addWidget(dl_browse)
        dl_row.addWidget(dl_open)
        dl_form.addRow(dl_row)
        root.addWidget(dl_box)

        media_box = QGroupBox("音声投稿")
        media_form = QFormLayout(media_box)
        auto_norm = QCheckBox("自動音量調整")
        _norm_on = True
        try:
            if self._settings_manager is not None:
                _norm_on = bool(self._settings_manager.get_auto_normalize_audio())
        except Exception:
            _norm_on = True
        auto_norm.setChecked(_norm_on)
        save_rec = QCheckBox("録音ファイルを保存")
        _save_on = True
        try:
            if self._settings_manager is not None:
                _save_on = bool(self._settings_manager.get_save_recorded_audio())
        except Exception:
            _save_on = True
        save_rec.setChecked(_save_on)
        media_checks = QHBoxLayout()
        media_checks.setContentsMargins(0, 0, 0, 0)
        media_checks.setSpacing(14)
        media_checks.addWidget(auto_norm)
        save_rec_row = QHBoxLayout()
        save_rec_row.setContentsMargins(0, 0, 0, 0)
        save_rec_row.setSpacing(8)
        save_rec_row.addWidget(save_rec)
        mp4_hint = QLabel("※MP4形式")
        mp4_hint.setStyleSheet("color: #7f899a; font-size: 10px;")
        save_rec_row.addWidget(mp4_hint)
        media_checks.addLayout(save_rec_row)
        media_checks.addStretch(1)
        media_form.addRow(media_checks)

        from src.core.paths import default_recordings_dir
        from pathlib import Path as _Pth
        _rec_dir = default_recordings_dir()
        try:
            if self._settings_manager is not None:
                _c = str(self._settings_manager.get_recorded_audio_dir() or "").strip()
                if _c:
                    _rec_dir = _Pth(_c)
        except Exception:
            pass
        try:
            _rec_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        path_row = QHBoxLayout()
        path_row.setSpacing(4)
        path_lbl = QLabel("保存先")
        path_lbl.setStyleSheet("color:#aeb6c5; font-size:11px;")
        rec_path_edit = QLineEdit(str(_rec_dir))
        rec_path_edit.setReadOnly(True)
        rec_path_edit.setToolTip(str(_rec_dir))
        rec_path_edit.setStyleSheet(
            "QLineEdit { color:#c5d4ea; background:#0f1117; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 6px; font-size:11px; }"
        )
        try:
            from src.ui.url_overlay import install_dark_lineedit_menu
            install_dark_lineedit_menu(rec_path_edit)
        except Exception:
            pass
        from src.ui.icons import make_folder_icon
        browse_btn = QToolButton()
        browse_btn.setText("参照")
        browse_btn.setToolTip("保存先を変更")
        browse_btn.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        open_folder_btn = QToolButton()
        open_folder_btn.setObjectName("open_folder_btn")
        open_folder_btn.setIcon(make_folder_icon(_COLOR_SECONDARY, 12))
        open_folder_btn.setIconSize(QSize(12, 12))
        open_folder_btn.setToolTip("フォルダを開く")
        open_folder_btn.setFixedSize(24, 24)
        open_folder_btn.setStyleSheet(
            f"QToolButton {{ background:{theme_color('SURFACE_HOVER')}; border:1px solid {theme_color('BORDER')}; border-radius:6px; }}"
            f"QToolButton:hover {{ background:{theme_color('SURFACE_HOVER')}; border:1px solid {theme_color('BORDER_STRONG')}; }}"
        )

        def _browse_rec_dir():
            from PySide6.QtWidgets import QFileDialog
            start = rec_path_edit.text().strip() or str(default_recordings_dir())
            chosen = QFileDialog.getExistingDirectory(dlg, "録音の保存先", start)
            if chosen:
                rec_path_edit.setText(chosen)
                rec_path_edit.setToolTip(chosen)

        def _open_rec_dir():
            import os, sys, subprocess
            from pathlib import Path as _P2
            folder = rec_path_edit.text().strip() or str(default_recordings_dir())
            fp = _P2(folder)
            try:
                fp.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            try:
                if sys.platform == "win32":
                    os.startfile(str(fp))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(fp)])
                else:
                    subprocess.Popen(["xdg-open", str(fp)])
            except Exception:
                pass

        browse_btn.clicked.connect(_browse_rec_dir)
        open_folder_btn.clicked.connect(_open_rec_dir)
        path_row.addWidget(path_lbl)
        path_row.addWidget(rec_path_edit, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(open_folder_btn)
        media_form.addRow(path_row)

        _vis_path = ""
        try:
            if self._settings_manager is not None:
                _vis_path = str(self._settings_manager.get_audio_visual_image() or "").strip()
        except Exception:
            _vis_path = ""
        vis_row = QHBoxLayout()
        vis_row.setSpacing(4)
        vis_lbl = QLabel("音声投稿画像")
        vis_lbl.setStyleSheet("color:#aeb6c5; font-size:11px;")
        _vis_orig = ""
        try:
            if self._settings_manager is not None:
                _vis_orig = str(self._settings_manager.get_audio_visual_image_original() or "").strip()
        except Exception:
            _vis_orig = ""
        _vis_state = {
            "path": _vis_path,
            "original": _vis_orig or _vis_path,
            "crop_x": 0.0,
            "crop_y": 0.0,
            "scale": 1.0,
            "rotation": 0.0,
        }
        try:
            if self._settings_manager is not None and _vis_path:
                cx, cy, sc, rot = self._settings_manager.get_audio_visual_image_transform()
                _vis_state.update({"crop_x": cx, "crop_y": cy, "scale": sc, "rotation": rot})
        except Exception:
            pass

        vis_thumb = QLabel()
        vis_thumb.setFixedSize(56, 56)
        vis_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vis_thumb.setStyleSheet(
            "QLabel { background:#0f1117; border:1px dashed #2b3242; border-radius:28px;"
            " color:#7f899a; font-size:10px; }"
        )
        vis_thumb.setText("未設定")
        vis_thumb.setToolTip("クリックで編集 / 画像をドロップ")
        vis_thumb.setAcceptDrops(True)

        def _refresh_vis_thumb() -> None:
            from PySide6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QColor
            from PySide6.QtCore import QRectF
            path = (_vis_state.get("path") or "").strip()
            if not path:
                vis_thumb.setPixmap(QPixmap())
                vis_thumb.setText("未設定")
                return
            try:
                from src.media.visual import _cover_square_image
                raw = QImage(path)
                if raw.isNull():
                    vis_thumb.setText("?")
                    return
                sq = _cover_square_image(
                    raw,
                    size=112,
                    crop_x=float(_vis_state.get("crop_x", 0.0)),
                    crop_y=float(_vis_state.get("crop_y", 0.0)),
                    scale=float(_vis_state.get("scale", 1.0)),
                    rotation=float(_vis_state.get("rotation", 0.0)),
                )
                pm = QPixmap(56, 56)
                pm.fill(QColor(0, 0, 0, 0))
                painter = QPainter(pm)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                path_c = QPainterPath()
                path_c.addEllipse(QRectF(1, 1, 54, 54))
                painter.setClipPath(path_c)
                painter.drawImage(QRectF(1, 1, 54, 54), sq)
                painter.end()
                vis_thumb.setText("")
                vis_thumb.setPixmap(pm)
            except Exception:
                vis_thumb.setText("?")

        def _open_vis_editor(path: str | None = None) -> None:
            from src.ui.avatar_edit import open_avatar_editor
            pth = (path or _vis_state.get("path") or "").strip()
            if not pth:
                return
            save_pref = False
            try:
                if self._settings_manager is not None:
                    save_pref = bool(self._settings_manager.get_save_cropped_visual_image())
            except Exception:
                save_pref = False
            original = (_vis_state.get("original") or pth or "").strip()
            crop_dest = ""
            try:
                if self._settings_manager is not None:
                    crop_dest = str(self._settings_manager.get_cropped_visual_dir() or "").strip()
            except Exception:
                crop_dest = ""
            result = open_avatar_editor(
                dlg,
                pth,
                crop_x=float(_vis_state.get("crop_x", 0.0)),
                crop_y=float(_vis_state.get("crop_y", 0.0)),
                scale=float(_vis_state.get("scale", 1.0)),
                rotation=float(_vis_state.get("rotation", 0.0)),
                save_cropped=save_pref,
                dest_dir=crop_dest or None,
            )
            if result is None:
                return
            path_r, cx, cy, sc, rot, saved_flag = result
            try:
                if self._settings_manager is not None:
                    self._settings_manager.save_save_cropped_visual_image(bool(saved_flag))
            except Exception:
                pass
            if saved_flag and path_r and path_r != original:
                _vis_state["original"] = original
                try:
                    if self._settings_manager is not None:
                        self._settings_manager.save_audio_visual_image_original(original)
                except Exception:
                    pass
            _vis_state.update({
                "path": path_r,
                "crop_x": cx,
                "crop_y": cy,
                "scale": sc,
                "rotation": rot,
            })
            _refresh_vis_thumb()

        def _pick_vis_image() -> None:
            from pathlib import Path as _VisPath
            from PySide6.QtWidgets import QFileDialog
            start = (_vis_state.get("path") or "").strip() or str(_VisPath.home())
            chosen, _ = QFileDialog.getOpenFileName(
                dlg,
                "音声投稿の中央画像",
                start,
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if chosen:
                _vis_state["path"] = chosen
                _vis_state["original"] = chosen
                _vis_state["crop_x"] = 0.0
                _vis_state["crop_y"] = 0.0
                _vis_state["scale"] = 1.0
                _vis_state["rotation"] = 0.0
                _open_vis_editor(chosen)

        def _clear_vis() -> None:
            _vis_state.update({
                "path": "",
                "original": "",
                "crop_x": 0.0,
                "crop_y": 0.0,
                "scale": 1.0,
                "rotation": 0.0,
            })
            try:
                self._settings_manager.save_audio_visual_image("")
                self._settings_manager.save_audio_visual_image_original("")
                self._settings_manager.save_audio_visual_image_transform(0.0, 0.0, 1.0, 0.0)
            except Exception:
                pass
            _refresh_vis_thumb()

        def _thumb_mouse(ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                if (_vis_state.get("path") or "").strip():
                    _open_vis_editor()
                else:
                    _pick_vis_image()
            return QLabel.mousePressEvent(vis_thumb, ev)

        def _thumb_drag_enter(ev):
            md = ev.mimeData()
            if md and md.hasUrls():
                for u in md.urls():
                    if u.toLocalFile().lower().endswith(
                        (".png", ".jpg", ".jpeg", ".webp", ".bmp")
                    ):
                        ev.acceptProposedAction()
                        return
            ev.ignore()

        def _thumb_drop(ev):
            md = ev.mimeData()
            if not md or not md.hasUrls():
                return
            for u in md.urls():
                fp = u.toLocalFile()
                if fp.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                    _vis_state["path"] = fp
                    _vis_state["original"] = fp
                    _vis_state["crop_x"] = 0.0
                    _vis_state["crop_y"] = 0.0
                    _vis_state["scale"] = 1.0
                    _vis_state["rotation"] = 0.0
                    _open_vis_editor(fp)
                    break

        vis_thumb.mousePressEvent = _thumb_mouse
        vis_thumb.dragEnterEvent = _thumb_drag_enter
        vis_thumb.dropEvent = _thumb_drop

        vis_browse = QToolButton()
        vis_browse.setText("選択")
        vis_browse.setToolTip("画像を選択")
        vis_browse.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        vis_edit_btn = QToolButton()
        vis_edit_btn.setText("編集")
        vis_edit_btn.setToolTip("画像の編集")
        vis_edit_btn.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        vis_clear = QToolButton()
        vis_clear.setText("クリア")
        vis_clear.setStyleSheet(
            "QToolButton { color:#c5d4ea; background:#1d2230; border:1px solid #4a7ec7;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { border:1px solid #5b8fd6; color:#e8eef8; }"
            "QToolButton:pressed { border:1px solid #3a6aad; }"
        )
        vis_browse.clicked.connect(_pick_vis_image)
        vis_edit_btn.clicked.connect(lambda: _open_vis_editor())
        vis_clear.clicked.connect(_clear_vis)
        def _sync_vis_btns():
            has = bool((_vis_state.get("path") or "").strip())
            vis_edit_btn.setEnabled(has)
            vis_clear.setEnabled(has)
        _old_refresh = _refresh_vis_thumb
        def _refresh_vis_thumb():
            _old_refresh()
            _sync_vis_btns()
        _refresh_vis_thumb()

        vis_row = QHBoxLayout()
        vis_row.setSpacing(6)
        vis_row.addWidget(vis_lbl)
        vis_row.addWidget(vis_thumb)
        vis_row.addWidget(vis_edit_btn)
        vis_row.addWidget(vis_browse)
        vis_row.addWidget(vis_clear)
        vis_row.addStretch(1)
        media_form.addRow(vis_row)

        crop_row = QHBoxLayout()
        crop_row.setSpacing(6)
        crop_lbl = QLabel("編集後の保存先")
        crop_lbl.setStyleSheet("color:#aeb6c5; font-size:11px;")
        crop_path_edit = QLineEdit()
        crop_path_edit.setReadOnly(True)
        try:
            from src.core.paths import default_audio_visual_dir
            _crop_default = str(default_audio_visual_dir())
        except Exception:
            _crop_default = ""
        try:
            if self._settings_manager is not None:
                _cd = str(self._settings_manager.get_cropped_visual_dir() or "").strip()
                if _cd:
                    _crop_default = _cd
        except Exception:
            pass
        crop_path_edit.setText(_crop_default)
        crop_path_edit.setStyleSheet(
            "QLineEdit { color:#c5d4ea; background:#0f1117; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 6px; font-size:11px; }"
        )
        _btn_ss = (
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )
        crop_browse_btn = QToolButton()
        crop_browse_btn.setText("参照")
        crop_browse_btn.setToolTip("保存先を変更")
        crop_browse_btn.setStyleSheet(_btn_ss)
        from src.ui.icons import make_folder_icon as _mk_crop_folder
        crop_folder_btn = QToolButton()
        crop_folder_btn.setObjectName("open_folder_btn")
        crop_folder_btn.setIcon(_mk_crop_folder("#aeb6c5", 12))
        crop_folder_btn.setIconSize(QSize(12, 12))
        crop_folder_btn.setToolTip("フォルダを開く")
        crop_folder_btn.setFixedSize(24, 24)
        crop_folder_btn.setStyleSheet(
            "QToolButton { background:#1d2230; border:1px solid #2b3242; border-radius:6px; }"
        )

        def _browse_crop_dir() -> None:
            from PySide6.QtWidgets import QFileDialog
            start = crop_path_edit.text().strip() or _crop_default
            chosen = QFileDialog.getExistingDirectory(dlg, "編集後画像の保存先", start)
            if chosen:
                crop_path_edit.setText(chosen)
                try:
                    if self._settings_manager is not None:
                        self._settings_manager.save_cropped_visual_dir(chosen)
                except Exception:
                    pass

        def _open_crop_folder() -> None:
            from pathlib import Path as _P
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            folder = _P(crop_path_edit.text().strip() or _crop_default or ".")
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

        crop_browse_btn.clicked.connect(_browse_crop_dir)
        crop_folder_btn.clicked.connect(_open_crop_folder)
        crop_row.addWidget(crop_lbl)
        crop_row.addWidget(crop_path_edit, 1)
        crop_row.addWidget(crop_browse_btn)
        crop_row.addWidget(crop_folder_btn)
        media_form.addRow(crop_row)
        root.addWidget(media_box)

        upd_box = QGroupBox("アップデート")
        upd_l = QVBoxLayout(upd_box)
        upd_l.setContentsMargins(8, 6, 8, 6)
        upd_l.setSpacing(4)
        auto_upd = QCheckBox("アップデートを自動で確認する")
        try:
            _auto = bool(self._settings_manager.get_auto_check_updates()) if self._settings_manager else False
        except Exception:
            _auto = False
        auto_upd.setChecked(_auto)
        from src.core.version import APP_VERSION as _APP_VER
        ver_lbl = QLabel(f"現在のバージョン: {_APP_VER}")
        ver_lbl.setStyleSheet("color:#7f899a; font-size:11px; background:transparent;")
        check_upd_btn = QToolButton()
        check_upd_btn.setText("今すぐ確認")
        check_upd_btn.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )

        check_upd_btn.clicked.connect(self.open_update_check)
        upd_row = QHBoxLayout()
        upd_row.setContentsMargins(0, 0, 0, 0)
        upd_row.setSpacing(14)
        upd_row.addWidget(auto_upd)
        upd_row.addWidget(ver_lbl)
        upd_row.addStretch(1)
        upd_row.addWidget(check_upd_btn)
        upd_l.addLayout(upd_row)
        root.addWidget(upd_box)

        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(dlg)
        except Exception:
            pass

        root.addWidget(buttons)

        def _apply() -> None:
            selected_theme = str(theme_combo.currentData() or "dark")
            if self._settings_manager is not None and hasattr(
                self._settings_manager, "save_ui_theme"
            ):
                self._settings_manager.save_ui_theme(selected_theme)
            try:
                self._apply_runtime_theme(selected_theme)
            except Exception:
                pass
            self._edge_dock_always_on_top = aot.isChecked()
            self._edge_dock_disable_on_fullscreen = bool(fs_guard.isChecked())
            self._dock_unread_indicator_enabled = bool(unread_ind.isChecked())
            self._edge_dock_width_lr = int(lr_w.value())
            self._edge_dock_height_lr = int(lr_h.value())
            self._edge_dock_width_tb = int(tb_w.value())
            self._edge_dock_height_tb = int(tb_h.value())
            self._edge_dock_column_count_lr = int(lr_c.value())
            self._edge_dock_column_count_tb = int(tb_c.value())
            self._edge_dock_zoom_percent = int(zoom.value())
            try:
                self._set_disable_x_keyboard_shortcuts(bool(x_sc_off.isChecked()))
            except Exception:
                pass
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass
            from src.browser.url_policy import (
                POLICY_ASK,
                POLICY_DEFAULT_BROWSER,
                POLICY_IN_APP,
                set_external_site_policy,
            )
            if rb_in_app.isChecked():
                _pol = POLICY_IN_APP
            elif rb_ask.isChecked():
                _pol = POLICY_ASK
            else:
                _pol = POLICY_DEFAULT_BROWSER
            set_external_site_policy(_pol)
            if self._settings_manager and hasattr(self._settings_manager, "save_external_site_policy"):
                self._settings_manager.save_external_site_policy(_pol)
            self._allowed_external_new_tab = bool(allowed_new_tab.isChecked())
            try:
                from src.browser.url_policy import set_allowed_external_new_tab
                set_allowed_external_new_tab(self._allowed_external_new_tab)
            except Exception:
                pass
            if self._settings_manager and hasattr(self._settings_manager, "save_allowed_external_new_tab"):
                try:
                    self._settings_manager.save_allowed_external_new_tab(self._allowed_external_new_tab)
                except Exception:
                    pass
            if self._settings_manager is not None:
                try:
                    self._settings_manager.save_auto_normalize_audio(auto_norm.isChecked())
                except Exception:
                    pass
                try:
                    self._settings_manager.save_auto_check_updates(auto_upd.isChecked())
                except Exception:
                    pass
                try:
                    self._settings_manager.save_save_recorded_audio(save_rec.isChecked())
                except Exception:
                    pass
                try:
                    self._settings_manager.save_recorded_audio_dir(rec_path_edit.text().strip())
                    try:
                        self._settings_manager.save_download_dir(dl_path_edit.text().strip())
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    self._settings_manager.save_audio_visual_image(_vis_state["path"])
                    self._settings_manager.save_audio_visual_image_original(
                        str(_vis_state.get("original") or _vis_state.get("path") or "")
                    )
                    self._settings_manager.save_audio_visual_image_transform(
                        float(_vis_state.get("crop_x", 0.0)),
                        float(_vis_state.get("crop_y", 0.0)),
                        float(_vis_state.get("scale", 1.0)),
                        float(_vis_state.get("rotation", 0.0)),
                    )
                except Exception:
                    pass
            self._edge_dock_column_count = self._column_count_for_edge()
            self._apply_edge_dock_always_on_top()
            if self._edge_dock_enabled and self._edge_dock_revealed:
                full = self._expanded_geometry_for_edge(self._edge_dock_direction)
                if self.geometry() != full:
                    self.setGeometry(full)
                self._update_edge_dock_column_visibility()
                self._dock_shape_mask_key = None
                self._apply_dock_shape_mask()
                self._apply_edge_dock_zoom()
            self._save_edge_dock_settings()

        buttons.rejected.connect(dlg.reject)
        aot.toggled.connect(
            lambda v: (
                setattr(self, "_edge_dock_always_on_top", bool(v)),
                self._apply_edge_dock_always_on_top(),
            )
        )
        unread_ind.toggled.connect(
            lambda v: (
                setattr(self, "_dock_unread_indicator_enabled", bool(v)),
                self._update_dock_notify_visual(),
            )
        )

        def _apply_settings_round_mask() -> None:
            try:
                ww = max(1, dlg.width())
                hh = max(1, dlg.height())
                from src.ui.window_polish import apply_native_window_polish, native_rounding_available
                if native_rounding_available():
                    dlg.clearMask()
                    apply_native_window_polish(dlg, corner="round")
                    return
                from src.ui.url_overlay import rounded_overlay_mask
                dlg.setMask(rounded_overlay_mask(ww, hh, 8))
            except Exception:
                pass

        class _SettingsMaskFilter(QObject):
            def eventFilter(self, obj, event):
                try:
                    if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
                        _apply_settings_round_mask()
                except Exception:
                    pass
                return False

        _mask_filter = _SettingsMaskFilter(dlg)
        dlg.installEventFilter(_mask_filter)
        QTimer.singleShot(0, _apply_settings_round_mask)

        dlg.adjustSize()
        pg = self.frameGeometry()
        x = pg.x() + max(0, (pg.width() - dlg.width()) // 2)
        y = pg.y() + max(0, (pg.height() - dlg.height()) // 2)
        screen = QGuiApplication.screenAt(pg.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            ag = screen.availableGeometry()
            x = max(ag.left(), min(x, ag.right() - dlg.width() + 1))
            y = max(ag.top(), min(y, ag.bottom() - dlg.height() + 1))
        dlg.move(x, y)

        try:
            from src.ui.theme import POPOVER_OPEN_MS, POPOVER_CLOSE_MS
        except Exception:
            POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
        try:
            dlg.setWindowOpacity(0.0)
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve

            def _settings_fade_in():
                anim = QPropertyAnimation(dlg, b"windowOpacity", dlg)
                anim.setDuration(int(POPOVER_OPEN_MS))
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()
                dlg._mayotter_fade_anim = anim

            QTimer.singleShot(0, _settings_fade_in)
        except Exception:
            try:
                dlg.setWindowOpacity(1.0)
            except Exception:
                pass

        def _settings_fade_close(result_code: int) -> None:
            if getattr(dlg, "_mayotter_closing", False):
                if not getattr(dlg, "_mayotter_done", False):
                    try:
                        dlg._mayotter_done = True
                        dlg.done(int(result_code))
                    except Exception:
                        try:
                            dlg.close()
                        except Exception:
                            pass
                return
            dlg._mayotter_closing = True
            dlg._mayotter_done = False

            def _cleanup_cursor() -> None:
                try:
                    while QApplication.overrideCursor() is not None:
                        QApplication.restoreOverrideCursor()
                except Exception:
                    pass
                try:
                    dlg.unsetCursor()
                except Exception:
                    pass
                try:
                    self.unsetCursor()
                except Exception:
                    pass

            def _finish():
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
                _cleanup_cursor()
                try:
                    dlg.done(int(result_code))
                except Exception:
                    try:
                        dlg.close()
                    except Exception:
                        pass

            try:
                from PySide6.QtCore import QPropertyAnimation, QEasingCurve
                anim = QPropertyAnimation(dlg, b"windowOpacity", dlg)
                anim.setDuration(int(POPOVER_CLOSE_MS))
                anim.setStartValue(float(dlg.windowOpacity() or 1.0))
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.Type.InCubic)
                anim.finished.connect(_finish)
                anim.start()
                dlg._mayotter_fade_anim = anim
            except Exception:
                _finish()
                return
            QTimer.singleShot(int(POPOVER_CLOSE_MS) + 100, _finish)

        def _on_settings_save() -> None:
            try:
                _apply()
            except Exception:
                import traceback
                traceback.print_exc()
            _settings_fade_close(int(QDialog.DialogCode.Accepted))

        def _on_settings_close() -> None:
            _settings_fade_close(int(QDialog.DialogCode.Rejected))

        try:
            buttons.accepted.disconnect()
            buttons.rejected.disconnect()
        except Exception:
            pass
        buttons.accepted.connect(_on_settings_save)
        buttons.rejected.connect(_on_settings_close)
        try:
            save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
            if save_btn is not None:
                try:
                    save_btn.clicked.disconnect()
                except Exception:
                    pass
                save_btn.clicked.connect(_on_settings_save)
                try:
                    buttons.accepted.disconnect(_on_settings_save)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
            if close_btn is not None:
                try:
                    close_btn.clicked.disconnect()
                except Exception:
                    pass
                close_btn.clicked.connect(_on_settings_close)
                try:
                    buttons.rejected.disconnect(_on_settings_close)
                except Exception:
                    pass
                buttons.rejected.connect(_on_settings_close)
        except Exception:
            pass
        try:
            close_tb.clicked.disconnect()
        except Exception:
            pass
        try:
            close_tb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            close_tb.raise_()
            close_tb.setCursor(Qt.CursorShape.PointingHandCursor)
        except Exception:
            pass
        close_tb.clicked.connect(_on_settings_close)
        try:
            close_tb.pressed.connect(_on_settings_close)
        except Exception:
            pass

        class _SettingsCloseFilter(QObject):
            def eventFilter(self, obj, event):
                try:
                    if obj is dlg and event.type() == QEvent.Type.Close:
                        if getattr(dlg, "_mayotter_done", False):
                            return False
                        if not getattr(dlg, "_mayotter_closing", False):
                            event.ignore()
                            _settings_fade_close(int(QDialog.DialogCode.Rejected))
                            return True
                        if not getattr(dlg, "_mayotter_done", False):
                            event.ignore()
                            return True
                except Exception:
                    pass
                return False

        _close_filter = _SettingsCloseFilter(dlg)
        dlg.installEventFilter(_close_filter)
        dlg.exec()

    def _save_edge_dock_settings(self) -> None:
        if not self._settings_manager or getattr(self, "_restoring_session", False):
            return
        self._edge_dock_edge_offset = self._get_edge_offset(self._edge_dock_direction)
        offsets = getattr(self, "_edge_dock_edge_offsets", None)
        clean_offsets = {}
        if isinstance(offsets, dict):
            clean_offsets = {
                k: float(max(0.0, min(1.0, float(v))))
                for k, v in offsets.items()
                if k in ("left", "right", "top", "bottom")
            }
        payload = {
            "edge_dock_enabled": bool(self._edge_dock_enabled),
            "edge_dock_direction": str(self._edge_dock_direction),
            "edge_dock_column_count": max(0, int(self._edge_dock_column_count)),
            "edge_dock_column_count_lr": max(0, min(8, int(self._edge_dock_column_count_lr))),
            "edge_dock_column_count_tb": max(0, min(8, int(self._edge_dock_column_count_tb))),
            "normal_column_count": max(0, int(self._normal_column_count)),
            "edge_dock_zoom_percent": max(50, min(150, int(self._edge_dock_zoom_percent))),
            "edge_dock_always_on_top": bool(self._edge_dock_always_on_top),
            "edge_dock_disable_on_fullscreen": bool(
                getattr(self, "_edge_dock_disable_on_fullscreen", True)
            ),
            "edge_dock_unread_indicator": bool(
                getattr(self, "_dock_unread_indicator_enabled", True)
            ),
            "edge_dock_width_lr": int(self._edge_dock_width_lr),
            "edge_dock_height_lr": int(self._edge_dock_height_lr),
            "edge_dock_width_tb": int(self._edge_dock_width_tb),
            "edge_dock_height_tb": int(self._edge_dock_height_tb),
            "edge_dock_panel_height_ratio": float(self._edge_dock_panel_height_ratio),
            "edge_dock_edge_offset": float(self._edge_dock_edge_offset),
            "edge_dock_edge_offsets": clean_offsets,
            "edge_dock_monitor_index": int(getattr(self, "_edge_dock_monitor_index", 0)),
        }
        try:
            self._settings_manager.save(payload)
        except Exception:
            pass

    def _load_edge_dock_settings(self) -> None:
        if self._settings_manager:
            self._edge_dock_enabled = self._settings_manager.get_edge_dock_enabled()
            self._edge_dock_direction = self._settings_manager.get_edge_dock_direction()
            self._edge_dock_column_count = self._settings_manager.get_edge_dock_column_count()
            if hasattr(self._settings_manager, "get_edge_dock_column_count_lr"):
                self._edge_dock_column_count_lr = self._settings_manager.get_edge_dock_column_count_lr()
                self._edge_dock_column_count_tb = self._settings_manager.get_edge_dock_column_count_tb()
            if hasattr(self._settings_manager, "get_normal_column_count"):
                self._normal_column_count = self._settings_manager.get_normal_column_count()
            if hasattr(self._settings_manager, "get_external_site_policy"):
                from src.browser.url_policy import set_external_site_policy
                set_external_site_policy(self._settings_manager.get_external_site_policy())

            else:
                self._edge_dock_column_count_lr = self._edge_dock_column_count
                self._edge_dock_column_count_tb = 2
            if hasattr(self._settings_manager, "get_edge_dock_zoom_percent"):
                self._edge_dock_zoom_percent = self._settings_manager.get_edge_dock_zoom_percent()
            if hasattr(self._settings_manager, "get_edge_dock_always_on_top"):
                self._edge_dock_always_on_top = self._settings_manager.get_edge_dock_always_on_top()
            if hasattr(self._settings_manager, "get_edge_dock_disable_on_fullscreen"):
                self._edge_dock_disable_on_fullscreen = (
                    self._settings_manager.get_edge_dock_disable_on_fullscreen()
                )
            if hasattr(self._settings_manager, "get_edge_dock_unread_indicator"):
                self._dock_unread_indicator_enabled = (
                    self._settings_manager.get_edge_dock_unread_indicator()
                )
            if hasattr(self._settings_manager, "get_allowed_external_new_tab"):
                try:
                    self._allowed_external_new_tab = bool(
                        self._settings_manager.get_allowed_external_new_tab()
                    )
                    from src.browser.url_policy import set_allowed_external_new_tab
                    set_allowed_external_new_tab(self._allowed_external_new_tab)
                except Exception:
                    self._allowed_external_new_tab = True
            if hasattr(self._settings_manager, "get_user_allowed_external"):
                try:
                    from src.browser.url_policy import set_user_allowed_external
                    set_user_allowed_external(
                        self._settings_manager.get_user_allowed_external()
                    )
                except Exception:
                    pass
            self._edge_dock_column_count = self._column_count_for_edge(self._edge_dock_direction)
            def _sz(key: str) -> int:
                try:
                    return max(0, int(self._settings_manager.get(key, 0) or 0))
                except (TypeError, ValueError):
                    return 0
            self._edge_dock_width_lr = _sz("edge_dock_width_lr")
            self._edge_dock_height_lr = _sz("edge_dock_height_lr")
            self._edge_dock_width_tb = _sz("edge_dock_width_tb")
            self._edge_dock_height_tb = _sz("edge_dock_height_tb")
            try:
                self._edge_dock_panel_height_ratio = float(
                    self._settings_manager.get("edge_dock_panel_height_ratio", 0.78) or 0.78
                )
            except (TypeError, ValueError):
                self._edge_dock_panel_height_ratio = 0.78
            try:
                self._edge_dock_edge_offset = float(
                    self._settings_manager.get("edge_dock_edge_offset", 0.5) or 0.5
                )
            except (TypeError, ValueError):
                self._edge_dock_edge_offset = 0.5
            self._edge_dock_edge_offset = max(0.0, min(1.0, self._edge_dock_edge_offset))
            # 方向ごとの最終位置（なければ単一オフセットで初期化）
            defaults = {
                "left": self._edge_dock_edge_offset,
                "right": self._edge_dock_edge_offset,
                "top": self._edge_dock_edge_offset,
                "bottom": self._edge_dock_edge_offset,
            }
            raw_offsets = self._settings_manager.get("edge_dock_edge_offsets", None)
            if isinstance(raw_offsets, dict):
                for k in ("left", "right", "top", "bottom"):
                    if k in raw_offsets:
                        try:
                            defaults[k] = max(0.0, min(1.0, float(raw_offsets[k])))
                        except (TypeError, ValueError):
                            pass
            self._edge_dock_edge_offsets = defaults
            # 現在方向の値を同期
            d = self._edge_dock_direction if self._edge_dock_direction in defaults else "right"
            self._edge_dock_edge_offset = defaults.get(d, 0.5)
            try:
                self._edge_dock_monitor_index = int(
                    self._settings_manager.get("edge_dock_monitor_index", 0) or 0
                )
            except (TypeError, ValueError):
                self._edge_dock_monitor_index = 0

    @staticmethod
    def _round_mask_region(width: int, height: int, radius: int = 10) -> QRegion:
        import math

        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPolygon

        w = max(1, int(width))
        h = max(1, int(height))
        r = max(0, min(int(radius), w // 2, h // 2))
        if r <= 0:
            return QRegion(0, 0, w, h)

        region = QRegion(0, r, w, max(1, h - r))
        if w > 2 * r:
            region = region.united(QRegion(r, 0, w - 2 * r, r))
        # 角丸は native region (SetWindowRgn) と同じ密な polygon で作る。
        # QRegion の楕円だと native 側がはみ出し、未描画の黒い画素が残る。
        samples = max(12, min(96, r * 4))

        def _arc(cx: int, cy: int, start: float, end: float) -> list:
            pts = []
            for i in range(samples + 1):
                a = start + (end - start) * (i / samples)
                pts.append(QPoint(round(cx + r * math.cos(a)), round(cy + r * math.sin(a))))
            return pts

        tl = _arc(r, r, math.pi, 1.5 * math.pi) + [QPoint(r, r)]
        region = region.united(QRegion(QPolygon(tl)))
        tr = _arc(w - r, r, 1.5 * math.pi, 2.0 * math.pi) + [QPoint(w - r, r)]
        region = region.united(QRegion(QPolygon(tr)))
        return region

    def _dock_outer_round_region(
        self, width: int, height: int, radius: int = 12, edge: str | None = None,
        all_corners: bool = False, flags: tuple | None = None,
    ) -> QRegion:
        """Dock の外形 region。丸める角は flags / all_corners / 方向で決まる。"""
        import math

        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPolygon

        w = max(1, int(width))
        h = max(1, int(height))
        r = max(0, min(int(radius), w // 2, h // 2))
        if r <= 0:
            return QRegion(0, 0, w, h)
        edge = edge or getattr(self, "_edge_dock_direction", "right") or "right"
        # 下辺は常に直角。Dock 接着面も直角にする。
        # left/right は上側の非接着角だけ、bottom は上2角だけ丸める。
        # 収納帯/アニメ中は接着面側を直角にして「上（反対側）に丸み」が来る形にする。
        # 展開後の fallback（DWM角丸が使えない環境）だけ四隅を丸める。
        rounded = flags if flags is not None else (True, True, True, True) if all_corners else {
                "left": (False, True, False, False),
                "right": (True, False, False, False),
                "top": (False, False, False, False),
                "bottom": (True, True, False, False),
            }.get(edge, (True, True, False, False))
        region = QRegion(0, 0, w, h)

        # 角丸は native region (SetWindowRgn) と同じ密な polygon で作る。
        # QRegion の楕円だと native 側がはみ出し、未描画の黒い画素が残る。
        samples = max(12, min(96, r * 4))

        def _arc(cx: int, cy: int, start: float, end: float) -> list:
            pts = []
            for i in range(samples + 1):
                a = start + (end - start) * (i / samples)
                pts.append(QPoint(round(cx + r * math.cos(a)), round(cy + r * math.sin(a))))
            return pts

        corners = (
            (rounded[0], QRect(0, 0, r, r), (r, r, math.pi, 1.5 * math.pi), QPoint(r, r)),
            (rounded[1], QRect(w - r, 0, r, r), (w - r, r, 1.5 * math.pi, 2.0 * math.pi), QPoint(w - r, r)),
            (rounded[2], QRect(w - r, h - r, r, r), (w - r, h - r, 0.0, 0.5 * math.pi), QPoint(w - r, h - r)),
            (rounded[3], QRect(0, h - r, r, r), (r, h - r, 0.5 * math.pi, math.pi), QPoint(r, h - r)),
        )
        for enabled, square, arc, tip in corners:
            if not enabled:
                continue
            region = region.subtracted(QRegion(square))
            quadrant = QRegion(QPolygon(_arc(*arc) + [tip]))
            region = region.united(quadrant)
        return region

    def _apply_dock_shape_mask(
        self, w: int | None = None, h: int | None = None, *, force: bool = False
    ) -> None:
        if not self._edge_dock_enabled:
            return
        if self._visual_commit_gate_active():
            self._hold_visual_commit_gate()
            return
        # force=True はアニメ中でも外形マスクを維持する（Right position-slide 用）
        if not force and not self.isVisible():
            return
        if not force and getattr(self, "_edge_dock_animating", False):
            return
        edge = getattr(self, "_edge_dock_direction", "right") or "right"
        # 展開が確定した Dock は Windows 11 の DWM 角丸（四隅）に任せる。
        # 1bit の region 円弧を見た目の輪郭にしない。
        dwm_round = False
        try:
            from src.ui.window_polish import native_rounding_available
            dwm_round = (
                native_rounding_available()
                and self._edge_dock_revealed
                and not getattr(self, "_edge_dock_animating", False)
                and not getattr(self, "_edge_dock_switching", False)
            )
        except Exception:
            pass
        try:
            from src.ui.window_polish import set_window_corner_preference
            set_window_corner_preference(self, "round" if dwm_round else "square")
        except Exception:
            pass
        self._refresh_native_borders()
        self._sync_dock_opaque_paint()
        # 収納中: Bottom は full HWND + local strip mask。他は strip サイズ HWND。
        if not self._edge_dock_revealed and not force:
            full = self._expanded_geometry_for_edge(edge)
            self._dock_slide_full_geom = QRect(full)
            self._edge_dock_reveal_progress = 0.0
            if edge == "bottom":
                fw, fh = max(1, full.width()), max(1, full.height())
                self._dock_slide_strip_geom = self._local_strip_rect("bottom", fw, fh)
                self._apply_reveal_mask(0.0)
            else:
                # position-slide stowed: strip サイズでも外側角丸を維持（clearMask しない）
                sw = max(1, self.width())
                sh = max(1, self.height())
                self._dock_slide_strip_geom = self._local_strip_rect(edge, sw, sh)
                radius = max(2, min(10, min(sw, sh) // 2))
                self.setMask(self._dock_peek_region(sw, sh, edge))
                self._dock_shape_mask_key = (sw, sh, radius, edge)
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass
            return
        ww = int(w if w is not None else self.width())
        hh = int(h if h is not None else self.height())
        if ww < 2 or hh < 2:
            self.setMask(QRegion())
            self._dock_shape_mask_key = None
            return
        if dwm_round:
            # 前状態の region が残っていれば外す。region 用の適用済み key も無効化し、
            # 直角へ戻る時に必ず再適用させる（DWM の corner mode とは別管理）。
            if not self.mask().isEmpty() or getattr(self, "_dock_shape_mask_key", None) is not None:
                self.clearMask()
                try:
                    from src.ui.window_polish import clear_native_region
                    clear_native_region(self)
                except Exception:
                    pass
            self._dock_shape_mask_key = None
            self._dock_native_region_key = None
            self._refresh_native_borders()
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass
            return
        radius = max(4, min(_DOCK_REVEAL_RADIUS, min(ww, hh) // 2))
        # key に edge を含め、方向切替時に必ず mask を差し替える
        theme_id = get_theme_id()
        key = (ww, hh, radius, edge, theme_id)
        same_mask = (
            not force
            and getattr(self, "_dock_shape_mask_key", None) == key
            and not self.mask().isEmpty()
        )
        self._dock_shape_mask_key = key

        if not same_mask:
            self.setMask(self._dock_outer_round_region(
                ww, hh, radius, edge=edge, all_corners=True
            ))
        if not getattr(self, "_edge_dock_animating", False) and not getattr(
            self, "_edge_dock_switching", False
        ):
            # Qt mask が既に同一keyで適用済み、かつ native region も同一keyで
            # 適用済みなら polygon 再生成と SetWindowRgn の結果は変わらない。
            # animating 中は native 適用を飛ばすため、適用済みkeyは別に持つ。
            native_stale = getattr(self, "_dock_native_region_key", None) != key
            if not same_mask or native_stale:
                try:
                    from src.ui.window_polish import apply_native_corner_region
                    round_flags = (True, True, True, True)
                    if apply_native_corner_region(
                        self,
                        radius=radius,
                        top_left=round_flags[0],
                        top_right=round_flags[1],
                        bottom_right=round_flags[2],
                        bottom_left=round_flags[3],
                    ):
                        self._dock_native_region_key = key
                except Exception:
                    pass
        try:
            self._update_dock_notify_visual()
        except Exception:
            pass

    def _schedule_normal_window_mask(self) -> None:
        if self._visual_commit_gate_active():
            self._window_mask_pending = True
            self._hold_visual_commit_gate()
            return
        if getattr(self, "_os_sizing", False):
            self._update_window_mask()
            return
        t = getattr(self, "_normal_mask_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(48)
            t.timeout.connect(self._apply_pending_normal_mask)
            self._normal_mask_timer = t
        self._window_mask_pending = True
        t.start()

    def _apply_pending_normal_mask(self) -> None:
        if self._visual_commit_gate_active():
            self._hold_visual_commit_gate()
            return
        if getattr(self, "_edge_dock_enabled", False):
            return
        self._window_mask_pending = False
        self._window_mask_key = None
        self._update_window_mask()

    def _update_window_mask(self) -> None:
        if self._visual_commit_gate_active():
            self._hold_visual_commit_gate()
            return
        if not self.isVisible() or self.isMaximized() or self.isFullScreen():
            if not self.mask().isEmpty():
                self.clearMask()
            self._window_mask_key = None
            try:
                from src.ui.window_polish import set_window_corner_preference
                set_window_corner_preference(self, "square")
            except Exception:
                pass
            return
        if self._edge_dock_enabled:
            self._apply_dock_shape_mask()
            return

        ww = max(1, int(self.width()))
        hh = max(1, int(self.height()))
        try:
            from src.ui.window_polish import (
                clear_native_region, native_rounding_available, set_window_corner_preference,
            )
            # Windows 11 では region 切り抜き（アンチエイリアス不可でギザギザ）をやめ、
            # DWM のアンチエイリアス付き角丸を使う。この場合は下辺も丸くなる。
            if native_rounding_available():
                key = (ww, hh, "normal-dwm-round", get_theme_id())
                if getattr(self, "_window_mask_key", None) != key:
                    self._window_mask_key = key
                    self._window_native_region_key = None
                    self._dock_native_region_key = None
                    self._dock_shape_mask_key = None
                    self.clearMask()
                    clear_native_region(self)
                set_window_corner_preference(self, "round")
                self._refresh_native_borders()
                return
        except Exception:
            pass
        try:
            from src.ui.window_polish import set_window_corner_preference
            # DWM は四隅をまとめて丸めるので、下辺を直角にするこの経路では
            # DWM の角丸を切り、上だけ丸い region を使う（Windows 10 向け）。
            set_window_corner_preference(self, "square")
        except Exception:
            pass

        theme_id = get_theme_id()
        key = (ww, hh, "normal-top-only", theme_id)
        # key が同一で native region 適用済みなら、polygon 再生成と
        # SetWindowRgn は結果が変わらない。有効化/非有効化の changeEvent は
        # サイズを変えないので、ここで毎回の再適用を止められる。
        same_mask = (
            getattr(self, "_window_mask_key", None) == key
            and not self.mask().isEmpty()
        )
        if not same_mask:
            self._window_mask_key = key
            self._window_mask_pending = False
            self.setMask(self._round_mask_region(ww, hh, 12))
        if not same_mask or getattr(self, "_window_native_region_key", None) != key:
            try:
                from src.ui.window_polish import apply_native_top_corner_region
                if apply_native_top_corner_region(
                    self, radius=12, top_left=True, top_right=True
                ):
                    self._window_native_region_key = key
            except Exception:
                pass

    def _local_from_physical(self, gx: int, gy: int) -> QPoint:
        handle = self.windowHandle()
        dpr = (handle.devicePixelRatio() if handle is not None else self.devicePixelRatioF()) or 1.0
        logical = QPoint(round(gx / dpr), round(gy / dpr))
        return self.mapFromGlobal(logical)

    @staticmethod
    def _widget_is_interactive_control(w) -> bool:
        if w is None:
            return False
        name = type(w).__name__
        if name in (
            "QPushButton", "QToolButton", "QLineEdit", "QPlainTextEdit", "QTextEdit",
            "QListWidget", "QComboBox", "QSpinBox", "QDoubleSpinBox", "QCheckBox",
            "QKeySequenceEdit", "QAbstractItemView", "QScrollBar", "QTabBar",
            "QTabWidget", "QSlider", "DownloadIconButton",
            "_ColumnDragHandle",
            "_BoundaryHandle",
        ):
            return True
        try:
            if str(w.objectName() or "") in ("col_drag_handle", "column_resize_handle"):
                return True
        except Exception:
            pass
        return False

    def _interactive_control_at_global(self, gp) -> bool:
        try:
            from PySide6.QtWidgets import QApplication
            w = QApplication.widgetAt(gp)
        except Exception:
            return False
        while w is not None:
            if self._widget_is_interactive_control(w):
                return True
            try:
                w = w.parentWidget()
            except Exception:
                break
        return False

    @staticmethod
    def _widget_is_column_reorder_grip(w) -> bool:
        while w is not None:
            try:
                if str(w.objectName() or "") == "col_drag_handle":
                    return True
                if type(w).__name__ == "_ColumnDragHandle":
                    return True
            except Exception:
                pass
            try:
                w = w.parentWidget()
            except Exception:
                break
        return False

    def _column_reorder_grip_at_global(self, gp) -> bool:
        try:
            from PySide6.QtWidgets import QApplication
            w = QApplication.widgetAt(gp)
        except Exception:
            return False
        return self._widget_is_column_reorder_grip(w)

    def _suspend_dock_popups(self) -> None:
        suspended: list[str] = []

        ov = getattr(self, "_column_add_overlay", None)
        if ov is not None and (ov.isVisible() or bool(getattr(ov, "_mayotter_fading_out", False))):
            try:
                ov.close_overlay(immediate=True)
            except Exception:
                pass
        dov = getattr(self, "_download_overlay", None)
        if dov is not None and (dov.isVisible() or bool(getattr(dov, "_mayotter_fading_out", False))):
            try:
                QApplication.instance().removeEventFilter(dov)
            except Exception:
                pass
            try:
                dov._mayotter_fading_out = False
            except Exception:
                pass
            try:
                dov.hide()
            except Exception:
                pass
            suspended.append("download")
        menu = getattr(self, "_current_service_menu", None)
        if menu is not None and menu.isVisible():
            try:
                QApplication.instance().removeEventFilter(menu)
            except Exception:
                pass
            try:
                menu.hide()
            except Exception:
                pass
            suspended.append("service_menu")
        self._suspended_dock_popups = suspended

    def _restore_dock_popups(self) -> None:
        suspended = list(getattr(self, "_suspended_dock_popups", None) or [])
        self._suspended_dock_popups = []
        if not suspended:
            return
        if "download" in suspended:
            self._restore_download_overlay_suspended()
        if "service_menu" in suspended:
            self._restore_service_menu_suspended()

    def _restore_download_overlay_suspended(self) -> None:
        dov = getattr(self, "_download_overlay", None)
        if dov is None:
            return
        try:
            if hasattr(dov, "open_history"):
                dov.open_history()
            else:
                dov.show()
        except Exception:
            pass

    def _restore_service_menu_suspended(self) -> None:
        menu = getattr(self, "_current_service_menu", None)
        if menu is None:
            return
        try:
            btn = getattr(self, "_add_twitter_btn", None)
            if btn is not None:
                pos = btn.mapToGlobal(btn.rect().bottomLeft())
                menu.move(pos)
            try:
                self._ensure_service_menu_above_dock(menu)
            except Exception:
                pass
            menu.show()
            menu.raise_()
            try:
                QApplication.instance().installEventFilter(menu)
            except Exception:
                pass
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            chrome = (
                getattr(self, "_add_twitter_btn", None),
                getattr(self, "_add_column_btn", None),
                getattr(self, "_download_icon_btn", None),
                getattr(self, "_record_btn", None),
                getattr(self, "_settings_btn", None),
                getattr(self, "_edge_dock_toggle_btn", None),
            )
            if obj in chrome and event.type() == QEvent.Type.MouseButtonPress:
                if getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
                    if self._edge_dock_enabled and self._edge_dock_revealed:
                        try:
                            self._set_interactive(True)
                        except Exception:
                            pass
                        try:
                            if self.mouseGrabber() is self:
                                self.releaseMouse()
                        except Exception:
                            pass
        except Exception:
            pass
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton
        ):
            if self._try_dispatch_restore_from_global(event):
                return True
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton
        ):
            if self._try_dispatch_boundary_action_from_global(event):
                return True
        if event.type() == QEvent.Type.MouseMove:
            self._update_restore_knob_cursor_from_global(event)
            self._update_boundary_action_cursor_from_global(event)

        if getattr(self, "_edge_dock_enabled", False):
            chev = getattr(self, "_dock_chrome_chevron", None)
            tray = getattr(self, "_dock_chrome_tray", None)
            if obj in (chev, tray) and event.type() in (
                QEvent.Type.Enter,
                QEvent.Type.HoverEnter,
            ):
                self._set_dock_chrome_expanded(True)
            elif obj in (chev, tray) and event.type() in (
                QEvent.Type.Leave,
                QEvent.Type.HoverLeave,
            ):
                if not getattr(self, "_edge_dock_dragging", False) and not getattr(
                    self, "_edge_dock_resizing", False
                ):
                    QTimer.singleShot(180, self._maybe_collapse_dock_chrome)
        if (
            event.type() == QEvent.Type.MouseMove
            and self._edge_dock_enabled
            and self._edge_dock_revealed
            and not self._edge_dock_resizing
            and not self._edge_dock_dragging
        ):
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                gp = None
            if gp is not None and self._column_reorder_grip_at_global(gp):
                if getattr(self, "_edge_cursor_forced", False):
                    try:
                        QApplication.restoreOverrideCursor()
                    except Exception:
                        pass
                    self._edge_cursor_forced = False
                if getattr(self, "_boundary_hand_cursor", False):
                    try:
                        QApplication.restoreOverrideCursor()
                    except Exception:
                        pass
                    self._boundary_hand_cursor = False
            elif gp is not None:
                local = self.mapFromGlobal(gp)
                if self.rect().contains(local):
                    self._update_resize_cursor(local)
                elif getattr(self, "_edge_cursor_forced", False):
                    QApplication.restoreOverrideCursor()
                    self._edge_cursor_forced = False
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton
            and self._edge_dock_enabled
            and self._edge_dock_revealed
            and not self._edge_dock_resizing
            and not self.isMaximized()
            and not self.isFullScreen()
        ):
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                gp = None
            if self._widget_is_column_reorder_grip(obj) or (
                gp is not None and self._column_reorder_grip_at_global(gp)
            ):
                return super().eventFilter(obj, event)
            if gp is not None and not self._interactive_control_at_global(gp):
                local = self.mapFromGlobal(gp)
                estr = self._hit_resize(local)
                if not estr:
                    code = self._resize_hit_code(local.x(), local.y())
                    estr = self._edges_str_from_ht_code(code) if code else ""
                if estr and self._prefer_webview_scroll_over_resize(gp, local, estr):
                    estr = ""
                if estr:
                    if self._begin_dock_manual_resize(estr, gp):
                        return True
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton
        ):
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                gp = None
            if gp is not None:
                w = QApplication.widgetAt(gp)
                col = self._column_from_widget(w)
                if col is not None and col is not self._active_column:
                    self._set_active_column(col)
        return super().eventFilter(obj, event)

    def _column_from_widget(self, w) -> AccountColumn | None:
        while w is not None:
            if isinstance(w, AccountColumn):
                return w
            w = w.parentWidget() if hasattr(w, "parentWidget") else None
        return None

    def _resize_hit_code(self, x: int, y: int) -> int:

        if self.isMaximized() or self.isFullScreen():
            return 0

        # 収納状態の細い帯はリサイズ対象にしない（展開時のみリサイズ可）
        if getattr(self, "_edge_dock_enabled", False) and not getattr(
            self, "_edge_dock_revealed", False
        ):
            return 0

        if self._point_on_restore_knob(x, y):
            return 0

        w = self.width()
        h = self.height()
        m = _RESIZE_MARGIN
        c = _RESIZE_CORNER

        left = x < m
        right = x >= w - m
        top = y < m
        bottom = y >= h - m
        # 角は辺より広い正方形で斜めリサイズを取りやすくする
        left_c = x < c
        right_c = x >= w - c
        top_c = y < c
        bottom_c = y >= h - c

        if getattr(self, "_edge_dock_enabled", False):
            dock = getattr(self, "_edge_dock_direction", "right")
            if dock == "left":
                left = False
                left_c = False
            elif dock == "right":
                right = False
                right_c = False
            elif dock == "top":
                top = False
                top_c = False
            elif dock == "bottom":
                bottom = False
                bottom_c = False

        if left_c and top_c:
            return _HTTOPLEFT
        if right_c and top_c:
            return _HTTOPRIGHT
        if left_c and bottom_c:
            return _HTBOTTOMLEFT
        if right_c and bottom_c:
            return _HTBOTTOMRIGHT
        if left:
            return _HTLEFT
        if right:
            return _HTRIGHT
        if top:
            return _HTTOP
        if bottom:
            return _HTBOTTOM
        return 0

    def _edges_str_from_ht_code(self, code: int) -> str:
        s = ""
        if code in (_HTLEFT, _HTTOPLEFT, _HTBOTTOMLEFT):
            s += "L"
        if code in (_HTRIGHT, _HTTOPRIGHT, _HTBOTTOMRIGHT):
            s += "R"
        if code in (_HTTOP, _HTTOPLEFT, _HTTOPRIGHT):
            s += "T"
        if code in (_HTBOTTOM, _HTBOTTOMLEFT, _HTBOTTOMRIGHT):
            s += "B"
        return s

    def _begin_dock_manual_resize(self, edges: str, global_pos) -> bool:
        if not edges:
            return False
        self._edge_dock_resizing = True
        self._edge_dock_resize_edges = edges
        self._edge_dock_resize_origin = global_pos
        self._edge_dock_resize_geom = QRect(self.geometry())
        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
        self.grabMouse()
        return True

    def _begin_edge_dock_drag_from_transition(self, global_pos: QPoint) -> bool:
        """方向切替shellを即座に中断し、その位置からDockドラッグへ戻る。"""
        if not self._edge_dock_enabled or not self._edge_dock_revealed:
            return False
        gate = getattr(self, "_transition_commit_gate", None)
        if gate is not None and gate.busy:
            try:
                gate.cancel(finalize=True)
            except Exception:
                return False
        try:
            self.setUpdatesEnabled(True)
            self._set_dock_content_updates(True)
            self._set_interactive(True)
            self._set_window_opaque(True)
        except Exception:
            pass
        self._edge_dock_animating = False
        self._edge_dock_dir_transitioning = False
        self._edge_dock_switching = False
        try:
            self._dock_shape_mask_key = None
            self._apply_dock_shape_mask(force=True)
        except Exception:
            pass
        try:
            self._store_live_size(self.width(), self.height(), self._edge_dock_direction)
        except Exception:
            pass

        anchor = self.mapFromGlobal(global_pos)
        anchor.setX(max(0, min(max(0, self.width() - 1), anchor.x())))
        anchor.setY(max(0, min(max(0, self.height() - 1), anchor.y())))
        self._edge_dock_dragging = True
        self._edge_dock_drag_start_direction = self._edge_dock_direction
        self._edge_dock_drag_anchor = anchor
        self._edge_dock_drag_last_global_pos = QPoint(global_pos)
        self._edge_dock_drag_offset = self._get_edge_offset(self._edge_dock_direction)
        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
            self._edge_detector.set_state(PanelState.EXPANDED)
            self._edge_detector.set_params(edge=self._edge_dock_direction)
        try:
            self.grabMouse()
        except Exception:
            self._edge_dock_dragging = False
            return False
        return True

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized() and not self.isFullScreen():
            pos = event.position().toPoint()
            code = self._resize_hit_code(pos.x(), pos.y())
            edges = _QT_EDGES_FOR_HT_CODE.get(code)
            child = self.childAt(pos)
            try:
                gpos = event.globalPosition().toPoint()
            except Exception:
                gpos = None
            if edges is not None:
                if gpos is not None and self._column_reorder_grip_at_global(gpos):
                    edges = None
                elif child is not None and self._widget_is_column_reorder_grip(child):
                    edges = None
            if edges is not None:
                if (
                    self._edge_dock_enabled
                    and self._edge_dock_revealed
                    and not self.isMaximized()
                ):
                    estr = self._edges_str_from_ht_code(code) or self._hit_resize(pos)
                    if estr and gpos is not None and self._prefer_webview_scroll_over_resize(
                        gpos, pos, estr
                    ):
                        estr = ""
                    if estr and self._begin_dock_manual_resize(
                        estr, event.globalPosition().toPoint()
                    ):
                        event.accept()
                        return
                else:
                    wh = self.windowHandle()
                    if wh is not None:
                        wh.startSystemResize(edges)
                        event.accept()
                        return

        interactable = self._edge_dock_revealed or self._edge_dock_animating
        if event.button() != Qt.MouseButton.LeftButton or not self._edge_dock_enabled or not interactable:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        if self._edge_dock_animating:
            if self._edge_animator:
                self._edge_animator.stop()
            self._edge_dock_animating = False
            self._edge_dock_revealed = True
            self._edge_dock_reveal_progress = 1.0
            self._apply_reveal_mask(1.0)
            self._set_window_opaque(True)
            self._set_interactive(True)
            if self._edge_detector:
                self._edge_detector.set_state(PanelState.EXPANDED)
        edges = self._hit_resize(pos)
        if edges:
            try:
                _gp = event.globalPosition().toPoint()
            except Exception:
                _gp = None
            if _gp is not None and self._prefer_webview_scroll_over_resize(_gp, pos, edges):
                edges = ""
        if edges:
            self._edge_dock_resizing = True
            self._edge_dock_resize_edges = edges
            self._edge_dock_resize_origin = event.globalPosition().toPoint()
            self._edge_dock_resize_geom = self.geometry()
            if self._edge_detector:
                self._edge_detector.set_pinned_open(True)
            self.grabMouse()
            event.accept()
            return
        try:
            gp = event.globalPosition().toPoint()
        except Exception:
            gp = None
        if gp is not None and (
            self._column_reorder_grip_at_global(gp)
            or self._interactive_control_at_global(gp)
        ):
            try:
                from PySide6.QtWidgets import QApplication
                while QApplication.overrideCursor() is not None:
                    QApplication.restoreOverrideCursor()
                self._edge_cursor_forced = False
                self._boundary_hand_cursor = False
            except Exception:
                pass
            super().mousePressEvent(event)
            return
        child = self.childAt(pos)
        w = child
        while w is not None and w is not self:
            if self._widget_is_interactive_control(w):
                super().mousePressEvent(event)
                return
            w = w.parentWidget()
        # 進行中の方向切替アニメがあれば止める（ドラッグ中はサイズ固定）
        prev_anim = getattr(self, "_edge_dir_anim", None)
        if prev_anim is not None:
            try:
                prev_anim.stop()
            except Exception:
                pass
            self._edge_dir_anim = None
        self._edge_dock_dir_transitioning = False
        # 収納・展開アニメが途中なら止めて状態を揃える（終了後の hover 不能を防ぐ）
        if self._edge_animator is not None:
            try:
                self._edge_animator.stop()
            except Exception:
                pass
        self._edge_dock_animating = False
        try:
            self._store_live_size(self.width(), self.height(), self._edge_dock_direction)
        except Exception:
            pass
        self._edge_dock_dragging = True
        self._edge_dock_drag_start_direction = self._edge_dock_direction
        self._edge_dock_drag_anchor = event.position().toPoint()
        self._edge_dock_drag_last_global_pos = event.globalPosition().toPoint()
        self._edge_dock_drag_offset = self._get_edge_offset(self._edge_dock_direction)
        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
            if self._edge_dock_revealed:
                self._edge_detector.set_state(PanelState.EXPANDED)
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if not self._edge_dock_enabled:
            if self._edge_dock_dragging or self._edge_dock_resizing:
                self._edge_dock_dragging = False
                self._edge_dock_drag_anchor = None
                self._edge_dock_drag_last_global_pos = None
                self._edge_dock_drag_start_direction = None
                self._edge_dock_drag_offset = None
                self._edge_dock_resizing = False
                self._edge_dock_resize_edges = ""
                self._edge_dock_resize_origin = None
                self._edge_dock_resize_geom = None
                try:
                    if self.mouseGrabber() is self:
                        self.releaseMouse()
                except Exception:
                    pass
            super().mouseMoveEvent(event)
            return
        if self._edge_dock_resizing and self._edge_dock_resize_origin and self._edge_dock_resize_geom:
            delta = event.globalPosition().toPoint() - self._edge_dock_resize_origin
            g = QRect(self._edge_dock_resize_geom)
            min_w, min_h = 240, 200
            dock = self._edge_dock_direction
            if "L" in self._edge_dock_resize_edges:
                g.setLeft(min(g.right() - min_w, self._edge_dock_resize_geom.left() + delta.x()))
            if "R" in self._edge_dock_resize_edges:
                g.setWidth(max(min_w, self._edge_dock_resize_geom.width() + delta.x()))
            if "T" in self._edge_dock_resize_edges:
                g.setTop(min(g.bottom() - min_h, self._edge_dock_resize_geom.top() + delta.y()))
            if "B" in self._edge_dock_resize_edges:
                g.setHeight(max(min_h, self._edge_dock_resize_geom.height() + delta.y()))
            screen = self._get_screen_geometry()
            if dock == "right":
                g.moveRight(screen.right())
            elif dock == "left":
                g.moveLeft(screen.left())
            elif dock == "bottom":
                g.moveBottom(screen.bottom())
            elif dock == "top":
                g.moveTop(screen.top())
            g = self._apply_dock_toplevel_geometry(g)
            fw, fh = max(1, g.width()), max(1, g.height())
            self._store_live_size(fw, fh, dock)
            t = 1.0 if self._edge_dock_revealed else float(getattr(self, "_edge_dock_reveal_progress", 0.0))
            self._apply_reveal_mask(t)
            self._apply_dock_shape_mask(fw, fh)
            if self._edge_dock_revealed:
                try:
                    self._fit_columns()
                except Exception:
                    pass
                try:
                    self._sync_webviews_to_columns_layout_safe()
                except Exception:
                    pass
            event.accept()
            return
        if self._edge_dock_dragging:
            self._follow_drag(event.globalPosition().toPoint())
            event.accept()
            return
        if self._edge_dock_enabled and self._edge_dock_revealed and not self._edge_dock_dragging and not self._edge_dock_resizing:
            self._update_resize_cursor(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self._edge_dock_enabled:
            self._edge_dock_dragging = False
            self._edge_dock_drag_anchor = None
            self._edge_dock_drag_last_global_pos = None
            self._edge_dock_drag_start_direction = None
            self._edge_dock_drag_offset = None
            self._edge_dock_resizing = False
            self._edge_dock_resize_edges = ""
            self._edge_dock_resize_origin = None
            self._edge_dock_resize_geom = None
            try:
                if self.mouseGrabber() is self:
                    self.releaseMouse()
            except Exception:
                pass
            super().mouseReleaseEvent(event)
            return
        if self._edge_dock_resizing:
            self._edge_dock_resizing = False
            self.releaseMouse()
            self._snap_to_dock_edge()
            edge = self._edge_dock_direction
            self._store_live_size(self.width(), self.height(), edge)
            self._dock_shape_mask_key = None
            self._apply_dock_shape_mask()
            if self._settings_manager:
                if edge in ("top", "bottom"):
                    self._settings_manager.set("edge_dock_width_tb", self._edge_dock_width_tb)
                    self._settings_manager.set("edge_dock_height_tb", self._edge_dock_height_tb)
                else:
                    self._settings_manager.set("edge_dock_width_lr", self._edge_dock_width_lr)
                    self._settings_manager.set("edge_dock_height_lr", self._edge_dock_height_lr)
            fw, fh = max(1, self.width()), max(1, self.height())
            clip = getattr(self, "_edge_dock_clip", None)
            root = getattr(self, "_edge_dock_root", None)
            if clip is not None:
                clip.setGeometry(0, 0, fw, fh)
            if root is not None:
                root.setGeometry(0, 0, fw, fh)
            if self._edge_dock_revealed:
                self._apply_reveal_mask(1.0)
                # 手動リサイズ終了時に非stowカラムの visibility を再適用する。
                # 直前に collapse 経路や count ベース hide で hide された列が
                # 残っていると「リサイズ後にカラムが消えた」ように見えるため。
                try:
                    self._update_edge_dock_column_visibility()
                except Exception:
                    pass
                self._fit_columns()
            else:
                full_c = self._expanded_geometry_for_edge(self._edge_dock_direction)
                if self.geometry() != full_c:
                    self.setGeometry(full_c)
                self._dock_slide_full_geom = QRect(full_c)
                self._dock_slide_strip_geom = QRect(self._collapsed_geometry())
                self._apply_reveal_mask(0.0)
            if self._edge_detector:
                self._edge_detector.set_pinned_open(False)
            event.accept()
            return
        if self._edge_dock_dragging:
            self._edge_dock_dragging = False
            self._edge_dock_drag_anchor = None
            self._edge_dock_drag_last_global_pos = None
            self.releaseMouse()
            # 辺が変わった直後のタブ描画が古いまま残るため、ドロップ後に描き直す
            self._refresh_tab_strip_layout()
            self._edge_dock_animating = False
            if self._edge_animator is not None:
                try:
                    self._edge_animator.stop()
                except Exception:
                    pass
            # 残留 size-lerp を破棄
            prev_anim = getattr(self, "_edge_dir_anim", None)
            if prev_anim is not None:
                try:
                    prev_anim.stop()
                except Exception:
                    pass
                self._edge_dir_anim = None

            start_dir = getattr(self, "_edge_dock_drag_start_direction", None)
            self._edge_dock_drag_start_direction = None
            new_dir = self._edge_dock_direction
            drag_offset = getattr(self, "_edge_dock_drag_offset", None)
            self._edge_dock_drag_offset = None
            if drag_offset is not None:
                self._set_edge_offset(drag_offset, new_dir)
            direction_changed = (
                start_dir is not None and start_dir != new_dir
            )

            if self._edge_dock_revealed:
                # 方向が変わった、または新方向の target サイズが現在と大きく異なる場合は
                # 表示中の live setGeometry を禁止し、離散 hide→commit→show のみ使う。
                full = self._expanded_geometry_for_edge(new_dir)
                cur = self.geometry()
                size_differs = (
                    abs(cur.width() - full.width()) > 8
                    or abs(cur.height() - full.height()) > 8
                )
                if direction_changed or size_differs:
                    gate = getattr(self, "_transition_commit_gate", None)
                    if gate is not None and not gate.busy and full.isValid():
                        def _commit_drag_direction() -> None:
                            self._apply_edge_direction_discrete(new_dir, target_geom=full)
                            self._snap_to_dock_edge()
                            self._set_interactive(True)
                            self._set_window_opaque(True)
                            if self._edge_detector:
                                self._edge_detector.set_pinned_open(False)
                                self._edge_detector.set_state(PanelState.EXPANDED)
                                self._edge_detector.set_params(edge=new_dir)
                            self._save_edge_dock_settings()
                            self._refresh_tab_strip_layout()
                        gate.contract(
                            full,
                            _commit_drag_direction,
                            source_edge=start_dir,
                            target_edge=new_dir,
                        )
                        event.accept()
                        return
                    self._apply_edge_direction_discrete(new_dir, target_geom=full)
                    self._snap_to_dock_edge()
                    self._set_interactive(True)
                    self._set_window_opaque(True)
                else:
                    # 同一方向・ほぼ同サイズ: 既存の軽量 commit（位置スナップのみ）
                    self._edge_dock_profile_lock = True
                    try:
                        self._commit_dock_container_geometry(full, revealed=True)
                        self._snap_to_dock_edge()
                        full = QRect(self.geometry())
                        self._dock_slide_full_geom = QRect(full)
                        self._update_edge_dock_column_visibility()
                        self._apply_dock_content_insets()
                        try:
                            self._fit_columns()
                        except Exception:
                            pass
                        try:
                            for col in self._columns:
                                if not col.isVisible():
                                    continue
                                for wv in getattr(col, "webviews", lambda: [])():
                                    if wv is None:
                                        continue
                                    try:
                                        wv.update()
                                    except Exception:
                                        pass
                            self._update_boundary_visibility()
                        except Exception:
                            pass
                        try:
                            self._set_dock_content_updates(True)
                        except Exception:
                            pass
                        try:
                            self._set_dock_webengines_visible(True)
                        except Exception:
                            pass
                        self._set_interactive(True)
                        self._set_window_opaque(True)
                    finally:
                        self._edge_dock_profile_lock = False
            self._dock_shape_mask_key = None
            try:
                self._apply_dock_shape_mask()
            except Exception:
                pass
            # detector を通常状態へ戻す（EXPANDING/COLLAPSING 残留で hover 不能になるのを防ぐ）
            if self._edge_detector:
                self._edge_detector.set_pinned_open(False)
                if self._edge_dock_revealed:
                    self._edge_detector.set_state(PanelState.EXPANDED)
                else:
                    self._edge_detector.set_state(PanelState.COLLAPSED)
                self._edge_detector.set_params(edge=self._edge_dock_direction)
            self._save_edge_dock_settings()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_active_column(self, column: AccountColumn) -> None:
        if self._active_column is column:
            return

        if self._active_column is not None:
            try:
                self._active_column.tabs_changed.disconnect(self._rebuild_strip)
                self._active_column.current_tab_changed.disconnect(self._rebuild_strip)
                self._active_column.tab_title_changed.disconnect(self._on_tab_title_changed)
            except (TypeError, RuntimeError):
                pass

        self._active_column = column
        try:
            self._mode_active[self._bound_layout_mode_key()] = column
        except Exception:
            pass
        self._rebuild_strip()

        if self._active_column is not None:
            self._active_column.tabs_changed.connect(self._rebuild_strip)
            self._active_column.current_tab_changed.connect(self._rebuild_strip)
            self._active_column.tab_title_changed.connect(self._on_tab_title_changed)

    def _rebuild_strip(self) -> None:
        if self._active_column is None:
            self._tab_strip.rebuild([], 0)
            return

        tabs = []
        badges = []
        current = self._active_column._current_tab
        for i, tab in enumerate(self._active_column.tab_views()):
            custom = (getattr(tab, "_custom_name", "") or "").strip()
            title = custom or self._natural_tab_title(tab, i)
            tabs.append(title)
            if i == current:
                try:
                    tab._tab_badge = ""
                except Exception:
                    pass
                badges.append("")
            else:
                badge = self._badge_text_for_tab(tab, title)
                badges.append(badge)

        self._tab_strip.rebuild(tabs, current, badges)

    @staticmethod
    def _natural_tab_title(tab, index: int) -> str:
        title = ""
        try:
            title = tab.title() if hasattr(tab, "title") else ""
        except Exception:
            title = ""
        if not title and hasattr(tab, "get_current_url"):
            try:
                title = tab.get_current_url() or ""
            except Exception:
                title = ""
        if not title:
            title = (getattr(tab, "_pending_restore_url", "") or "").strip()
        return title or f"Tab {index + 1}"

    @staticmethod
    def _badge_text_for_tab(tab, title: str = "") -> str:
        try:
            stored = getattr(tab, "_tab_badge", None)
            if stored:
                return str(stored)
        except Exception:
            pass
        t = title or ""
        try:
            if hasattr(tab, "title"):
                t = tab.title() or t
        except Exception:
            pass
        m = re.match(r"^\((\d+)\)\s*", str(t) or "")
        if m:
            n = int(m.group(1))
            if n <= 0:
                return ""
            return str(n) if n < 100 else "99"
        return ""

    def _clear_strip(self) -> None:
        self._tab_strip.rebuild([], 0)

    def _on_tab_strip_new_tab(self) -> None:
        col = self._active_column
        if col is None:
            return
        self._on_new_tab_requested("https://x.com/home", col)

    def _on_tab_chip_selected(self, index: int) -> None:
        if self._active_column is not None:
            try:
                views = self._active_column.tab_views()
                if 0 <= index < len(views):
                    views[index]._tab_badge = ""
            except Exception:
                pass
            self._active_column.set_current_tab(index)
            try:
                self._rebuild_strip()
            except Exception:
                pass

    def _on_tab_chip_close(self, index: int) -> None:
        if self._active_column is not None:
            self._active_column.close_tab(index)

    def _show_tab_context_menu(self, index: int, global_pos) -> None:
        col = self._active_column
        if col is None:
            return
        views = col.tab_views()
        if not (0 <= index < len(views)):
            return
        menu = QMenu(self)
        self._style_mayotter_menu(menu)
        rename_act = menu.addAction("名前を変更")
        chosen = menu.exec(global_pos)
        if chosen == rename_act:
            self._prompt_rename_tab(views[index], index)

    def _prompt_rename_tab(self, tab, index: int) -> None:
        if self._name_overlay is None or tab is None:
            return
        natural = self._natural_tab_title(tab, index)
        current = (getattr(tab, "_custom_name", "") or "").strip() or natural
        self._name_overlay.open_prompt("タブ名", current, "保存", allow_empty=True)
        self._name_prompt_mode = ("rename_tab", tab, natural)
        self._ensure_name_overlay_accepted_connected()

    def _on_tab_reorder(self, from_index: int, to_index: int) -> None:
        if self._active_column is not None:
            self._active_column.move_tab(from_index, to_index)

    def _on_tab_title_changed(self) -> None:
        if self._active_column is not None:
            self._rebuild_strip()

    def _on_column_activated(self, column: AccountColumn) -> None:
        self._set_active_column(column)


    def _ensure_service_menu_above_dock(self, menu) -> None:
        """Dock(ON=WindowStaysOnTop)時にサービスメニューが背後に隠れないよう昇格する。

        ColumnAddOverlay の _promote_overlay_tool と同契約だが、
        サービスメニューは既に Tool + global 座標で配置済みのため
        geometry の parent→global 再マップは行わない。
        """
        if menu is None:
            return
        parent_topmost = False
        try:
            if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
                parent_topmost = True
        except Exception:
            pass
        try:
            ph = self.windowHandle()
            if ph is not None and bool(ph.flags() & Qt.WindowType.WindowStaysOnTopHint):
                parent_topmost = True
        except Exception:
            pass
        if not parent_topmost:
            # 通常ウィンドウ: 既存フラグのまま。transient だけ張って親子関係を保つ
            try:
                _ = self.winId()
                _ = menu.winId()
                wh = menu.windowHandle()
                ph = self.windowHandle()
                if wh is not None and ph is not None:
                    wh.setTransientParent(ph)
            except Exception:
                pass
            return
        try:
            flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            # setWindowFlags は hide するため、呼び出し前の global geometry を保持
            geo = menu.geometry()
            menu.setWindowFlags(flags)
            menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            menu.setGeometry(geo)
        except Exception:
            pass
        try:
            _ = self.winId()
            _ = menu.winId()
            wh = menu.windowHandle()
            ph = self.windowHandle()
            if wh is not None and ph is not None:
                wh.setTransientParent(ph)
        except Exception:
            pass

    def _open_service_menu(self, grok: bool) -> None:
        cur = getattr(self, "_current_service_menu", None)
        if cur is not None and cur.isVisible():
            self._service_menu_closed_at = time.monotonic()
            def _clear():
                self._current_service_menu = None
                try:
                    cur.deleteLater()
                except Exception:
                    pass
            try:
                from src.ui.theme import menu_dropdown_hide
                menu_dropdown_hide(cur, on_finished=_clear)
            except Exception:
                try:
                    cur.hide()
                except Exception:
                    pass
                _clear()
            return

        closed_at = float(getattr(self, "_service_menu_closed_at", 0.0) or 0.0)
        if closed_at and (time.monotonic() - closed_at) < 0.35:
            self._service_menu_closed_at = 0.0
            if cur is not None:
                try:
                    cur.deleteLater()
                except Exception:
                    pass
                self._current_service_menu = None
            return
        if cur is not None:
            try:
                cur.hide()
                cur.deleteLater()
            except Exception:
                pass
            self._current_service_menu = None
        menu = self._build_service_menu(grok)
        self._current_service_menu = menu

        menu._on_auto_closed = lambda: setattr(self, "_service_menu_closed_at", time.monotonic())

        try:
            menu.ensurePolished()
            menu.adjustSize()
            w = max(1, int(menu.sizeHint().width() or menu.width() or 160))
            h = max(1, int(menu.sizeHint().height() or menu.height() or 40))

            menu.resize(w, h)
            menu.adjustSize()
            w = max(w, int(menu.width()))
            h = max(h, int(menu.height()))
            menu.setFixedSize(w, h)
            menu._apply_service_menu_mask()
        except Exception:
            pass
        pos = self._add_twitter_btn.mapToGlobal(self._add_twitter_btn.rect().bottomLeft())
        menu.move(pos)

        # Dock ON 時 MainWindow は WindowStaysOnTopHint 付き。
        # ColumnAddOverlay(+カラム) は _promote_overlay_tool で topmost+transient に昇格するが、
        # サービスメニュー(+X) は未対応のため Dock 背後に隠れ、選択・追加できなくなる。
        # メニューは既に Tool+global 配置済みなので、geometry 再マップはせず
        # topmost / transient だけを overlay と同じ契約で付与する。
        try:
            self._ensure_service_menu_above_dock(menu)
        except Exception:
            pass

        try:
            QApplication.instance().installEventFilter(menu)
        except Exception:
            pass
        try:
            from src.ui.theme import menu_dropdown_show
            menu_dropdown_show(menu)
        except Exception:
            menu.show()

    def _build_service_menu(self, grok: bool) -> _ServiceMenu:
        menu = _ServiceMenu(self)

        accounts = self._pickable_accounts(grok)
        for acc in accounts:
            menu.add_profile(acc)

        menu.new_account_requested.connect(lambda: self._prompt_new_account_name(grok))
        menu.rename_requested.connect(self._prompt_rename_account)
        menu.delete_requested.connect(lambda entry: self._delete_account(entry["account_id"]))

        return menu

    def _prompt_new_account_name(self, grok: bool) -> None:
        if getattr(self, "_current_service_menu", None) is not None:
            try:
                self._current_service_menu.hide()
                self._current_service_menu.close()
            except Exception:
                pass
            self._current_service_menu = None
        QTimer.singleShot(0, lambda: self._open_new_account_prompt(grok))

    def _open_new_account_prompt(self, grok: bool) -> None:
        if self._name_overlay is None:
            return
        self._name_overlay.open_prompt("新規アカウント", "", "作成")
        self._name_prompt_mode = ("create", grok, None)
        self._ensure_name_overlay_accepted_connected()
        try:
            self._name_overlay.raise_()
            self._name_overlay.activateWindow()
            self._name_overlay._input.setFocus()
            self._name_overlay._input.selectAll()
        except Exception:
            pass

    def _prompt_rename_account(self, entry: dict) -> None:
        if getattr(self, "_current_service_menu", None) is not None:
            try:
                self._current_service_menu.hide()
                self._current_service_menu.close()
            except Exception:
                pass
            self._current_service_menu = None
        aid = entry["account_id"]
        current_name = entry.get("display_name", "")
        self._name_overlay.open_prompt("アカウント名", current_name, "作成")
        self._name_prompt_mode = ("rename", False, aid)
        self._ensure_name_overlay_accepted_connected()

    def _ensure_name_overlay_accepted_connected(self) -> None:
        if self._name_overlay is None:
            return
        if getattr(self, "_name_overlay_accepted_wired", False):
            return
        self._name_overlay.accepted.connect(self._on_name_overlay_accepted)
        self._name_overlay_accepted_wired = True

    def _on_name_overlay_accepted(self, name: str) -> None:
        mode = getattr(self, "_name_prompt_mode", None)
        if not mode:
            return
        kind = mode[0]
        if kind == "create":
            self._create_named_account(name, bool(mode[1]))
        elif kind == "rename" and mode[2]:
            self._rename_account(str(mode[2]), name)
        elif kind == "rename_tab" and mode[1] is not None:
            tab = mode[1]
            natural = str(mode[2] or "")
            value = (name or "").strip()
            try:
                if not value or value == natural:
                    if hasattr(tab, "_custom_name"):
                        delattr(tab, "_custom_name")
                else:
                    tab._custom_name = value
            except Exception:
                pass
            self._rebuild_strip()
            self._save_columns()
        self._name_prompt_mode = None

    def _rename_account(self, account_id: str, new_name: str) -> None:
        for col in self._columns:
            if col.get_account_id() == account_id:
                col.set_display_name(new_name)
                break

        if account_id in self._known_accounts:
            self._known_accounts[account_id]["display_name"] = new_name

        self._save_accounts()

    def _delete_account(self, account_id: str) -> None:
        cols_to_remove = [col.get_column_id() for col in self._columns
                          if col.get_account_id() == account_id]
        for cid in cols_to_remove:
            self._remove_column(cid)

        self._known_accounts.pop(account_id, None)
        self._save_accounts()

        profile_in_use = False
        try:
            for packs in (self._twitter_packs, self._grok_packs):
                for columns in packs.values():
                    if any(col.get_account_id() == account_id for col in columns):
                        profile_in_use = True
                        break
                if profile_in_use:
                    break
        except Exception:
            profile_in_use = True

        if not profile_in_use:
            try:
                self._profile_manager.remove(account_id, cleanup_data=False)
                QTimer.singleShot(
                    0,
                    lambda aid=account_id: self._profile_manager.delete_profile_data(aid),
                )
            except Exception:
                pass

        if hasattr(self, '_current_service_menu') and self._current_service_menu is not None:
            self._current_service_menu.hide()
            self._current_service_menu = None

    def _shutdown_trace(self, stage: str, **detail) -> None:
        import os
        import time as _time
        from datetime import datetime, timezone
        mono_ms = int(_time.monotonic() * 1000)
        if not hasattr(self, "_shutdown_mono0_ms") or self._shutdown_mono0_ms is None:
            self._shutdown_mono0_ms = mono_ms
        dt_ms = mono_ms - int(self._shutdown_mono0_ms)
        parts = [f"mono_ms={mono_ms}", f"dt_ms={dt_ms}"]
        parts.extend(f"{k}={v!r}" for k, v in detail.items())
        line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3]} {stage}"
        if parts:
            line += " " + " ".join(parts)
        try:
            from src.core.paths import LOGS_DIR
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOGS_DIR / "shutdown.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        except Exception:
            pass
        if (os.environ.get("MAYOTTER_DEBUG") or "").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            print(f"[Shutdown] {line}", flush=True)

    def _account_add_trace(self, stage: str, **detail) -> None:
        import os
        enabled = (
            (os.environ.get("MAYOTTER_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")
            or (os.environ.get("MAYOTTER_ACCOUNT_TRACE") or "").strip().lower() in ("1", "true", "yes", "on")
        )
        if not enabled:
            return
        from datetime import datetime, timezone
        parts = [f"{k}={v!r}" for k, v in detail.items()]
        line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {stage}"
        if parts:
            line += " " + " ".join(parts)
        try:
            from src.core.paths import LOGS_DIR
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            log_path = LOGS_DIR / "last_account_add.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        except Exception:
            pass
        print(f"[AccountAdd] {line}", flush=True)

    def _create_named_account(self, name: str, grok: bool) -> None:
        from src.core.models import Account
        from src.browser.profile_manager import resolve_profile_path
        from uuid import uuid4

        name = (name or "").strip()
        if not name:
            return

        try:
            from src.core.paths import LOGS_DIR
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            (LOGS_DIR / "last_account_add.log").write_text("", encoding="utf-8")
        except Exception:
            pass

        self._account_add_trace("create_named_start", name=name, grok=bool(grok))
        aid = str(uuid4())
        initial = GROK_HOME_URL if grok else "https://x.com/"
        self._account_add_trace(
            "paths_ready",
            aid=aid,
            profile_path=str(resolve_profile_path(aid)),
        )
        account = Account(
            account_id=aid,
            display_name=name,
            initial_url=initial,
            profile_path="",
        )
        self._known_accounts[aid] = {
            "account_id": aid,
            "display_name": name,
            "initial_url": initial,
            "grok": bool(grok),
            "_create_profile": True,
        }
        self._account_add_trace("registry_ok", aid=aid)

        acc_ref = account
        grok_flag = bool(grok)
        aid_ref = aid

        def _finish_create() -> None:
            self._account_add_trace("deferred_add_column_run", aid=aid_ref)
            try:
                self._add_column(acc_ref, service_grok=grok_flag)
            except Exception as exc:
                import traceback
                self._account_add_trace("add_column_exception", err=repr(exc))
                try:
                    from src.core.paths import LOGS_DIR
                    with open(LOGS_DIR / "last_account_add.log", "a", encoding="utf-8") as f:
                        f.write(traceback.format_exc() + "\n")
                except Exception:
                    pass
                self._known_accounts.pop(aid_ref, None)
                try:
                    self._on_media_status(f"アカウントを追加できませんでした: {exc}")
                except Exception:
                    print(f"[Mayotter] add account failed: {exc!r}", flush=True)
                return
            self._account_add_trace("create_named_done", aid=aid_ref)
            if self._settings_manager:
                try:
                    self._save_accounts()
                    self._account_add_trace("save_accounts_ok", aid=aid_ref)
                except Exception as exc:
                    self._account_add_trace("save_accounts_fail", err=repr(exc))

        self._account_add_trace("deferred_add_column_scheduled", aid=aid)
        QTimer.singleShot(0, _finish_create)

    def _restore_account(self, account_id: str, grok: bool) -> None:
        from src.core.models import Account

        # 現在表示中の pack（Dock なら lr/tb、通常なら normal）だけを「既に開いている」とみなす。
        # normal pack を見ると、Dock 中の +X が Dock pack に追加されなくなる。
        active = list(getattr(self, "_columns", None) or [])
        for col in active:
            try:
                if col.get_account_id() != account_id:
                    continue
            except Exception:
                continue
            # 既存カラムが個別収納中なら先に復帰（タブだけ切り替わって本体が見えないのを防ぐ）
            if getattr(col, "is_individually_stowed", lambda: False)():
                try:
                    self._restore_single_column(col)
                except Exception:
                    pass
            # 一括収納で隠れている場合も戻す
            stowed = list(getattr(self, "_stowed_columns", None) or [])
            if col in stowed:
                try:
                    col.show()
                except Exception:
                    pass
                remaining = [c for c in stowed if c is not col]
                self._stowed_columns = remaining
                try:
                    key = self._bound_layout_mode_key()
                    if hasattr(self, "_mode_stowed_columns") and self._mode_stowed_columns is not None:
                        self._mode_stowed_columns[key] = list(remaining)
                except Exception:
                    pass
                try:
                    self._update_stow_restore_rail()
                except Exception:
                    pass
            if not col.isVisible():
                try:
                    col.show()
                except Exception:
                    pass
            self._set_active_column(col)
            try:
                self._fit_columns()
            except Exception:
                pass
            return

        # アクティブ pack に無い → 現在モードへ新規追加（_add_column が pack 追記と
        # _sync_count_from_active_list で edge_dock_column_count_lr/tb を +1 する）
        acc_info = self._known_accounts.get(account_id)
        if not acc_info:
            return

        account = Account(
            account_id=account_id,
            display_name=acc_info.get("display_name", ""),
            initial_url=GROK_HOME_URL if grok else "https://x.com/",
            profile_path=acc_info.get("legacy_profile_path", "") or acc_info.get("profile_path", ""),
        )

        self._add_column(account, service_grok=bool(grok))
        # +カラム経路（_on_column_added）と同様に永続化。再起動・Dock OFF/ON 後も数を維持する
        try:
            self._save_columns()
            self._save_accounts()
        except Exception:
            pass

    @staticmethod
    def _is_valid_saved_account(acc: dict) -> bool:
        return bool((acc.get("account_id") or "").strip())

    def _pickable_accounts(self, grok: bool) -> list[dict]:
        return [
            a for a in self._known_accounts.values()
            if a.get("grok", False) == grok and a.get("display_name")
        ]

    def _load_accounts(self) -> None:
        if not self._settings_manager:
            return

        from src.core.models import Account

        self._load_edge_dock_settings()

        raw_settings = self._settings_manager.load()
        raw_accounts = raw_settings.get("accounts") if "accounts" in raw_settings else None
        if isinstance(raw_accounts, list):
            registered_ids = {
                str(acc.get("account_id") or "").strip().lower()
                for acc in raw_accounts
                if isinstance(acc, dict) and str(acc.get("account_id") or "").strip()
            }
            try:
                self._profile_manager.cleanup_orphaned_profile_data(registered_ids)
            except Exception:
                pass
            account_source = raw_accounts
        else:
            account_source = self._settings_manager.get_accounts()

        accounts = [
            a for a in account_source
            if isinstance(a, dict) and self._is_valid_saved_account(a)
        ]
        for acc in accounts:
            aid = acc.get("account_id", "")
            if not aid:
                continue

            grok = "grok.com" in acc.get("initial_url", "")
            leg = (acc.get("profile_path") or "").strip()
            self._known_accounts[aid] = {
                "account_id": aid,
                "display_name": acc.get("display_name", ""),
                "initial_url": acc.get("initial_url", "https://x.com/"),
                "grok": grok,
            }
            if leg:
                self._known_accounts[aid]["legacy_profile_path"] = leg

        column_configs = list(self._settings_manager.get_columns() or [])
        try:
            column_configs.sort(key=lambda c: int(c.get("position", 0) or 0))
        except Exception:
            pass

        STAGGER_MS = 150
        loaded_index = 0
        self._restoring_session = True

        # 明示的な []（全削除済み）は正当な状態。accounts からの再生成は未初期化時のみ。
        try:
            _sm0 = getattr(self, "_settings_manager", None)
            _has_normal = bool(
                _sm0 is not None
                and hasattr(_sm0, "has_columns_for_mode")
                and _sm0.has_columns_for_mode("normal")
            )
        except Exception:
            _has_normal = False
        if column_configs or _has_normal:
            for col_conf in column_configs:
                aid = (col_conf.get("source_account_id") or "").strip()
                if not aid:
                    continue
                if aid not in self._known_accounts:
                    continue
                acc_info = self._known_accounts[aid]
                from src.core.models import migrate_column_type
                raw_type = col_conf.get("column_type", "home")
                col_type = migrate_column_type(raw_type)
                source_url = col_conf.get("source_url", "") or ""
                if col_type == "profile" and source_url and not source_url.startswith("http"):
                    source_url = ""
                tabs_raw = col_conf.get("tabs")
                active_tab = int(col_conf.get("active_tab", 0) or 0)
                skip_tab0_nav = False
                if isinstance(tabs_raw, list) and tabs_raw:
                    first = tabs_raw[0]
                    if isinstance(first, dict):
                        fu = (first.get("url") or "").strip()
                    else:
                        fu = (str(first) or "").strip()
                    if fu and not fu.startswith("about:") and not fu.startswith("data:"):
                        source_url = fu
                    if active_tab > 0 and len(tabs_raw) > active_tab:
                        skip_tab0_nav = True
                account = Account(
                    account_id=aid,
                    display_name=acc_info.get("display_name", ""),
                    profile_path=acc_info.get("legacy_profile_path", "") or acc_info.get("profile_path", "") or "",
                    initial_url=source_url or acc_info.get("initial_url", "https://x.com/"),
                )
                raw_cid = (col_conf.get("column_id") or "").strip()
                if not raw_cid or raw_cid == f"col_{aid}":
                    from uuid import uuid4
                    raw_cid = f"col_{aid}_{uuid4().hex[:10]}"
                column_config = Column(
                    column_id=raw_cid,
                    column_type=col_type,
                    source_account_id=aid,
                    source_url=source_url,
                    title=col_conf.get("title", ""),
                    position=col_conf.get("position", loaded_index),
                    width=int(col_conf.get("width") or AccountColumn.DEFAULT_WIDTH),
                )
                defer_ms = STAGGER_MS * loaded_index if loaded_index > 0 else None
                if skip_tab0_nav:
                    try:
                        column_config._skip_initial_load = True
                        column_config._pending_tab0_url = source_url
                    except Exception:
                        pass
                self._add_column(account, column_config, defer_load_ms=defer_ms)
                try:
                    col = self._columns[-1] if self._columns else None
                    if col is not None and isinstance(tabs_raw, list) and tabs_raw:
                        self._restore_column_tabs(
                            col, tabs_raw, active_tab, defer_load_ms=defer_ms
                        )
                    if col is not None:
                        # 個別収納と←→一括収納は別状態
                        # normal pack 実体へ即適用（Dock 起動で bind が先に走っても失わない）
                        if bool(col_conf.get("individually_stowed")):
                            try:
                                pw = int(col_conf.get("width") or 0)
                                if pw >= AccountColumn.MIN_WIDTH:
                                    col._width_before_individual_stow = pw
                                col.set_individually_stowed(True)
                            except Exception:
                                pass
                            if not hasattr(self, "_pending_stow_ids") or self._pending_stow_ids is None:
                                self._pending_stow_ids = []
                            try:
                                self._pending_stow_ids.append(col.get_column_id())
                            except Exception:
                                pass
                        elif bool(col_conf.get("stowed")):
                            if not hasattr(self, "_mode_stowed_columns") or self._mode_stowed_columns is None:
                                self._mode_stowed_columns = {"normal": [], "lr": [], "tb": []}
                            if col not in self._mode_stowed_columns.setdefault("normal", []):
                                self._mode_stowed_columns["normal"].append(col)
                except Exception:
                    pass
                loaded_index += 1
        else:
            for acc in accounts:
                aid = acc.get("account_id", "")
                if not aid:
                    continue
                if acc.get("open", True):
                    account = Account(
                        account_id=aid,
                        display_name=acc.get("display_name", ""),
                        profile_path=acc.get("profile_path", ""),
                        initial_url=acc.get("initial_url", "https://x.com/"),
                    )
                    defer_ms = STAGGER_MS * loaded_index if loaded_index > 0 else None
                    self._add_column(account, defer_load_ms=defer_ms)
                    loaded_index += 1

        self._columns = self._service_packs()["normal"]
        if self._columns:
            self._normal_column_count = max(1, len(self._columns))
        self._twitter_columns = self._twitter_packs["normal"]
        self._grok_columns = self._grok_packs["normal"]
        try:
            self._seed_mode_packs_from_settings()
        except Exception:
            pass
        # Dock ON 起動では空 pack を先に bind しない。実カラムを生成してから切り替える。
        if self._edge_dock_enabled:
            try:
                self._ensure_mode_columns(self._layout_mode_key())
            except Exception:
                pass
        self._bind_active_columns(skip_ensure=True)
        self._restoring_session = False
        try:
            if self._settings_manager and hasattr(
                self._settings_manager, "get_column_widths_for_mode"
            ):
                seed = self._settings_manager.get_column_widths_for_mode("normal") or {}
            elif self._settings_manager:
                seed = self._settings_manager.get_column_widths() or {}
            else:
                seed = {}
            self._preferred_widths = {
                str(k): int(v)
                for k, v in (seed or {}).items()
                if v and str(k)
            }
            if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._mode_preferred_widths["normal"] = dict(self._preferred_widths)
        except Exception:
            pass
        try:
            self._apply_individual_stow_on_startup()
        except Exception:
            pass
        QTimer.singleShot(0, self._fit_columns_after_restore)
        QTimer.singleShot(50, self._apply_persisted_stow_on_startup)

    def _seed_mode_packs_from_settings(self) -> None:
        """非アクティブな pack は設定だけ保持し、WebEngine は初回使用時に作る。"""
        if not self._settings_manager:
            return
        if not hasattr(self._settings_manager, "get_columns_for_mode"):
            return
        if not hasattr(self, "_deferred_mode_configs") or self._deferred_mode_configs is None:
            self._deferred_mode_configs = {"lr": [], "tb": []}
        if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
            self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
        for mode in ("lr", "tb"):
            try:
                configs = list(self._settings_manager.get_columns_for_mode(mode) or [])
            except Exception:
                configs = []
            try:
                configs.sort(key=lambda c: int(c.get("position", 0) or 0))
            except Exception:
                pass
            self._deferred_mode_configs[mode] = [dict(c) for c in configs if isinstance(c, dict)]
            if configs:
                if mode == "lr":
                    self._edge_dock_column_count_lr = max(1, len(configs))
                else:
                    self._edge_dock_column_count_tb = max(1, len(configs))
            try:
                widths = self._settings_manager.get_column_widths_for_mode(mode) or {}
                self._mode_preferred_widths[mode] = {
                    str(k): int(v) for k, v in widths.items() if v and str(k)
                }
            except Exception:
                pass

    def _materialize_mode_pack_from_settings(self, mode: str) -> bool:
        if mode not in ("lr", "tb") or not self._settings_manager:
            return False
        packs = self._service_packs()
        lst = packs.setdefault(mode, [])
        if lst:
            return True
        deferred = getattr(self, "_deferred_mode_configs", None) or {}
        configs = list(deferred.get(mode) or [])
        if not configs:
            try:
                configs = list(self._settings_manager.get_columns_for_mode(mode) or [])
            except Exception:
                configs = []
        if not configs:
            return False
        try:
            configs.sort(key=lambda c: int(c.get("position", 0) or 0))
        except Exception:
            pass
        try:
            widths = self._settings_manager.get_column_widths_for_mode(mode) or {}
        except Exception:
            widths = {}
        for col_conf in configs:
            if not isinstance(col_conf, dict):
                continue
            aid = (col_conf.get("source_account_id") or "").strip()
            if not aid or aid not in self._known_accounts:
                continue
            src = col_conf.get("source_url", "") or ""
            tabs_pre = col_conf.get("tabs")
            if isinstance(tabs_pre, list) and tabs_pre:
                t0 = tabs_pre[0]
                if isinstance(t0, dict):
                    src = (t0.get("url") or src or "").strip() or src
                else:
                    src = (str(t0) or src or "").strip() or src
            info = {
                "account_id": aid,
                "display_name": col_conf.get("title", "") or aid[:8],
                "initial_url": src or "https://x.com/",
                "column_type": col_conf.get("column_type", "home"),
                "source_url": src or "",
                "title": col_conf.get("title", "") or "",
                "column_id": (col_conf.get("column_id") or "").strip(),
            }
            reg = self._known_accounts.get(aid, {})
            if reg:
                info["legacy_profile_path"] = reg.get("legacy_profile_path", "") or reg.get("profile_path", "")
                info["display_name"] = reg.get("display_name", "") or info["display_name"]
                info["initial_url"] = reg.get("initial_url", "") or info["initial_url"]
            before = len(lst)
            self._spawn_column_into_mode(mode, info)
            if len(lst) <= before:
                continue
            col = lst[-1]
            try:
                active_tab = int(col_conf.get("active_tab", 0) or 0)
                if isinstance(tabs_pre, list) and tabs_pre:
                    self._restore_column_tabs(col, tabs_pre, active_tab)
            except Exception:
                pass
            try:
                if bool(col_conf.get("stowed")):
                    if col not in self._mode_stowed_columns.setdefault(mode, []):
                        self._mode_stowed_columns[mode].append(col)
            except Exception:
                pass
            try:
                if bool(col_conf.get("individually_stowed")):
                    pw = int(col_conf.get("width") or 0)
                    if pw >= AccountColumn.MIN_WIDTH:
                        col._width_before_individual_stow = pw
                    col.set_individually_stowed(True)
            except Exception:
                pass
            w = int(col_conf.get("width") or 0)
            cid = col.get_column_id()
            if cid in widths and widths[cid] > 0:
                w = int(widths[cid])
            elif aid in widths and widths[aid] > 0:
                w = int(widths[aid])
            if w >= AccountColumn.MIN_WIDTH:
                try:
                    if getattr(col, "is_individually_stowed", lambda: False)():
                        col._width_before_individual_stow = w
                    else:
                        col.set_width(w, emit_signal=False)
                except Exception:
                    pass
        if hasattr(self, "_deferred_mode_configs"):
            self._deferred_mode_configs[mode] = []
        if mode == "lr" and lst:
            self._edge_dock_column_count_lr = max(1, len(lst))
        elif mode == "tb" and lst:
            self._edge_dock_column_count_tb = max(1, len(lst))
        return bool(lst)

    def _notify_dock_activity(self) -> None:
        if not bool(getattr(self, "_edge_dock_enabled", False)):
            return
        if getattr(self, "_edge_dock_fs_yielded", False):
            return
        if getattr(self, "_dock_notify_busy", False):
            return
        self._dock_notify_busy = True
        try:
            from PySide6.QtWidgets import QLabel
            bubble = getattr(self, "_dock_notify_bubble", None)
            if bubble is None:
                bubble = QLabel(None)
                bubble.setObjectName("dock_notify_bubble")
                bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
                bubble.setFixedSize(28, 22)
                bubble.setStyleSheet(
                    "QLabel#dock_notify_bubble {"
                    " background:#3d6aa8; color:#f1f3f7; border-radius:8px;"
                    " font-size:11px; font-weight:700;"
                    " border:1px solid #4a7ec7;"
                    "}"
                )
                bubble.setWindowFlags(
                    Qt.WindowType.Tool
                    | Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.WindowDoesNotAcceptFocus
                )
                bubble.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
                bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self._dock_notify_bubble = bubble
            n = 1
            try:
                n = max(1, int(getattr(self._download_icon_btn, "_completed_count", 1) or 1))
            except Exception:
                pass
            bubble.setText("9+" if n > 9 else str(n))
            g = self.geometry()
            edge = str(getattr(self, "_edge_dock_direction", "right") or "right")
            bw, bh = 28, 22
            if edge == "right":
                x = g.x() - bw - 2
                y = g.y() + max(0, (g.height() - bh) // 2)
            elif edge == "left":
                x = g.x() + g.width() + 2
                y = g.y() + max(0, (g.height() - bh) // 2)
            elif edge == "top":
                x = g.x() + max(0, (g.width() - bw) // 2)
                y = g.y() + g.height() + 2
            else:
                x = g.x() + max(0, (g.width() - bw) // 2)
                y = g.y() - bh - 2
            bubble.setGeometry(int(x), int(y), bw, bh)
            try:
                bubble.setWindowOpacity(1.0)
            except Exception:
                pass
            bubble.show()
            bubble.raise_()
            def _hide():
                try:
                    bubble.hide()
                except Exception:
                    pass
                self._dock_notify_busy = False
                # Dock 側で通知を見せた時点で既読。Dock OFF 側のバッジも消す
                self._mark_downloads_read()
            QTimer.singleShot(1600, _hide)
        except Exception:
            self._dock_notify_busy = False

    def _mark_downloads_read(self) -> None:
        """ダウンロード完了の未読を、Dock・Dock OFF のどちらの表示でも既読にする。"""
        try:
            self._download_icon_btn.clear_completed()
        except Exception:
            pass
        bubble = getattr(self, "_dock_notify_bubble", None)
        if bubble is not None:
            try:
                bubble.hide()
            except Exception:
                pass
        self._dock_notify_busy = False

    def _toggle_download_history(self) -> None:
        ov = self._download_overlay
        if ov is None:
            return
        if getattr(self, "_download_toggling", False):
            return
        self._download_toggling = True
        try:
            fading = bool(getattr(ov, "_mayotter_fading_out", False)) and ov.isVisible()
            vis = bool(ov.is_open())
            if vis or fading:
                ov.close_overlay()
                return
            self._ensure_download_history_restored()
            ov.open_history()
            self._mark_downloads_read()
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda: setattr(self, "_download_toggling", False))

    def _go_home_focused(self) -> None:
        if self._active_column is not None:
            self._active_column.go_home()

    def _open_multi_post_dialog(self) -> None:
        accounts = {
            a["account_id"]: a
            for a in self._pickable_accounts(grok=False)
        }
        if not accounts:
            return
        from src.ui.multi_post_dialog import MultiPostDialog

        cur = getattr(self, "_multi_post_dialog", None)
        if cur is not None and cur.is_open():
            cur.close_popup()
            return
        # +カラム のボタンと同じ見た目名で、外側クリック判定から除外されているため明示的に閉じる
        cov = self._column_add_overlay
        if cov is not None and cov.is_open():
            cov.close_overlay()
        dlg = MultiPostDialog(
            accounts, self._submit_multi_post, self, trigger=self._multi_post_btn
        )
        self._multi_post_dialog = dlg
        dlg.closed.connect(lambda: setattr(self, "_multi_post_dialog", None))
        dlg.open_below(self._multi_post_btn)

    def _floating_popups(self) -> list:
        """メインウィンドウとは別の最上位ウィンドウで出るポップアップ。移動時に追従させる。"""
        names = (
            "_column_add_overlay", "_url_overlay", "_name_overlay", "_confirm_overlay",
            "_download_overlay", "_recording_overlay", "_current_service_menu",
            "_multi_post_dialog",
        )
        return [w for w in (getattr(self, n, None) for n in names) if w is not None]

    def _sync_floating_popups_to(self, x: int, y: int) -> None:
        """メインウィンドウの左上(物理px)が (x, y) になる移動へ、浮遊ポップアップを同時に追従させる。

        WM_WINDOWPOSCHANGING（本体が動く前）から呼ぶことで、本体とポップアップを同じフレームで動かす。
        Qt の moveEvent は本体が動いた後に届くため、そこだけに頼ると1フレーム遅れて揺れる。
        """
        if int(x) <= -30000 or int(y) <= -30000:
            return  # 最小化中の退避位置には追従しない
        last = getattr(self, "_popup_sync_pos", None)
        self._popup_sync_pos = (int(x), int(y))
        if last is None:
            return
        dx, dy = int(x) - last[0], int(y) - last[1]
        if not dx and not dy:
            return
        from PySide6.QtWidgets import QComboBox

        targets = []
        for w in self._floating_popups():
            try:
                if w.isVisible() and w.isWindow():
                    targets.append(w)
                    for combo in w.findChildren(QComboBox):
                        pop = getattr(combo, "_list_popup", None)
                        if pop is not None and pop.isVisible():
                            targets.append(pop)
            except Exception:
                pass
        if not targets:
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.BeginDeferWindowPos.restype = wintypes.HANDLE
        user32.DeferWindowPos.restype = wintypes.HANDLE
        user32.DeferWindowPos.argtypes = [
            wintypes.HANDLE, wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.EndDeferWindowPos.argtypes = [wintypes.HANDLE]
        hdwp = user32.BeginDeferWindowPos(len(targets))
        dpr = max(1.0, float(self.devicePixelRatioF()))
        for w in targets:
            try:
                rect = wintypes.RECT()
                user32.GetWindowRect(int(w.winId()), ctypes.byref(rect))
                # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                hdwp = user32.DeferWindowPos(
                    hdwp, int(w.winId()), None, rect.left + dx, rect.top + dy, 0, 0, 0x0001 | 0x0004 | 0x0010
                )
                locked = getattr(w, "_locked_xy", None)
                if locked:
                    w._locked_xy = (
                        int(round(locked[0] + dx / dpr)), int(round(locked[1] + dy / dpr))
                    )
            except Exception:
                pass
        if hdwp:
            user32.EndDeferWindowPos(hdwp)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        # 通常は WM_WINDOWPOSCHANGING で追従済み。取りこぼし（clamp 等）の補正だけここで行う。
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(int(self.winId()), ctypes.byref(rect))
            self._sync_floating_popups_to(rect.left, rect.top)
        except Exception:
            pass

    def _submit_multi_post(self, text: str, account_ids: list[str]) -> list[str]:
        """各アカウントのカラムへ投稿画面（本文入り）を開く。カラムが無いアカウント名を返す。"""
        from urllib.parse import quote

        url = "https://x.com/intent/post?text=" + quote(text, safe="")
        cols = list(self._columns) + [
            c for c in self._twitter_packs["normal"] if c not in self._columns
        ]
        missing = []
        targets = []
        for aid in account_ids:
            col = next((c for c in cols if c.get_account_id() == aid), None)
            if col is None:
                missing.append(str((self._known_accounts.get(aid) or {}).get("display_name") or aid))
            else:
                targets.append(col)
        if missing:
            return missing
        for col in targets:
            self._on_new_tab_requested(url, col)
        return []

    def _open_column_add_overlay(self) -> None:
        ov = self._column_add_overlay
        if ov is None:
            return
        mp = getattr(self, "_multi_post_dialog", None)
        if mp is not None and mp.is_open():
            mp.close_popup()
        if getattr(self, "_column_add_toggling", False):
            return
        self._column_add_toggling = True
        try:
            fading = bool(getattr(ov, "_mayotter_fading_out", False)) and ov.isVisible()
            vis = bool(ov.is_open())
            if vis or fading:
                ov.close_overlay()
                return
            accounts = {
                a["account_id"]: a
                for a in self._pickable_accounts(grok=self._grok_mode)
            }
            if self._edge_dock_enabled and self._edge_detector is not None:
                self._edge_detector.set_pinned_open(True)
            try:
                ov.open_for(accounts)
            except Exception:
                if self._edge_dock_enabled and self._edge_detector is not None:
                    self._edge_detector.set_pinned_open(False)
                raise
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda: setattr(self, "_column_add_toggling", False))

    def _on_column_add_overlay_closed(self) -> None:
        if not self._edge_dock_enabled or self._edge_detector is None:
            return
        if self._edge_dock_dragging or self._edge_dock_resizing:
            return
        self._edge_detector.set_pinned_open(False)

    def _on_column_added(self, column_config: Column) -> None:
        from src.core.models import Account

        aid = column_config.source_account_id
        acc_info = self._known_accounts.get(aid)
        if not acc_info:
            return

        account = Account(
            account_id=aid,
            display_name=acc_info.get("display_name", ""),
            profile_path=acc_info.get("legacy_profile_path", "") or acc_info.get("profile_path", ""),
            initial_url=acc_info.get("initial_url", "https://x.com/"),
        )
        self._add_column(account, column_config)
        try:
            self._save_columns()
            self._save_accounts()
        except Exception:
            pass

    def _sync_window_chrome_icons(self) -> None:
        try:
            if self.isMaximized():
                self._win_max_btn.setIcon(make_restore_icon(_COLOR_SECONDARY, 12))
                self._win_max_btn.setToolTip("元のサイズに戻す")
            else:
                self._win_max_btn.setIcon(make_maximize_icon(_COLOR_SECONDARY, 12))
                self._win_max_btn.setToolTip("最大化")
        except Exception:
            pass

    def _stop_window_opacity_anim(self) -> None:
        anim = getattr(self, "_win_opacity_anim", None)
        if anim is None:
            return
        try:
            anim.stop()
        except Exception:
            pass
        self._win_opacity_anim = None

    def _run_window_opacity(
        self, end: float, duration_ms: int, on_finished=None, *, ease_in: bool = False
    ) -> None:
        """トップレベル windowOpacity のみ。子や WebView は触らない。"""
        if getattr(self, "_close_fade_anim", None) is not None:
            # 終了フェード中は干渉しない
            return
        self._stop_window_opacity_anim()
        self._win_opacity_gen = int(getattr(self, "_win_opacity_gen", 0) or 0) + 1
        gen = self._win_opacity_gen
        try:
            cur = float(self.windowOpacity())
        except Exception:
            cur = 1.0
        end = max(0.0, min(1.0, float(end)))
        if abs(cur - end) < 0.02:
            try:
                self.setWindowOpacity(end)
            except Exception:
                pass
            if callable(on_finished):
                on_finished()
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(max(40, int(duration_ms)))
        anim.setStartValue(cur)
        anim.setEndValue(end)
        anim.setEasingCurve(
            QEasingCurve.Type.InCubic if ease_in else QEasingCurve.Type.OutCubic
        )

        def _done() -> None:
            if gen != getattr(self, "_win_opacity_gen", None):
                return
            self._win_opacity_anim = None
            try:
                self.setWindowOpacity(end)
            except Exception:
                pass
            if callable(on_finished):
                try:
                    on_finished()
                except Exception:
                    pass

        anim.finished.connect(_done)
        self._win_opacity_anim = anim
        anim.start()

    def _minimize_window(self) -> None:
        """短い opacity フェード後に showMinimized。Dock ON 時は無効。"""
        if getattr(self, "_edge_dock_enabled", False):
            return
        if self.isMinimized():
            return
        if getattr(self, "_close_fade_anim", None) is not None:
            return

        def _after() -> None:
            # 最小化中は opacity=0 のまま。復元時の一瞬完全表示を防ぐ。
            try:
                self.setWindowOpacity(0.0)
            except Exception:
                pass
            try:
                self.showMinimized()
            except Exception:
                pass

        self._run_window_opacity(0.0, 120, _after, ease_in=True)

    def _toggle_maximized(self) -> None:
        """OS状態変更 + 短い opacity フェードイン。Dock ON 時は無効。"""
        if getattr(self, "_edge_dock_enabled", False):
            return
        if getattr(self, "_close_fade_anim", None) is not None:
            return
        try:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
        except Exception:
            pass
        try:
            self.setWindowOpacity(0.0)
        except Exception:
            pass
        self._run_window_opacity(1.0, 140)
        try:
            self._sync_window_chrome_icons()
        except Exception:
            pass

    def _column_for_webview(self, webview: XWebView) -> AccountColumn | None:
        if webview is None:
            return None
        for col in self._columns:
            tabs = list(getattr(col, "_tabs", []))
            if webview in tabs:
                return col
        return None

    def enter_media_wide(self, webview: XWebView) -> bool:
        if webview is None:
            return False
        if self._media_wide_view is webview:
            return True
        if self._media_wide_view is not None:
            try:
                self.exit_media_wide(self._media_wide_view)
            except Exception:
                pass

        col = self._column_for_webview(webview)
        if col is None:
            return False

        self._media_wide_view = webview
        self._media_wide_column = col
        self._media_wide_hidden_columns = []
        self._media_wide_saved_widths = {}
        self._media_wide_last_vw = 0

        for c in self._columns:
            try:
                self._media_wide_saved_widths[c.get_column_id()] = int(c.width())
            except Exception:
                pass
            if c is not col and c.isVisible():
                self._media_wide_hidden_columns.append(c)
                c.hide()

        top = getattr(self, "_top_bar", None)
        self._media_wide_top_bar_was_visible = bool(top is not None and top.isVisible())
        if top is not None and top.isVisible():
            top.hide()

        nav = getattr(col, "_nav_frame", None)
        self._media_wide_nav_was_visible = bool(nav is not None and nav.isVisible())
        if nav is not None and nav.isVisible():
            nav.hide()

        try:
            tabs = list(getattr(col, "_tabs", []))
            if webview in tabs:
                idx = tabs.index(webview)
                if hasattr(col, "set_current_tab"):
                    col.set_current_tab(idx)
                else:
                    for i, t in enumerate(tabs):
                        if i == idx:
                            t.show()
                        else:
                            t.hide()
                    col._current_tab = idx
        except Exception:
            webview.show()

        self._apply_media_wide_geometry()

        try:
            webview.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

        if self._media_wide_esc is None:
            esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            esc.setContext(Qt.ShortcutContext.WindowShortcut)
            esc.activated.connect(self._on_media_wide_escape)
            self._media_wide_esc = esc
        self._media_wide_esc.setEnabled(True)
        return True

    def exit_media_wide(self, webview: XWebView | None = None) -> None:
        active = self._media_wide_view
        if active is None:
            return
        if webview is not None and webview is not active:
            return

        col = self._media_wide_column
        hidden = list(self._media_wide_hidden_columns)
        saved_widths = dict(self._media_wide_saved_widths)
        nav_was = self._media_wide_nav_was_visible
        top_was = self._media_wide_top_bar_was_visible

        self._media_wide_view = None
        self._media_wide_column = None
        self._media_wide_hidden_columns = []
        self._media_wide_saved_widths = {}
        self._media_wide_last_vw = 0

        if self._media_wide_esc is not None:
            self._media_wide_esc.setEnabled(False)

        if col is not None:
            nav = getattr(col, "_nav_frame", None)
            if nav is not None and nav_was:
                nav.show()

        top = getattr(self, "_top_bar", None)
        if top is not None and top_was:
            top.show()

        for c in hidden:
            try:
                c.show()
            except Exception:
                pass

        restored = False
        for c in self._columns:
            cid = None
            try:
                cid = c.get_column_id()
            except Exception:
                continue
            if cid in saved_widths and saved_widths[cid] > 0:
                try:
                    c.set_width(saved_widths[cid], emit_signal=False)
                    restored = True
                except Exception:
                    pass
        if not restored:
            try:
                self._fit_columns()
            except Exception:
                pass
        else:
            try:
                self._update_boundary_visibility()
            except Exception:
                pass

        try:
            active._media_wide_active = False
        except Exception:
            pass
        try:
            active.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def _apply_media_wide_geometry(self) -> None:
        col = self._media_wide_column
        if col is None or self._media_wide_view is None:
            return
        try:
            vw = int(self._scroll.viewport().width())
        except Exception:
            vw = int(self.width())
        if vw <= 0:
            vw = max(1, int(self.width()))
        if vw == self._media_wide_last_vw and col.width() >= max(1, vw - 2):
            return
        self._media_wide_last_vw = vw
        try:
            col.set_width(vw, emit_signal=False)
        except Exception:
            try:
                col.setFixedWidth(vw)
            except Exception:
                pass
        try:
            self._media_wide_view.show()
            self._media_wide_view.raise_()
        except Exception:
            pass

    def _on_media_wide_escape(self) -> None:
        view = self._media_wide_view
        if view is None:
            return
        try:
            view._exit_media_wide(notify_page=True)
        except Exception:
            try:
                self.exit_media_wide(view)
            except Exception:
                pass

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if getattr(self, "_start_maximized", False):
            self._start_maximized = False
            QTimer.singleShot(0, self.showMaximized)
        if self._resize_filter is not None:
            self._resize_filter._cached_win_id = int(self.winId())
        QTimer.singleShot(0, self._update_window_mask)
        stably_collapsed = (
            self._edge_dock_enabled
            and not self._edge_dock_revealed
            and not self._edge_dock_animating
        )
        if not stably_collapsed:
            QTimer.singleShot(0, self._fit_columns)

    def resizeEvent(self, event: QEvent) -> None:
        super().resizeEvent(event)
        try:
            self._update_empty_state()
        except Exception:
            pass
        if self._media_wide_view is not None:
            self._apply_media_wide_geometry()
        # 方向切替 / Dock ON/OFF の離散置換中は、setGeometry の副作用を最小化する。
        # mask / fit / QTimer を走らせると最終 state と競合して黒帯の原因になる。
        if getattr(self, "_edge_dock_switching", False):
            if self._edge_dock_clip and self._edge_dock_root:
                fw = max(1, self.width())
                fh = max(1, self.height())
                cg = QRect(0, 0, fw, fh)
                if self._edge_dock_clip.geometry() != cg:
                    self._edge_dock_clip.setGeometry(cg)
                if self._edge_dock_root.size() != QSize(fw, fh):
                    self._edge_dock_root.resize(fw, fh)
            return
        if not getattr(self, "_edge_dock_enabled", False):
            self._schedule_normal_window_mask()
        elif not getattr(self, "_edge_dock_animating", False):
            # 展開/収納アニメ中は _apply_reveal_mask が setMask を担当する。
            # ここで full shape mask を当てると中間 frame が消える。
            self._update_window_mask()
        os_sizing = bool(getattr(self, "_os_sizing", False))
        # OS リサイズ中も content geometry を追従（HWND だけ伸びて黒帯になるのを防ぐ）
        if (
            self._edge_dock_enabled
            and self._edge_dock_revealed
            and not self._edge_dock_animating
            and not getattr(self, "_edge_dock_switching", False)
            and os_sizing
            and self.width() > self.EDGE_DOCK_INDICATOR_WIDTH * 4
        ):
            self._store_live_size(self.width(), self.height())

        if self._edge_dock_clip and self._edge_dock_root:
            fw = max(1, self.width())
            fh = max(1, self.height())
            cg = QRect(0, 0, fw, fh)
            if self._edge_dock_clip.geometry() != cg:
                self._edge_dock_clip.setGeometry(cg)
            if self._edge_dock_enabled:
                if self._edge_dock_root.size() != QSize(fw, fh):
                    self._edge_dock_root.resize(fw, fh)
                t = float(getattr(self, "_edge_dock_reveal_progress", 1.0 if self._edge_dock_revealed else 0.0))
                self._apply_reveal_mask(t)
            else:
                if self._edge_dock_root.geometry() != cg:
                    self._edge_dock_root.setGeometry(cg)
        stably_collapsed = (
            self._edge_dock_enabled
            and not self._edge_dock_revealed
            and not self._edge_dock_animating
        )
        if self._edge_dock_enabled and self._edge_dock_animating:
            self._update_chrome_by_window_width()
            return
        if (
            self._edge_dock_enabled
            and self._edge_dock_revealed
            and not getattr(self, "_edge_dock_switching", False)
            and self.width() > self.EDGE_DOCK_INDICATOR_WIDTH * 4
        ):
            self._store_live_size(self.width(), self.height())
        # 手動 Dock リサイズ中は mouseMove が毎フレーム fit する。ここでは二重 fit を避け
        # layout-safe WE 同期だけ行う。
        if getattr(self, "_edge_dock_resizing", False):
            try:
                self._sync_webviews_to_columns_layout_safe()
            except Exception:
                pass
            self._update_chrome_by_window_width()
            return
        if not stably_collapsed:
            try:
                self._fit_columns()
            except Exception:
                pass
            try:
                self._sync_webviews_to_columns_layout_safe()
            except Exception:
                pass
        if getattr(self, "_stowed_columns", None):
            self._update_stow_restore_rail()
        self._update_chrome_by_window_width()
        if stably_collapsed and bool(getattr(self, "_dock_has_unread", False)):
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass

    def _sync_webviews_to_columns_layout_safe(self) -> None:
        """列幅変更・ウィンドウリサイズ後に WE を追従させる（境界ハンドルは覆わない）。"""
        for col in self._layout_visible_columns():
            for wv in getattr(col, "webviews", lambda: [])() or []:
                try:
                    self._layout_safe_webview_geometry(wv)
                except Exception:
                    pass

    def _sync_dock_after_os_resize(self) -> None:
        if not self._edge_dock_enabled:
            return
        if self._edge_dock_animating:
            return
        fw, fh = max(1, self.width()), max(1, self.height())
        clip = getattr(self, "_edge_dock_clip", None)
        root = getattr(self, "_edge_dock_root", None)
        if clip is not None:
            cg = QRect(0, 0, fw, fh)
            if clip.geometry() != cg:
                clip.setGeometry(cg)
        if root is not None:
            if self._edge_dock_revealed:
                if root.size() != QSize(fw, fh):
                    root.resize(fw, fh)
                self._apply_reveal_mask(1.0)
            else:
                cg = QRect(0, 0, fw, fh)
                if root.geometry() != cg:
                    root.setGeometry(cg)
        if self._edge_dock_revealed and fw > self.EDGE_DOCK_INDICATOR_WIDTH * 4:
            self._store_live_size(fw, fh, self._edge_dock_direction)
            try:
                self._fit_columns()
            except Exception:
                pass
            try:
                self._sync_webviews_to_columns_layout_safe()
            except Exception:
                pass

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange and getattr(self, "_edge_dock_enabled", False):
            state = self.windowState()
            bad = Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized
            if state & bad:
                self.setWindowState(state & ~bad)
                if not self.isVisible():
                    self.show()
            super().changeEvent(event)
            QTimer.singleShot(0, self._update_window_mask)
            return
        old_min = False
        if event.type() == QEvent.Type.WindowStateChange:
            try:
                old_min = bool(event.oldState() & Qt.WindowState.WindowMinimized)
            except Exception:
                old_min = False
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_recording_overlay_minimized()
            # タスクバー復元: 最小化中に opacity=0 を維持しているので、そのまま 0→1
            if (
                old_min
                and not self.isMinimized()
                and not getattr(self, "_edge_dock_enabled", False)
                and getattr(self, "_close_fade_anim", None) is None
            ):
                try:
                    # 既に 0 ならそのまま。1 に戻っていた場合だけ先に 0 にする。
                    if float(self.windowOpacity() or 1.0) > 0.05:
                        self.setWindowOpacity(0.0)
                except Exception:
                    try:
                        self.setWindowOpacity(0.0)
                    except Exception:
                        pass
                self._run_window_opacity(1.0, 140)
            elif self.isMinimized():
                # 最小化中は 1.0 に戻さない（復元点滅の原因になる）
                pass
            else:
                anim = getattr(self, "_win_opacity_anim", None)
                running = False
                try:
                    from PySide6.QtCore import QAbstractAnimation
                    running = (
                        anim is not None
                        and anim.state() == QAbstractAnimation.State.Running
                    )
                except Exception:
                    running = anim is not None
                if not running:
                    try:
                        self.setWindowOpacity(1.0)
                    except Exception:
                        pass
            try:
                self._sync_window_chrome_icons()
            except Exception:
                pass
            QTimer.singleShot(0, self._update_window_mask)

    def closeEvent(self, event) -> None:

        if not getattr(self, "_close_fade_done", False):
            event.ignore()
            self._close_fade_done = True
            try:
                self._stop_window_opacity_anim()
            except Exception:
                pass
            try:
                from PySide6.QtCore import QPropertyAnimation, QEasingCurve
                anim = QPropertyAnimation(self, b"windowOpacity", self)
                anim.setDuration(120)
                anim.setStartValue(float(self.windowOpacity() or 1.0))
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.Type.InCubic)
                anim.finished.connect(self.close)
                self._close_fade_anim = anim
                anim.start()
            except Exception:
                self._close_fade_done = True
                self.close()
            return
        try:
            self._stop_media_runtime()
        except Exception:
            pass
        try:
            self._save_edge_dock_settings()
            if self._settings_manager:
                geom = self.saveGeometry()
                if self._edge_dock_enabled:
                    if hasattr(self._settings_manager, "save_window_geometry_dock"):
                        self._settings_manager.save_window_geometry_dock(geom)
                else:
                    if hasattr(self._settings_manager, "save_window_geometry_normal"):
                        self._settings_manager.save_window_geometry_normal(geom)
                    else:
                        self._settings_manager.save_window_geometry(geom)
            self._persist_download_history()
            self._save_accounts()
            try:
                self._save_columns()
            except Exception:
                pass
            try:
                self._persist_individual_stow_state()
            except Exception:
                pass
        except Exception:
            pass
        try:
            self._shutdown_mono0_ms = None
            self._shutdown_trace("mainwindow_close_start")
            self._shutdown_runtime()
            self._shutdown_trace("mainwindow_close_runtime_done")
        except Exception as exc:
            try:
                self._shutdown_trace("mainwindow_close_runtime_fail", err=repr(exc))
            except Exception:
                pass
        if self._resize_filter is not None:
            self._resize_filter._alive = False
            app = QGuiApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._resize_filter)
            self._resize_filter = None
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            try:
                self._shutdown_trace("application_about_to_quit")
            except Exception:
                pass
            app.quit()

    def _attach_timing_log(self, stage: str, **extra) -> None:
        import time as _time
        now = _time.monotonic()
        base = getattr(self, "_attach_t0_mono", None)
        parts = [f"stage={stage}", f"mono={now:.3f}"]
        if base is not None:
            parts.append(f"dt_from_T0={now - base:.3f}s")
        for k, v in extra.items():
            parts.append(f"{k}={v}")
        try:
            target = getattr(self, "_recording_target", None) or {}
            wv = target.get("webview")
            if wv is not None and hasattr(wv, "seconds_since_user_gesture"):
                s = wv.seconds_since_user_gesture()
                parts.append(f"since_webview_gesture={s if s is not None else 'none'}")
                if s is not None:
                    parts.append(f"T0_source=webview_last_input")
        except Exception:
            pass
        self._media_log("ATTACH_TIMING", " ".join(parts))

    def _media_log(self, tag: str, message: str) -> None:
        try:
            from src.media.debug_log import media_debug
            media_debug(tag, message or "")
        except Exception:
            pass

    def _on_media_status(self, message: str) -> None:
        self._media_log("MEDIA", message or "")
        try:
            if self._record_btn is not None:
                self._record_btn.setToolTip("音声投稿")
        except Exception:
            pass

    def _stop_media_runtime(self) -> None:
        try:
            if self._media_convert_worker is not None:
                self._media_convert_worker.cancel()
        except Exception:
            pass
        try:
            if self._audio_recorder is not None and self._audio_recorder.is_recording:
                self._audio_recorder.cancel()
        except Exception:
            pass
        self._media_convert_worker = None
        self._recording_target = None

    def _capture_recording_target(self) -> dict | None:
        col = getattr(self, "_active_column", None)
        if col is None:
            return None
        try:
            wv = col.current_webview()
        except Exception:
            wv = None
        if wv is None:
            return None
        try:
            page = wv.page()
        except Exception:
            page = None
        tab_index = getattr(col, "_current_tab", 0)
        return {
            "column": col,
            "tab_index": tab_index,
            "webview": wv,
            "page": page,
        }

    def _target_still_valid(self, target: dict | None) -> bool:
        if not target:
            return False
        col = target.get("column")
        wv = target.get("webview")
        if col is None or wv is None:
            return False
        try:
            if not hasattr(col, "current_webview"):
                return False
            tabs = col.tab_views() if hasattr(col, "tab_views") else list(getattr(col, "_tabs", []))
            if wv not in tabs:
                return False
            try:
                if wv.page() is None:
                    return False
            except Exception:
                return False
            return True
        except Exception:
            return False

    def _persist_recorded_mp4(self, mp4_path: str) -> str | None:
        from pathlib import Path as _P
        import shutil
        from datetime import datetime
        from src.core.paths import default_recordings_dir

        src = _P(mp4_path)
        if not src.is_file() or src.stat().st_size < 32:
            return None
        custom = ""
        try:
            if self._settings_manager is not None:
                custom = str(self._settings_manager.get_recorded_audio_dir() or "").strip()
        except Exception:
            custom = ""
        dest_dir = _P(custom) if custom else default_recordings_dir()
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            dest_dir = default_recordings_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"voice_{stamp}_{src.name}"
        if dest.resolve() == src.resolve():
            return str(src)
        shutil.copy2(str(src), str(dest))
        return str(dest)

    def _show_recording_overlay(self) -> None:
        try:
            if getattr(self, "_recording_overlay", None) is None:
                from src.media.visual import make_recording_overlay
                self._recording_overlay = make_recording_overlay(None)
            ov = self._recording_overlay
            ov.set_elapsed(0)
            try:
                geo = self.geometry()
                ov.move(geo.x() + geo.width() - ov.width() - 24, geo.y() + 56)
            except Exception:
                pass
            try:
                from src.ui.theme import popover_show
                popover_show(ov)
            except Exception:
                ov.show()
            ov.raise_()
        except Exception as exc:
            self._media_log("REC", f"overlay_failed={exc}")

    def _sync_recording_overlay_minimized(self) -> None:
        """最小化中は録音ポップアップも隠し、復元で戻す（録音自体は続ける）。"""
        ov = getattr(self, "_recording_overlay", None)
        if ov is None:
            return
        if self.isMinimized():
            if ov.isVisible():
                ov.hide()
                self._rec_overlay_hidden_by_min = True
        elif getattr(self, "_rec_overlay_hidden_by_min", False):
            self._rec_overlay_hidden_by_min = False
            ov.setWindowOpacity(1.0)
            ov.show()
            ov.raise_()

    def _hide_recording_overlay(self) -> None:
        self._rec_overlay_hidden_by_min = False
        try:
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None:
                try:
                    from src.ui.theme import popover_hide
                    popover_hide(ov)
                except Exception:
                    ov.hide()
        except Exception:
            pass

    def _on_recording_level(self, peak: float, rms: float) -> None:
        try:
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None and ov.isVisible():
                ov.push_level(float(peak), float(rms))
        except Exception:
            pass

    def _toggle_recording(self) -> None:
        try:
            if self._record_btn is not None:
                self._record_btn.setToolTip("音声投稿")
        except Exception:
            pass
        self._media_log("REC", "button_clicked")

        rec = self._audio_recorder
        if rec is not None and rec.is_recording:
            self._media_log("REC", "stop requested")
            try:
                if self._record_btn is not None:
                    self._record_btn.setToolTip("音声投稿")
            except Exception:
                pass
            rec.stop()
            return

        self._media_log("REC", "target_capture_started")
        target = self._capture_recording_target()
        self._recording_target = target
        if target is None:
            self._media_log("REC", "target_capture_done=None (no active webview; record still proceeds)")
        else:
            col = target.get("column")
            self._media_log(
                "REC",
                f"target_capture_done column={id(col) if col is not None else None} "
                f"webview={id(target.get('webview'))} tab={target.get('tab_index')}",
            )

        try:
            page = (target or {}).get("page") if target else None
            wv = (target or {}).get("webview") if target else None
            if wv is not None:
                try:
                    wv.setFocus(Qt.FocusReason.MouseFocusReason)
                except Exception:
                    pass
            if page is not None:
                def _composer_cb(result):
                    self._media_log("REC", f"composer_check={result!r}")
                try:
                    page.runJavaScript(getattr(self, "_COMPOSER_PROBE_JS", "({})"), _composer_cb)
                except Exception as exc:
                    self._media_log("REC", f"composer_check exception={exc!r}")
            else:
                self._media_log("REC", "composer_check=skipped (no page)")
        except Exception as exc:
            self._media_log("REC", f"composer_check outer={exc!r}")

        try:
            from src.media.recorder import AudioRecorder
        except Exception as exc:
            self._recording_target = None
            self._media_log("REC", f"import AudioRecorder failed: {exc}")
            self._on_media_status(f"録音モジュールを読み込めません: {exc}")
            return
        try:
            if self._audio_recorder is not None:
                self._audio_recorder.cancel()
        except Exception:
            pass
        self._audio_recorder = AudioRecorder(self)
        self._audio_recorder.started.connect(self._on_recording_started)
        self._audio_recorder.elapsed.connect(self._on_recording_elapsed)
        self._audio_recorder.stopped.connect(self._on_recording_stopped)
        self._audio_recorder.failed.connect(self._on_recording_failed)
        self._audio_recorder.level.connect(self._on_recording_level)
        try:
            target = getattr(self, "_recording_target", None) or {}
            wv = target.get("webview")
            if wv is not None and getattr(wv, "_last_user_gesture_mono", None) is not None:
                self._attach_t0_mono = float(wv._last_user_gesture_mono)
            else:
                self._attach_t0_mono = None
            self._attach_timing_log(
                "T1_record_start",
                recording_elapsed_target="0",
            )
        except Exception:
            pass
        self._media_log("REC", "recorder_start")
        try:
            if self._record_btn is not None:
                self._record_btn.setToolTip("音声投稿")
        except Exception:
            pass
        self._audio_recorder.start()

    def _on_recording_started(self) -> None:
        try:
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None and hasattr(ov, "set_recording_mode"):
                ov.set_recording_mode()
        except Exception:
            pass
        self._recording_elapsed_sec = 0
        self._media_log("REC", "recording_started")
        try:
            self._record_btn.setIcon(make_stop_icon(_COLOR_DANGER, 14))
            self._record_btn.setProperty("recording", "true")
            self._record_btn.style().unpolish(self._record_btn)
            self._record_btn.style().polish(self._record_btn)
            if getattr(self, "_edge_dock_enabled", False):
                self._record_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                self._record_btn.setText("")
                self._record_btn.setFixedSize(24, 24)
                self._record_btn.setToolTip("音声投稿")
            else:
                self._record_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                self._record_btn.setText("REC 00:00")
                self._record_btn.setFixedSize(96, 28)
                self._record_btn.setToolTip("音声投稿")
        except Exception:
            pass
        self._show_recording_overlay()

    def _on_recording_elapsed(self, seconds: int) -> None:
        self._recording_elapsed_sec = int(seconds)
        try:
            m, s = divmod(int(seconds), 60)
            stamp = f"{m:02d}:{s:02d}"
            if getattr(self, "_edge_dock_enabled", False):
                self._record_btn.setText("")
                self._record_btn.setToolTip("音声投稿")
            else:
                self._record_btn.setText(f"REC {stamp}")
                self._record_btn.setToolTip("音声投稿")
        except Exception:
            pass
        try:
            if self._recording_overlay is not None:
                self._recording_overlay.set_elapsed(int(seconds))
        except Exception:
            pass

    def _on_recording_failed(self, message: str) -> None:
        self._recording_target = None
        self._hide_recording_overlay()
        self._reset_record_button()
        self._media_log("REC", f"failed {message}")
        self._on_media_status(message or "録音に失敗しました")

    def _on_recording_stopped(self, wav_path: str) -> None:
        try:
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None and hasattr(ov, "set_processing"):
                ov.set_processing("音声を処理中…")
                ov.show()
                ov.raise_()
            else:
                self._hide_recording_overlay()
        except Exception:
            self._hide_recording_overlay()
        self._reset_record_button()
        try:
            self._attach_timing_log(
                "T2_record_stop",
                elapsed_sec=getattr(self, "_recording_elapsed_sec", None),
            )
        except Exception:
            pass
        self._media_log("MEDIA", f"recording={wav_path}")
        self._process_audio_source_for_post(
            wav_path,
            normalize=None,
            is_recording=True,
            min_bytes=44,
            empty_msg="録音ファイルが空です",
        )

    def _process_audio_source_for_post(
        self,
        source_path: str,
        *,
        normalize: bool | None = None,
        is_recording: bool = False,
        min_bytes: int = 32,
        empty_msg: str = "音声ファイルが空です",
        webview=None,
        page=None,
    ) -> None:
        if getattr(self, "_media_convert_worker", None) is not None:
            self._media_log("MEDIA", "process_audio skipped reason=convert_in_progress")
            self._on_media_status("音声を変換中です…")
            return

        if webview is not None:
            try:
                col = getattr(self, "_active_column", None)
                tab_index = getattr(col, "_current_tab", 0) if col is not None else None
                live_page = page
                if live_page is None:
                    try:
                        live_page = webview.page()
                    except Exception:
                        live_page = None
                self._recording_target = {
                    "column": col,
                    "tab_index": tab_index,
                    "webview": webview,
                    "page": live_page,
                }
                self._media_log(
                    "MEDIA",
                    f"dnd_target webview={id(webview)} page={id(live_page) if live_page else None}",
                )
            except Exception as exc:
                self._media_log("MEDIA", f"dnd_target_set_failed={exc!r}")

        self._media_convert_is_recording = bool(is_recording)

        try:
            self._show_recording_overlay()
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None and hasattr(ov, "set_processing"):
                ov.set_processing("音声を処理中…")
                ov.show()
                ov.raise_()
        except Exception:
            pass

        self._on_media_status("MP4変換中… 0%")
        try:
            from pathlib import Path as _P
            p = _P(source_path)
            if not p.is_file() or p.stat().st_size < int(min_bytes):
                self._on_media_status(empty_msg)
                self._recording_target = None
                self._hide_recording_overlay()
                return
        except Exception as exc:
            self._on_media_status(str(exc))
            self._recording_target = None
            self._hide_recording_overlay()
            return
        try:
            from src.media.media_converter import start_conversion
        except Exception as exc:
            self._on_media_status(str(exc))
            self._recording_target = None
            self._hide_recording_overlay()
            return

        if normalize is None:
            use_norm = True
            try:
                if self._settings_manager is not None:
                    use_norm = bool(self._settings_manager.get_auto_normalize_audio())
            except Exception:
                use_norm = True
        else:
            use_norm = bool(normalize)

        try:
            self._attach_timing_log("T3_mp4_start")
        except Exception:
            pass
        self._media_log(
            "MEDIA",
            f"conversion_start normalize={use_norm} is_recording={is_recording} src={source_path}",
        )
        _vis_img = None
        try:
            if self._settings_manager is not None:
                _p = str(self._settings_manager.get_audio_visual_image() or "").strip()
                if _p:
                    _vis_img = _p
        except Exception:
            _vis_img = None
        _cx = _cy = 0.0
        _sc = 1.0
        _rot = 0.0
        try:
            if self._settings_manager is not None:
                _cx, _cy, _sc, _rot = self._settings_manager.get_audio_visual_image_transform()
        except Exception:
            try:
                if self._settings_manager is not None:
                    _cx, _cy = self._settings_manager.get_audio_visual_image_crop()
            except Exception:
                _cx = _cy = 0.0
        worker = start_conversion(
            source_path,
            normalize=use_norm,
            center_image_path=_vis_img,
            crop_x=_cx,
            crop_y=_cy,
            scale=_sc,
            rotation=_rot,
            declick=bool(self._media_convert_is_recording),
        )
        self._media_convert_worker = worker
        worker.signals.progress.connect(self._on_media_convert_progress)
        worker.signals.finished.connect(self._on_media_convert_finished)
        worker.signals.failed.connect(self._on_media_convert_failed)

    def _on_media_convert_progress(self, fraction: float) -> None:
        try:
            pct = int(max(0, min(100, fraction * 100)))
            self._record_btn.setToolTip("音声投稿")
            self._media_log("MEDIA", f"conversion_progress={pct}")
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None and hasattr(ov, "set_processing"):
                ov.set_processing(f"音声を処理中… {pct}%")
        except Exception:
            pass

    def _on_media_convert_finished(self, source: str, mp4_path: str) -> None:
        self._media_convert_worker = None
        try:
            self._hide_recording_overlay()
        except Exception:
            pass
        self._media_log("MEDIA", f"conversion_finished={mp4_path}")
        try:
            from src.media.ffmpeg_util import probe_duration_seconds
            src_d = probe_duration_seconds(source)
            out_d = probe_duration_seconds(mp4_path)
            delta = None if src_d is None or out_d is None else (out_d - src_d)
            self._media_log(
                "MEDIA",
                f"duration_compare source={src_d!r} mp4={out_d!r} delta={delta!r}",
            )
            try:
                from pathlib import Path as _Psrc
                src_p = _Psrc(source)
                if src_p.is_file() and src_p.suffix.lower() == ".wav":
                    from src.media.ffmpeg_util import wav_peak_rms
                    peak_info = wav_peak_rms(src_p) or {}
                    self._media_log(
                        "MEDIA",
                        f"wav_vs_mp4_triage "
                        f"wav_peak={peak_info.get('wav_peak')!r} "
                        f"wav_rms={peak_info.get('wav_rms')!r} "
                        f"wav_frames={peak_info.get('frames')!r} "
                        f"wav_rate={peak_info.get('rate')!r} "
                        f"wav_channels={peak_info.get('channels')!r} "
                        f"wav_duration_sec={peak_info.get('duration_sec')!r} "
                        f"wav_sample_count={peak_info.get('sample_count')!r} "
                        f"wav_pcm_min={peak_info.get('pcm_min')!r} "
                        f"wav_pcm_max={peak_info.get('pcm_max')!r} "
                        f"mp4_duration={out_d!r} mp4_path={mp4_path}",
                    )
            except Exception as triage_exc:
                self._media_log("MEDIA", f"wav_vs_mp4_triage_failed={triage_exc!r}")
        except Exception as exc:
            self._media_log("MEDIA", f"duration_compare_failed={exc!r}")
        try:
            from pathlib import Path as _P
            p = _P(mp4_path)
            if not p.is_file() or p.stat().st_size < 32:
                self._on_media_status("音声をMP4へ変換できませんでした（出力なし）")
                self._recording_target = None
                return
        except Exception as exc:
            self._on_media_status(str(exc))
            self._recording_target = None
            return
        try:
            import os as _os_keep
            keep_wav = bool(
                _os_keep.environ.get("MAYOTTER_KEEP_REC_WAV")
                or _os_keep.environ.get("MAYOTTER_MEDIA_DEBUG")
            )
            from src.media.media_converter import cleanup_temp_media, is_audio_path
            if is_audio_path(source):
                if keep_wav:
                    self._media_log(
                        "MEDIA",
                        f"cleanup_temp_media skipped (KEEP_REC_WAV) source={source}",
                    )
                else:
                    cleanup_temp_media(source)
        except Exception:
            pass

        is_rec = bool(getattr(self, "_media_convert_is_recording", True))
        save_mp4 = False
        if is_rec:
            save_mp4 = True
            try:
                if self._settings_manager is not None:
                    save_mp4 = bool(self._settings_manager.get_save_recorded_audio())
            except Exception:
                save_mp4 = True
        kept_path = mp4_path
        if save_mp4:
            try:
                kept_path = self._persist_recorded_mp4(mp4_path) or mp4_path
                self._media_log("MEDIA", f"recorded_mp4_saved={kept_path}")
                self._on_media_status(f"録音MP4を保存しました: {kept_path}")
            except Exception as exc:
                self._media_log("MEDIA", f"recorded_mp4_save_failed={exc}")
        else:
            self._media_log(
                "MEDIA",
                "persist_skipped "
                + ("save_recorded_audio=OFF" if is_rec else "source=external_file"),
            )

        try:
            from pathlib import Path as _P2
            sz = _P2(kept_path).stat().st_size if _P2(kept_path).is_file() else -1
        except Exception:
            sz = -1
        self._media_log(
            "ATTACH",
            f"start stage=A_mp4_ok file_path={kept_path} file_exists={sz >= 0} file_size={sz}",
        )
        try:
            self._attach_timing_log("T4_mp4_done", file_size=sz)
            self._attach_timing_log("T5_attach_start")
        except Exception:
            pass

        target = getattr(self, "_recording_target", None)
        target_ok = target is not None and self._target_still_valid(target)
        self._media_log(
            "ATTACH",
            f"target_captured={target is not None} target_valid={target_ok} "
            f"column={id((target or {}).get('column')) if target else None} "
            f"tab={(target or {}).get('tab_index') if target else None} "
            f"webview={id((target or {}).get('webview')) if target else None}",
        )

        use_recording = True
        if not target_ok:
            self._media_log("ATTACH", "start_target invalid → try active column fallback")
            use_recording = False
            col = getattr(self, "_active_column", None)
            try:
                wv_now = col.current_webview() if col is not None else None
            except Exception:
                wv_now = None
            if wv_now is None:
                self._recording_target = None
                self._media_log("ATTACH", "failed stage=B_attach_start reason=no_target")
                if not save_mp4:
                    def _later_cleanup2(path=kept_path):
                        try:
                            from src.media.media_converter import cleanup_temp_media
                            cleanup_temp_media(path)
                        except Exception:
                            pass
                    QTimer.singleShot(30_000, _later_cleanup2)
                if save_mp4:
                    self._on_media_status("音声の自動添付に失敗しました（添付先なし・MP4は保存済み）")
                else:
                    self._on_media_status("音声の自動添付に失敗しました（添付先なし）")
                return

        self._media_log("ATTACH", f"stage=B_pending_ready use_recording_target={use_recording}")
        import os as _os_poc
        if _os_poc.environ.get("MAYOTTER_CDP_POC", "").strip().lower() in ("1", "true", "yes", "on"):
            self._media_log("CDP_POC", "enabled → DOM.setFileInputFiles path (no chooser)")
            self._on_media_status("Composerへ添付中…")
            self._run_cdp_attach_poc([kept_path], use_recording_target=use_recording)
        elif _os_poc.environ.get("MAYOTTER_DT_POC", "").strip() in ("1", "true", "True", "yes"):
            self._media_log("DT_POC", "enabled → DataTransfer path (no chooser)")
            self._on_media_status("Composerへ添付中…")
            self._run_datatransfer_attach_poc([kept_path], use_recording_target=use_recording)
        else:
            self._offer_pending_attach_near_composer(
                [kept_path], use_recording_target=use_recording
            )
        if not save_mp4:
            def _later_cleanup(path=kept_path):
                try:
                    from src.media.media_converter import cleanup_temp_media
                    cleanup_temp_media(path)
                except Exception:
                    pass
            QTimer.singleShot(120_000, _later_cleanup)

    def _on_media_convert_failed(self, source: str, message: str) -> None:
        self._media_convert_worker = None
        self._recording_target = None
        try:
            ov = getattr(self, "_recording_overlay", None)
            if ov is not None and hasattr(ov, "set_error"):
                ov.set_error(message or "音声の処理に失敗しました")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2500, self._hide_recording_overlay)
            else:
                self._hide_recording_overlay()
        except Exception:
            try:
                self._hide_recording_overlay()
            except Exception:
                pass
        self._media_log("MEDIA", f"conversion_failed={message}")
        self._media_log("ATTACH", "skipped reason=conversion_failed")
        self._on_media_status(message or "音声をMP4へ変換できませんでした")

    def _reset_record_button(self) -> None:
        try:
            self._record_btn.setIcon(make_mic_icon(_COLOR_ACCENT_SOFT, 16))
            self._record_btn.setIconSize(QSize(16, 16))
            self._record_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self._record_btn.setText("")
            self._record_btn.setFixedSize(24, 24)
            self._record_btn.setProperty("recording", "false")
            self._record_btn.style().unpolish(self._record_btn)
            self._record_btn.style().polish(self._record_btn)
            self._record_btn.setToolTip("音声投稿")
        except Exception:
            pass

    _ATTACH_MAX_ATTEMPTS = 4
    _ATTACH_RETRY_MS = 350
    _ATTACH_CHECK_MS = 500
    _ATTACH_REACTIVATE_MS = 120

    _COMPOSER_PROBE_JS = r"""
    (function() {
      function findBox() {
        return document.querySelector(
          '[data-testid="tweetTextarea_0"], div[role="textbox"][data-testid^="tweetTextarea"],' +
          'div[role="textbox"][contenteditable="true"]'
        );
      }
      function findFileInput() {
        var preferred = document.querySelector(
          'input[data-testid="fileInput"], input[type="file"][accept*="video"], input[type="file"][accept*="image"]'
        );
        if (preferred) return preferred;
        var nodes = document.querySelectorAll('input[type="file"]');
        for (var i = 0; i < nodes.length; i++) {
          var n = nodes[i];
          var a = (n.getAttribute('accept') || '').toLowerCase();
          if (!a || a.indexOf('video') >= 0 || a.indexOf('image') >= 0
              || a.indexOf('audio') >= 0 || a === '*/*') return n;
        }
        return nodes.length ? nodes[0] : null;
      }
      function findMediaButton() {
        return document.querySelector(
          '[aria-label="Add photos or video"], [data-testid="fileInput"],' +
          'button[aria-label*="media" i], button[aria-label*="photo" i],' +
          'button[aria-label*="Media" i], button[aria-label*="画像" i],' +
          'button[aria-label*="動画" i], div[role="button"][aria-label*="Media" i],' +
          'div[role="button"][aria-label*="photo" i], div[role="button"][aria-label*="Add photos" i]'
        );
      }
      function elInfo(el) {
        if (!el) return null;
        var r = el.getBoundingClientRect();
        return {
          tag: el.tagName,
          id: el.id || '',
          testid: el.getAttribute('data-testid') || '',
          role: el.getAttribute('role') || '',
          connected: !!el.isConnected,
          disabled: !!el.disabled,
          display: (el.style && el.style.display) || '',
          w: Math.round(r.width), h: Math.round(r.height),
          x: Math.round(r.left + r.width / 2),
          y: Math.round(r.top + r.height / 2),
          key: (el.getAttribute('data-testid') || '') + '|' + el.tagName + '|' +
               Math.round(r.left) + ',' + Math.round(r.top)
        };
      }
      var box = findBox();
      var input = findFileInput();
      var btn = findMediaButton();
      var ae = document.activeElement;
      return JSON.stringify({
        composer_present: !!box,
        file_input_present: !!input,
        file_input_connected: !!(input && input.isConnected),
        media_button_present: !!btn,
        media_button_rect: btn ? elInfo(btn) : null,
        file_input_info: input ? elInfo(input) : null,
        box_info: box ? elInfo(box) : null,
        active_element: ae ? (ae.tagName + ':' + (ae.getAttribute('data-testid') || ae.getAttribute('role') || '')) : '',
        active_is_composer: !!(ae && box && (ae === box || box.contains(ae))),
        has_focus: document.hasFocus ? document.hasFocus() : null
      });
    })();
    """

    def _offer_pending_attach_near_composer(
        self,
        paths: list[str],
        *,
        use_recording_target: bool = True,
    ) -> None:
        from pathlib import Path as _P
        from src.browser.webview import MayotterPage

        paths = [p for p in paths if p]
        if not paths:
            return
        for pth in paths:
            try:
                if not (_P(pth).is_file() and _P(pth).stat().st_size > 0):
                    self._on_media_status("添付するMP4が見つかりません")
                    return
            except Exception:
                self._on_media_status("添付するMP4が見つかりません")
                return

        if use_recording_target:
            target = getattr(self, "_recording_target", None)
            if not self._target_still_valid(target):
                self._recording_target = None
                self._media_log("ATTACH", "failed stage=offer reason=target_invalid")
                self._on_media_status("音声の添付先が見つかりません")
                return
            wv = target["webview"]
            page = target.get("page") or wv.page()
        else:
            col = getattr(self, "_active_column", None)
            try:
                wv = col.current_webview() if col is not None else None
            except Exception:
                wv = None
            if wv is None:
                self._on_media_status("音声の添付先が見つかりません")
                return
            page = wv.page()

        try:
            page.pending_attach_files = list(paths)
            page._attach_choose_served = False
            MayotterPage.pending_attach_files = list(paths)
            page._attach_auto_mode = False
        except Exception as exc:
            self._media_log("ATTACH", f"pending_set_failed={exc!r}")
            self._on_media_status("音声の添付に失敗しました")
            return

        self._media_log(
            "ATTACH",
            f"pending_set near_composer_ui paths={paths} page={id(page)}",
        )
        self._on_media_status("MP4の準備ができました — Composer付近の「音声を添付」を押してください")

        inject = r"""
        (function() {
          try {
            var OLD = document.getElementById('mayotter-voice-attach');
            if (OLD) OLD.remove();
            var oldChip = document.getElementById('mayotter-attach-chip');
            if (oldChip) oldChip.remove();

            function findBox() {
              return document.querySelector(
                '[data-testid="tweetTextarea_0"], div[role="textbox"][data-testid^="tweetTextarea"],' +
                'div[role="textbox"][contenteditable="true"]'
              );
            }
            function findFileInput(root) {
              var scope = root || document;
              var preferred = scope.querySelector(
                'input[data-testid="fileInput"], input[type="file"][accept*="video"],' +
                'input[type="file"][accept*="image"]'
              );
              if (preferred) return preferred;
              var nodes = scope.querySelectorAll('input[type="file"]');
              for (var i = 0; i < nodes.length; i++) {
                var n = nodes[i];
                if (!n.isConnected) continue;
                var a = (n.getAttribute('accept') || '').toLowerCase();
                if (!a || a.indexOf('video') >= 0 || a.indexOf('image') >= 0
                    || a.indexOf('audio') >= 0 || a === '*/*') return n;
              }
              return nodes.length ? nodes[0] : null;
            }
            function findMediaButton(root) {
              var scope = root || document;
              return scope.querySelector(
                '[aria-label="Add photos or video"], button[aria-label*="media" i],' +
                'button[aria-label*="photo" i], button[aria-label*="画像" i],' +
                'div[role="button"][aria-label*="Add photos" i]'
              );
            }
            function composerRoot(box) {
              if (!box) return null;
              var n = box;
              for (var i = 0; i < 14 && n; i++) {
                if (n.querySelector && (n.querySelector('input[type="file"]')
                    || n.querySelector('[data-testid="toolBar"]')
                    || n.querySelector('[role="group"]'))) {
                  return n;
                }
                n = n.parentElement;
              }
              return box.parentElement;
            }

            var box = findBox();
            if (!box) return 'no_composer';
            var root = composerRoot(box) || box.parentElement || document.body;

            var host = document.createElement('div');
            host.id = 'mayotter-voice-attach';
            host.setAttribute('data-mayotter', 'voice-attach');
            host.style.cssText = [
              'display:flex', 'align-items:center', 'gap:8px',
              'margin:8px 0 4px 0', 'padding:0',
              'font-family:system-ui,-apple-system,sans-serif',
              'pointer-events:auto', 'z-index:1000', 'position:relative'
            ].join(';');

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.id = 'mayotter-voice-attach-btn';
            btn.textContent = '音声を添付';
            btn.setAttribute('aria-label', 'Mayotter 音声を添付');
            // Mayotter chrome (not X blue): slate panel + accent border
            btn.style.cssText = [
              'appearance:none', 'cursor:pointer',
              'padding:8px 14px', 'border-radius:8px',
              'border:1px solid #3d5a80',
              'background:linear-gradient(180deg,#1a2332 0%,#121a24 100%)',
              'color:#f1f3f7', 'font-size:13px', 'font-weight:600',
              'letter-spacing:0.02em',
              'box-shadow:0 1px 0 rgba(255,255,255,0.06) inset, 0 2px 8px rgba(0,0,0,0.35)'
            ].join(';');

            var tag = document.createElement('span');
            tag.textContent = 'Mayotter';
            tag.style.cssText = 'font-size:11px;color:#7a8eaa;font-weight:600;user-select:none;';

            var busy = false;
            btn.addEventListener('click', function (ev) {
              ev.preventDefault();
              ev.stopPropagation();
              if (busy || btn.disabled) return;
              busy = true;
              btn.disabled = true;
              btn.textContent = '添付中…';
              btn.style.opacity = '0.75';
              btn.style.cursor = 'default';

              var input = findFileInput(root) || findFileInput(document);
              if (!input) {
                var mb = findMediaButton(root) || findMediaButton(document);
                if (mb) { try { mb.click(); } catch (e0) {} }
                input = findFileInput(root) || findFileInput(document);
              }
              if (input) {
                try { input.click(); } catch (e1) {}
              }
              // Re-enable after a while if chooser did not complete (MainWindow polls)
              setTimeout(function () {
                if (!btn.isConnected) return;
                if (btn.getAttribute('data-done') === '1') return;
                busy = false;
                btn.disabled = false;
                btn.textContent = '音声を添付';
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
              }, 8000);
            }, true);

            host.appendChild(btn);
            host.appendChild(tag);

            // Place immediately after the textbox block when possible
            var anchor = box;
            while (anchor && anchor.parentElement && anchor.parentElement !== root
                   && anchor.parentElement.querySelector
                   && !anchor.parentElement.querySelector('[data-testid="toolBar"]')) {
              if (anchor.nextSibling) break;
              anchor = anchor.parentElement;
            }
            if (anchor && anchor.parentElement) {
              if (anchor.nextSibling) {
                anchor.parentElement.insertBefore(host, anchor.nextSibling);
              } else {
                anchor.parentElement.appendChild(host);
              }
            } else {
              root.appendChild(host);
            }
            return 'injected_near_composer';
          } catch (e) {
            return 'err:' + String(e);
          }
        })();
        """

        def _after_inject(res):
            self._media_log("ATTACH", f"near_composer_ui={res!r}")
            if not res or (isinstance(res, str) and res.startswith("err")):
                self._on_media_status("音声の添付に失敗しました")
                return
            if res == "no_composer":
                self._recording_target = None
                self._on_media_status("音声の添付先が見つかりません")
                return
            state = {"i": 0, "finished": False}

            def _cleanup_ui(done=False):
                try:
                    page.runJavaScript(
                        "(function(){var h=document.getElementById('mayotter-voice-attach');"
                        "if(!h)return;"
                        "var b=document.getElementById('mayotter-voice-attach-btn');"
                        + ("if(b){b.setAttribute('data-done','1');}h.remove();" if done
                           else "if(b){b.disabled=false;b.textContent='音声を添付';b.style.opacity='1';}")
                        + "})();"
                    )
                except Exception:
                    pass

            def _finish_transaction():
                if state.get("finished"):
                    return
                state["finished"] = True
                self._media_log(
                    "ATTACH",
                    "stage=I_complete chooseFiles_served=True pending_cleared=True "
                    "(transaction done, no further media probe)",
                )
                _cleanup_ui(done=True)
                self._recording_target = None
                self._on_media_status("音声を添付しました")

            delays_ms = [400, 600, 800, 1000, 1200, 1500, 2000, 2500, 3000, 3000]

            def _tick():
                if state.get("finished"):
                    return
                if state["i"] >= len(delays_ms):
                    self._media_log("ATTACH", "near_composer_timeout waiting_for_chooser")
                    _cleanup_ui(done=True)
                    self._recording_target = None
                    self._on_media_status("音声の添付に失敗しました")
                    state["finished"] = True
                    return

                served = bool(getattr(page, "_attach_choose_served", False))
                still_pending = bool(getattr(page, "pending_attach_files", None))

                if served and not still_pending:
                    _finish_transaction()
                    return

                state["i"] += 1
                QTimer.singleShot(
                    delays_ms[min(state["i"], len(delays_ms) - 1)], _tick
                )

            QTimer.singleShot(delays_ms[0], _tick)

        try:
            page.runJavaScript(inject, _after_inject)
        except Exception as exc:
            self._media_log("ATTACH", f"inject_failed={exc!r}")
            self._on_media_status("音声の添付に失敗しました")

    def _run_cdp_attach_poc(self, paths: list[str], *, use_recording_target: bool = True) -> None:
        from pathlib import Path as _P
        from src.browser.cdp_poc import run_set_files_for_page, remote_debugging_port

        def _log(msg: str) -> None:
            self._media_log("CDP_POC", msg)

        paths = [p for p in paths if p]
        if not paths:
            _log("abort reason=no_paths")
            return
        mp4 = str(_P(paths[0]).resolve())

        if use_recording_target:
            target = getattr(self, "_recording_target", None)
            if not self._target_still_valid(target):
                _log("abort reason=target_invalid")
                self._recording_target = None
                self._on_media_status("音声の自動添付に失敗しました")
                return
            wv = target["webview"]
            page = target.get("page") or wv.page()
        else:
            col = getattr(self, "_active_column", None)
            try:
                wv = col.current_webview() if col is not None else None
            except Exception:
                wv = None
            if wv is None:
                _log("abort reason=no_webview")
                self._on_media_status("音声の自動添付に失敗しました")
                return
            page = wv.page()

        try:
            dt_id = page.devToolsId()
        except Exception as exc:
            _log(f"devtools_id_failed={exc!r}")
            self._on_media_status("音声の自動添付に失敗しました")
            return
        _log(f"devtools_id={dt_id}")
        port = remote_debugging_port()
        _log(f"debug_port={port}")

        before_holder = {"raw": None}

        def _after_before(raw_before):
            before_holder["raw"] = raw_before
            import json
            try:
                before = json.loads(raw_before) if isinstance(raw_before, str) else (raw_before or {})
            except Exception:
                before = {}
            _log(
                f"media_before remove={before.get('remove_count')} "
                f"attach={before.get('attachment_count')} "
                f"preview={before.get('preview_count')}"
            )

            def _worker():
                result = run_set_files_for_page(devtools_id=str(dt_id), mp4_path=mp4, port=port)
                _log(f"cdp_result connected={result.get('connected')} set_ok={result.get('set_ok')} error={result.get('error')}")
                _log(f"input_files_after={result.get('input_files_after')}")

                def _on_main():
                    if not result.get("set_ok"):
                        self._recording_target = None
                        self._on_media_status("音声の自動添付に失敗しました")
                        _log("attachment_confirmed=False reason=set_failed")
                        return
                    delays = [300, 600, 1200, 2000, 3000]
                    state = {"i": 0}

                    def _poll():
                        def _got(raw_after):
                            try:
                                after = json.loads(raw_after) if isinstance(raw_after, str) else (raw_after or {})
                            except Exception:
                                after = {}
                            try:
                                b = json.loads(before_holder["raw"]) if isinstance(before_holder["raw"], str) else (before_holder["raw"] or {})
                            except Exception:
                                b = {}
                            d_r = int(after.get("remove_count") or 0) - int(b.get("remove_count") or 0)
                            d_a = int(after.get("attachment_count") or 0) - int(b.get("attachment_count") or 0)
                            d_p = int(after.get("preview_count") or 0) - int(b.get("preview_count") or 0)
                            _log(
                                f"media_after poll={state['i']} remove={after.get('remove_count')} "
                                f"attach={after.get('attachment_count')} preview={after.get('preview_count')} "
                                f"delta_remove={d_r} delta_attach={d_a} delta_preview={d_p}"
                            )
                            if d_r > 0 or d_a > 0 or d_p > 0:
                                _log("attachment_confirmed=True")
                                self._recording_target = None
                                self._on_media_status("音声を添付しました")
                                return
                            state["i"] += 1
                            if state["i"] >= len(delays):
                                _log("attachment_confirmed=False")
                                self._recording_target = None
                                self._on_media_status("音声の自動添付に失敗しました")
                                return
                            QTimer.singleShot(delays[state["i"]], lambda: page.runJavaScript(
                                self._COMPOSER_MEDIA_PROBE_JS, _got
                            ))
                        page.runJavaScript(self._COMPOSER_MEDIA_PROBE_JS, _got)

                    QTimer.singleShot(delays[0], _poll)

                QTimer.singleShot(0, _on_main)

            import threading
            threading.Thread(target=_worker, daemon=True).start()

        try:
            page.runJavaScript(self._COMPOSER_MEDIA_PROBE_JS, _after_before)
        except Exception as exc:
            _log(f"before_probe_failed={exc!r}")
            self._on_media_status("音声の自動添付に失敗しました")

    def _run_datatransfer_attach_poc(self, paths: list[str], *, use_recording_target: bool = True) -> None:
        import base64
        import json
        from pathlib import Path as _P

        def _log(msg: str) -> None:
            self._media_log("DT_POC", msg)

        paths = [p for p in paths if p]
        if not paths:
            _log("abort reason=no_paths")
            return
        mp4 = paths[0]
        try:
            data = _P(mp4).read_bytes()
        except Exception as exc:
            _log(f"abort reason=read_failed err={exc!r}")
            self._on_media_status("音声の自動添付に失敗しました")
            return
        if len(data) < 32:
            _log(f"abort reason=too_small size={len(data)}")
            self._on_media_status("音声の自動添付に失敗しました")
            return

        if use_recording_target:
            target = getattr(self, "_recording_target", None)
            if not self._target_still_valid(target):
                _log("abort reason=target_invalid")
                self._recording_target = None
                self._on_media_status("音声の自動添付に失敗しました")
                return
            wv = target["webview"]
            page = target.get("page") or wv.page()
        else:
            col = getattr(self, "_active_column", None)
            try:
                wv = col.current_webview() if col is not None else None
            except Exception:
                wv = None
            if wv is None:
                _log("abort reason=no_webview")
                self._on_media_status("音声の自動添付に失敗しました")
                return
            page = wv.page()

        name = _P(mp4).name
        b64 = base64.b64encode(data).decode("ascii")
        _log(
            f"start file={mp4} size={len(data)} name={name!r} "
            f"b64_len={len(b64)} page={id(page)}"
        )

        before_holder = {"raw": None}

        def _after_before(raw_before):
            before_holder["raw"] = raw_before
            try:
                before = json.loads(raw_before) if isinstance(raw_before, str) else (raw_before or {})
            except Exception:
                before = {}
            _log(
                f"media_before remove={before.get('remove_count')} "
                f"attach={before.get('attachment_count')} "
                f"preview={before.get('preview_count')} "
                f"keys={before.get('keys')}"
            )

            js = r"""
            (function(b64, fileName, mime) {
              function log(o) { return JSON.stringify(o); }
              function findComposerRoot() {
                var box = document.querySelector(
                  '[data-testid="tweetTextarea_0"], div[role="textbox"][data-testid^="tweetTextarea"],' +
                  'div[role="textbox"][contenteditable="true"]'
                );
                if (!box) return null;
                var n = box;
                for (var i = 0; i < 12 && n; i++) {
                  if (n.querySelector && n.querySelector('input[type="file"]')) return n;
                  n = n.parentElement;
                }
                return box.closest('form') || box.parentElement || document.body;
              }
              function findFileInput(root) {
                if (!root) return null;
                var preferred = root.querySelector(
                  'input[data-testid="fileInput"], input[type="file"][accept*="video"],' +
                  'input[type="file"][accept*="image"]'
                );
                if (preferred) return preferred;
                var nodes = root.querySelectorAll('input[type="file"]');
                for (var i = 0; i < nodes.length; i++) {
                  var n = nodes[i];
                  if (!n.isConnected) continue;
                  var a = (n.getAttribute('accept') || '').toLowerCase();
                  if (!a || a.indexOf('video') >= 0 || a.indexOf('image') >= 0
                      || a.indexOf('audio') >= 0 || a === '*/*') return n;
                }
                return nodes.length ? nodes[0] : null;
              }
              try {
                var root = findComposerRoot();
                var input = findFileInput(root);
                var out = {
                  composer_found: !!root,
                  file_input_found: !!input,
                  file_input_connected: !!(input && input.isConnected),
                  file_input_disabled: !!(input && input.disabled),
                  before_input_files: input && input.files ? input.files.length : -1,
                  dt_files_length: 0,
                  after_input_files: -1,
                  change_dispatched: false,
                  input_dispatched: false,
                  assign_error: null,
                  file_name: null,
                  file_type: null,
                  file_size: null
                };
                if (!input) return log(out);
                // decode base64 → Uint8Array
                var bin = atob(b64);
                var len = bin.length;
                var bytes = new Uint8Array(len);
                for (var i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
                var file = new File([bytes], fileName, { type: mime || 'video/mp4' });
                out.file_name = file.name;
                out.file_type = file.type;
                out.file_size = file.size;
                var dt = new DataTransfer();
                dt.items.add(file);
                out.dt_files_length = dt.files.length;
                try {
                  input.files = dt.files;
                } catch (e) {
                  out.assign_error = String(e);
                }
                out.after_input_files = input.files ? input.files.length : -1;
                if (input.files && input.files[0]) {
                  out.after_name = input.files[0].name;
                  out.after_size = input.files[0].size;
                  out.after_type = input.files[0].type;
                }
                try {
                  input.dispatchEvent(new Event('input', { bubbles: true }));
                  out.input_dispatched = true;
                } catch (e1) { out.input_error = String(e1); }
                try {
                  input.dispatchEvent(new Event('change', { bubbles: true }));
                  out.change_dispatched = true;
                } catch (e2) { out.change_error = String(e2); }
                // Also try InputEvent if available
                try {
                  if (typeof InputEvent === 'function') {
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, data: null }));
                  }
                } catch (e3) {}
                return log(out);
              } catch (e) {
                return log({ fatal: String(e) });
              }
            })
            """
            call = (
                f"({js})({json.dumps(b64)}, {json.dumps(name)}, {json.dumps('video/mp4')})"
            )

            def _after_js(raw_js):
                _log(f"js_result_raw_type={type(raw_js).__name__}")
                try:
                    info = json.loads(raw_js) if isinstance(raw_js, str) else (raw_js or {})
                except Exception:
                    info = {"parse_error": repr(raw_js)[:500]}
                for k in (
                    "composer_found", "file_input_found", "file_input_connected",
                    "file_input_disabled", "dt_files_length", "file_name", "file_type",
                    "file_size", "before_input_files", "after_input_files",
                    "after_name", "after_size", "after_type",
                    "change_dispatched", "input_dispatched", "assign_error", "fatal",
                ):
                    if k in info:
                        _log(f"{k}={info[k]}")

                delays = [200, 400, 800, 1500, 2500]
                state = {"i": 0}

                def _poll():
                    def _got(raw_after):
                        try:
                            after = json.loads(raw_after) if isinstance(raw_after, str) else (raw_after or {})
                        except Exception:
                            after = {}
                        try:
                            before = json.loads(before_holder["raw"]) if isinstance(before_holder["raw"], str) else (before_holder["raw"] or {})
                        except Exception:
                            before = {}
                        d_r = int(after.get("remove_count") or 0) - int(before.get("remove_count") or 0)
                        d_a = int(after.get("attachment_count") or 0) - int(before.get("attachment_count") or 0)
                        d_p = int(after.get("preview_count") or 0) - int(before.get("preview_count") or 0)
                        _log(
                            f"media_after poll={state['i']} remove={after.get('remove_count')} "
                            f"attach={after.get('attachment_count')} preview={after.get('preview_count')} "
                            f"delta_remove={d_r} delta_attach={d_a} delta_preview={d_p} "
                            f"keys={after.get('keys')}"
                        )
                        confirmed = d_r > 0 or d_a > 0 or d_p > 0
                        if confirmed:
                            _log("attachment_confirmed=True")
                            self._recording_target = None
                            self._on_media_status("音声を添付しました")
                            return
                        state["i"] += 1
                        if state["i"] >= len(delays):
                            _log("attachment_confirmed=False")
                            self._recording_target = None
                            self._on_media_status("音声の自動添付に失敗しました")
                            return
                        QTimer.singleShot(delays[state["i"]], lambda: page.runJavaScript(
                            self._COMPOSER_MEDIA_PROBE_JS, _got
                        ))
                    page.runJavaScript(self._COMPOSER_MEDIA_PROBE_JS, _got)

                QTimer.singleShot(delays[0], _poll)

            try:
                page.runJavaScript(call, _after_js)
            except Exception as exc:
                _log(f"runJavaScript_failed={exc!r}")
                self._recording_target = None
                self._on_media_status("音声の自動添付に失敗しました")

        try:
            page.runJavaScript(self._COMPOSER_MEDIA_PROBE_JS, _after_before)
        except Exception as exc:
            _log(f"before_probe_failed={exc!r}")
            self._on_media_status("音声の自動添付に失敗しました")

    def _attach_files_to_composer(
        self,
        paths: list[str],
        *,
        use_recording_target: bool = False,
        attempt: int = 0,
    ) -> None:
        from pathlib import Path as _P
        from src.browser.webview import MayotterPage

        paths = [x for x in paths if x]
        if not paths:
            self._media_log("ATTACH", "failed stage=B_attach_start reason=empty_paths")
            return
        for pth in paths:
            try:
                pp = _P(pth)
                exists = pp.is_file() and pp.stat().st_size > 0
                size = pp.stat().st_size if pp.is_file() else -1
            except Exception:
                exists = False
                size = -1
            self._media_log(
                "ATTACH",
                f"attempt={attempt} file_path={pth} file_exists={exists} file_size={size}",
            )
            if not exists:
                self._media_log("ATTACH", "failed stage=B_attach_start reason=file_missing")
                self._on_media_status("添付するMP4が見つかりません")
                return

        if use_recording_target:
            target = getattr(self, "_recording_target", None)
            valid = self._target_still_valid(target)
            self._media_log(
                "ATTACH",
                f"stage=C_target target_valid={valid} "
                f"column={id((target or {}).get('column')) if target else None} "
                f"tab={(target or {}).get('tab_index') if target else None} "
                f"webview={id((target or {}).get('webview')) if target else None}",
            )
            if not valid:
                self._recording_target = None
                self._set_attach_auto_mode(None, False)
                self._media_log("ATTACH", "failed stage=C_target reason=target_invalid")
                self._on_media_status("音声の自動添付に失敗しました（添付先が閉じられました）")
                return
            wv = target["webview"]
            try:
                live = wv.page()
            except Exception:
                live = None
            page = live or target.get("page")
            if page is not None:
                target["page"] = page
            self._media_log("ATTACH", f"stage=C_target page_valid={page is not None} page={id(page)}")
        else:
            col = getattr(self, "_active_column", None)
            if col is None:
                self._on_media_status("音声の自動添付に失敗しました（カラムなし）")
                return
            try:
                wv = col.current_webview()
            except Exception:
                wv = None
            if wv is None:
                self._on_media_status("音声の自動添付に失敗しました（WebViewなし）")
                return
            page = wv.page()

        if page is None or wv is None:
            self._recording_target = None
            self._on_media_status("音声の自動添付に失敗しました（pageなし）")
            return

        def _set_pending() -> None:
            page.pending_attach_files = list(paths)
            page._attach_choose_served = False
            page._attach_auto_mode = True
            MayotterPage.pending_attach_files = list(paths)
            MayotterPage._attach_auto_mode_global = True
            self._media_log(
                "ATTACH",
                f"stage=D_pending pending_set=True pending_count={len(paths)} page={id(page)}",
            )

        def _served() -> bool:
            try:
                return bool(getattr(page, "_attach_choose_served", False))
            except Exception:
                return False

        def _done(msg: str = "音声を添付しました") -> None:
            def _on_v(ok, info):
                if ok:
                    self._report_attach_success(page)
                else:
                    self._report_attach_failure(page, "media_not_detected")
            self._verify_x_composer_media(page, on_result=_on_v)

        def _fail(reason: str) -> None:
            self._recording_target = None
            self._set_attach_auto_mode(page, False)
            try:
                page.pending_attach_files = None
                MayotterPage.pending_attach_files = None
            except Exception:
                pass
            self._media_log("ATTACH", f"attach_success=False attach_fail_reason={reason}")
            self._on_media_status("音声の自動添付に失敗しました")

        def _retry(reason: str) -> None:
            max_a = int(getattr(self, "_ATTACH_MAX_ATTEMPTS", 4))
            delay = int(getattr(self, "_ATTACH_RETRY_MS", 350))
            if attempt + 1 < max_a:
                self._media_log("ATTACH", f"retry reason={reason} next={attempt + 1}/{max_a}")
                self._on_media_status("Composerへ添付中…")
                QTimer.singleShot(
                    delay,
                    lambda: self._attach_files_to_composer(
                        paths,
                        use_recording_target=use_recording_target,
                        attempt=attempt + 1,
                    ),
                )
                return
            _fail(reason)

        def _log_probe(tag: str, raw) -> dict:
            import json
            info = {}
            try:
                if isinstance(raw, str):
                    info = json.loads(raw)
                elif isinstance(raw, dict):
                    info = raw
            except Exception:
                info = {}
            self._media_log(
                "ATTACH",
                f"{tag} composer_present={info.get('composer_present')} "
                f"file_input_present={info.get('file_input_present')} "
                f"file_input_connected={info.get('file_input_connected')} "
                f"media_button_present={info.get('media_button_present')} "
                f"media_button_rect={info.get('media_button_rect')} "
                f"page_focus={info.get('has_focus')} "
                f"active_element={info.get('active_element')!r} "
                f"active_is_composer={info.get('active_is_composer')}",
            )
            return info

        def _after_probe(raw):
            info = _log_probe("composer_state", raw)
            self._reactivate_composer_then_attach(wv, page, paths, attempt, info)

        try:
            _set_pending()
            page.runJavaScript(self._COMPOSER_PROBE_JS, _after_probe)
        except Exception as exc:
            _fail(f"probe_exception:{exc}")

    def _reactivate_composer_then_attach(
        self, wv, page, paths: list[str], attempt: int, prior_info: dict
    ) -> None:
        from src.browser.webview import MayotterPage

        def _set_pending() -> None:
            page.pending_attach_files = list(paths)
            page._attach_choose_served = False
            page._attach_auto_mode = True
            MayotterPage.pending_attach_files = list(paths)
            MayotterPage._attach_auto_mode_global = True

        try:
            wv.setFocus(Qt.FocusReason.MouseFocusReason)
            wv.activateWindow()
        except Exception:
            pass

        box = (prior_info or {}).get("box_info") or {}
        bx = box.get("x")
        by = box.get("y")
        if bx is not None and by is not None and int(box.get("w") or 0) > 2:
            self._media_log("ATTACH", f"composer_reactivate_click x={bx} y={by}")
            try:
                self._synthesize_webview_click(wv, float(bx), float(by))
            except Exception as exc:
                self._media_log("ATTACH", f"composer_reactivate_click_fail={exc!r}")
        else:
            self._media_log("ATTACH", "composer_reactivate_js_focus")
            try:
                page.runJavaScript(
                    "(function(){var b=document.querySelector("
                    "'[data-testid=\"tweetTextarea_0\"],div[role=\"textbox\"][data-testid^=\"tweetTextarea\"],"
                    "div[role=\"textbox\"][contenteditable=\"true\"]');"
                    "if(b){try{b.focus();}catch(e){} try{b.click();}catch(e){}} return !!b;})();"
                )
            except Exception:
                pass

        delay = int(getattr(self, "_ATTACH_REACTIVATE_MS", 120))

        def _after_reactivate():
            _set_pending()
            def _after_reprobe(raw):
                import json
                info = {}
                try:
                    if isinstance(raw, str):
                        info = json.loads(raw)
                    elif isinstance(raw, dict):
                        info = raw
                except Exception:
                    info = {}
                self._media_log(
                    "ATTACH",
                    f"after_reactivate composer_present={info.get('composer_present')} "
                    f"file_input_present={info.get('file_input_present')} "
                    f"media_button_present={info.get('media_button_present')} "
                    f"active_is_composer={info.get('active_is_composer')} "
                    f"box_key={(info.get('box_info') or {}).get('key')} "
                    f"input_key={(info.get('file_input_info') or {}).get('key')} "
                    f"btn_key={(info.get('media_button_rect') or {}).get('key')}",
                )
                if prior_info:
                    old_in = (prior_info.get("file_input_info") or {}).get("key")
                    new_in = (info.get("file_input_info") or {}).get("key")
                    old_btn = (prior_info.get("media_button_rect") or {}).get("key")
                    new_btn = (info.get("media_button_rect") or {}).get("key")
                    if old_in or new_in:
                        self._media_log(
                            "ATTACH",
                            f"file_input_node_changed={old_in != new_in} before={old_in} after={new_in}",
                        )
                    if old_btn or new_btn:
                        self._media_log(
                            "ATTACH",
                            f"media_button_node_changed={old_btn != new_btn} before={old_btn} after={new_btn}",
                        )
                self._open_file_chooser_for_attach(wv, page, paths, attempt, info)

            try:
                page.runJavaScript(self._COMPOSER_PROBE_JS, _after_reprobe)
            except Exception as exc:
                self._media_log("ATTACH", f"reprobe_fail={exc!r}")
                self._open_file_chooser_for_attach(wv, page, paths, attempt, prior_info or {})

        QTimer.singleShot(delay, _after_reactivate)

    def _set_attach_auto_mode(self, page, enabled: bool) -> None:
        from src.browser.webview import MayotterPage

        try:
            MayotterPage._attach_auto_mode_global = bool(enabled)
        except Exception:
            pass
        if page is not None:
            try:
                page._attach_auto_mode = bool(enabled)
            except Exception:
                pass
        if not enabled:
            try:
                target = getattr(self, "_recording_target", None)
                if target and target.get("page") is not None:
                    target["page"]._attach_auto_mode = False
            except Exception:
                pass
            try:
                MayotterPage.pending_attach_files = None
            except Exception:
                pass

    _COMPOSER_MEDIA_PROBE_JS = r"""
    (function() {
      function visible(el) {
        if (!el || !el.isConnected) return false;
        try {
          var st = window.getComputedStyle(el);
          if (!st || st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0')
            return false;
          var r = el.getBoundingClientRect();
          return r.width > 2 && r.height > 2;
        } catch (e) { return false; }
      }
      function composerRoots() {
        var roots = [];
        var boxes = document.querySelectorAll(
          '[data-testid="tweetTextarea_0"], div[role="textbox"][data-testid^="tweetTextarea"]'
        );
        for (var i = 0; i < boxes.length; i++) {
          var b = boxes[i];
          var root = b.closest('[data-testid="toolBar"]') ||
                     b.closest('div[role="dialog"]') ||
                     b.closest('form') ||
                     b.parentElement;
          // Climb a few levels to include attachment area near the textbox
          var scope = b;
          for (var up = 0; up < 8 && scope; up++) {
            scope = scope.parentElement;
          }
          if (scope) roots.push(scope);
          else if (root) roots.push(root);
        }
        // de-dupe
        var out = [];
        for (var j = 0; j < roots.length; j++) {
          if (out.indexOf(roots[j]) < 0) out.push(roots[j]);
        }
        return out.length ? out : [document.body];
      }
      function collect(scope) {
        var remove = 0, attach = 0, preview = 0;
        var keys = [];
        // Remove controls for media (strong signal when NEW)
        var rms = scope.querySelectorAll(
          '[aria-label*="Remove" i], [aria-label*="削除"], [data-testid="removeButton"],' +
          'button[aria-label*="Remove media" i]'
        );
        for (var i = 0; i < rms.length; i++) {
          if (visible(rms[i])) {
            remove++;
            keys.push('rm:' + (rms[i].getAttribute('aria-label') || '').slice(0, 40));
          }
        }
        var atts = scope.querySelectorAll(
          '[data-testid="attachments"], [data-testid="media-attachment"],' +
          '[data-testid="attachmentsMedia"]'
        );
        for (var a = 0; a < atts.length; a++) {
          if (visible(atts[a]) || (atts[a].isConnected && atts[a].querySelector('img,video'))) {
            attach++;
            keys.push('att:' + (atts[a].getAttribute('data-testid') || 'attachments'));
          }
        }
        var pvs = scope.querySelectorAll(
          '[data-testid="attachments"] img, [data-testid="attachments"] video,' +
          '[data-testid="media-attachment"] img, [data-testid="media-attachment"] video'
        );
        for (var p = 0; p < pvs.length; p++) {
          if (visible(pvs[p])) {
            preview++;
            keys.push('pv:' + (pvs[p].tagName || ''));
          }
        }
        return {remove: remove, attach: attach, preview: preview, keys: keys};
      }
      var roots = composerRoots();
      var total = {remove: 0, attach: 0, preview: 0, keys: []};
      for (var r = 0; r < roots.length; r++) {
        var c = collect(roots[r]);
        total.remove += c.remove;
        total.attach += c.attach;
        total.preview += c.preview;
        for (var k = 0; k < c.keys.length; k++) total.keys.push(c.keys[k]);
      }
      var fileInfo = [];
      var inputs = document.querySelectorAll(
        'input[data-testid="fileInput"], input[type="file"]'
      );
      for (var i = 0; i < inputs.length && i < 4; i++) {
        try {
          var f = inputs[i].files;
          var n = f ? f.length : 0;
          var names = [];
          for (var j = 0; j < n && j < 3; j++) {
            names.push((f[j].name || '') + ':' + (f[j].size || 0));
          }
          fileInfo.push({len: n, names: names});
        } catch (e) { fileInfo.push({len: -1}); }
      }
      // NOTE: role=progressbar is intentionally NOT a success signal
      // (device log: progress:1 alone caused false I_success).
      return JSON.stringify({
        composer_root_found: roots.length > 0 && roots[0] !== document.body,
        remove: total.remove,
        attach: total.attach,
        preview: total.preview,
        keys: total.keys,
        file_inputs: fileInfo
      });
    })();
    """

    def _snapshot_composer_media(self, page, *, on_ready) -> None:
        def _after(raw):
            import json
            info = {}
            try:
                if isinstance(raw, str):
                    info = json.loads(raw)
                elif isinstance(raw, dict):
                    info = raw
            except Exception:
                info = {}
            self._media_log(
                "ATTACH",
                f"H_snapshot_before remove={info.get('remove')} attach={info.get('attach')} "
                f"preview={info.get('preview')} keys={info.get('keys')!r} "
                f"file_inputs={info.get('file_inputs')!r}",
            )
            on_ready(info)

        try:
            page.runJavaScript(self._COMPOSER_MEDIA_PROBE_JS, _after)
        except Exception as exc:
            self._media_log("ATTACH", f"H_snapshot_before_error={exc!r}")
            on_ready({})

    def _media_snapshot_score(self, snap: dict | None) -> tuple[int, int, int, int]:
        if not snap:
            return (0, 0, 0, 0)
        try:
            remove = int(snap.get("remove") or 0)
            attach = int(snap.get("attach") or 0)
            preview = int(snap.get("preview") or 0)
        except Exception:
            remove = attach = preview = 0
        files = 0
        try:
            for fi in snap.get("file_inputs") or []:
                files += max(0, int(fi.get("len") or 0))
        except Exception:
            files = 0
        return remove, attach, preview, files

    def _media_evidence_from_diff(self, before: dict | None, after: dict | None) -> dict:
        br, ba, bp, bf = self._media_snapshot_score(before)
        ar, aa, ap, af = self._media_snapshot_score(after)
        d_remove = ar - br
        d_attach = aa - ba
        d_preview = ap - bp
        d_files = af - bf
        strong = d_remove > 0 or d_attach > 0 or d_preview > 0
        aux_files = d_files > 0
        confirmed = strong or (aux_files and (aa > 0 or ap > 0 or ar > 0))
        evidence = {
            "before": {"remove": br, "attach": ba, "preview": bp, "files": bf},
            "after": {"remove": ar, "attach": aa, "preview": ap, "files": af},
            "delta": {
                "remove": d_remove,
                "attach": d_attach,
                "preview": d_preview,
                "files": d_files,
            },
            "strong": strong,
            "aux_files": aux_files,
            "confirmed": confirmed,
            "after_keys": list((after or {}).get("keys") or []),
        }
        return evidence

    def _verify_x_composer_media(
        self, page, *, on_result, before_snapshot=None, delays_ms=None
    ) -> None:
        delays = list(delays_ms or (150, 300, 500, 900, 1500))
        before = before_snapshot if before_snapshot is not None else {}
        self._media_log(
            "ATTACH",
            f"stage=H_wait_composer_media before={self._media_snapshot_score(before)}",
        )

        def _tick(idx: int = 0) -> None:
            def _after(raw, _idx=idx):
                import json
                after = {}
                try:
                    if isinstance(raw, str):
                        after = json.loads(raw)
                    elif isinstance(raw, dict):
                        after = raw
                except Exception:
                    after = {}
                evidence = self._media_evidence_from_diff(before, after)
                self._media_log(
                    "ATTACH",
                    f"stage=H_composer_media_detected={evidence['confirmed']} "
                    f"evidence={evidence!r} poll={_idx}",
                )
                if evidence["confirmed"]:
                    on_result(True, evidence)
                    return
                if _idx + 1 < len(delays):
                    QTimer.singleShot(delays[_idx + 1], lambda: _tick(_idx + 1))
                else:
                    on_result(False, evidence)

            try:
                page.runJavaScript(self._COMPOSER_MEDIA_PROBE_JS, _after)
            except Exception as exc:
                self._media_log("ATTACH", f"stage=H_probe_error={exc!r}")
                on_result(False, {"error": str(exc)})

        QTimer.singleShot(delays[0] if delays else 150, lambda: _tick(0))

    def _report_attach_success(self, page=None) -> None:
        self._recording_target = None
        self._set_attach_auto_mode(page, False)
        try:
            if page is not None:
                page.pending_attach_files = None
            from src.browser.webview import MayotterPage
            MayotterPage.pending_attach_files = None
        except Exception:
            pass
        self._media_log("ATTACH", "stage=I_success attach_success=True (composer media detected)")
        try:
            self._attach_timing_log("T10_media_confirmed")
        except Exception:
            pass
        self._on_media_status("音声を添付しました")

    def _report_attach_failure(self, page=None, reason: str = "media_not_detected") -> None:
        self._recording_target = None
        self._set_attach_auto_mode(page, False)
        try:
            if page is not None:
                page.pending_attach_files = None
            from src.browser.webview import MayotterPage
            MayotterPage.pending_attach_files = None
        except Exception:
            pass
        self._media_log("ATTACH", f"failed stage=H_composer_media reason={reason} attach_success=False")
        try:
            self._attach_timing_log("T_fail", reason=reason)
        except Exception:
            pass
        self._on_media_status("音声の自動添付に失敗しました")

    def _open_file_chooser_for_attach(
        self, wv, page, paths: list[str], attempt: int, info: dict
    ) -> None:
        from src.browser.webview import MayotterPage

        def _set_pending() -> None:
            page.pending_attach_files = list(paths)
            page._attach_choose_served = False
            page._attach_auto_mode = True
            MayotterPage.pending_attach_files = list(paths)
            MayotterPage._attach_auto_mode_global = True
            self._media_log(
                "ATTACH",
                f"stage=D_pending pending_set=True pending_count={len(paths)}",
            )

        def _served() -> bool:
            try:
                return bool(getattr(page, "_attach_choose_served", False))
            except Exception:
                return False

        def _done() -> None:
            def _on_v(ok, info):
                if ok:
                    self._report_attach_success(page)
                else:
                    self._report_attach_failure(page, "media_not_detected_after_chooser")
            self._verify_x_composer_media(page, on_result=_on_v)

        def _fail(stage: str, reason: str) -> None:
            self._recording_target = None
            self._set_attach_auto_mode(page, False)
            try:
                page.pending_attach_files = None
                MayotterPage.pending_attach_files = None
            except Exception:
                pass
            self._media_log(
                "ATTACH",
                f"failed stage={stage} reason={reason} attach_success=False",
            )
            self._on_media_status("音声の自動添付に失敗しました")

        def _retry(reason: str) -> None:
            max_a = int(getattr(self, "_ATTACH_MAX_ATTEMPTS", 4))
            delay = int(getattr(self, "_ATTACH_RETRY_MS", 350))
            if attempt + 1 < max_a:
                self._media_log("ATTACH", f"retry reason={reason} next={attempt + 1}/{max_a}")
                QTimer.singleShot(
                    delay,
                    lambda: self._attach_files_to_composer(
                        paths, use_recording_target=True, attempt=attempt + 1
                    ),
                )
                return
            _fail("E_chooser", reason)

        if not info.get("composer_present") and not info.get("file_input_present"):
            self._media_log(
                "ATTACH",
                f"composer_present={info.get('composer_present')} "
                f"file_input_present={info.get('file_input_present')} "
                f"media_button_present={info.get('media_button_present')}",
            )
            _retry("no_composer")
            return

        self._media_log(
            "ATTACH",
            f"composer_present={info.get('composer_present')} "
            f"file_input_present={info.get('file_input_present')} "
            f"media_button_present={info.get('media_button_present')}",
        )

        def _after_before_snap(before: dict) -> None:
            _set_pending()
            self._set_attach_auto_mode(page, True)

            self._media_log(
                "ATTACH",
                "stage=E_drop skipped=True reason=device_proven_nonfunctional",
            )

            _run_synthetic(before)

        def _run_synthetic(before: dict) -> None:
            btn = info.get("media_button_rect") or {}
            inp = info.get("file_input_info") or {}
            targets = []
            if btn.get("w", 0) > 2 and btn.get("h", 0) > 2:
                targets.append(("media_button", btn.get("x"), btn.get("y")))
            if inp.get("x") is not None:
                targets.append(("file_input", inp.get("x"), inp.get("y")))

            try:
                wv.setFocus(Qt.FocusReason.MouseFocusReason)
                wv.activateWindow()
            except Exception:
                pass

            self._media_log("ATTACH", "stage=E_chooser synthetic_click_begin")
            for name, cx, cy in targets:
                if cx is None or cy is None:
                    continue
                try:
                    self._synthesize_webview_click(wv, float(cx), float(cy))
                    self._media_log("ATTACH", f"synthetic_click_result=ok target={name}")
                except Exception as exc:
                    self._media_log(
                        "ATTACH", f"synthetic_click_result=fail target={name} {exc!r}"
                    )
                _set_pending()
                if _served():
                    self._media_log("ATTACH", "stage=F_chooseFiles_called (via synthetic)")
                    def _on_v(ok, ev):
                        if ok:
                            self._report_attach_success(page)
                        else:
                            self._report_attach_failure(
                                page, "media_not_detected_after_chooser"
                            )
                    self._verify_x_composer_media(
                        page, on_result=_on_v, before_snapshot=before
                    )
                    return

            check_ms = int(getattr(self, "_ATTACH_CHECK_MS", 500))

            def _check(n=0):
                if _served():
                    self._media_log("ATTACH", "stage=F_chooseFiles_called stage=G_returned")
                    def _on_v(ok, ev):
                        if ok:
                            self._report_attach_success(page)
                        else:
                            self._report_attach_failure(
                                page, "media_not_detected_after_chooser"
                            )
                    self._verify_x_composer_media(
                        page, on_result=_on_v, before_snapshot=before
                    )
                    return
                self._media_log(
                    "ATTACH",
                    f"chooseFiles_check n={n} served=False "
                    f"pending_inst={bool(getattr(page, 'pending_attach_files', None))} "
                    f"pending_class={bool(getattr(MayotterPage, 'pending_attach_files', None))}",
                )
                if n < 1 and targets:
                    _set_pending()
                    name, cx, cy = targets[0]
                    try:
                        self._synthesize_webview_click(wv, float(cx), float(cy))
                    except Exception:
                        pass
                    QTimer.singleShot(check_ms, lambda: _check(n + 1))
                    return
                _retry("chooseFiles_not_called_no_user_activation")

            QTimer.singleShot(check_ms, lambda: _check(0))

        self._snapshot_composer_media(page, on_ready=_after_before_snap)
        return

    def _synthesize_webview_click(self, webview, css_x: float, css_y: float) -> None:
        from PySide6.QtCore import QPoint, QPointF, QEvent
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        try:
            self._attach_timing_log("T6_synthetic_click", css_x=css_x, css_y=css_y)
        except Exception:
            pass
        local = QPoint(int(round(css_x)), int(round(css_y)))
        try:
            r = webview.rect()
            local.setX(max(2, min(r.width() - 2, local.x())))
            local.setY(max(2, min(r.height() - 2, local.y())))
        except Exception:
            pass
        try:
            webview.setFocus()
            webview.activateWindow()
        except Exception:
            pass
        global_pos = webview.mapToGlobal(local)
        try:
            webview._suppress_user_gesture_mark = True
        except Exception:
            pass
        try:
            for etype in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
            ):
                ev = QMouseEvent(
                    etype,
                    QPointF(local),
                    QPointF(global_pos),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton if etype == QEvent.Type.MouseButtonPress
                    else Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                QApplication.sendEvent(webview, ev)
                QApplication.processEvents()
        finally:
            try:
                webview._suppress_user_gesture_mark = False
            except Exception:
                pass

    def _set_disable_x_keyboard_shortcuts(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._disable_x_keyboard_shortcuts = enabled
        try:
            from src.browser.webview import set_disable_x_keyboard_shortcuts
            set_disable_x_keyboard_shortcuts(enabled)
        except Exception:
            pass
        try:
            if self._settings_manager is not None and hasattr(
                self._settings_manager, "save_disable_x_keyboard_shortcuts"
            ):
                self._settings_manager.save_disable_x_keyboard_shortcuts(enabled)
        except Exception:
            pass
        try:
            self._apply_x_shortcut_policy_all_views()
        except Exception:
            pass

    def _apply_x_shortcut_policy_all_views(self) -> None:
        try:
            from src.browser.webview import (
                get_disable_x_keyboard_shortcuts,
                is_x_twitter_url,
                x_shortcut_script,
            )
        except Exception:
            return
        enabled = get_disable_x_keyboard_shortcuts()
        script = x_shortcut_script(enabled)
        for col in self._iter_all_columns_for_shutdown():
            views = []
            try:
                if hasattr(col, "webviews"):
                    views = list(col.webviews() or [])
            except Exception:
                views = []
            if not views:
                views = list(getattr(col, "_tabs", []) or [])
            for wv in views:
                try:
                    url = ""
                    try:
                        url = wv.url().toString() if wv.url() else ""
                    except Exception:
                        url = ""
                    if not is_x_twitter_url(url):
                        continue
                    page = wv.page() if hasattr(wv, "page") else None
                    if page is None:
                        continue
                    page.runJavaScript(script)
                except Exception:
                    pass

    def _iter_all_columns_for_shutdown(self):
        seen = set()
        packs_list = []
        for attr in ("_twitter_packs", "_grok_packs"):
            packs = getattr(self, attr, None) or {}
            if isinstance(packs, dict):
                packs_list.append(packs)
        for packs in packs_list:
            for key in ("normal", "lr", "tb"):
                for col in list(packs.get(key) or []):
                    cid = id(col)
                    if cid in seen:
                        continue
                    seen.add(cid)
                    yield col
        if not seen:
            for col in list(getattr(self, "_columns", []) or []):
                yield col

    def open_update_check(self) -> None:
        if getattr(self, "_update_flow_busy", False):
            return
        try:
            prev = getattr(self, "_update_flow_dialog", None)
            if prev is not None:
                try:
                    prev.hide()
                    prev.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass

        repo = ""
        try:
            if self._settings_manager is not None and hasattr(
                self._settings_manager, "get_github_repo"
            ):
                repo = self._settings_manager.get_github_repo()
        except Exception:
            pass

        try:
            from src.ui.update_dialog import UpdateDialog

            dlg = UpdateDialog(self, github_repo=repo, on_apply_success=self.close)
            self._update_flow_dialog = dlg

            def _set_update_busy(busy: bool) -> None:
                self._update_flow_busy = bool(busy)

            def _clear_update_dialog() -> None:
                if getattr(self, "_update_flow_dialog", None) is dlg:
                    self._update_flow_dialog = None

            dlg.busyChanged.connect(_set_update_busy)
            dlg.finishedClosing.connect(_clear_update_dialog)
            dlg.destroyed.connect(lambda *_: _clear_update_dialog())
            dlg.show_centered()
        except Exception:
            self._update_flow_busy = False

    def _shutdown_runtime(self) -> None:
        import time as _time

        def _ms() -> int:
            return int(_time.monotonic() * 1000)

        FLUSH_MAX_MS = 400

        self._shutdown_mono0_ms = _ms()
        self._shutdown_trace("application_shutdown_start")

        t0 = _ms()
        if self._edge_animator is not None:
            try:
                self._edge_animator.stop()
            except Exception:
                pass
        if self._edge_detector is not None:
            try:
                self._edge_detector.stop()
            except Exception:
                pass
        self._shutdown_trace("phase_edge_stop_done", elapsed_ms=_ms() - t0)

        columns = list(self._iter_all_columns_for_shutdown())
        all_views = []
        for col in columns:
            try:
                views = []
                if hasattr(col, "webviews"):
                    views = list(col.webviews() or [])
                if not views:
                    views = list(getattr(col, "_tabs", []) or [])
                all_views.extend(views)
            except Exception:
                pass
        self._shutdown_trace(
            "webview_cleanup_start",
            columns=len(columns),
            views=len(all_views),
        )

        t0 = _ms()
        self._shutdown_trace("phase_media_pause_start")
        _MEDIA_PAUSE_JS = (
            "(function(){try{"
            "var ns=document.querySelectorAll('video,audio');"
            "for(var i=0;i<ns.length;i++){var m=ns[i];try{m.pause();"
            "m.removeAttribute('src');m.load();}catch(e){}}"
            "}catch(e){}})();"
        )
        for wv in all_views:
            try:
                page = wv.page() if hasattr(wv, "page") else None
                if page is not None and hasattr(page, "runJavaScript"):
                    page.runJavaScript(_MEDIA_PAUSE_JS)
            except Exception:
                pass
        try:
            QApplication.processEvents()
        except Exception:
            pass
        self._shutdown_trace("phase_media_pause_done", elapsed_ms=_ms() - t0)

        t0 = _ms()
        self._shutdown_trace("phase_stop_start")
        for wv in all_views:
            try:
                page = wv.page() if hasattr(wv, "page") else None
                if page is not None and hasattr(page, "triggerAction"):
                    from PySide6.QtWebEngineCore import QWebEnginePage
                    page.triggerAction(QWebEnginePage.WebAction.Stop)
            except Exception:
                pass
        self._shutdown_trace("phase_stop_done", elapsed_ms=_ms() - t0)

        t0 = _ms()
        self._shutdown_trace("phase_processEvents_after_stop_start")
        try:
            QApplication.processEvents()
        except Exception:
            pass
        self._shutdown_trace(
            "phase_processEvents_after_stop_done",
            elapsed_ms=_ms() - t0,
        )

        t0 = _ms()
        self._shutdown_trace("phase_setPage_None_start")
        for wv in all_views:
            try:
                wv.setPage(None)
            except Exception:
                pass
        self._shutdown_trace("phase_setPage_None_done", elapsed_ms=_ms() - t0)

        t0 = _ms()
        self._shutdown_trace("phase_deleteLater_start")
        for wv in all_views:
            try:
                wv.deleteLater()
            except Exception:
                pass
        self._shutdown_trace("phase_deleteLater_done", elapsed_ms=_ms() - t0)

        t0 = _ms()
        self._shutdown_trace("phase_eventloop_flush_start", max_ms=FLUSH_MAX_MS)
        wait_mode = "none"
        try:
            from PySide6.QtCore import QEventLoop, QTimer
            QApplication.processEvents()
            quiet = 0
            deadline = t0 + FLUSH_MAX_MS
            while _ms() < deadline:
                t1 = _ms()
                QApplication.processEvents()
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
            QApplication.processEvents()
        except Exception:
            wait_mode = "error"
            try:
                QApplication.processEvents()
            except Exception:
                pass
        flush_elapsed = _ms() - t0
        self._shutdown_trace(
            "phase_eventloop_flush_done",
            elapsed_ms=flush_elapsed,
            wait_mode=wait_mode,
            max_ms=FLUSH_MAX_MS,
        )
        self._shutdown_trace(
            "phase_eventloop_1200_done",
            elapsed_ms=flush_elapsed,
            wait_mode=wait_mode,
            note="adaptive_flush",
        )
        self._shutdown_trace("webview_cleanup_done")

        t0 = _ms()
        self._shutdown_trace("phase_prepare_shutdown_start")
        try:
            pm = getattr(self, "_profile_manager", None)
            if pm is not None and hasattr(pm, "prepare_shutdown"):
                pm.prepare_shutdown(timeout_ms=200)
        except Exception as exc:
            self._shutdown_trace("profile_cleanup_fail", err=repr(exc))
        self._shutdown_trace("phase_prepare_shutdown_done", elapsed_ms=_ms() - t0)

        self._shutdown_trace(
            "application_shutdown_done",
            total_elapsed_ms=_ms() - int(getattr(self, "_shutdown_mono0_ms", _ms())),
        )

    def _add_column(
        self,
        account,
        column_config: Column | None = None,
        defer_load_ms: int | None = None,
        *,
        service_grok: bool | None = None,
    ) -> None:
        if column_config is None:
            from src.core.models import Column as ColumnModel
            column_config = ColumnModel(
                source_account_id=account.account_id,
                source_url=account.initial_url,
                title=account.display_name or "Home",
                width=AccountColumn.DEFAULT_WIDTH,
            )

        self._account_add_trace(
            "add_column_enter",
            aid=account.account_id,
            defer=defer_load_ms,
            service_grok=service_grok,
        )
        self._account_add_trace("profile_open_enter", aid=account.account_id)
        is_new = bool(getattr(account, "_mayotter_create_profile", False))
        if not is_new:
            reg_tmp = self._known_accounts.get(account.account_id, {}) or {}
            is_new = bool(reg_tmp.get("_create_profile"))
        profile = self._open_profile_for_account(
            account.account_id,
            legacy_path=self._legacy_profile_path_for(
                account.account_id, getattr(account, "profile_path", "") or ""
            ),
            create=is_new,
        )
        if profile is None:
            self._account_add_trace(
                "profile_missing_abort_add_column",
                aid=account.account_id,
            )
            try:
                self._on_media_status(
                    f"Profileデータが見つかりません（{account.display_name or account.account_id[:8]}）"
                )
            except Exception:
                pass
            return
        if account.account_id in self._known_accounts:
            self._known_accounts[account.account_id].pop("_create_profile", None)
        try:
            storage = profile.persistentStoragePath()
        except Exception:
            storage = ""
        self._account_add_trace(
            "profile_ready",
            aid=account.account_id,
            storage=storage,
            profile_id=id(profile),
        )
        self._account_add_trace("webview_ctor_enter", aid=account.account_id)
        webview = XWebView(profile)
        self._account_add_trace("webview_ready", aid=account.account_id, view_id=id(webview))
        load_url = (column_config.source_url or "").strip()
        skip_initial = bool(getattr(column_config, "_skip_initial_load", False))
        pending_tab0 = (getattr(column_config, "_pending_tab0_url", None) or "").strip()
        if column_config.column_type in ("profile", "lists") and not load_url:
            pass
        elif skip_initial:
            if pending_tab0 or load_url:
                webview._pending_restore_url = pending_tab0 or load_url
        elif load_url:
            webview._pending_restore_url = load_url
            if defer_load_ms is not None and int(defer_load_ms) > 0:
                webview._pending_restore_delay_ms = int(defer_load_ms)
        self._account_add_trace(
            "nav_scheduled",
            aid=account.account_id,
            pending=getattr(webview, "_pending_restore_url", None),
            delay=getattr(webview, "_pending_restore_delay_ms", 0),
        )

        self._account_add_trace("account_column_ctor_enter", aid=account.account_id)
        column = AccountColumn(
            account_id=account.account_id,
            display_name=account.display_name,
            webview=webview,
            initial_url=column_config.source_url,
            width=column_config.width,
            column_id=column_config.column_id,
            column_type=column_config.column_type,
            title=column_config.title,
        )
        self._account_add_trace(
            "account_column_ctor_done",
            aid=account.account_id,
            cid=column.get_column_id(),
        )
        column.closed.connect(lambda cid=column.get_column_id(): self._remove_column(cid))
        column.activated.connect(lambda c=column: self._on_column_activated(c))
        column.url_edit_requested.connect(lambda c=column: self._open_url_overlay_for(c))
        column.new_tab_requested.connect(lambda url, c=column: self._on_new_tab_requested(url, c))
        column.tabs_changed.connect(self._save_columns)
        column.resized.connect(lambda w: self._save_column_widths())
        column.enabled_changed.connect(lambda e: self._save_accounts())
        column.boundary_dragged.connect(lambda delta, c=column: self._on_boundary_dragged(c, delta))
        column.boundary_drag_finished.connect(self._on_boundary_drag_finished)
        column.stow_right_requested.connect(self._stow_columns_right_of)
        column.stow_self_requested.connect(self._stow_single_column)
        column.restore_self_requested.connect(self._restore_single_column)
        column.reset_widths_requested.connect(self._reset_all_column_widths)
        column.reorder_requested.connect(
            lambda x, c=column: self._commit_column_reorder_at(c, x)
        )
        if hasattr(column, "reorder_drag_moved"):
            column.reorder_drag_moved.connect(
                lambda x, c=column: self._on_column_reorder_drag_moved(c, x)
            )
        if hasattr(column, "reorder_drag_finished"):
            column.reorder_drag_finished.connect(self._on_column_reorder_drag_finished)

        if hasattr(webview, "download_progress"):
            webview.download_progress.connect(self._on_download_progress)

        reg0 = self._known_accounts.get(account.account_id, {})
        if service_grok is not None:
            is_grok = bool(service_grok)
        else:
            is_grok = bool(reg0.get("grok"))
            if not is_grok:
                seed_url = reg0.get("initial_url") or account.initial_url or ""
                is_grok = ("grok.com" in seed_url) and ("x.com" not in seed_url)
        if account.account_id not in self._known_accounts:
            self._known_accounts[account.account_id] = {
                "account_id": account.account_id,
                "display_name": account.display_name,
                "initial_url": reg0.get("initial_url") or account.initial_url,
                "grok": is_grok,
            }
        else:
            entry = self._known_accounts[account.account_id]
            if service_grok is not None:
                entry["grok"] = bool(service_grok)

        self._column_configs.append(column_config)

        if is_grok != self._grok_mode and not getattr(self, "_restoring_session", False):
            pack = self._grok_packs if is_grok else self._twitter_packs
            pack["normal"].append(column)
            self._account_add_trace(
                "column_parked_other_service",
                aid=account.account_id,
                is_grok=is_grok,
            )
            return

        if getattr(self, "_restoring_session", False):
            key = "normal"
        else:
            key = self._bound_layout_mode_key()
        packs = self._service_packs()
        packs[key].append(column)
        self._columns = packs[key]
        # 収納中カラム群ではなく、開いている側へ追加する
        try:
            stowed = getattr(self, "_stowed_columns", None) or []
            if column in stowed:
                stowed = [c for c in stowed if c is not column]
                self._stowed_columns = stowed
            mode_key = key
            if hasattr(self, "_mode_stowed_columns") and self._mode_stowed_columns is not None:
                ms = list(self._mode_stowed_columns.get(mode_key) or [])
                if column in ms:
                    self._mode_stowed_columns[mode_key] = [c for c in ms if c is not column]
        except Exception:
            pass
        # 収納カラムの後ろではなく、表示中の末尾に並べる
        try:
            stowed_set = set(getattr(self, "_stowed_columns", None) or [])
            if stowed_set and column in self._columns:
                self._columns.remove(column)
                insert_at = 0
                for i, c in enumerate(self._columns):
                    if c not in stowed_set:
                        insert_at = i + 1
                self._columns.insert(insert_at, column)
        except Exception:
            pass
        self._scroll_layout.addWidget(column)
        column.show()
        self._account_add_trace("column_shown", aid=account.account_id, cid=column.get_column_id())
        if len(self._columns) == 1:
            self._set_active_column(column)
        else:
            self._set_active_column(column)
        self._sync_count_from_active_list()
        if getattr(self, "_restoring_session", False):
            try:
                w = int(getattr(column_config, "width", 0) or 0)
                if w >= AccountColumn.MIN_WIDTH:
                    column.set_width(w, emit_signal=False)
            except Exception:
                pass
            self._update_boundary_visibility()
        else:
            self._fit_after_column_add(column)
            try:
                self._column_add_settling = True
                self._fit_columns()
            except Exception:
                pass
            finally:
                self._column_add_settling = False
            self._update_boundary_visibility()
            if self._edge_dock_enabled and self._edge_dock_revealed:
                try:
                    column.show()
                except Exception:
                    pass
        try:
            delay = int(getattr(webview, "_pending_restore_delay_ms", 0) or 0)
        except Exception:
            delay = 0
        if getattr(webview, "_pending_restore_url", None):
            self._account_add_trace("materialize_nav", aid=account.account_id, delay=delay)
            if delay > 0:
                QTimer.singleShot(delay, self._materialize_visible_pending_loads)
            else:
                QTimer.singleShot(0, self._materialize_visible_pending_loads)
        self._account_add_trace("add_column_done", aid=account.account_id)

    def _paint_empty_logo_in_window(self, p: QPainter) -> None:
        """Dock の展開/収納中は、本体が背景を塗る同じフレームでロゴも描く。

        子部品のロゴは root の表示を待つので、最初の1フレームだけ背景だけが見えてしまう。
        """
        logo = getattr(self, "_empty_logo", None)
        scroll = getattr(self, "_scroll", None)
        if logo is None or scroll is None or not logo._want:
            return
        try:
            vp = scroll.viewport()
            tl = vp.mapTo(self, QPoint(0, 0))
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            logo.draw(p, QRect(tl, vp.size()), 1.0)
            p.restore()
        except Exception:
            pass

    def _update_empty_state(self) -> None:
        """カラムが無いときの中央ロゴを、表示領域に合わせて出し入れする。

        「見えているカラムが無い」ではなく「現在のモードにカラムが存在しない」で判定する。
        Dock の収納/展開や切替の途中はカラムが一時的に隠れるだけで、ロゴは動かさない。
        """
        # 通常カラムが残っていなければ背景。個別収納・一括収納だけが残る場合も含む
        stowed_bulk = set(getattr(self, "_stowed_columns", None) or [])
        empty = not any(
            not getattr(c, "is_individually_stowed", lambda: False)() and c not in stowed_bulk
            for c in self._columns
        )
        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        logo = getattr(self, "_empty_logo", None)
        if logo is None:
            logo = self._empty_logo = _EmptyStateLogo(scroll.viewport())
        vp = scroll.viewport()
        if logo.parentWidget() is not vp:
            logo.setParent(vp)
        if logo.geometry() != vp.rect():
            logo.setGeometry(vp.rect())
        # 個別収納帯（左右の端に並ぶ）を除いた背景部分の中央へ置く
        left, right = 0, vp.width()
        mid = vp.width() / 2.0
        for c in self._columns:
            try:
                if not getattr(c, "is_individually_stowed", lambda: False)() or not c.isVisible():
                    continue
                r = QRect(c.mapTo(vp, QPoint(0, 0)), c.size())
                if r.center().x() < mid:
                    left = max(left, r.right() + 1)
                else:
                    right = min(right, r.left())
            except Exception:
                pass
        logo.set_insets(left, max(0, vp.width() - right))
        busy = bool(
            getattr(self, "_edge_dock_animating", False)
            or getattr(self, "_edge_dock_switching", False)
        )
        logo.set_visible_animated(bool(empty), instant=busy)

    def _remove_column(self, column_id_or_account_id: str) -> None:
        target_col = None
        target_idx = -1

        for i, col in enumerate(self._columns):
            if col.get_column_id() == column_id_or_account_id:
                target_col = col
                target_idx = i
                break

        if target_col is None:
            for i, col in enumerate(self._columns):
                if col.get_account_id() == column_id_or_account_id:
                    target_col = col
                    target_idx = i
                    break
        if target_col is None:
            return

        try:
            cid = str(target_col.get_column_id() or "")
        except Exception:
            cid = ""
        key = self._bound_layout_mode_key()
        host = getattr(self, "_scroll_content", None)
        if host is not None:
            host.setUpdatesEnabled(False)
        try:
            if self._active_column is target_col:
                self._active_column = None
                self._clear_strip()

            try:
                target_col.hide()
            except Exception:
                pass
            self._scroll_layout.removeWidget(target_col)
            self._columns.pop(target_idx)

            for packs in (self._twitter_packs, self._grok_packs):
                for mode, lst in packs.items():
                    if lst is self._columns:
                        continue
                    if target_col in lst:
                        lst.remove(target_col)

            self._stowed_columns = [
                c for c in list(getattr(self, "_stowed_columns", None) or [])
                if c is not target_col
            ]
            for mode in ("normal", "lr", "tb"):
                if hasattr(self, "_mode_stowed_columns"):
                    self._mode_stowed_columns[mode] = [
                        c for c in list(self._mode_stowed_columns.get(mode) or [])
                        if c is not target_col
                    ]
            if cid and hasattr(self, "_mode_stow_saved_widths"):
                self._mode_stow_saved_widths.setdefault(key, {}).pop(cid, None)
            if cid and hasattr(self, "_mode_preferred_widths"):
                self._mode_preferred_widths.setdefault(key, {}).pop(cid, None)
            if cid:
                self._stow_saved_widths.pop(cid, None)
                self._preferred_widths.pop(cid, None)
                self._column_configs = [
                    conf for conf in list(getattr(self, "_column_configs", None) or [])
                    if str(getattr(conf, "column_id", "") or "") != cid
                ]
            for mode, active_col in list(getattr(self, "_mode_active", {}).items()):
                if active_col is target_col:
                    self._mode_active[mode] = None

            try:
                target_col.setParent(None)
            except Exception:
                pass
            target_col.deleteLater()

            if self._columns and self._active_column is None:
                visible = [c for c in self._columns if c.isVisible()]
                self._set_active_column(visible[0] if visible else self._columns[0])

            self._sync_count_from_active_list()
            self._fit_columns()
            self._update_boundary_visibility()
            self._update_stow_restore_rail()
        finally:
            if host is not None:
                host.setUpdatesEnabled(True)
                host.update()

        try:
            self._mode_stowed_columns[key] = list(self._stowed_columns)
            self._mode_stow_saved_widths[key] = dict(self._stow_saved_widths or {})
            self._mode_preferred_widths[key] = dict(self._preferred_widths or {})
        except Exception:
            pass
        self._save_accounts()
        self._save_columns()
        self._save_column_widths()

    def _ensure_column_insert_indicator(self) -> None:
        if getattr(self, "_column_insert_indicator", None) is not None:
            return
        from PySide6.QtWidgets import QFrame
        ind = QFrame(self._scroll_content if self._scroll_content is not None else self)
        ind.setObjectName("column_insert_indicator")
        ind.setStyleSheet(
            "QFrame#column_insert_indicator {"
            "  background: #1d9bf0; border: none; border-radius: 1px;"
            "}"
        )
        ind.setFixedWidth(3)
        ind.hide()
        self._column_insert_indicator = ind

    def _stowed_column_set(self) -> set:
        try:
            return {
                c for c in (getattr(self, "_stowed_columns", None) or [])
                if not getattr(c, "is_individually_stowed", lambda: False)()
            }
        except Exception:
            return set()

    def _capture_column_reorder_slots(self, column: AccountColumn) -> None:
        base = list(getattr(self, "_reorder_original", None) or self._columns)
        stowed = self._stowed_column_set()
        active = [c for c in base if c not in stowed or c is column]
        slots = {}
        for c in active:
            try:
                left = float(c.mapToGlobal(c.rect().topLeft()).x())
                width = float(max(1, int(c.width())))
            except Exception:
                continue
            slots[c] = (left, width)
        self._reorder_active_original = active
        self._reorder_slots = slots

    def _reorder_order_from_global_x(
        self, column: AccountColumn, global_x: float
    ) -> list:
        base = list(getattr(self, "_reorder_original", None) or self._columns)
        if column not in base:
            return base
        stowed = self._stowed_column_set()
        active = [c for c in base if c not in stowed or c is column]
        if column not in active:
            return base

        original_active = list(
            getattr(self, "_reorder_active_original", None) or active
        )
        if column not in original_active:
            original_active = active
        original_index = {c: i for i, c in enumerate(original_active)}
        moving_index = original_index.get(column, active.index(column))
        slots = dict(getattr(self, "_reorder_slots", None) or {})

        others = [c for c in active if c is not column]
        insert_at = 0
        for other in others:
            try:
                left, width = slots[other]
            except Exception:
                try:
                    left = float(other.mapToGlobal(other.rect().topLeft()).x())
                    width = float(max(1, int(other.width())))
                except Exception:
                    continue
            # ドラッグ開始時の固定座標を使う。左側の相手は右1/3境界、
            # 右側の相手は左1/3境界を越えたときだけ順序を変える。
            other_index = original_index.get(other, 0)
            fraction = 2.0 / 3.0 if other_index < moving_index else 1.0 / 3.0
            threshold = float(left) + float(width) * fraction
            if float(global_x) > threshold:
                insert_at += 1

        insert_at = max(0, min(insert_at, len(others)))
        active_order = list(others)
        active_order.insert(insert_at, column)

        full = []
        ai = 0
        for item in base:
            if item in stowed and item is not column:
                full.append(item)
            else:
                full.append(active_order[ai])
                ai += 1
        return full

    def _update_column_reorder_indicator(
        self, column: AccountColumn, order: list
    ) -> None:
        self._ensure_column_insert_indicator()
        ind = self._column_insert_indicator
        host = self._scroll_content
        if host is None:
            ind.hide()
            return

        stowed = self._stowed_column_set()
        original_active = list(
            getattr(self, "_reorder_active_original", None)
            or [c for c in self._reorder_original if c not in stowed or c is column]
        )
        target_active = [c for c in order if c not in stowed or c is column]
        if column not in original_active or column not in target_active:
            ind.hide()
            return
        old_index = original_active.index(column)
        new_index = target_active.index(column)
        if old_index == new_index:
            ind.hide()
            return

        slots = dict(getattr(self, "_reorder_slots", None) or {})
        try:
            target_slot = original_active[new_index]
            left, width = slots[target_slot]
            global_edge = left if new_index < old_index else left + width
            host_left = float(host.mapToGlobal(QPoint(0, 0)).x())
            local_x = int(round(global_edge - host_left))
            ind.setParent(host)
            ind.setGeometry(local_x - 1, 0, 3, max(1, host.height()))
            ind.show()
            ind.raise_()
        except Exception:
            ind.hide()

    def _on_column_reorder_drag_moved(self, column: AccountColumn, global_x: float) -> None:
        if column not in self._columns or column in self._stowed_column_set():
            return
        if getattr(self, "_reorder_original", None) is None:
            self._reorder_original = list(self._columns)
            self._reorder_dragging = column
            self._capture_column_reorder_slots(column)
            try:
                from PySide6.QtWidgets import QApplication
                while QApplication.overrideCursor() is not None:
                    QApplication.restoreOverrideCursor()
                self._edge_cursor_forced = False
            except Exception:
                pass

        order = self._reorder_order_from_global_x(column, float(global_x))
        self._reorder_preview_order = list(order)
        self._update_column_reorder_indicator(column, order)

    def _rebuild_column_reorder_layout(self) -> None:
        try:
            for c in self._columns:
                self._scroll_layout.removeWidget(c)
            for i, c in enumerate(self._columns):
                self._scroll_layout.insertWidget(i, c)
            self._scroll_content.updateGeometry()
            self._scroll_layout.invalidate()
            self._scroll_layout.activate()
        except Exception:
            return
        try:
            self._fit_columns()
        except Exception:
            pass
        try:
            self._update_boundary_visibility()
            self._sync_webviews_to_columns_layout_safe()
        except Exception:
            pass
        if self._scroll is not None:
            try:
                self._scroll.viewport().update()
            except Exception:
                pass

    def _clear_column_reorder_drag(self) -> None:
        ind = getattr(self, "_column_insert_indicator", None)
        if ind is not None:
            ind.hide()
        col = getattr(self, "_reorder_dragging", None)
        if col is not None:
            try:
                col.setGraphicsEffect(None)
                col._reorder_opacity_effect = None
            except Exception:
                pass
        self._reorder_original = None
        self._reorder_preview_order = None
        self._reorder_dragging = None
        self._reorder_active_original = None
        self._reorder_slots = None

    def _on_column_reorder_drag_finished(self) -> None:
        self._clear_column_reorder_drag()

    def _commit_column_reorder_at(self, column: AccountColumn, global_x) -> None:
        if column not in self._columns:
            return
        original = getattr(self, "_reorder_original", None)
        if original is None or getattr(self, "_reorder_dragging", None) is None:
            return

        order = list(getattr(self, "_reorder_preview_order", None) or original)
        if global_x is not None:
            try:
                order = self._reorder_order_from_global_x(column, float(global_x))
            except Exception:
                pass

        if order != list(self._columns):
            # pack/list の同一性を維持する。新しい list へ差し替えると normal pack の
            # alias が古い順序を保持し、保存・再bind時に位置が食い違う。
            self._columns[:] = order
            self._rebuild_column_reorder_layout()
            self._save_accounts()

        self._clear_column_reorder_drag()

    def _redistribute_equal_widths(self) -> None:
        if getattr(self, "_restoring_session", False):
            return
        visible = [c for c in self._columns if c.isVisible()]
        if not visible:
            return
        viewport_width = self._scroll.viewport().width() if self._scroll is not None else 0
        if viewport_width <= 0:
            viewport_width = max(1, self.width() - 8)
        stow_w = AccountColumn.STOWED_WIDTH
        min_w = AccountColumn.MIN_WIDTH
        # 個別収納スロットは均等割の対象外（_fit_columns と同じ扱い）
        normals = [
            c for c in visible
            if not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        stowed = [
            c for c in visible
            if getattr(c, "is_individually_stowed", lambda: False)()
        ]
        for col in stowed:
            try:
                col._current_width = stow_w
                col.setMinimumWidth(stow_w)
                col.setMaximumWidth(stow_w)
                col.setFixedWidth(stow_w)
                col.updateGeometry()
            except Exception:
                pass
        if not normals:
            self._update_boundary_visibility()
            return
        avail = max(0, viewport_width - len(stowed) * stow_w)
        n = len(normals)
        base = max(min_w, avail // n)
        widths = [base] * n
        rem = avail - sum(widths)
        i = 0
        while rem > 0 and n > 0:
            widths[i % n] += 1
            rem -= 1
            i += 1
        while rem < 0 and n > 0:
            idx = n - 1 - (i % n)
            if widths[idx] > min_w:
                widths[idx] -= 1
                rem += 1
            i += 1
            if i > n * 8:
                break
        for col, w in zip(normals, widths):
            col.set_width(w, emit_signal=False)
        # リセット後の幅を preferred に即時反映（resize→_fit_columns で古い幅が復活しないように）
        pref = dict(getattr(self, "_preferred_widths", None) or {})
        snap = dict(getattr(self, "_stow_saved_widths", None) or {})
        for col, w in zip(normals, widths):
            try:
                cid = col.get_column_id()
            except Exception:
                cid = ""
            if not cid:
                continue
            pref[cid] = int(w)
            snap.pop(cid, None)
        self._preferred_widths = pref
        self._stow_saved_widths = snap
        try:
            key = self._bound_layout_mode_key()
            if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._mode_preferred_widths[key] = dict(pref)
        except Exception:
            pass
        if self._scroll_layout is not None:
            for col in normals:
                self._scroll_layout.setStretchFactor(col, 0)
        self._update_boundary_visibility()
        self._save_column_widths()

    def _fit_after_column_add(self, new_col) -> None:
        visible = [c for c in self._columns if c.isVisible()]
        if not visible:
            return
        viewport_width = self._scroll.viewport().width() if self._scroll is not None else 0
        if viewport_width <= 0:
            viewport_width = max(1, self.width() - 8)
        min_w = AccountColumn.MIN_WIDTH
        default_w = float(AccountColumn.DEFAULT_WIDTH)
        stow_w = AccountColumn.STOWED_WIDTH
        # 現在モードの preferred を補完（Dock pack 初回など cid が空のとき他モード比を転写）
        try:
            key = self._bound_layout_mode_key()
            self._ensure_mode_preferred_weights(key, visible)
        except Exception:
            pass
        pref = dict(getattr(self, "_preferred_widths", None) or {})

        def _is_stowed(col) -> bool:
            return bool(getattr(col, "is_individually_stowed", lambda: False)())

        def _weight(col) -> float:
            try:
                cid = col.get_column_id()
            except Exception:
                cid = ""
            if cid and float(pref.get(cid) or 0) > 0:
                return max(float(min_w), float(pref[cid]))
            try:
                live = float(col.get_width() or 0)
            except Exception:
                live = 0.0
            if live >= min_w:
                return live
            return default_w

        if new_col is None or new_col not in visible:
            return

        stowed_cols = [c for c in visible if _is_stowed(c)]
        normal_cols = [c for c in visible if not _is_stowed(c)]
        stowed_sum = stow_w * len(stowed_cols)
        avail = max(0, int(viewport_width) - stowed_sum)

        if not normal_cols:
            for col in stowed_cols:
                col.set_width(stow_w, emit_signal=False)
            if self._scroll_layout is not None:
                for col in visible:
                    try:
                        self._scroll_layout.setStretchFactor(col, 0)
                    except Exception:
                        pass
            self._save_column_widths()
            return

        # 既存通常カラムのウェイト（相対比を維持）。
        # 新規は既存 weight の平均（全て同じならその共通値）。既存が無ければ DEFAULT_WIDTH。
        existing_weights: list[float] = []
        for col in normal_cols:
            if col is new_col:
                continue
            existing_weights.append(_weight(col))
        if existing_weights:
            new_weight = sum(existing_weights) / float(len(existing_weights))
        else:
            new_weight = default_w
        new_weight = max(float(min_w), float(new_weight))

        weights: list[float] = []
        for col in normal_cols:
            if col is new_col:
                weights.append(new_weight)
            else:
                weights.append(_weight(col))

        total_w = sum(weights) or float(len(weights))
        # まず比率どおりに配分
        raw = [avail * (w / total_w) for w in weights]
        widths = [max(min_w, int(round(r))) for r in raw]

        # viewport との差分を調整（比率を大きく崩さないようウェイト比例で）
        diff = avail - sum(widths)
        if diff != 0 and widths:
            # 差分をウェイト比で分配（整数）
            order = sorted(range(len(widths)), key=lambda i: weights[i], reverse=(diff > 0))
            t = 0
            while t < abs(diff):
                progressed = False
                for i in order:
                    if t >= abs(diff):
                        break
                    if diff > 0:
                        widths[i] += 1
                        t += 1
                        progressed = True
                    elif widths[i] > min_w:
                        widths[i] -= 1
                        t += 1
                        progressed = True
                if not progressed:
                    break

        # MIN を下回るカラムがあれば、余剰のあるカラムから移す
        for i, w in enumerate(widths):
            if w >= min_w:
                continue
            need = min_w - w
            widths[i] = min_w
            for j in sorted(range(len(widths)), key=lambda k: widths[k], reverse=True):
                if need <= 0:
                    break
                if j == i:
                    continue
                can = widths[j] - min_w
                if can <= 0:
                    continue
                take = min(can, need)
                widths[j] -= take
                need -= take

        for col, w in zip(normal_cols, widths):
            col.set_width(max(min_w, int(w)), emit_signal=False)
        for col in stowed_cols:
            col.set_width(stow_w, emit_signal=False)

        if self._scroll_layout is not None:
            for col in visible:
                try:
                    self._scroll_layout.setStretchFactor(col, 0)
                except Exception:
                    pass
        try:
            cid_new = ""
            try:
                cid_new = new_col.get_column_id()
            except Exception:
                cid_new = ""
            pref_out = dict(getattr(self, "_preferred_widths", None) or {})
            # ensure で埋めた既存値を維持しつつ、新規だけ weight を載せる
            if cid_new:
                pref_out[cid_new] = float(new_weight)
            self._preferred_widths = pref_out
            try:
                key = self._bound_layout_mode_key()
                if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                    self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
                self._mode_preferred_widths[key] = dict(pref_out)
            except Exception:
                pass
            if self._settings_manager and cid_new:
                widths_to_save = {}
                for col in self._columns:
                    try:
                        cid = col.get_column_id()
                    except Exception:
                        continue
                    if not cid:
                        continue
                    if getattr(col, "is_individually_stowed", lambda: False)():
                        w = int(
                            pref_out.get(cid)
                            or getattr(col, "_width_before_individual_stow", 0)
                            or 0
                        )
                    else:
                        w = int(pref_out.get(cid) or 0)
                        if w <= 0:
                            try:
                                w = int(col.get_width() or 0)
                            except Exception:
                                w = 0
                    if w > 0:
                        widths_to_save[cid] = w
                mode = self._bound_layout_mode_key()
                if hasattr(self._settings_manager, "save_column_widths_for_mode"):
                    self._settings_manager.save_column_widths_for_mode(mode, widths_to_save)
                elif mode == "normal":
                    self._settings_manager.save_column_widths(widths_to_save)
        except Exception:
            pass

    def _reset_all_column_widths(self) -> None:
        self._redistribute_equal_widths()

    def _stow_columns_list(self, to_stow, visible, keep_visible=None) -> None:
        keep_visible = list(keep_visible or [])
        # 個別収納は一括収納membershipへ入れない。左右一括収納は
        # 展開中カラムだけを対象にし、個別収納はそのまま残す。
        to_stow = [
            c for c in (to_stow or [])
            if not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        if not to_stow:
            return

        visible_individual = [
            c for c in visible
            if getattr(c, "is_individually_stowed", lambda: False)()
        ]
        visible_normal = [
            c for c in visible
            if not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        if (
            visible_individual
            and len(visible_normal) == 1
            and visible_normal[0] in to_stow
        ):
            return
        snap: dict = dict(getattr(self, "_stow_saved_widths", None) or {})
        pref = dict(getattr(self, "_preferred_widths", None) or {})
        for col in visible:
            if getattr(col, "is_individually_stowed", lambda: False)():
                continue
            try:
                cid = col.get_column_id()
                live = int(col.get_width() or col.width() or 0)
            except Exception:
                cid = ""
                live = int(col.width()) if col.width() > 0 else 0
            if not cid:
                continue
            if cid in snap and int(snap.get(cid) or 0) > 0:
                continue
            w = int(pref.get(cid) or 0)
            if w <= 0:
                w = live
            if w > 0:
                snap[cid] = w
        self._stow_saved_widths = snap
        self.hide_boundary_actions()
        for col in self._columns:
            h = getattr(col, "_resize_handle", None)
            if h is None:
                continue
            try:
                h._actions_visible = False
                h._expand = 0.0
                h.set_hint(False)
            except Exception:
                pass
        if not hasattr(self, "_stowed_columns") or self._stowed_columns is None:
            self._stowed_columns = []
        for col in to_stow:
            col.hide()
            if col in self._stowed_columns:
                continue
            self._stowed_columns.append(col)
        try:
            key = self._bound_layout_mode_key()
            if not hasattr(self, "_mode_stowed_columns") or self._mode_stowed_columns is None:
                self._mode_stowed_columns = {"normal": [], "lr": [], "tb": []}
            if not hasattr(self, "_mode_stow_saved_widths") or self._mode_stow_saved_widths is None:
                self._mode_stow_saved_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._mode_stowed_columns[key] = list(self._stowed_columns)
            self._mode_stow_saved_widths[key] = dict(self._stow_saved_widths or {})
            self._bound_mode_key = key
        except Exception:
            pass
        if self._active_column in to_stow:
            if keep_visible:
                self._set_active_column(keep_visible[-1])
            else:
                self._active_column = None
                self._clear_strip()
        self._fit_columns()
        self._update_boundary_visibility()
        self.hide_boundary_actions()
        self._update_stow_restore_rail()
        self._persist_stowed_state()


    def _stow_columns_left_of(self, boundary_col) -> None:
        if boundary_col is None:
            return
        visible = [c for c in self._columns if c.isVisible()]
        if boundary_col not in visible:
            return
        idx = visible.index(boundary_col)
        boundary_individual = getattr(
            boundary_col, "is_individually_stowed", lambda: False
        )()
        end_idx = idx if boundary_individual else idx + 1
        candidates = visible[:end_idx]
        to_stow = [
            c for c in candidates
            if not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        if not to_stow:
            return
        keep_visible = [c for c in visible if c not in to_stow]
        self._stow_columns_list(to_stow, visible, keep_visible=keep_visible)

    def _stow_columns_right_of(self, boundary_col) -> None:
        if boundary_col is None:
            return
        visible = [c for c in self._columns if c.isVisible()]
        if boundary_col not in visible:
            return
        idx = visible.index(boundary_col)
        candidates = visible[idx + 1 :]
        to_stow = [
            c for c in candidates
            if not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        if not to_stow:
            return
        keep_visible = [c for c in visible if c not in to_stow]
        self._stow_columns_list(to_stow, visible, keep_visible=keep_visible)


    def _normal_visible_columns(self):
        out = []
        for c in self._columns:
            try:
                if not c.isVisible():
                    continue
                if getattr(c, "is_individually_stowed", lambda: False)():
                    continue
                out.append(c)
            except Exception:
                continue
        return out

    def _update_individual_stow_buttons(self) -> None:
        normals = self._normal_visible_columns()
        can_stow = len(normals) > 1
        tip_on = "このカラムを収納"
        tip_off = "最後のカラムは収納できません"
        for col in self._columns:
            btn = getattr(col, "_stow_btn", None)
            if btn is None:
                continue
            try:
                if getattr(col, "is_individually_stowed", lambda: False)():
                    continue
                btn.setEnabled(can_stow)
                btn.setToolTip(tip_on if can_stow else tip_off)
            except Exception:
                pass

    def _stowed_column_at_local(self, local):
        """ウィンドウ座標 local の位置にある個別収納カラム（無ければ None）。"""
        for c in self._columns:
            try:
                if not getattr(c, "is_individually_stowed", lambda: False)() or not c.isVisible():
                    continue
                if QRect(c.mapTo(self, QPoint(0, 0)), c.size()).contains(local):
                    return c
            except Exception:
                pass
        return None

    def _sync_stowed_hover(self) -> None:
        """個別収納の↔・名前を、カーソル位置の収納帯だけに出す（全収納帯を一括で整合させる）。"""
        if getattr(self, "_boundary_dragging", False):
            return
        try:
            owner = self._stowed_hover_owner(QCursor.pos())
        except Exception:
            owner = None
        for c in list(self._columns):
            try:
                if not getattr(c, "is_individually_stowed", lambda: False)():
                    continue
                if c is owner:
                    c._show_stowed_restore_btn()
                    c._show_stowed_name_label()
                elif owner is not None:
                    # 隣へ移った: 重なり残りを避けて即消す
                    c._hide_stowed_restore_btn_now()
                    c._hide_stowed_name_label_now()
                else:
                    c._fade_stowed_restore_btn(False)
                    c._fade_stowed_name_label(False)
            except Exception:
                pass

    def _poll_stowed_hover(self) -> None:
        """enter/leave が WebEngine 等に吸われて届かない場合の保険。持ち主が変わったときだけ整合させる。"""
        owner = self._stowed_hover_owner(QCursor.pos())
        if owner is getattr(self, "_stowed_hover_last_owner", None):
            return
        self._stowed_hover_last_owner = owner
        self._sync_stowed_hover()

    def _stowed_hover_owner(self, global_pos):
        """カーソル位置の個別収納カラム。収納帯の上を優先し、無ければ↔ノブの上の持ち主。"""
        stowed = [
            c for c in self._columns
            if getattr(c, "is_individually_stowed", lambda: False)() and c.isVisible()
        ]
        for c in stowed:
            if c.rect().contains(c.mapFromGlobal(global_pos)):
                return c
        for c in stowed:
            btn = getattr(c, "_stowed_restore_btn", None)
            if btn is not None and btn.isVisible() and btn.rect().contains(btn.mapFromGlobal(global_pos)):
                return c
        return None

    def _stow_single_column(self, column) -> None:
        if column is None:
            return
        if getattr(column, "is_individually_stowed", lambda: False)():
            return
        if column not in self._columns:
            try:
                if column.parent() is None:
                    return
            except Exception:
                return
        # 最後の通常表示カラムは個別収納しない
        if len(self._normal_visible_columns()) <= 1:
            return
        # preferred はユーザーが決めた相対 weight。収納では変更しない。
        # 旧設定などで欠けている場合だけ、現在モードの初期 weight を一度補完する。
        try:
            self._ensure_mode_preferred_weights(self._bound_layout_mode_key(), self._columns)
        except Exception:
            pass
        pref = dict(getattr(self, "_preferred_widths", None) or {})
        try:
            cid = column.get_column_id()
            pw = int(pref.get(cid) or 0)
            if cid and pw >= AccountColumn.MIN_WIDTH:
                column._width_before_individual_stow = pw
        except Exception:
            pass
        # enter の幅固定と fit の再配分を同一フレームにまとめ、隙間描画を出さない
        host = getattr(self, "_scroll_content", None)
        if host is not None:
            host.setUpdatesEnabled(False)
        try:
            try:
                column.set_individually_stowed(True)
            except Exception:
                return
            self._fit_columns()
        finally:
            if host is not None:
                host.setUpdatesEnabled(True)
        self._update_individual_stow_buttons()
        if self._active_column is column:
            others = [
                c for c in self._columns
                if c is not column and c.isVisible()
                and not getattr(c, "is_individually_stowed", lambda: False)()
            ]
            if others:
                self._set_active_column(others[0])
            else:
                self._active_column = None
                self._clear_strip()
        try:
            self._save_columns()
        except Exception:
            pass
        try:
            self._persist_individual_stow_state()
        except Exception:
            pass

    def _restore_single_column(self, column) -> None:
        if column is None:
            return
        if not getattr(column, "is_individually_stowed", lambda: False)():
            return
        if column not in self._columns:
            try:
                if column.parent() is None:
                    return
            except Exception:
                return
        try:
            self._suppress_all_boundary_hover_ui()
        except Exception:
            pass

        host = getattr(self, "_scroll_content", None)
        if host is not None:
            host.setUpdatesEnabled(False)
        try:
            try:
                column.set_individually_stowed(False)
            except Exception:
                return
            self._fit_columns()
        finally:
            if host is not None:
                host.setUpdatesEnabled(True)
                host.update()

        # WebEngine は祖先Widgetの描画停止を解除してから再表示する。
        try:
            column.reveal_after_restore()
        except Exception:
            pass
        self._update_individual_stow_buttons()
        try:
            self._save_columns()
        except Exception:
            pass
        try:
            self._persist_individual_stow_state()
        except Exception:
            pass


    def _persist_stowed_state(self) -> None:
        if not self._settings_manager:
            return
        if getattr(self, "_restoring_session", False):
            return
        # 一括収納membershipを保存する。個別収納状態は別系統で保存され、両方を同時に持てる。
        ids = []
        seen = set()
        for col in list(getattr(self, "_stowed_columns", None) or []):
            try:
                cid = col.get_column_id()
            except Exception:
                continue
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(cid)
        for _lst in (getattr(self, "_mode_stowed_columns", None) or {}).values():
            for col in list(_lst or []):
                try:
                    cid = col.get_column_id()
                except Exception:
                    continue
                if cid and cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
        widths = dict(getattr(self, "_stow_saved_widths", None) or {})
        for _w in (getattr(self, "_mode_stow_saved_widths", None) or {}).values():
            for k, v in dict(_w or {}).items():
                if k not in widths and v:
                    widths[k] = v
        if hasattr(self._settings_manager, "save_stowed_state"):
            self._settings_manager.save_stowed_state(ids, widths)

    def _clear_persisted_stowed_state(self) -> None:
        if self._settings_manager and hasattr(self._settings_manager, "clear_stowed_state"):
            self._settings_manager.clear_stowed_state()

    def _persist_individual_stow_state(self) -> None:
        if not self._settings_manager:
            return
        if getattr(self, "_restoring_session", False):
            return
        # 旧グローバルキーはnormal互換専用。Dock操作でMainの互換状態を上書きしない。
        if self._bound_layout_mode_key() != "normal":
            return
        if not hasattr(self._settings_manager, "save_individually_stowed_state"):
            return
        ids = []
        widths = {}
        for col in list(getattr(self, "_columns", None) or []):
            try:
                if not getattr(col, "is_individually_stowed", lambda: False)():
                    continue
                cid = col.get_column_id()
            except Exception:
                continue
            if not cid:
                continue
            ids.append(cid)
            try:
                w = int(getattr(col, "_width_before_individual_stow", 0) or 0)
            except Exception:
                w = 0
            if w > 0:
                widths[cid] = w
        self._settings_manager.save_individually_stowed_state(ids, widths)

    def _apply_individual_stow_on_startup(self) -> None:
        # 全 mode pack へ、各 mode の保存設定を source of truth として適用する。
        # Dock ON 起動でも normal pack の個別収納を落とさない（Dock OFF 復帰用）。
        if not self._settings_manager:
            return
        packs = self._service_packs() if hasattr(self, "_service_packs") else {}
        widths_global = {}
        ids_global = []
        if hasattr(self._settings_manager, "get_individually_stowed_state"):
            try:
                state = self._settings_manager.get_individually_stowed_state() or {}
                ids_global = list(state.get("column_ids") or [])
                widths_global = dict(state.get("widths") or {})
            except Exception:
                ids_global = []
                widths_global = {}
        pending = list(getattr(self, "_pending_stow_ids", None) or [])
        self._pending_stow_ids = []

        any_applied = False
        for mode in ("normal", "lr", "tb"):
            cols = list((packs or {}).get(mode) or [])
            if not cols:
                continue
            confs = []
            try:
                if hasattr(self._settings_manager, "get_columns_for_mode"):
                    confs = list(self._settings_manager.get_columns_for_mode(mode) or [])
                elif mode == "normal":
                    confs = list(self._settings_manager.get_columns() or [])
            except Exception:
                confs = []

            by_id = {}
            for col in cols:
                try:
                    by_id[col.get_column_id()] = col
                except Exception:
                    continue

            targets = []
            seen = set()

            def _add(col, pw: int = 0):
                if col is None:
                    return
                try:
                    key = col.get_column_id() or id(col)
                except Exception:
                    key = id(col)
                if key in seen:
                    return
                seen.add(key)
                targets.append((col, pw))

            for i, conf in enumerate(confs):
                try:
                    if not bool(conf.get("individually_stowed")):
                        continue
                except Exception:
                    continue
                col = None
                cid = str(conf.get("column_id") or "").strip()
                if cid:
                    col = by_id.get(cid)
                if col is None and i < len(cols):
                    col = cols[i]
                pw = 0
                try:
                    pw = int(conf.get("width") or 0)
                except Exception:
                    pw = 0
                if not pw and cid:
                    pw = int(widths_global.get(cid) or 0)
                _add(col, pw)

            # normal のみ: pending / グローバル ID（互換）
            if mode == "normal":
                for cid in pending + ids_global:
                    if not cid:
                        continue
                    _add(by_id.get(cid), int(widths_global.get(cid) or 0))

            # 展開中のカラムを最低1つ残す。更新や旧設定で全カラムが個別収納になった
            # 状態（通常操作では作れない）を復元しない。
            budget = len(cols) - 1 - sum(
                1 for c in cols if getattr(c, "is_individually_stowed", lambda: False)()
            )
            for col, pw in targets:
                try:
                    if getattr(col, "is_individually_stowed", lambda: False)():
                        any_applied = True
                        continue
                    if budget <= 0:
                        continue
                    budget -= 1
                    if not pw:
                        try:
                            pw = int(widths_global.get(col.get_column_id()) or 0)
                        except Exception:
                            pw = 0
                    if not pw:
                        pw = int(getattr(col, "_width_before_individual_stow", 0) or 0)
                    if pw >= AccountColumn.MIN_WIDTH:
                        col._width_before_individual_stow = pw
                    col.set_individually_stowed(True)
                    any_applied = True
                except Exception:
                    continue

        if not any_applied:
            return
        # 表示中 pack だけ fit（非表示 pack は触らない）
        try:
            self._fit_columns()
        except Exception:
            pass
        try:
            self._update_individual_stow_buttons()
        except Exception:
            pass


    def _apply_persisted_stow_on_startup(self) -> None:
        # 一括収納の既存復元（個別収納は _apply_individual_stow_on_startup）
        widths = {}
        if self._settings_manager and hasattr(self._settings_manager, "get_stowed_state"):
            try:
                state = self._settings_manager.get_stowed_state() or {}
                widths = dict(state.get("widths") or {})
                legacy_ids = list(state.get("column_ids") or [])
            except Exception:
                legacy_ids = []
        else:
            legacy_ids = []

        by_id = {}
        for col in self._columns:
            try:
                by_id[col.get_column_id()] = col
            except Exception:
                continue

        stowed = []
        seen = set()
        for cid in legacy_ids:
            if not cid or cid in seen:
                continue
            col = by_id.get(cid)
            if col is None:
                continue
            seen.add(cid)
            stowed.append(col)
        for col in list(
            (getattr(self, "_mode_stowed_columns", None) or {}).get(
                self._bound_layout_mode_key() if hasattr(self, "_bound_layout_mode_key") else "normal"
            )
            or []
        ):
            if col in stowed:
                continue
            if col in self._columns:
                stowed.append(col)

        # 展開中のカラムを最低1つ残す（個別収納を含め、全部が収納された状態を復元しない）
        while stowed and not any(
            c not in stowed and not getattr(c, "is_individually_stowed", lambda: False)()
            for c in self._columns
        ):
            stowed.pop()

        if not stowed:
            return

        for col in stowed:
            try:
                col.hide()
            except Exception:
                pass
        self._stowed_columns = stowed
        self._stow_saved_widths = dict(widths) if widths else dict(
            getattr(self, "_stow_saved_widths", {}) or {}
        )
        try:
            if not hasattr(self, "_mode_stowed_columns") or self._mode_stowed_columns is None:
                self._mode_stowed_columns = {"normal": [], "lr": [], "tb": []}
            key = self._bound_layout_mode_key()
            self._mode_stowed_columns[key] = list(stowed)
            self._bound_mode_key = key
        except Exception:
            pass
        self._fit_columns()
        self._update_boundary_visibility()
        self.hide_boundary_actions()
        self._update_stow_restore_rail()

    def _restore_stowed_columns(self, side: str | None = None) -> None:
        all_stowed = list(getattr(self, "_stowed_columns", None) or [])
        if not all_stowed:
            return
        if side in ("left", "right"):
            target = self._stowed_columns_for_side(side)
        else:
            target = list(all_stowed)
        if not target:
            return
        active = set(self._columns)
        snap = dict(getattr(self, "_stow_saved_widths", None) or {})
        target_set = set(target)
        for col in target:
            if col in active:
                col.show()
        remaining = [c for c in all_stowed if c not in target_set]
        self._stowed_columns = remaining
        self._apply_stow_saved_widths(snap)
        if not remaining:
            self._stow_saved_widths = {}
        try:
            key = self._bound_layout_mode_key()
            if hasattr(self, "_mode_stowed_columns") and self._mode_stowed_columns is not None:
                self._mode_stowed_columns[key] = list(remaining)
            if hasattr(self, "_mode_stow_saved_widths") and self._mode_stow_saved_widths is not None:
                if remaining:
                    self._mode_stow_saved_widths[key] = dict(self._stow_saved_widths or {})
                else:
                    self._mode_stow_saved_widths[key] = {}
            if hasattr(self, "_mode_preferred_widths") and self._mode_preferred_widths is not None:
                self._mode_preferred_widths[key] = dict(self._preferred_widths or {})
        except Exception:
            pass
        if not remaining and self._bound_layout_mode_key() == "normal":
            self._clear_persisted_stowed_state()
        else:
            try:
                self._persist_stowed_state()
            except Exception:
                pass
        self._update_boundary_visibility()
        self.hide_boundary_actions()
        self._update_stow_restore_rail()

    def _apply_stow_saved_widths(self, snap: dict) -> None:
        # 一括収納の snapshot は旧設定との互換用。ユーザーの preferred weight は
        # 収納/展開では書き換えず、現在の表示可能幅へ同じ比率で再正規化する。
        self._fit_columns()

    def _point_on_restore_knob(self, local_x: int, local_y: int) -> bool:
        return self._restore_knob_side_at(local_x, local_y) is not None

    def _restore_knob_side_at(self, local_x: int, local_y: int) -> str | None:
        mapping = (
            ("_stow_restore_rail", "right"),
            ("_stow_restore_rail_left", "left"),
        )
        for name, side in mapping:
            rail = getattr(self, name, None)
            if rail is None:
                continue
            try:
                if not rail.isVisible():
                    continue
                if QRect(rail.geometry()).contains(local_x, local_y):
                    return side
            except Exception:
                continue
        return None

    def _try_dispatch_restore_from_global(self, event) -> bool:
        # Dock 有効かつ未展開のときだけグローバル restore を無効化（展開中は通常と同じ経路へ）
        if getattr(self, "_edge_dock_enabled", False) and not getattr(
            self, "_edge_dock_revealed", False
        ):
            return False
        stowed = getattr(self, "_stowed_columns", None) or []
        if not stowed:
            return False
        try:
            gp = event.globalPosition().toPoint()
        except Exception:
            return False
        local = self.mapFromGlobal(gp)
        side = self._restore_knob_side_at(local.x(), local.y())
        if not side:
            return False
        self._restore_stowed_columns(side=side)
        return True

    def _update_restore_knob_cursor_from_global(self, event) -> None:
        # Dock 有効かつ未展開のときだけカーソル処理を無効化（展開中は通常と同じ経路へ）
        if getattr(self, "_edge_dock_enabled", False) and not getattr(
            self, "_edge_dock_revealed", False
        ):
            self._clear_restore_hand_cursor()
            return
        side = None
        try:
            gp = event.globalPosition().toPoint()
            local = self.mapFromGlobal(gp)
            side = self._restore_knob_side_at(local.x(), local.y())
        except Exception:
            side = None
        on = side is not None
        # 左右それぞれ独立に hover を更新する（右だけだと左が leave を取り逃したまま残る）
        for name, want in (
            ("_stow_restore_rail", "right"),
            ("_stow_restore_rail_left", "left"),
        ):
            rail = getattr(self, name, None)
            if rail is not None and hasattr(rail, "set_app_hover"):
                try:
                    rail.set_app_hover(side == want)
                except Exception:
                    pass
        forced = bool(getattr(self, "_restore_hand_cursor", False))
        if on and not forced:
            QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)
            self._restore_hand_cursor = True
        elif not on and forced:
            QApplication.restoreOverrideCursor()
            self._restore_hand_cursor = False

    def _clear_restore_hand_cursor(self) -> None:
        if getattr(self, "_restore_hand_cursor", False):
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._restore_hand_cursor = False
        for name in ("_stow_restore_rail", "_stow_restore_rail_left"):
            rail = getattr(self, name, None)
            if rail is not None and hasattr(rail, "set_app_hover"):
                try:
                    rail.set_app_hover(False)
                except Exception:
                    pass


    def _stow_index_groups(self) -> tuple[list, list, list, list]:
        cols = list(getattr(self, "_columns", None) or [])
        stowed = list(getattr(self, "_stowed_columns", None) or [])
        if not stowed:
            return cols, [], [], []
        stowed_set = set(stowed)
        vis_idxs = []
        stow_idxs = []
        for i, c in enumerate(cols):
            if c in stowed_set:
                stow_idxs.append(i)
                continue
            try:
                if not c.isVisible():
                    continue
                # 個別収納は一括収納とは独立した状態。左右端の個別収納を
                # 一括収納の「可視端」として扱うと、収納側判定が内側へ押し込まれ
                # restore knob が消える/反対側へ移る。通常表示カラムだけを基準にする。
                if getattr(c, "is_individually_stowed", lambda: False)():
                    continue
                vis_idxs.append(i)
            except Exception:
                vis_idxs.append(i)
        return cols, stowed, vis_idxs, stow_idxs

    def _stowed_columns_for_side(self, side: str) -> list:
        cols, stowed, vis_idxs, stow_idxs = self._stow_index_groups()
        if not stow_idxs:
            return []
        if not vis_idxs:
            mid = max(1, len(cols)) / 2.0
            if side == "left":
                return [cols[i] for i in stow_idxs if i < mid]
            return [cols[i] for i in stow_idxs if i >= mid]
        vmin = min(vis_idxs)
        vmax = max(vis_idxs)
        if side == "left":
            return [cols[i] for i in stow_idxs if i < vmin]
        return [cols[i] for i in stow_idxs if i > vmax]

    def _stow_side_flags(self) -> tuple[bool, bool]:
        cols, stowed, vis_idxs, stow_idxs = self._stow_index_groups()
        if not stow_idxs:
            return False, False
        if not vis_idxs:
            # 全収納時は列順の前後で左右を分ける（両方固定表示にしない）
            mid = max(1, len(cols)) / 2.0
            has_left = any(i < mid for i in stow_idxs)
            has_right = any(i >= mid for i in stow_idxs)
            if not has_left and not has_right:
                has_right = True
            return has_left, has_right
        vmin = min(vis_idxs)
        vmax = max(vis_idxs)
        has_left = any(i < vmin for i in stow_idxs)
        has_right = any(i > vmax for i in stow_idxs)
        if not has_left and not has_right:
            has_right = True
        return has_left, has_right

    def _update_stow_restore_rail(self) -> None:
        rail = getattr(self, "_stow_restore_rail", None)
        # Dock 収納中（未展開）だけ隠す。展開中は通常と同じく左右 Knob を出す
        if getattr(self, "_edge_dock_enabled", False) and not getattr(
            self, "_edge_dock_revealed", False
        ):
            left_rail = getattr(self, "_stow_restore_rail_left", None)
            self._clear_restore_hand_cursor()
            for r in (rail, left_rail):
                if r is None:
                    continue
                try:
                    r.hide()
                    r.setGeometry(-2000, -2000, 1, 1)
                except Exception:
                    pass
            return
        stowed = getattr(self, "_stowed_columns", None) or []
        has = bool(stowed)
        if has and rail is None:
            from src.ui.stow_restore_knob import StowRestoreKnob

            rail = StowRestoreKnob(self, side="right")
            rail.restoreRequested.connect(self._restore_stowed_columns)
            self._stow_restore_rail = rail
            self._stow_restore_knob_class = StowRestoreKnob
        rail = getattr(self, "_stow_restore_rail", None)
        if rail is None:
            return
        has_left, has_right = self._stow_side_flags()
        left_rail = getattr(self, "_stow_restore_rail_left", None)
        cls = getattr(self, "_stow_restore_knob_class", None)
        if has_left and left_rail is None and cls is not None:
            left_rail = cls(self, side="left")
            left_rail.restoreRequested.connect(self._restore_stowed_columns)
            self._stow_restore_rail_left = left_rail
        left_rail = getattr(self, "_stow_restore_rail_left", None)

        def _stow_y_like_boundary() -> int:
            ctrl_bottom = 32
            try:
                tb = getattr(self, "_top_bar", None)
                if tb is not None and tb.isVisible():
                    g = tb.geometry()
                    ctrl_bottom = int(g.y() + g.height())
            except Exception:
                pass
            safe_min = ctrl_bottom + 16

            try:
                cols = getattr(self, "_columns", None) or []
                for col in cols:
                    if col is None or not col.isVisible():
                        continue
                    wv = None
                    for name in ("_webview", "_view", "webview"):
                        wv = getattr(col, name, None)
                        if wv is not None:
                            break
                    if wv is not None and hasattr(wv, "mapTo"):
                        pt = wv.mapTo(self, QPoint(0, 0))
                        return max(safe_min, int(pt.y()) + 8)
                    top = col.mapTo(self, QPoint(0, 0)).y()
                    return max(safe_min, int(top) + 36)
            except Exception:
                pass
            return max(safe_min, ctrl_bottom + 40)

        def _hide_rail(r) -> None:
            if r is None:
                return
            try:
                r.hide()
                r.setGeometry(-2000, -2000, 1, 1)
            except Exception:
                pass

        def _reposition_rail(r) -> None:
            if r is None:
                return
            # Dock 未展開時だけ隠す。展開中は通常と同じ配置へ進む
            if getattr(self, "_edge_dock_enabled", False) and not getattr(
                self, "_edge_dock_revealed", False
            ):
                _hide_rail(r)
                return
            side = getattr(r, "_side", "right")
            # 遅延呼び出し時に side 状態が変わっていても古い表示を出さない
            try:
                cur_left, cur_right = self._stow_side_flags()
            except Exception:
                cur_left, cur_right = False, False
            if side == "left" and not cur_left:
                _hide_rail(r)
                return
            if side != "left" and not cur_right:
                _hide_rail(r)
                return
            r.setParent(self)
            hit = int(getattr(r, "_HIT", 30))
            if side == "left":
                x = 0
            else:
                x = max(0, self.width() - hit)
            y = _stow_y_like_boundary()
            y = min(y, max(8, self.height() - hit - 8))
            r.setGeometry(x, y, hit, hit)
            r.setVisible(True)
            r.show()
            r.raise_()
            try:
                r.winId()
            except Exception:
                pass

        if not has:
            self._clear_restore_hand_cursor()
            _hide_rail(rail)
            _hide_rail(left_rail)
            return
        if has_right:
            _reposition_rail(rail)
            QTimer.singleShot(0, lambda r=rail: _reposition_rail(r))
            QTimer.singleShot(100, lambda r=rail: _reposition_rail(r))
        else:
            _hide_rail(rail)
        if has_left and left_rail is not None:
            _reposition_rail(left_rail)
            QTimer.singleShot(0, lambda r=left_rail: _reposition_rail(r))
            QTimer.singleShot(100, lambda r=left_rail: _reposition_rail(r))
        else:
            _hide_rail(left_rail)


    def _column_layout_target_width(self) -> int:
        """AccountColumn 群が埋めるべき水平 client 幅。

        切替直後は viewport 幅が旧値のまま残り、その幅で fit すると右側に黒帯が出る。
        Dock 有効時は root 幅（scroll の余白を除く）、無効時は central 幅を使い、
        取れないときだけ scroll/viewport の幅へフォールバックする。
        """
        def _scroll_h_margins() -> int:
            try:
                if self._scroll is None:
                    return 0
                m = self._scroll.contentsMargins()
                return max(0, int(m.left()) + int(m.right()))
            except Exception:
                return 0

        if getattr(self, "_edge_dock_enabled", False):
            root = getattr(self, "_edge_dock_root", None)
            if root is not None:
                try:
                    rw = int(root.width() or 0)
                    if rw > 0:
                        return max(1, rw - _scroll_h_margins())
                except Exception:
                    pass
            try:
                ww = int(self.width() or 0)
                if ww > 0:
                    return max(1, ww - _scroll_h_margins())
            except Exception:
                pass
        else:
            try:
                # central は枠の 1px 分だけ内側。MainWindow 幅で並べると右端が 2px はみ出し、
                # 10px の個別収納帯だけ左端より細く見える
                cw = self.centralWidget()
                ww = int(cw.width() or 0) if cw is not None else 0
                if ww <= 0:
                    ww = int(self.width() or 0)
                if ww > 0:
                    return ww
            except Exception:
                pass
        try:
            if self._scroll is not None:
                sw = int(self._scroll.width() or 0)
                if sw > 0:
                    return max(1, sw - _scroll_h_margins())
        except Exception:
            pass
        try:
            if self._scroll is not None and self._scroll.viewport() is not None:
                vw = int(self._scroll.viewport().width() or 0)
                if vw > 0:
                    return vw
        except Exception:
            pass
        return 0

    def _column_layout_target_height(self, window_height: int | None = None) -> int:
        """AccountColumn群が埋めるべき垂直client高さ。Dock起動直後は viewport 高さが旧値なので root/top-level から出す。"""
        try:
            h = int(window_height or 0)
        except Exception:
            h = 0
        if h <= 0:
            if getattr(self, "_edge_dock_enabled", False):
                root = getattr(self, "_edge_dock_root", None)
                try:
                    h = int(root.height() or 0) if root is not None else 0
                except Exception:
                    h = 0
            if h <= 0:
                try:
                    h = int(self.height() or 0)
                except Exception:
                    h = 0
        if h <= 0:
            try:
                return max(1, int(self._scroll.viewport().height() or 0))
            except Exception:
                return 1

        top_h = 0
        top = getattr(self, "_top_bar", None)
        if top is not None:
            try:
                if not top.isHidden():
                    top_h = max(0, int(top.height() or top.sizeHint().height() or 0))
            except Exception:
                top_h = 0

        margin_h = 0
        scroll = getattr(self, "_scroll", None)
        if scroll is not None:
            try:
                m = scroll.contentsMargins()
                margin_h = max(0, int(m.top()) + int(m.bottom()))
            except Exception:
                margin_h = 0
        return max(1, h - top_h - margin_h)

    def _fit_columns_after_restore(self, *, _attempt: int = 0) -> None:
        try:
            vw = 0
            if self._scroll is not None and self._scroll.viewport() is not None:
                vw = int(self._scroll.viewport().width() or 0)
        except Exception:
            vw = 0
        if vw <= 0 and _attempt < 8:
            QTimer.singleShot(50, lambda: self._fit_columns_after_restore(_attempt=_attempt + 1))
            return
        self._fit_columns()

    def _layout_visible_columns(self) -> list:
        """active pack の layout 対象を isVisible() に依存せず返す。

        起動直後は表示対象の列でも isVisible() が False になるため、明示hideと一括収納だけを除外する。
        """
        columns = list(getattr(self, "_columns", None) or [])
        stowed = set(getattr(self, "_stowed_columns", None) or [])
        logical = []
        for col in columns:
            if col in stowed:
                continue
            try:
                if col.isHidden():
                    continue
            except Exception:
                pass
            logical.append(col)
        if logical:
            return logical
        return [col for col in columns if col not in stowed]

    def _fit_columns(
        self, *, target_width: int | None = None, target_height: int | None = None
    ) -> None:
        if self._media_wide_view is not None:
            self._apply_media_wide_geometry()
            return
        if getattr(self, "_edge_dock_enabled", False) and getattr(self, "_edge_dock_animating", False):
            return
        if getattr(self, "_boundary_pending", None) is not None:
            return
        if getattr(self, "_boundary_dragging", False):
            return
        visible = self._layout_visible_columns()
        self._update_empty_state()
        if not visible:
            return

        # 追加直後は _fit_after_column_add で幅確定済みのため再計算しない
        if getattr(self, "_column_add_settling", False):
            try:
                if self._scroll_layout is not None:
                    self._scroll_layout.invalidate()
                    if self._scroll_content is not None and self._scroll_content.layout() is not None:
                        self._scroll_content.layout().activate()
            except Exception:
                pass
            try:
                self._update_boundary_visibility()
                self._update_individual_stow_buttons()
            except Exception:
                pass
            return

        # Dock OFF のprestageではトップレベルHWNDがまだ旧Dock幅なので、
        # 呼び出し側から最終Main幅を渡して子レイアウトを先に確定する。
        try:
            viewport_width = int(target_width or 0)
        except Exception:
            viewport_width = 0
        if viewport_width <= 0:
            try:
                viewport_width = int(self._column_layout_target_width() or 0)
            except Exception:
                viewport_width = 0
        if viewport_width <= 0:
            return

        n = len(visible)
        min_w = AccountColumn.MIN_WIDTH
        stow_w = AccountColumn.STOWED_WIDTH

        preferred = dict(getattr(self, "_preferred_widths", None) or {})
        saved = {}
        if self._settings_manager:
            mode = self._bound_layout_mode_key()
            if hasattr(self._settings_manager, "get_column_widths_for_mode"):
                saved = self._settings_manager.get_column_widths_for_mode(mode) or {}
            else:
                saved = self._settings_manager.get_column_widths() or {}

        col_config_by_id = {conf.column_id: conf for conf in self._column_configs}

        is_stowed = [
            bool(getattr(c, "is_individually_stowed", lambda: False)())
            for c in visible
        ]
        stowed_count = sum(1 for s in is_stowed if s)

        def _pref_w(col) -> float:
            cid = col.get_column_id()
            aid = col.get_account_id()
            live_w = 0
            try:
                live_w = int(col.get_width() or 0)
            except Exception:
                live_w = 0
            if cid in preferred and preferred[cid] > 0:
                return float(preferred[cid])
            if cid in saved and saved[cid] > 0:
                return float(saved[cid])
            if aid in saved and saved[aid] > 0:
                return float(saved[aid])
            if cid in col_config_by_id and col_config_by_id[cid].width > 0:
                return float(col_config_by_id[cid].width)
            if live_w >= AccountColumn.MIN_WIDTH:
                return float(live_w)
            return float(AccountColumn.DEFAULT_WIDTH)

        pref_list = [_pref_w(c) for c in visible]
        widths = [stow_w if s else 0 for s in is_stowed]
        normal_idxs = [k for k, s in enumerate(is_stowed) if not s]

        try:
            self._scroll_layout.setAlignment(
                Qt.AlignmentFlag.AlignRight
                if stowed_count > 0 and not normal_idxs
                else Qt.AlignmentFlag.AlignLeft
            )
        except Exception:
            pass

        if stowed_count > 0 and normal_idxs:
            # 収納スロット分を除いた viewport を通常カラムへ preferred 比率で配分
            # preferred 自体は書き換えない（復帰・幅リセット用の値を維持）
            avail = max(0, int(viewport_width) - stowed_count * stow_w)
            seg_total = sum(pref_list[k] for k in normal_idxs) or 1.0
            for idx in normal_idxs:
                widths[idx] = max(min_w, int(avail * pref_list[idx] / seg_total))
            for idx, s in enumerate(is_stowed):
                if s:
                    widths[idx] = stow_w
            diff = avail - sum(widths[k] for k in normal_idxs)
            for t in range(abs(diff)):
                idx = normal_idxs[t % len(normal_idxs)]
                if diff > 0:
                    widths[idx] += 1
                elif widths[idx] > min_w:
                    widths[idx] -= 1
        elif stowed_count > 0:
            for idx, s in enumerate(is_stowed):
                widths[idx] = stow_w if s else max(min_w, int(round(pref_list[idx])))
        else:
            # preferred 上の各カラム中心（viewport に正規化）を基準に配分
            total_pref = sum(pref_list) or 1.0
            scale = float(viewport_width) / total_pref
            ideal_centers = []
            acc = 0.0
            for p in pref_list:
                ideal_centers.append(acc + p * scale * 0.5)
                acc += p * scale
            i = 0
            while i < n:
                if is_stowed[i]:
                    widths[i] = stow_w
                    i += 1
                    continue
                j = i
                while j < n and not is_stowed[j]:
                    j += 1
                if i > 0 and is_stowed[i - 1]:
                    left_edge = ideal_centers[i - 1] + stow_w * 0.5
                else:
                    left_edge = 0.0
                if j < n and is_stowed[j]:
                    right_edge = ideal_centers[j] - stow_w * 0.5
                else:
                    right_edge = float(viewport_width)
                seg_avail = max(0, int(round(right_edge - left_edge)))
                seg_idxs = list(range(i, j))
                seg_total = sum(pref_list[k] for k in seg_idxs) or 1.0
                for idx in seg_idxs:
                    widths[idx] = max(min_w, int(seg_avail * pref_list[idx] / seg_total))
                diff = seg_avail - sum(widths[idx] for idx in seg_idxs)
                for t in range(abs(diff)):
                    idx = seg_idxs[t % len(seg_idxs)]
                    if diff > 0:
                        widths[idx] += 1
                    elif widths[idx] > min_w:
                        widths[idx] -= 1
                i = j
            if normal_idxs:
                diff = viewport_width - sum(widths)
                for t in range(abs(diff)):
                    idx = normal_idxs[t % len(normal_idxs)]
                    if diff > 0:
                        widths[idx] += 1
                    elif widths[idx] > min_w:
                        widths[idx] -= 1

        # 最終幅だけを一度反映する。通常カラムは fixed の付け外しをせず、
        # setMin/Max + 必要時の resize のみ。layout.activate は位置決めに使う。
        changed_normals = []
        for col, w, stowed in zip(visible, widths, is_stowed):
            try:
                if stowed:
                    if int(getattr(col, "_current_width", 0) or 0) != stow_w or int(col.maximumWidth()) != stow_w:
                        col._current_width = stow_w
                        col.setMinimumWidth(stow_w)
                        col.setMaximumWidth(stow_w)
                        col.setFixedWidth(stow_w)
                else:
                    tw = max(min_w, int(w))
                    cur = int(getattr(col, "_current_width", 0) or 0)
                    if cur != tw or int(col.width()) != tw or int(col.maximumWidth()) != tw:
                        col._current_width = tw
                        # fit後の合計幅はviewport幅そのもの。各列を確定幅へ固定し、
                        # QHBoxLayoutが削除直後などにsizeHintより縮めて右側へ空白を
                        # 作る余地を残さない。次のfitで再計算されるため固定は一時的。
                        col.setMinimumWidth(tw)
                        col.setMaximumWidth(tw)
                        if int(col.width()) != tw:
                            col.resize(tw, col.height() if col.height() > 0 else max(1, self._scroll.viewport().height()))
                        else:
                            col.updateGeometry()
                        changed_normals.append((col, tw))
            except Exception:
                pass

        if self._scroll_layout is not None:
            for col in visible:
                try:
                    self._scroll_layout.setStretchFactor(col, 0)
                except Exception:
                    pass
        try:
            content_h = int(target_height or 0)
        except Exception:
            content_h = 0
        if content_h <= 0:
            content_h = self._column_layout_target_height()
        content_h = max(1, int(content_h))
        total_w = max(1, int(sum(widths)))
        content_w = max(viewport_width, total_w)
        self._scroll_content.setMinimumWidth(0)
        self._scroll_content.setMaximumWidth(16777215)
        self._scroll_content.setMinimumHeight(0)
        self._scroll_content.setMaximumHeight(16777215)
        self._scroll_content.resize(content_w, content_h)
        self._scroll_layout.invalidate()
        self._scroll_layout.setGeometry(self._scroll_content.rect())
        self._scroll_layout.activate()
        # 起動Dockではlayout eventより先にここへ来ることがある。幅だけでなく
        # 高さも権威あるcontent高さへ揃え、旧Main高さを残さない。
        for col in visible:
            try:
                if int(col.height()) != content_h:
                    col.resize(max(1, int(col.width())), content_h)
            except Exception:
                pass
        # activate 後にまだ幅がずれている場合のみ一度補正
        for col, tw in changed_normals:
            try:
                if int(col.width()) != tw:
                    col.resize(tw, content_h)
            except Exception:
                pass
        if stowed_count > 0:
            for col, stowed in zip(visible, is_stowed):
                if not stowed:
                    continue
                try:
                    if int(col.width()) != stow_w or int(col.maximumWidth()) != stow_w:
                        col._current_width = stow_w
                        col.setMinimumWidth(stow_w)
                        col.setMaximumWidth(stow_w)
                        col.setFixedWidth(stow_w)
                except Exception:
                    pass
        # WebView は body の layout 配下なので明示 setGeometry しない
        # （layout と競合して余分な resize を起こす）
        self._update_boundary_visibility()
        self._update_individual_stow_buttons()

    def _update_boundary_visibility(self) -> None:
        # 通常同士が隣接なら左カラムに境界。間に個別収納がある場合は
        # 連続する収納スロット全体を境界領域とし、各スロットに同じ左右通常カラムを紐づける
        for col in self._columns:
            col.set_boundary_enabled(False)
            if hasattr(col, "_boundary_right_col"):
                col._boundary_right_col = None
            if hasattr(col, "_boundary_left_col"):
                col._boundary_left_col = None
        ordered = [c for c in self._columns if c.isVisible()]
        normals = [
            (i, c) for i, c in enumerate(ordered)
            if not getattr(c, "is_individually_stowed", lambda: False)()
        ]
        for k in range(max(0, len(normals) - 1)):
            i1, left = normals[k]
            i2, right = normals[k + 1]
            if i2 == i1 + 1:
                left._boundary_right_col = right
                left.set_boundary_enabled(True)
                if hasattr(left, "_position_resize_handles"):
                    left._position_resize_handles()
            else:
                # 間の個別収納は見た目・展開は個別のまま。
                # 幅調整だけ同じ左右通常カラムに紐づけ、各スロットの太い領域全体で
                # 同一のカラム幅調整を開始できるようにする（先頭だけ enable しない）。
                for mi in range(i1 + 1, i2):
                    mid = ordered[mi]
                    if not getattr(mid, "is_individually_stowed", lambda: False)():
                        continue
                    mid._boundary_left_col = left
                    mid._boundary_right_col = right
                    mid.set_boundary_enabled(True)
                    if hasattr(mid, "_position_resize_handles"):
                        mid._position_resize_handles()

    def _check_hibernation(self) -> None:
        for col in self._columns:
            for tab in col.webviews():
                if hasattr(tab, "maybe_freeze"):
                    tab.maybe_freeze()

    def _suppress_all_boundary_hover_ui(self) -> None:
        """カラム幅ドラッグ中: 共有UI・展開↔・名前・青ヒントをすべて消す。"""
        try:
            self.hide_boundary_actions()
        except Exception:
            pass
        for col in getattr(self, "_columns", None) or []:
            try:
                h = getattr(col, "_resize_handle", None)
                if h is not None:
                    try:
                        h._expand_anim.stop()
                    except Exception:
                        pass
                    h._actions_visible = False
                    h._expand = 0.0
                    h.set_hint(False)
                if hasattr(col, "_hide_stowed_restore_btn_now"):
                    col._hide_stowed_restore_btn_now()
                if hasattr(col, "_hide_stowed_name_label_now"):
                    col._hide_stowed_name_label_now()
            except Exception:
                pass

    def _on_boundary_dragged(self, column: AccountColumn, delta: int) -> None:
        if not getattr(self, "_boundary_dragging", False):
            self._boundary_dragging = True
            self._suppress_all_boundary_hover_ui()
        else:
            self._boundary_dragging = True
        if getattr(column, "is_individually_stowed", lambda: False)():
            left_col = getattr(column, "_boundary_left_col", None)
            right_col = getattr(column, "_boundary_right_col", None)
            if left_col is None or right_col is None:
                ordered = [c for c in self._columns if c.isVisible()]
                try:
                    idx = ordered.index(column)
                except ValueError:
                    return
                left_col = None
                for j in range(idx - 1, -1, -1):
                    if not getattr(ordered[j], "is_individually_stowed", lambda: False)():
                        left_col = ordered[j]
                        break
                right_col = None
                for j in range(idx + 1, len(ordered)):
                    if not getattr(ordered[j], "is_individually_stowed", lambda: False)():
                        right_col = ordered[j]
                        break
            if left_col is None or right_col is None:
                return
        else:
            left_col = column
            right_col = getattr(column, "_boundary_right_col", None)
            if right_col is None or right_col not in self._columns:
                normals = [
                    c for c in self._columns
                    if c.isVisible()
                    and not getattr(c, "is_individually_stowed", lambda: False)()
                ]
                if column not in normals:
                    return
                idx = normals.index(column)
                if idx >= len(normals) - 1:
                    return
                right_col = normals[idx + 1]
            if getattr(right_col, "is_individually_stowed", lambda: False)():
                return

        if not hasattr(left_col, "_drag_base_width"):
            left_col._drag_base_width = left_col.get_width()
            right_col._drag_base_width = right_col.get_width()

        total = left_col._drag_base_width + right_col._drag_base_width
        new_left = max(AccountColumn.MIN_WIDTH, left_col._drag_base_width + delta)
        new_right = max(AccountColumn.MIN_WIDTH, right_col._drag_base_width - delta)

        if new_left + new_right > total:
            if delta > 0:
                new_left = total - AccountColumn.MIN_WIDTH
                new_right = AccountColumn.MIN_WIDTH
            else:
                new_left = AccountColumn.MIN_WIDTH
                new_right = total - AccountColumn.MIN_WIDTH

        self._boundary_pending = (left_col, new_left, right_col, new_right)
        timer = getattr(self, "_boundary_coalesce_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_boundary_pending)
            self._boundary_coalesce_timer = timer
        if not timer.isActive():
            timer.start(16)

    def _apply_boundary_pending(self) -> None:
        pending = getattr(self, "_boundary_pending", None)
        if not pending:
            return
        left_col, new_left, right_col, new_right = pending
        self._boundary_pending = None
        left_col.set_width(new_left, emit_signal=False)
        right_col.set_width(new_right, emit_signal=False)
        try:
            resized = getattr(self, "_boundary_user_resized_cids", None)
            if not isinstance(resized, set):
                resized = set()
            for col in (left_col, right_col):
                if col is None:
                    continue
                if getattr(col, "is_individually_stowed", lambda: False)():
                    continue
                try:
                    cid = col.get_column_id()
                except Exception:
                    cid = ""
                if cid:
                    resized.add(cid)
            self._boundary_user_resized_cids = resized
            if resized:
                pref = dict(getattr(self, "_preferred_widths", None) or {})
                for col in (left_col, right_col):
                    if col is None or getattr(col, "is_individually_stowed", lambda: False)():
                        continue
                    try:
                        cid = col.get_column_id()
                        live = int(col.get_width() or 0)
                    except Exception:
                        continue
                    if cid and live >= AccountColumn.MIN_WIDTH:
                        pref[cid] = float(live)
                self._preferred_widths = pref
                key = self._bound_layout_mode_key()
                if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                    self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
                mode_pref = dict(self._mode_preferred_widths.get(key) or {})
                mode_pref.update({cid: pref[cid] for cid in resized if cid in pref})
                self._mode_preferred_widths[key] = mode_pref
        except Exception:
            pass
        content = getattr(self, "_scroll_content", None)
        if content is not None and content.layout() is not None:
            content.layout().activate()
        # 列幅変更中も WE を新幅へ追従（境界ハンドルは覆わない）
        try:
            for col in (left_col, right_col):
                for wv in getattr(col, "webviews", lambda: [])() or []:
                    self._layout_safe_webview_geometry(wv)
        except Exception:
            pass

    def _on_boundary_drag_finished(self) -> None:
        timer = getattr(self, "_boundary_coalesce_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._apply_boundary_pending()
        for col in self._columns:
            if hasattr(col, "_drag_base_width"):
                del col._drag_base_width
        self._boundary_dragging = False
        self._boundary_pending = None
        try:
            self._sync_webviews_to_columns_layout_safe()
        except Exception:
            pass
        try:
            resized = getattr(self, "_boundary_user_resized_cids", None) or set()
            if resized:
                pref = dict(getattr(self, "_preferred_widths", None) or {})
                for col in list(getattr(self, "_columns", None) or []):
                    try:
                        cid = col.get_column_id()
                    except Exception:
                        continue
                    if not cid or cid not in resized:
                        continue
                    if getattr(col, "is_individually_stowed", lambda: False)():
                        continue
                    try:
                        live = int(col.get_width() or 0)
                    except Exception:
                        live = 0
                    if live >= AccountColumn.MIN_WIDTH:
                        pref[cid] = live
                self._preferred_widths = pref
                try:
                    key = self._bound_layout_mode_key()
                    if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                        self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
                    mode_pref = dict(self._mode_preferred_widths.get(key) or {})
                    mode_pref.update({cid: pref[cid] for cid in resized if cid in pref})
                    self._mode_preferred_widths[key] = mode_pref
                except Exception:
                    pass
            self._boundary_user_resized_cids = set()
        except Exception:
            self._boundary_user_resized_cids = set()
        self._save_column_widths()

    def _save_column_widths(self) -> None:
        if not self._settings_manager:
            return
        mode = self._bound_layout_mode_key()
        # preferred は表示pxではなく、ユーザー操作でのみ更新される相対 weight。
        # Dock/収納/展開/ウィンドウresizeで変化したlive幅を既存weightへ書き戻さない。
        try:
            self._ensure_mode_preferred_weights(mode, self._columns)
        except Exception:
            pass
        pref = dict(getattr(self, "_preferred_widths", None) or {})
        snap = dict(getattr(self, "_stow_saved_widths", None) or {})
        stowed = set(getattr(self, "_stowed_columns", None) or [])
        widths = {}
        by_account: dict[str, list[int]] = {}

        for col in self._columns:
            try:
                cid = col.get_column_id()
                aid = col.get_account_id()
            except Exception:
                continue
            if not cid:
                continue

            try:
                w = int(round(float(pref.get(cid) or 0)))
            except Exception:
                w = 0

            # preferred が無い旧データだけ一度seedする。以後はlive幅で上書きしない。
            if w < AccountColumn.MIN_WIDTH:
                if getattr(col, "is_individually_stowed", lambda: False)():
                    w = int(getattr(col, "_width_before_individual_stow", 0) or 0)
                elif col in stowed:
                    w = int(snap.get(cid) or 0)
                if w < AccountColumn.MIN_WIDTH:
                    try:
                        w = int(col.get_width() or 0)
                    except Exception:
                        w = 0
                if w >= AccountColumn.MIN_WIDTH:
                    pref[cid] = float(w)

            if w > 0:
                widths[cid] = int(w)
            if aid and w > 0:
                by_account.setdefault(aid, []).append(int(w))

        self._preferred_widths = pref
        try:
            if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._mode_preferred_widths[mode] = dict(pref)
        except Exception:
            pass

        for aid, ws in by_account.items():
            if len(ws) == 1 and ws[0] > 0:
                widths[aid] = ws[0]
        if hasattr(self._settings_manager, "save_column_widths_for_mode"):
            self._settings_manager.save_column_widths_for_mode(mode, widths)
        elif mode == "normal":
            self._settings_manager.save_column_widths(widths)

    def _save_accounts(self) -> None:
        if not self._settings_manager:
            return

        open_ids = {col.get_account_id() for col in self._columns}
        other_store = self._grok_columns if not self._grok_mode else self._twitter_columns

        accounts = []
        seen_ids = set()

        for col in self._columns:
            aid = col.get_account_id()
            if aid not in self._known_accounts:
                continue
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            reg = self._known_accounts.get(aid, {})
            accounts.append({
                "account_id": aid,
                "display_name": col.get_display_name() or reg.get("display_name", ""),
                "initial_url": reg.get("initial_url") or col.get_initial_url() or "https://x.com/",
                "enabled": col.is_enabled(),
                "open": True,
            })

        for col in other_store:
            aid = col.get_account_id()
            if aid not in self._known_accounts:
                continue
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            reg = self._known_accounts.get(aid, {})
            accounts.append({
                "account_id": aid,
                "display_name": col.get_display_name() or reg.get("display_name", ""),
                "initial_url": reg.get("initial_url") or col.get_initial_url() or "https://x.com/",
                "enabled": col.is_enabled(),
                "open": aid in open_ids,
            })

        for aid, info in self._known_accounts.items():
            if aid not in seen_ids:
                seen_ids.add(aid)
                accounts.append({
                    "account_id": aid,
                    "display_name": info.get("display_name", ""),
                    "initial_url": info.get("initial_url", "https://x.com/"),
                    "enabled": True,
                    "open": False,
                })

        self._settings_manager.save_accounts(accounts)
        self._save_columns()

    def _serialize_column_state(self, col, position: int, for_mode: str | None = None) -> dict:
        from src.core.models import migrate_column_type
        from uuid import uuid4
        aid = col.get_account_id()
        try:
            cid = (col.get_column_id() or "").strip()
        except Exception:
            cid = ""
        if not cid or cid == f"col_{aid}":
            cid = f"col_{aid}_{uuid4().hex[:10]}"
            try:
                col._column_id = cid
            except Exception:
                pass
        tabs_state = {"tabs": [], "active_tab": 0}
        try:
            if hasattr(col, "export_tabs_state"):
                tabs_state = col.export_tabs_state() or tabs_state
        except Exception:
            tabs_state = {"tabs": [], "active_tab": 0}
        tabs = list(tabs_state.get("tabs") or [])
        active = int(tabs_state.get("active_tab", 0) or 0)
        if not tabs:
            cur = ""
            try:
                cur = (col.get_current_tab_url() or "").strip()
            except Exception:
                cur = ""
            if not cur:
                cur = col.get_initial_url() or ""
            tabs = [{"url": cur}]
            active = 0
        active = max(0, min(active, len(tabs) - 1))
        cur_url = (tabs[active].get("url") or "").strip() if tabs else ""
        if not cur_url:
            try:
                cur_url = (col.get_current_tab_url() or "").strip()
            except Exception:
                cur_url = col.get_initial_url() or ""
        try:
            cid = (col.get_column_id() or cid).strip()
        except Exception:
            pass
        individually = False
        try:
            individually = bool(getattr(col, "is_individually_stowed", lambda: False)())
        except Exception:
            individually = False
        bulk_stowed = False
        try:
            # ←→一括収納のみ。個別収納とは別フラグ
            if not individually:
                key = for_mode or self._bound_layout_mode_key()
                if key == self._bound_layout_mode_key():
                    bulk_stowed = col in (getattr(self, "_stowed_columns", None) or [])
                else:
                    bulk_stowed = col in (
                        (getattr(self, "_mode_stowed_columns", None) or {}).get(key) or []
                    )
        except Exception:
            bulk_stowed = False
        # column stateにもlive表示幅ではなくpreferred weightを保存する。
        # これにより収納/展開/Dock切替後の一時px幅が次回起動の比率へ混入しない。
        width_out = 0
        try:
            mode = for_mode or self._bound_layout_mode_key()
            mode_pref = dict((getattr(self, "_mode_preferred_widths", None) or {}).get(mode) or {})
            if mode == self._bound_layout_mode_key():
                current_pref = dict(getattr(self, "_preferred_widths", None) or {})
                for k, v in current_pref.items():
                    mode_pref.setdefault(k, v)
            width_out = int(round(float(mode_pref.get(cid) or 0)))
        except Exception:
            width_out = 0
        if width_out < AccountColumn.MIN_WIDTH:
            try:
                width_out = int(getattr(col, "_width_before_individual_stow", 0) or 0)
            except Exception:
                width_out = 0
        if width_out < AccountColumn.MIN_WIDTH:
            try:
                snap = getattr(self, "_stow_saved_widths", None) or {}
                width_out = int(snap.get(cid) or 0)
            except Exception:
                width_out = 0
        if width_out < AccountColumn.MIN_WIDTH:
            try:
                width_out = max(1, int(col.get_width() or 0))
            except Exception:
                width_out = AccountColumn.DEFAULT_WIDTH
        return {
            "column_id": cid,
            "column_type": migrate_column_type(col.get_column_type()),
            "source_account_id": aid,
            "source_url": cur_url,
            "title": col.get_title() or col.get_display_name() or f"Column {position + 1}",
            "position": position,
            "width": width_out,
            "tabs": tabs,
            "active_tab": active,
            "stowed": bool(bulk_stowed),
            "individually_stowed": bool(individually),
        }

    def _save_columns(self) -> None:
        if not self._settings_manager:
            return
        if getattr(self, "_restoring_session", False):
            return

        def _pack_to_list(cols, mode: str) -> list:
            out = []
            seen = set()
            pos = 0
            for col in list(cols or []):
                try:
                    entry = self._serialize_column_state(col, pos, for_mode=mode)
                except Exception:
                    continue
                cid = (entry.get("column_id") or "").strip()
                if cid and cid in seen:
                    from uuid import uuid4
                    cid = f"{cid}_{uuid4().hex[:6]}"
                    entry["column_id"] = cid
                    try:
                        col._column_id = cid
                    except Exception:
                        pass
                if cid:
                    seen.add(cid)
                out.append(entry)
                pos += 1
            return out

        mode_data = {}
        packs = self._service_packs()
        active_key = self._bound_layout_mode_key()

        deferred = getattr(self, "_deferred_mode_configs", None) or {}
        for mode in ("normal", "lr", "tb"):
            cols = list((packs or {}).get(mode) or [])
            if mode == active_key:
                cols = list(self._columns)
            elif not cols and mode in deferred:
                # 未materializeのDock packもそのまま保存対象に含める。
                # 削除済み状態を空listとして保存でき、旧設定からの復活を防ぐ。
                mode_data[mode] = [
                    dict(item) for item in list(deferred.get(mode) or [])
                    if isinstance(item, dict)
                ]
                continue
            mode_data[mode] = _pack_to_list(cols, mode)

        try:
            if mode_data and hasattr(self._settings_manager, "save_columns_for_modes"):
                self._settings_manager.save_columns_for_modes(mode_data)
            else:
                for mode, data in mode_data.items():
                    if hasattr(self._settings_manager, "save_columns_for_mode"):
                        self._settings_manager.save_columns_for_mode(mode, data)
                    elif mode == "normal":
                        self._settings_manager.save_columns(data)
        except Exception:
            pass

        try:
            self._persist_stowed_state()
        except Exception:
            pass

    def _open_url_overlay_for(self, column: AccountColumn | None) -> None:
        import time as _time
        if column is None:
            return
        self._set_active_column(column)
        ov = self._url_overlay
        if ov is None:
            return

        if ov.is_open() or getattr(ov, "_mayotter_fading_out", False):

            if getattr(ov, "_column", None) is column:
                ov.close_overlay()
                self._url_overlay_closed_at = _time.monotonic()
                return
            ov.close_overlay()
        closed_at = float(getattr(self, "_url_overlay_closed_at", 0.0) or 0.0)
        if closed_at and (_time.monotonic() - closed_at) < 0.28:
            return
        ov.open_for(column)

    def _ask_external_site(self, url: str, page=None) -> bool:
        self._schedule_external_site_confirm(url, page)
        return False

    def _schedule_external_site_confirm(self, url: str, page=None) -> None:
        from PySide6.QtCore import QTimer

        url = (url or "").strip()
        if not url:
            return
        QTimer.singleShot(
            0,
            lambda u=url, p=page: self._show_external_site_confirm(u, p),
        )

    def _show_external_site_confirm(self, url: str, page=None) -> None:
        from src.ui.external_site_confirm_dialog import ExternalSiteConfirmDialog
        from src.browser.url_policy import open_in_default_browser

        existing = getattr(self, "_external_confirm_dialog", None)
        if existing is not None:
            try:
                if existing.isVisible():
                    return
            except Exception:
                pass

        url = (url or "").strip()
        if not url:
            return

        page_ref = page

        def _clear_pending():
            try:
                if getattr(self, "_external_confirm_dialog", None) is dlg:
                    self._external_confirm_dialog = None
            except Exception:
                pass

        dlg = ExternalSiteConfirmDialog(url, self)

        def _on_choice(choice: str):
            if choice == "browser":
                try:
                    open_in_default_browser(url)
                except Exception:
                    pass
            elif choice == "app":
                self._open_confirmed_external_in_app(url, page_ref)

        def _on_destroyed(*_a):
            _clear_pending()

        dlg.choiceMade.connect(_on_choice)
        try:
            dlg.destroyed.connect(_on_destroyed)
        except Exception:
            pass

        self._external_confirm_dialog = dlg
        dlg.show_with_fade()

    def _open_confirmed_external_in_app(self, url: str, page=None) -> None:
        from PySide6.QtCore import QUrl
        from src.browser.webview import MayotterPage

        url = (url or "").strip()
        if not url:
            return

        target_page = page
        target_view = None
        if target_page is not None:
            try:
                _ = target_page.objectName()
            except Exception:
                target_page = None
        if target_page is not None and isinstance(target_page, MayotterPage):
            try:
                target_page.mark_user_confirmed_external(url)
            except Exception:
                pass
            try:
                target_view = target_page.view() if hasattr(target_page, "view") else None
            except Exception:
                target_view = None

        if target_view is None:
            try:
                col = getattr(self, "_active_column", None)
                if col is not None and hasattr(col, "current_webview"):
                    target_view = col.current_webview()
            except Exception:
                target_view = None

        if target_view is None:
            return
        try:
            _ = target_view.objectName()
        except Exception:
            return

        try:
            opener = getattr(target_view, "tab_opener", None)
            if callable(opener):
                page2 = target_view.page()
                if isinstance(page2, MayotterPage):
                    page2.mark_user_confirmed_external(url)
                target_view.setUrl(QUrl(url))
                return
        except Exception:
            pass
        try:
            page2 = target_view.page()
            if isinstance(page2, MayotterPage):
                page2.mark_user_confirmed_external(url)
            target_view.setUrl(QUrl(url))
        except Exception:
            try:
                if hasattr(target_view, "load_url"):
                    page2 = target_view.page()
                    if isinstance(page2, MayotterPage):
                        page2.mark_user_confirmed_external(url)
                    target_view.load_url(url)
            except Exception:
                pass

    def _install_url_policy_handlers(self) -> None:
        try:
            from src.browser.webview import MayotterPage
            MayotterPage.ask_handler_async = self._schedule_external_site_confirm
            MayotterPage.ask_handler = self._ask_external_site
        except Exception:
            pass
        if self._settings_manager and hasattr(self._settings_manager, "get_external_site_policy"):
            try:
                from src.browser.url_policy import set_external_site_policy
                set_external_site_policy(self._settings_manager.get_external_site_policy())
            except Exception:
                pass

    def _restore_column_tabs(
        self,
        column: AccountColumn,
        tabs: list | None,
        active_tab: int = 0,
        *,
        defer_load_ms: int | None = None,
    ) -> None:
        if column is None:
            return
        raw_tabs = list(tabs or [])
        if not raw_tabs:
            return

        restored: list[tuple[str, str]] = []
        for item in raw_tabs:
            if isinstance(item, dict):
                url = (item.get("url") or "").strip()
                custom = (item.get("custom_name") or "").strip()
            else:
                url = (str(item) or "").strip()
                custom = ""
            if url.startswith("about:") or url.startswith("data:"):
                url = ""
            restored.append((url, custom))
        if not any(url for url, _ in restored):
            return

        aid = column.get_account_id()
        profile = self._profile_manager.get(aid)
        if profile is None:
            info = self._known_accounts.get(aid, {})
            profile = self._open_profile_for_account(
                aid,
                legacy_path=info.get("legacy_profile_path", "") or info.get("profile_path", ""),
                create=False,
            )
            if profile is None:
                return

        try:
            idx = int(active_tab or 0)
        except Exception:
            idx = 0
        idx = max(0, min(idx, len(restored) - 1))

        existing = column.tab_views()
        if existing:
            first_url, first_custom = restored[0]
            first = existing[0]
            if first_custom:
                first._custom_name = first_custom
            if first_url and not getattr(first, "_pending_restore_url", None):
                first._pending_restore_url = first_url

        for i, (url, custom) in enumerate(restored[1:], start=1):
            try:
                webview = XWebView(profile)
                if hasattr(webview, "download_progress"):
                    webview.download_progress.connect(self._on_download_progress)
                if custom:
                    webview._custom_name = custom
                if url:
                    webview._pending_restore_url = url
                    if defer_load_ms and i == idx:
                        webview._pending_restore_delay_ms = int(defer_load_ms) + i * 50
                column.add_tab_view(webview, activate=False)
            except Exception:
                pass

        try:
            idx = max(0, min(idx, column.tab_count() - 1))
            column.set_current_tab(idx)
        except Exception:
            pass

    def _on_new_tab_requested(self, url: str, column: AccountColumn | None = None) -> None:

        text = (url or "").strip()
        if not text or text.startswith("about:") or text.startswith("data:"):
            return
        try:
            from src.browser.url_policy import decide_navigation, open_in_default_browser
            action = decide_navigation(text)
        except Exception:
            action = "in_app"
        if action == "external_browser":
            try:
                open_in_default_browser(text)
            except Exception:
                pass
            return
        if action == "block":
            return
        if action == "ask":
            if not self._ask_external_site(text):
                return
        col = column if column is not None else self._active_column
        if col is None:
            return
        self._set_active_column(col)
        aid = col.get_account_id()
        profile = self._profile_manager.get(aid)
        if profile is None:
            info = self._known_accounts.get(aid, {})
            profile = self._open_profile_for_account(
                aid,
                legacy_path=info.get("legacy_profile_path", "") or info.get("profile_path", ""),
                create=False,
            )
            if profile is None:
                return
        webview = XWebView(profile)
        if hasattr(webview, "download_progress"):
            webview.download_progress.connect(self._on_download_progress)
        col.add_tab_view(webview)
        try:
            webview.load_url(text, restore=True)
        except TypeError:
            webview.load_url(text)
        except Exception:
            pass
        try:
            self._save_columns()
        except Exception:
            pass

    def _persist_download_history(self) -> None:
        if not self._settings_manager or self._download_overlay is None:
            return
        try:
            history = self._download_overlay.export_history()
            self._settings_manager.save_download_history(history)
        except Exception:
            pass

    def _ensure_download_history_restored(self) -> None:
        if getattr(self, "_download_history_restored", False):
            return
        self._download_history_restored = True
        self._restore_download_history()

    def _restore_download_history(self) -> None:
        if not self._settings_manager or self._download_overlay is None:
            return
        try:
            from src.ui.url_overlay import DownloadItem
            for entry in self._settings_manager.get_download_history():
                item = DownloadItem(
                    entry.get("file_path", ""),
                    entry.get("file_name", ""),
                    entry.get("mime_type", ""),
                )
                if entry.get("timestamp"):
                    item.timestamp = float(entry["timestamp"])
                self._download_overlay.add_download(item)
        except Exception:
            pass

    def _on_download_progress(self, download_id: str, file_name: str, file_path: str, progress: float, status: str) -> None:
        if not getattr(self, "_download_history_restored", False):
            self._ensure_download_history_restored()
        if self._download_icon_btn is not None:
            if status in ("started", "progress"):
                self._download_icon_btn.set_progress(progress)
            elif status == "completed":
                self._download_icon_btn.set_progress(1.0)
            elif status in ("cancelled", "failed"):
                self._download_icon_btn.reset_progress()

        if file_name and status in ("started", "progress", "completed", "cancelled", "failed"):
            from src.ui.url_overlay import DownloadItem
            item = DownloadItem(
                file_path or "",
                file_name,
                status=status,
                progress=progress if status in ("started", "progress") else (1.0 if status == "completed" else 0.0),
            )
            item.download_id = download_id or ""
            if self._download_overlay is not None:
                self._download_overlay.add_download(item)

        if status == "completed" and download_id not in self._download_seen_ids:
            self._download_seen_ids.add(download_id)
            if self._download_icon_btn is not None:
                self._download_icon_btn.increment_completed()
                try:
                    self._notify_dock_activity()
                except Exception:
                    pass
            self._persist_download_history()
