

from __future__ import annotations

import re

import ctypes
import sys

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
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt,
    QUrl,
    QEvent,
    QTimer,
    QPropertyAnimation,
    QVariantAnimation,
    QEasingCurve,
    QPoint,
    QRect,
    QSize,
    Signal,
    QObject,
    QAbstractNativeEventFilter,
)
from PySide6.QtGui import (
    QCursor,
    QAction,
    QGuiApplication,
    QRegion,
    QColor,
    QPainter,
    QPen,
    QPixmap,
    QKeySequence,
    QShortcut,
)

from src.browser.profile_manager import ProfileManager
from src.ui.account_column import AccountColumn
from src.browser.webview import XWebView
from src.ui.url_overlay import UrlOverlay, TextPromptOverlay, ConfirmOverlay, DownloadIconButton, DownloadOverlay, ColumnAddOverlay
from src.ui.icons import (
    make_settings_icon,
    make_close_icon, make_edit_icon,
    make_edge_dock_icon,
    make_minimize_icon,
    make_maximize_icon,
    make_restore_icon,
    make_stop_icon,
    make_mic_icon,
    make_chevron_left_icon,
    make_plus_icon,
)
from src.core.models import GROK_HOME_URL, Column
from src.ui.edge_dock import EdgeDetector, EdgeAnimator, PanelState

_WM_NCHITTEST = 0x0084
_WM_NCLBUTTONDBLCLK = 0x00A3
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
_HTCAPTION = 2

_RESIZE_MARGIN = 2

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
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            from src.ui.theme import overlay_stylesheet, SURFACE, BORDER, TEXT, TEXT_SECONDARY, RADIUS_MD
            self.setStyleSheet(
                overlay_stylesheet()
                + f"""
                QFrame#service_menu {{
                    background-color: {SURFACE};
                    border: 1px solid {BORDER};
                    border-radius: {RADIUS_MD}px;
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

                # windowOpacity
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

        from src.ui.url_overlay import rounded_overlay_mask
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        self.setMask(rounded_overlay_mask(w, h, self._corner_radius))

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
        edit_btn.setIcon(make_edit_icon("#93a5c4", 12))
        edit_btn.setIconSize(QSize(12, 12))
        edit_btn.setFixedSize(20, 20)
        edit_btn.setToolTip("名前を変更")
        edit_btn.clicked.connect(lambda checked=False, a=account: self.rename_requested.emit(a))
        row_layout.addWidget(edit_btn)

        del_btn = QToolButton()
        del_btn.setObjectName("service_menu_del_btn")
        del_btn.setText("")
        del_btn.setIcon(make_close_icon("#93a5c4", 10))
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

    def _on_row_clicked(self, account: dict) -> None:
        self.hide()
        self._pending_account = account
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

    def clear_profiles(self) -> None:
        for row in self._rows:
            self._profile_layout.removeWidget(row)
            _dispose_widget_no_toplevel(row)
        self._rows.clear()
        self._profile_accounts.clear()

class _TabChip(QWidget):

    selected = Signal()
    close_requested = Signal()
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
        self.close_btn.setText("\u2715")
        self.close_btn.setFixedSize(16, 16)
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
        self._badge_text = ""

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
        self._badge_text = text
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

class _TabStrip(QWidget):

    tab_selected = Signal(int)
    tab_close_requested = Signal(int)
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

        self._add_gap = QWidget(self)
        self._add_gap.setFixedWidth(5)
        self._add_gap.setFixedHeight(1)
        self._add_gap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._add_btn = QToolButton(self)
        self._add_btn.setObjectName("tab_add_btn")
        self._add_btn.setText("")
        self._add_btn.setIcon(make_plus_icon("#aeb6c5", 10))
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
            "  background: #0b111f;"
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
            item = self._layout.takeAt(0)
            w = item.widget()
        for i, c in enumerate(others):
            if i == insert_index:
                self._layout.addWidget(ph)
            self._layout.addWidget(c)
        if insert_index >= len(others):
            self._layout.addWidget(ph)
        self._layout.addStretch(1)
        src_chip = self._chips[src]
        if src_chip.isVisible() or src_chip.x() > -1000:
            src_chip.setVisible(False)
            src_chip.move(-10000, -10000)
        self._drop_line.raise_()

    def _compute_drop_index(self, global_x: float) -> int:
        src = self._drag_source_index
        count = 0
        for i, other in enumerate(self._chips):
            if i == src:
                continue
            if other.mapToGlobal(other.rect().topLeft()).x() + int(max(1, other.width()) / 3) < global_x:
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
        self._layout.addStretch(1)

class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_ulonglong),
        ("lParam", ctypes.c_longlong),
        ("time", ctypes.c_ulong),
        ("pt", ctypes.c_long * 2),
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

        if msg.message == _WM_ENTERSIZEMOVE:
            w = self._window
            if w is not None:
                w._os_sizing = True
            return False, 0
        if msg.message == _WM_EXITSIZEMOVE:
            w = self._window
            if w is not None and getattr(w, "_os_sizing", False):
                w._os_sizing = False
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
                        if hasattr(w, "_fit_columns"):
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
            return True, resize_code

        m = _RESIZE_MARGIN
        w, h = self._window.width(), self._window.height()
        return False, 0

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

        self.EDGE_DOCK_ANIMATION_DURATION = 150
        self.EDGE_DOCK_HOVER_LEAVE_DELAY = 200
        self.EDGE_DOCK_TRIGGER_WIDTH = 8
        self.EDGE_DOCK_ON_ANIMATION_DURATION = 200
        self.EDGE_DOCK_INDICATOR_WIDTH = 4
        self.EDGE_DOCK_KEEP_OPEN_MARGIN = 40
        self.EDGE_SWITCH_HYSTERESIS_PX = 40

        self._edge_dock_enabled = False
        self._edge_dock_direction = "right"
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
        self._edge_dock_candidate_edge: str | None = None
        self._edge_dir_anim: QVariantAnimation | None = None

        self._edge_dock_width_lr = 0
        self._edge_dock_height_lr = 0
        self._edge_dock_width_tb = 0
        self._edge_dock_height_tb = 0
        self._edge_dock_panel_height_ratio = 0.78

        self._edge_dock_reveal_progress = 0.0
        self._edge_dock_animating = False
        self._dock_geom_reenter = False
        self._dock_slide_proxy: QLabel | None = None
        self._dock_slide_use_proxy = False
        self._dock_collapse_chrome = False
        self._edge_dock_anim_cw = 0
        self._edge_dock_anim_ch = 0
        self._edge_dock_opaque_fill = False

        self._edge_dock_clip: QWidget | None = None
        self._edge_dock_root: QWidget | None = None

        self._edge_dock_animation: QPropertyAnimation | None = None
        self._edge_dock_leave_timer: QTimer | None = None
        self._edge_dock_hover_inside = False
        self._edge_dock_normal_geometry: QRect | None = None
        self._scroll_layout: QHBoxLayout | None = None
        self._current_service_menu: _ServiceMenu | None = None
        self._suspended_dock_popups: list[str] = []

        self._edge_dock_dragging = False
        self._edge_dock_drag_origin: QPoint | None = None
        self._edge_dock_drag_geom: QRect | None = None
        self._edge_dock_resizing = False
        self._os_sizing = False
        self._edge_dock_resize_edges = ""
        self._edge_dock_resize_origin: QPoint | None = None
        self._edge_dock_resize_geom: QRect | None = None
        self._edge_dock_edge_cursor_forced = False
        self._edge_cursor_forced = False
        self._mode_stowed_columns: dict[str, list] = {"normal": [], "lr": [], "tb": []}
        self._mode_stow_saved_widths: dict[str, dict] = {"normal": {}, "lr": {}, "tb": {}}
        self._stowed_columns: list = []
        self._stow_saved_widths: dict = {}
        self._bound_mode_key: str = "normal"
        self._pending_stow_ids: list = []
        self._stow_restore_rail = None
        self._stow_restore_rail_left = None
        self._StowRestoreKnobClass = None
        self._boundary_hand_cursor = False

        self._edge_detector: EdgeDetector | None = None
        self._edge_animator: EdgeAnimator | None = None

        self._download_seen_ids: set[str] = set()

        self._resize_filter = _RootHitTestFilter(self)
        QGuiApplication.instance().installNativeEventFilter(self._resize_filter)

        self.setWindowTitle("Mayotter")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        try:
            from src.browser.webview import attach_capture_holder_parent
            attach_capture_holder_parent(self)
        except Exception:
            pass
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setContentsMargins(1, 1, 1, 1)
        self.setMinimumSize(320, 240)

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
        except Exception:
            pass

        self._setup_ui()
        self._apply_theme()
        self._load_accounts()
        self._restore_download_history()
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
                local = self._top_bar.mapTo(self, event.position().toPoint())
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
                            ok = wh.startSystemResize(edges)
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

        self._tab_strip = _TabStrip()
        self._tab_strip_layout = self._tab_strip._layout
        self._tab_strip.tab_selected.connect(self._on_tab_chip_selected)
        self._tab_strip.tab_close_requested.connect(self._on_tab_chip_close)
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
        self._record_btn.setIcon(make_mic_icon("#9fb4d8", 14))
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
        self._edge_dock_toggle_btn.setIcon(make_edge_dock_icon("#aeb6c5", 12))
        self._edge_dock_toggle_btn.setIconSize(QSize(12, 12))
        self._edge_dock_toggle_btn.setToolTip("Dock を有効にする / 右クリックで収納位置")
        self._edge_dock_toggle_btn.clicked.connect(self._toggle_edge_dock)
        self._edge_dock_toggle_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._edge_dock_toggle_btn.customContextMenuRequested.connect(self._show_edge_dock_menu)
        top_bar_layout.addWidget(self._edge_dock_toggle_btn)

        self._dock_chrome_chevron = QToolButton()
        self._dock_chrome_chevron.setObjectName("dock_chrome_chevron")
        self._dock_chrome_chevron.setIcon(make_chevron_left_icon("#aeb6c5", 12))
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
        self._settings_btn.setIcon(make_settings_icon("#93a5c4", 14))
        self._settings_btn.setIconSize(QSize(14, 14))
        self._settings_btn.setFixedSize(24, 24)
        self._settings_btn.setToolTip("設定")
        self._settings_btn.clicked.connect(self._open_settings_dialog)
        tray_l.addWidget(self._settings_btn)

        top_bar_layout.addWidget(self._dock_chrome_tray)

        self._win_min_btn = QToolButton()
        self._win_min_btn.setObjectName("win_min_btn")
        self._win_min_btn.setText("")
        self._win_min_btn.setIcon(make_minimize_icon("#aeb6c5", 12))
        self._win_min_btn.setIconSize(QSize(12, 12))
        self._win_min_btn.setFixedSize(24, 24)
        self._win_min_btn.setToolTip("最小化")
        self._win_min_btn.clicked.connect(self.showMinimized)
        top_bar_layout.addWidget(self._win_min_btn)

        self._win_max_btn = QToolButton()
        self._win_max_btn.setObjectName("win_max_btn")
        self._win_max_btn.setText("")
        self._win_max_btn.setIcon(make_maximize_icon("#aeb6c5", 12))
        self._win_max_btn.setIconSize(QSize(12, 12))
        self._win_max_btn.setFixedSize(24, 24)
        self._win_max_btn.setToolTip("最大化")
        self._win_max_btn.clicked.connect(self._toggle_maximized)
        top_bar_layout.addWidget(self._win_max_btn)

        self._win_close_btn = QToolButton()
        self._win_close_btn.setObjectName("win_close_btn")
        self._win_close_btn.setText("")
        self._win_close_btn.setIcon(make_close_icon("#aeb6c5", 12))
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
        _cp.setColor(self._edge_dock_clip.backgroundRole(), QColor("#0b111f"))
        self._edge_dock_clip.setPalette(_cp)
        self._edge_dock_root = QWidget(self._edge_dock_clip)
        self._edge_dock_root.setObjectName("edgeDockRoot")
        self._edge_dock_root.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._edge_dock_root.setAutoFillBackground(True)
        _rp = self._edge_dock_root.palette()
        _rp.setColor(self._edge_dock_root.backgroundRole(), QColor("#0b111f"))
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
        self._init_boundary_action_overlay()

        self._setup_shortcuts()

    def _apply_theme(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background-color: #0f1117; }
            QMainWindow {
                background-color: #0f1117;
            }
            #top_bar {
                background-color: #0f1117;
                border-bottom: 1px solid #2b3242;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
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
            #column_resize_handle[hint="true"] #boundary_hint_bar {
                background-color: rgba(122, 158, 218, 0.18);
            }
            #boundary_hint_bar {
                background-color: transparent;
            }
            #url_bar {
                background-color: #181c26;
                border: 1px solid #232a38;
                border-radius: 6px;
                padding: 0 8px;
                color: #f1f3f7;
                selection-background-color: #2f517d;
            }
            #back_btn, #forward_btn, #reload_btn, #home_btn {
                background-color: transparent;
                border: none;
                color: #93a5c4;
                border-radius: 4px;
            }
            #back_btn:hover, #forward_btn:hover, #reload_btn:hover, #home_btn:hover {
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
                padding: 0 4px;
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
        """)

        QTimer.singleShot(0, self._update_window_mask)

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

    def _screen_at(self, pos: QPoint):
        for sc in QGuiApplication.screens():
            if sc.geometry().contains(pos):
                return sc
        return QGuiApplication.primaryScreen()

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

    def _expanded_geometry_for_edge(self, edge: str, size: QSize | None = None) -> QRect:
        screen = self._get_screen_geometry()
        size = size or self._panel_size_for_edge(edge)
        offset = float(self._edge_dock_edge_offset)
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
        offset = float(self._edge_dock_edge_offset)
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
        saved_offset = float(self._edge_dock_edge_offset)
        saved_offset = max(0.0, min(1.0, saved_offset))
        saved_monitor = int(getattr(self, "_edge_dock_monitor_index", 0) or 0)

        g = self.geometry()
        self._edge_dock_normal_geometry = QRect(g.x(), g.y(), g.width(), g.height())
        self._edge_dock_enabled = True
        self._edge_dock_direction = saved_direction
        self._edge_dock_edge_offset = saved_offset
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
        self.setGeometry(full)
        self._dock_shape_mask_key = None
        self._apply_dock_shape_mask(full.width(), full.height())
        self._apply_reveal_mask(1.0)

        self._setup_edge_detector()
        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
            self._edge_detector.set_state(PanelState.EXPANDED)
            self._edge_detector.start()

        self._set_interactive(True)
        self._set_window_opaque(True)
        self._update_edge_dock_column_visibility()
        try:
            self._set_dock_webengines_visible(True)
        except Exception:
            pass
        self._apply_dock_content_insets()
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
        self._edge_dock_revealed = False
        self._edge_dock_reveal_progress = 0.0
        self._edge_dock_animating = False
        try:
            self._update_stow_restore_rail()
        except Exception:
            pass

        if self._edge_dock_direction not in ("left", "right", "top", "bottom"):
            self._edge_dock_direction = self._detect_edge_dock_direction()
        self._edge_dock_edge_offset = self._calculate_edge_offset()

        full = self._expanded_geometry()
        self.setGeometry(full)
        try:
            self.setWindowOpacity(1.0)
        except Exception:
            pass
        self._dock_shape_mask_key = None
        self._apply_dock_shape_mask(full.width(), full.height())

        self._setup_edge_detector()

        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
        self._expand_edge_dock()
        QTimer.singleShot(1500, self._end_edge_dock_reveal_grace)

        self._edge_detector.start()

        try:
            self._ensure_dock_notify_timer()
            self._ensure_edge_dock_fs_timer()
        except Exception:
            pass
        try:
            self._schedule_dock_notify_refresh()
        except Exception:
            pass

        self._update_edge_dock_ui()
        self._save_edge_dock_settings()

    def _end_edge_dock_reveal_grace(self) -> None:
        if self._edge_dock_enabled and self._edge_detector:
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

    def _calculate_edge_offset(self) -> float:
        screen = QGuiApplication.screenAt(self.pos())
        if not screen:
            screen = QGuiApplication.primaryScreen()
        geom = screen.availableGeometry()
        center = self.geometry().center()

        direction = self._edge_dock_direction
        if direction == "left":
            return (center.y() - geom.top()) / geom.height()
        elif direction == "right":
            return (center.y() - geom.top()) / geom.height()
        elif direction == "top":
            return (center.x() - geom.left()) / geom.width()
        else:
            return (center.x() - geom.left()) / geom.width()

    def _stop_edge_dock(self) -> None:
        if not self._edge_dock_enabled:
            return

        try:
            self._save_columns()
            self._save_column_widths()
            if self._settings_manager and hasattr(self._settings_manager, "save_window_geometry_dock"):
                self._settings_manager.save_window_geometry_dock(self.saveGeometry())
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

        try:
            self.setUpdatesEnabled(False)
            self._set_dock_content_updates(False)
        except Exception:
            pass
        try:
            if self._edge_dock_clip and self._edge_dock_root:
                cg = QRect(0, 0, max(1, self._edge_dock_clip.width()), max(1, self._edge_dock_clip.height()))
                self._edge_dock_root.setGeometry(cg)
            self._set_window_opaque(True)
            self._set_interactive(True)

            g = self._edge_dock_normal_geometry
            self._edge_dock_normal_geometry = None
            if g is None and self._settings_manager and hasattr(self._settings_manager, "get_window_geometry_normal"):
                try:
                    raw = self._settings_manager.get_window_geometry_normal()
                    if raw:

                        self.restoreGeometry(raw)
                        g = None
                except Exception:
                    g = None
            if g is not None:

                try:
                    self.setGeometry(g.x(), g.y(), g.width(), g.height())
                except Exception:
                    pass
            self._apply_mode_column_visibility()
            try:
                self._set_dock_webengines_visible(True)
            except Exception:
                pass
            self._window_mask_key = None
            self._window_mask_pending = False
            self._update_window_mask()

            handle = self.windowHandle()
            if handle is not None and bool(handle.flags() & Qt.WindowType.WindowStaysOnTopHint):
                handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                if sys.platform == "win32":
                    try:
                        import ctypes
                        hwnd = int(self.winId())
                        if hwnd:
                            ctypes.windll.user32.SetWindowPos(
                                hwnd, -2, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010,
                            )
                    except Exception:
                        pass
        finally:
            try:
                self._set_dock_content_updates(True)
                self.setUpdatesEnabled(True)
            except Exception:
                pass

        self._update_edge_dock_ui()
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
                from PySide6.QtGui import QColor, QPalette
                pal = menu.palette()
                for role in (
                    QPalette.ColorRole.WindowText,
                    QPalette.ColorRole.Text,
                    QPalette.ColorRole.ButtonText,
                ):
                    pal.setColor(role, QColor("#f1f3f7"))
                pal.setColor(QPalette.ColorRole.Window, QColor("#181c26"))
                pal.setColor(QPalette.ColorRole.Base, QColor("#0f1117"))
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

    def _set_edge_dock_direction(self, direction: str) -> None:
        if direction not in ("left", "right", "top", "bottom"):
            return
        if self._edge_animator is not None:
            self._edge_animator.stop()
        self._edge_dock_animating = False
        self._edge_dock_profile_lock = True
        self._edge_dock_geom_start = None
        self._edge_dock_geom_end = None
        self._edge_dock_direction = direction
        if self._edge_detector:
            self._edge_detector.set_params(edge=direction)
        if self._edge_dock_enabled:
            self._dock_shape_mask_key = None
            self._clear_collapse_slide_proxy()
            root = getattr(self, "_edge_dock_root", None)
            if root is not None and not root.isVisible():
                root.show()
            if self._edge_dock_revealed:
                size = self._panel_size_for_edge(direction)
                full = self._expanded_geometry_for_edge(direction, size)
                profile = "TB" if direction in ("top", "bottom") else "LR"
                self.setGeometry(full)
                self._edge_dock_anim_cw = max(1, full.width())
                self._edge_dock_anim_ch = max(1, full.height())
                if root is not None:
                    root.setGeometry(0, 0, full.width(), full.height())
                clip = getattr(self, "_edge_dock_clip", None)
                if clip is not None:
                    clip.setGeometry(0, 0, full.width(), full.height())
                self._edge_dock_reveal_progress = 1.0
                self._apply_reveal_mask(1.0)
                self._fit_columns()
            else:
                collapsed = self._collapsed_geometry()
                self.setGeometry(collapsed)
                self._edge_dock_reveal_progress = 0.0
                root = getattr(self, "_edge_dock_root", None)
                clip = getattr(self, "_edge_dock_clip", None)
                if root is not None and clip is not None:
                    cg = QRect(0, 0, max(1, collapsed.width()), max(1, collapsed.height()))
                    clip.setGeometry(cg)
                    root.setGeometry(cg)
        self._edge_dock_column_count = self._column_count_for_edge(direction)
        if self._edge_dock_revealed:
            self._update_edge_dock_column_visibility()
            try:
                self._set_dock_content_updates(True)
                self._set_dock_webengines_visible(True)
            except Exception:
                pass
            self._dock_shape_mask_wh = None
            self._apply_dock_shape_mask()
        self._edge_dock_profile_lock = False
        self._save_edge_dock_settings()
        self._update_edge_dock_ui()
        self._apply_edge_dock_always_on_top()
        self._apply_edge_dock_zoom()

    def _toggle_edge_dock(self) -> None:
        if self._edge_dock_enabled:
            self._stop_edge_dock()
        else:
            self._start_edge_dock()
        self._save_edge_dock_settings()

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
        bg_color = QColor("#0b111f")
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        dirty = event.rect()
        if self._edge_dock_animating and getattr(self, "_dock_window_lerp", False):
            p.end()
            return
        if getattr(self, "_edge_dock_opaque_fill", False) or self._edge_dock_revealed or self._edge_dock_animating:
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

    def _apply_reveal_mask(self, t: float) -> None:
        t = max(0.0, min(1.0, float(t)))
        self._edge_dock_reveal_progress = t

        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        if root is None or clip is None:
            return

        ind = self.EDGE_DOCK_INDICATOR_WIDTH
        edge = self._edge_dock_direction

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
                    if abs(cg.width() - g.width()) >= 3 or abs(cg.height() - g.height()) >= 3:
                        self._apply_dock_shape_mask(g.width(), g.height())
                    try:
                        import time as _time
                        n = int(getattr(self, "_dock_anim_frame_n", 0)) + 1
                        self._dock_anim_frame_n = n
                        t0 = float(getattr(self, "_dock_anim_t0", 0.0) or 0.0)
                        if t0 <= 0.0:
                            self._dock_anim_t0 = _time.monotonic()
                        elif n % 8 == 0:
                            elapsed = _time.monotonic() - t0
                    except Exception:
                        pass
                fw, fh = max(1, g.width()), max(1, g.height())
                if clip.geometry() != QRect(0, 0, fw, fh):
                    clip.setGeometry(0, 0, fw, fh)
                if not root.isVisible():
                    root.show()
                if root.geometry() != QRect(0, 0, fw, fh):
                    root.setGeometry(0, 0, fw, fh)
            if getattr(self, "_dock_expand_we_pending", False) and t >= 0.40:
                self._dock_expand_we_pending = False
                try:
                    if max(1, self.width()) > self.EDGE_DOCK_INDICATOR_WIDTH * 4:
                        self._fit_columns()
                except Exception:
                    pass
                self._set_dock_content_updates(True)
                self._set_dock_webengines_visible(True)
                self._apply_edge_dock_zoom()
            return

        fw = max(1, self.width())
        fh = max(1, self.height())
        if clip.geometry() != QRect(0, 0, fw, fh):
            clip.setGeometry(0, 0, fw, fh)
        if root.size() != QSize(fw, fh) or root.pos() != QPoint(0, 0):
            root.setGeometry(0, 0, fw, fh)
    def _clear_collapse_slide_proxy(self) -> None:
        self._dock_slide_use_proxy = False
        self._dock_collapse_chrome = False
        self._edge_dock_expand_lerp = False
        self._dock_window_lerp = False
        self._dock_expand_we_pending = False
        self._dock_anim_frame_n = 0
        self._dock_anim_t0 = 0.0
        self._dock_slide_full_geom = None
        self._dock_slide_strip_geom = None
        proxy = getattr(self, "_dock_slide_proxy", None)
        self._dock_slide_proxy = None
        if proxy is not None:
            _dispose_widget_no_toplevel(proxy)

    def _expand_edge_dock(self) -> None:
        if self._edge_dock_revealed or self._edge_dock_animating:
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
        strip = QRect(self.geometry())
        if (
            strip.width() <= self.EDGE_DOCK_INDICATOR_WIDTH * 4
            or strip.height() <= self.EDGE_DOCK_INDICATOR_WIDTH * 4
        ):
            strip = QRect(self._collapsed_geometry())
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        self._dock_shape_mask_wh = None
        self._dock_slide_full_geom = QRect(full)
        self._dock_slide_strip_geom = QRect(strip)
        self._edge_dock_anim_cw = max(1, full.width())
        self._edge_dock_anim_ch = max(1, full.height())
        self._dock_window_lerp = True
        self._dock_expand_we_pending = True
        self._dock_anim_frame_n = 0
        self._dock_anim_t0 = 0.0
        self._set_window_opaque(True)

        if not self.isVisible():
            self.show()
        self._edge_dock_column_count = self._column_count_for_edge()
        count = min(self._edge_dock_column_count, max(1, len(self._columns)))
        stowed_set = self._stowed_column_set()
        for i, col in enumerate(self._columns):
            if i < count and col not in stowed_set:
                col.show()
            else:
                col.hide()
        root = getattr(self, "_edge_dock_root", None)
        if root is not None and not root.isVisible():
            root.show()
        # WebEngine は hide せず updates だけ止める（setVisible(False) は再表示時の黒画面が長い）
        self._set_dock_content_updates(False)

        if self.geometry() != strip:
            self.setGeometry(strip)
        self._apply_dock_shape_mask(strip.width(), strip.height())
        self._apply_reveal_mask(0.0)
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
        for col in self._columns:
            try:
                if not visible:
                    for wv in getattr(col, "webviews", lambda: [])():
                        wv.setVisible(False)
                else:
                    if hasattr(col, "_enforce_single_visible_tab"):
                        col._enforce_single_visible_tab()
                    else:
                        tabs = list(getattr(col, "webviews", lambda: [])())
                        cur = int(getattr(col, "_current_tab", 0) or 0)
                        if tabs:
                            cur = max(0, min(cur, len(tabs) - 1))
                        for i, wv in enumerate(tabs):
                            wv.setVisible(i == cur)
            except Exception:
                pass

    def _collapse_edge_dock(self) -> None:
        if not self._edge_dock_revealed or self._edge_dock_animating:
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
        self._dock_shape_mask_wh = None
        self._clear_collapse_slide_proxy()

        self._store_live_size(self.width(), self.height(), self._edge_dock_direction)
        self._snap_to_dock_edge()
        live = QRect(self.geometry())
        self._dock_slide_full_geom = QRect(live)
        self._dock_slide_strip_geom = QRect(self._collapsed_geometry())
        self._edge_dock_anim_cw = max(1, live.width())
        self._edge_dock_anim_ch = max(1, live.height())
        self._dock_window_lerp = True
        self._dock_expand_we_pending = False
        self._dock_anim_frame_n = 0
        self._dock_anim_t0 = 0.0

        self._set_window_opaque(True)
        self._set_dock_content_updates(False)

        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        if root is not None and not root.isVisible():
            root.show()
        if clip is not None:
            clip.setGeometry(0, 0, live.width(), live.height())
        if root is not None:
            root.setGeometry(0, 0, live.width(), live.height())

        self._apply_dock_shape_mask(live.width(), live.height())
        self._apply_reveal_mask(1.0)
        self._edge_animator.animate_reveal(1.0, 0.0, self._edge_animator.collapse_duration, False)

    def _on_expand_finished(self) -> None:
        self._dock_window_lerp = False
        self._dock_expand_we_pending = False
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
        self._apply_reveal_mask(1.0)
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
                    parent = wv.parentWidget()
                    if parent is None or not parent.size().isValid():
                        continue
                    r = parent.rect()
                    if r.width() <= 0 or r.height() <= 0:
                        continue
                    if wv.geometry() != r:
                        wv.setGeometry(r)
        except Exception:
            pass
        # bind 後の _columns (lr/tb) に対して updates / WebEngine 表示を適用する
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
        except Exception:
            pass
        # fit / WebEngine geometry 確定後に境界を再同期（切替直後の 0 高さ handle を防ぐ）
        try:
            self._update_boundary_visibility()
        except Exception:
            pass
        self._apply_dock_shape_mask()
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
        try:
            import sys
            if sys.platform != "win32":
                return False
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            try:
                our = int(self.winId())
                if hwnd == our:
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
            mon = user32.MonitorFromWindow(hwnd, 2)
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                return False
            mw = int(mi.rcMonitor.right - mi.rcMonitor.left)
            mh = int(mi.rcMonitor.bottom - mi.rcMonitor.top)
            if mw <= 0 or mh <= 0:
                return False
            return (ww >= int(mw * 0.97)) and (hh >= int(mh * 0.97))
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
            if self._edge_dock_revealed and not self._edge_dock_animating:
                self._collapse_edge_dock()
        except Exception:
            pass
        # 最前面だけ外す。MainWindow 全体の hide はせず、通常の収納 strip として残す
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
                collapsed = self._collapsed_geometry()
                if self.geometry() != collapsed:
                    self.setGeometry(collapsed)
                self._apply_dock_shape_mask(collapsed.width(), collapsed.height())
        except Exception:
            pass
        try:
            self._update_dock_notify_visual()
        except Exception:
            pass

    def _on_collapse_finished(self) -> None:
        self._dock_window_lerp = False
        self._dock_expand_we_pending = False
        self._clear_collapse_slide_proxy()
        self._edge_dock_animating = False
        self._edge_dock_anim_cw = self._edge_dock_anim_ch = 0
        self._edge_dock_revealed = False
        self._edge_detector.set_state(PanelState.COLLAPSED)
        self._edge_dock_reveal_progress = 0.0
        # 収納中も WebEngine は hide しない（再展開時の setVisible コストを避ける）
        # updates は止めたまま。カラムも非 stow は表示したまま 4px にクリップされる
        self._set_dock_content_updates(False)
        try:
            stowed_set = self._stowed_column_set()
        except Exception:
            stowed_set = set()
        for col in self._columns:
            if col in stowed_set:
                col.hide()
        collapsed = self._collapsed_geometry()
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)
        if self.geometry() != collapsed:
            self.setGeometry(collapsed)
        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        if root is not None and clip is not None:
            cg = QRect(0, 0, max(1, collapsed.width()), max(1, collapsed.height()))
            clip.setGeometry(cg)
            root.setGeometry(cg)
        self._dock_shape_mask_key = None
        self._apply_dock_shape_mask(collapsed.width(), collapsed.height())
        self._set_window_opaque(True)
        self._set_interactive(False)
        try:
            self._schedule_dock_notify_refresh()
        except Exception:
            try:
                self._update_dock_notify_visual()
            except Exception:
                pass

    def _force_dark_scrollbars(self, area) -> None:
        from PySide6.QtGui import QPalette, QColor
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
                dark = QColor("#141820")
                thumb = QColor("#3d4a5e")
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
        w = _DockNotifySphereWidget(diameter=d, color=getattr(self, "_DOCK_NOTIFY_COLOR", "#5b8fd6"))
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
        g = self.geometry()
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
                from ctypes import wintypes
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
        if self._edge_dock_enabled and self._edge_dock_revealed:
            if self._edge_dock_direction in ("top", "bottom"):
                return "tb"
            return "lr"
        return "normal"

    def _service_packs(self) -> dict:
        return self._grok_packs if self._grok_mode else self._twitter_packs

    def _active_column_count(self) -> int:
        key = self._layout_mode_key()
        if key == "tb":
            return max(1, int(self._edge_dock_column_count_tb))
        if key == "lr":
            return max(1, int(self._edge_dock_column_count_lr))
        n = len(getattr(self, "_columns", None) or [])
        if n > 0:
            return n
        return max(1, int(getattr(self, "_normal_column_count", 1) or 1))

    def _sync_count_from_active_list(self) -> None:
        key = self._layout_mode_key()
        n = max(0, len(self._columns))
        if key == "tb":
            self._edge_dock_column_count_tb = max(1, n) if n else 1
            self._edge_dock_column_count = self._edge_dock_column_count_tb
        elif key == "lr":
            self._edge_dock_column_count_lr = max(1, n) if n else 1
            self._edge_dock_column_count = self._edge_dock_column_count_lr
        else:
            self._normal_column_count = max(1, n) if n else 1
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
        from src.browser.webview import XWebView

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
        column.resized.connect(lambda w: self._save_column_widths())
        column.enabled_changed.connect(lambda e: self._save_accounts())
        column.boundary_dragged.connect(lambda delta, c=column: self._on_boundary_dragged(c, delta))
        column.boundary_drag_finished.connect(self._on_boundary_drag_finished)
        column.stow_right_requested.connect(self._stow_columns_right_of)
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
        if len(lst) >= target:
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
        ]
        stowed_set = set(mode_stowed)

        # 同一 mode / 同一リストなら layout の takeAt+hide+再追加を避け、WebEngine の再アタッチを防ぐ
        if (
            prev_key == key
            and getattr(self, "_columns", None) is new_list
            and getattr(self, "_bound_mode_key", None) == key
        ):
            self._stowed_columns = mode_stowed
            self._mode_stowed_columns[key] = list(mode_stowed)
            self._stow_saved_widths = dict(self._mode_stow_saved_widths.get(key) or {})
            if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._preferred_widths = dict(self._mode_preferred_widths.get(key) or {})
            for col in self._columns:
                if col in stowed_set:
                    col.hide()
                elif not col.isVisible():
                    col.show()
            if not getattr(self, "_edge_dock_animating", False):
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

        for col in self._columns:
            self._scroll_layout.addWidget(col)
            if col in stowed_set:
                col.hide()
            else:
                col.show()

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

        if not getattr(self, "_edge_dock_animating", False):
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
        on = bool(self._edge_dock_always_on_top)
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
        m = 5
        dock = self._edge_dock_direction
        if pos.x() <= m and dock != "left":
            e += "L"
        elif pos.x() >= r.width() - m and dock != "right":
            e += "R"
        if pos.y() <= m and dock != "top":
            e += "T"
        elif pos.y() >= r.height() - m and dock != "bottom":
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

    def _edge_target_geometry(self, edge: str, top_left: QPoint, screen: QRect) -> QRect:
        psz = self._panel_size_for_edge(edge)
        size = QSize(psz.width(), psz.height())
        if edge in ("left", "right"):
            x = screen.left() if edge == "left" else screen.right() - size.width() + 1
            y = max(screen.top(), min(screen.bottom() - size.height() + 1, top_left.y()))
            return QRect(x, y, size.width(), size.height())
        y = screen.top() if edge == "top" else screen.bottom() - size.height() + 1
        x = max(screen.left(), min(screen.right() - size.width() + 1, top_left.x()))
        return QRect(x, y, size.width(), size.height())

    def _start_edge_direction_transition(
        self, new_edge: str, top_left: QPoint, screen: QRect
    ) -> None:
        if getattr(self, "_edge_dock_dir_transitioning", False):
            return
        target = self._edge_target_geometry(new_edge, top_left, screen)
        start = QRect(self.geometry())
        if start == target:
            self._finish_edge_direction_transition(new_edge, target)
            return

        prev_anim = getattr(self, "_edge_dir_anim", None)
        if prev_anim is not None:
            try:
                prev_anim.stop()
            except Exception:
                pass
            self._edge_dir_anim = None

        self._edge_dock_dir_transitioning = True
        self._edge_dock_candidate_edge = new_edge
        self._edge_dock_profile_lock = True
        self._edge_dock_direction = new_edge
        if self._edge_detector:
            self._edge_detector.set_params(edge=new_edge)
        if new_edge in ("left", "right"):
            usable = max(1, screen.height() - target.height())
            self._edge_dock_edge_offset = max(
                0.0, min(1.0, (top_left.y() - screen.top()) / usable)
            )
        else:
            usable = max(1, screen.width() - target.width())
            self._edge_dock_edge_offset = max(
                0.0, min(1.0, (top_left.x() - screen.left()) / usable)
            )
        self._edge_dock_column_count = self._column_count_for_edge(new_edge)

        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(max(120, min(280, int(self.EDGE_DOCK_ANIMATION_DURATION))))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_edge_direction_frame)
        anim.finished.connect(
            lambda e=new_edge, g=QRect(target): self._finish_edge_direction_transition(e, g)
        )
        self._edge_dir_anim = anim
        anim.start()

    def _on_edge_direction_frame(self, value) -> None:
        if not isinstance(value, QRect):
            return
        self.setGeometry(value)
        root = getattr(self, "_edge_dock_root", None)
        clip = getattr(self, "_edge_dock_clip", None)
        if clip is not None:
            clip.setGeometry(0, 0, max(1, value.width()), max(1, value.height()))
        if root is not None:
            root.setGeometry(0, 0, max(1, value.width()), max(1, value.height()))

    def _finish_edge_direction_transition(self, edge: str, geom: QRect) -> None:
        self._edge_dock_direction = edge
        self._edge_dock_candidate_edge = None
        self._edge_dock_dir_transitioning = False
        self._edge_dock_profile_lock = True
        try:
            if self.geometry() != geom:
                self.setGeometry(geom)
            root = getattr(self, "_edge_dock_root", None)
            clip = getattr(self, "_edge_dock_clip", None)
            if clip is not None:
                clip.setGeometry(0, 0, max(1, geom.width()), max(1, geom.height()))
            if root is not None:
                root.setGeometry(0, 0, max(1, geom.width()), max(1, geom.height()))
            self._apply_reveal_mask(1.0 if self._edge_dock_revealed else 0.0)
            self._dock_shape_mask_wh = None
            self._dock_shape_mask_key = None
            self._apply_dock_shape_mask(geom.width(), geom.height())
            if self._edge_dock_revealed:
                self._apply_mode_column_visibility()
                self._enforce_all_columns_single_tab()
        finally:
            self._edge_dock_profile_lock = False
        self._edge_dir_anim = None
        self._save_edge_dock_settings()
        self._update_edge_dock_ui()

    def _follow_drag(self, top_left: QPoint) -> None:
        if getattr(self, "_edge_dock_dir_transitioning", False):
            return

        prev = self._edge_dock_direction
        cursor = QCursor.pos()
        sc = self._screen_at(cursor)
        screen = sc.availableGeometry()

        screens = QGuiApplication.screens()
        if sc in screens:
            self._edge_dock_monitor_index = screens.index(sc)

        dl = max(0, cursor.x() - screen.left())
        dr = max(0, screen.right() - cursor.x())
        dt = max(0, cursor.y() - screen.top())
        db = max(0, screen.bottom() - cursor.y())
        dists = {"left": dl, "right": dr, "top": dt, "bottom": db}
        nearest = min(dists, key=dists.get)
        hyst = int(getattr(self, "EDGE_SWITCH_HYSTERESIS_PX", 40))
        ordered = sorted(dists.values())
        in_corner = len(ordered) >= 2 and ordered[1] < 110
        need = hyst + (56 if in_corner else 0)
        if prev in dists:
            if nearest != prev and dists[nearest] + need < dists[prev]:
                edge = nearest
            else:
                edge = prev
        else:
            edge = nearest

        if edge != prev:
            self._start_edge_direction_transition(edge, top_left, screen)
            return

        size = self.size()
        self._edge_dock_profile_lock = True
        try:
            if edge in ("left", "right"):
                usable = max(1, screen.height() - size.height())
                offset = (top_left.y() - screen.top()) / usable
                x = screen.left() if edge == "left" else screen.right() - size.width() + 1
                y = max(screen.top(), min(screen.bottom() - size.height() + 1, top_left.y()))
                self.setGeometry(QRect(x, y, size.width(), size.height()))
            else:
                usable = max(1, screen.width() - size.width())
                offset = (top_left.x() - screen.left()) / usable
                y = screen.top() if edge == "top" else screen.bottom() - size.height() + 1
                x = max(screen.left(), min(screen.right() - size.width() + 1, top_left.x()))
                self.setGeometry(QRect(x, y, size.width(), size.height()))
        finally:
            self._edge_dock_profile_lock = False

        offset = max(0.0, min(1.0, offset))
        self._edge_dock_edge_offset = offset
        if self._edge_detector:
            self._edge_detector.set_params(edge=edge)

    def _update_edge_dock_ui(self) -> None:
        from PySide6.QtWidgets import QSizePolicy

        if hasattr(self, "_edge_dock_toggle_btn"):
            btn = self._edge_dock_toggle_btn
            if self._edge_dock_enabled:
                btn.setText("")
                btn.setIcon(make_edge_dock_icon("#f1f3f7", 14))
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
                btn.setIcon(make_edge_dock_icon("#aeb6c5", 12))
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

        dock_order = [
            getattr(self, "_add_twitter_btn", None),
            getattr(self, "_add_column_btn", None),
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
        from src.ui.icons import make_reset_widths_icon, make_stow_left_icon, make_stow_right_icon
        from PySide6.QtGui import QPainter, QColor, QPen

        self._boundary_action_col = None
        self._boundary_gap_active = None
        self._boundary_gap_lock = False
        self._boundary_reset_btn = None
        self._boundary_stow_btn = None
        self._boundary_action_film = None

        self._boundary_icon_stow_left = make_stow_left_icon("#9fb4d8", 14)
        self._boundary_icon_stow_right = make_stow_right_icon("#9fb4d8", 14)
        self._boundary_icon_stow = self._boundary_icon_stow_right
        self._boundary_icon_reset = make_reset_widths_icon("#9fb4d8", 14)

        class _BoundaryInteractionOverlay(QWidget):
            def __init__(self, owner):
                super().__init__(owner)
                self._owner = owner
                self._t = 0.0
                self._cx = 0
                self._top = 0
                self._bot = 0
                self._stow_left_rect = None
                self._stow_right_rect = None
                self._stow_rect = None
                self._reset_rect = None
                self._press_on_action = False
                self._breathe = 0.0
                self.setObjectName("boundary_interaction_overlay")
                self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self.setMouseTracking(True)
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.setEnabled(True)
                self._breathe_anim = QVariantAnimation(self)
                self._breathe_anim.setDuration(1800)
                self._breathe_anim.setStartValue(0.0)
                self._breathe_anim.setEndValue(1.0)
                self._breathe_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
                self._breathe_anim.setLoopCount(-1)
                self._breathe_anim.valueChanged.connect(self._on_breathe)
                try:
                    self.winId()
                except Exception:
                    pass

            def _on_breathe(self, value) -> None:
                try:
                    self._breathe = float(value)
                except (TypeError, ValueError):
                    self._breathe = 0.0
                if self._t > 0.5 and self.isVisible():
                    self.update()

            def _sync_breathe(self) -> None:
                anim = getattr(self, "_breathe_anim", None)
                if anim is None:
                    return
                if self._t >= 0.95 and self.isVisible():
                    if anim.state() != QVariantAnimation.State.Running:
                        anim.start()
                else:
                    if anim.state() == QVariantAnimation.State.Running:
                        anim.stop()
                    self._breathe = 0.0

            def set_state(self, cx: int, top: int, bot: int, t: float) -> None:
                self._cx = int(cx)
                self._top = int(top)
                self._bot = int(bot)
                self._t = max(0.0, min(1.0, float(t)))
                self._refresh_action_rects()
                self._sync_breathe()
                self.update()

            def _layout_metrics(self):
                t = self._t
                btn = 22
                fixed_w = 52
                if fixed_w % 2:
                    fixed_w += 1
                h = max(40, self._bot - self._top)
                return t, btn, fixed_w, h

            def _get_action_rects(self, w: int, h: int, t: float, btn: int = 22):
                from PySide6.QtCore import QRect
                if t <= 0.02 or w < 4 or h < 20:
                    return None, None, None
                s = min(max(26, btn + 6), max(26, (w - 6) // 2), max(26, h // 5))
                margin = 6
                gap = 2
                stow_y = margin
                reset_y = h - s - margin
                if reset_y < stow_y + s + 8:
                    reset_y = stow_y + s + 8
                if reset_y + s > h:
                    reset_y = max(0, h - s)
                pair = s * 2 + gap
                left_x = max(0, (w - pair) // 2)
                right_x = left_x + s + gap
                reset_x = max(0, min(w - s, (w - s) // 2))
                return (
                    QRect(left_x, stow_y, s, s),
                    QRect(right_x, stow_y, s, s),
                    QRect(reset_x, reset_y, s, s),
                )

            def _get_visual_rects(self, hits, t: float, btn: int = 22):
                from PySide6.QtCore import QRect
                if not hits or any(h is None for h in hits):
                    return tuple(None for _ in (hits or (None, None, None)))
                scale = 0.94 + 0.06 * t
                b = float(getattr(self, "_breathe", 0.0) or 0.0)
                tri = 1.0 - abs(2.0 * b - 1.0)
                scale *= 0.985 + 0.015 * tri
                vs = max(14, int(round(btn * scale)))
                out = []
                for hit in hits:
                    vs2 = min(vs, hit.width() - 2, hit.height() - 2)
                    if vs2 < 10:
                        out.append(hit)
                        continue
                    x = hit.x() + (hit.width() - vs2) // 2
                    y = hit.y() + (hit.height() - vs2) // 2
                    out.append(QRect(x, y, vs2, vs2))
                return tuple(out)

            def _refresh_action_rects(self) -> None:
                t, btn, fixed_w, h = self._layout_metrics()
                w = max(1, self.width()) if self.width() > 0 else fixed_w
                hh = max(1, self.height()) if self.height() > 0 else h
                left, right, reset = self._get_action_rects(w, hh, t, btn)
                self._stow_left_rect = left
                self._stow_right_rect = right
                self._stow_rect = right
                self._reset_rect = reset
                self._apply_knob_mask()

            def _apply_knob_mask(self) -> None:
                try:
                    self.clearMask()
                except Exception:
                    pass

            def paintEvent(self, event) -> None:
                t, btn, fixed_w, h = self._layout_metrics()
                if t <= 0.02:
                    self._stow_left_rect = None
                    self._stow_right_rect = None
                    self._stow_rect = None
                    self._reset_rect = None
                    self.clearMask()
                    return
                p = QPainter(self)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                w = self.width()
                hh = self.height()
                left, right, reset = self._get_action_rects(w, hh, t, btn)
                self._stow_left_rect = left
                self._stow_right_rect = right
                self._stow_rect = right
                self._reset_rect = reset
                self._apply_knob_mask()
                v_left, v_right, v_reset = self._get_visual_rects(
                    (self._stow_left_rect, self._stow_right_rect, self._reset_rect), t, btn
                )

                b = float(getattr(self, "_breathe", 0.0) or 0.0)
                tri = 1.0 - abs(2.0 * b - 1.0)
                lift = 1.0 + 0.04 * tri
                face = QColor(
                    min(255, int(37 * lift)),
                    min(255, int(43 * lift)),
                    min(255, int(56 * lift)),
                )
                edge = QColor(
                    min(255, int(61 * lift)),
                    min(255, int(70 * lift)),
                    min(255, int(92 * lift)),
                )
                knob_op = t
                for r in (v_left, v_right, v_reset):
                    if r is None:
                        continue
                    p.setOpacity(knob_op)
                    p.setPen(QPen(edge, 1))
                    p.setBrush(face)
                    rad = min(r.width(), r.height()) / 2.0
                    p.drawRoundedRect(r, rad, rad)
                    p.setOpacity(1.0)

                for r, icon in (
                    (v_left, getattr(self._owner, "_boundary_icon_stow_left", None)),
                    (v_right, getattr(self._owner, "_boundary_icon_stow_right", None)),
                    (v_reset, self._owner._boundary_icon_reset),
                ):
                    if r is None or icon is None:
                        continue
                    pm = icon.pixmap(14, 14)
                    if pm.isNull():
                        continue
                    p.setOpacity(knob_op)
                    ix = r.x() + (r.width() - 14) // 2
                    iy = r.y() + (r.height() - 14) // 2
                    p.drawPixmap(ix, iy, pm)
                    p.setOpacity(1.0)
                p.end()

            def mousePressEvent(self, event) -> None:
                if event.button() != Qt.MouseButton.LeftButton:
                    super().mousePressEvent(event)
                    return
                self._refresh_action_rects()
                pos = event.position().toPoint()
                self._press_pos = pos
                self._press_gpos = event.globalPosition()
                self._handed_off = False
                on_left = self._stow_left_rect is not None and self._stow_left_rect.contains(pos)
                on_right = self._stow_right_rect is not None and self._stow_right_rect.contains(pos)
                on_reset = self._reset_rect is not None and self._reset_rect.contains(pos)
                self._press_on_action = bool(on_left or on_right or on_reset)
                event.accept()

            def _update_hover_cursor(self, pos) -> None:
                self._refresh_action_rects()
                if self._stow_left_rect is not None and self._stow_left_rect.contains(pos):
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                elif self._stow_right_rect is not None and self._stow_right_rect.contains(pos):
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                elif self._reset_rect is not None and self._reset_rect.contains(pos):
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)

            def mouseMoveEvent(self, event) -> None:
                pos = event.position().toPoint()
                press_g = getattr(self, "_press_gpos", None)
                if press_g is None or getattr(self, "_handed_off", False):
                    self._update_hover_cursor(pos)
                    super().mouseMoveEvent(event)
                    return
                if getattr(self, "_press_on_action", False):
                    event.accept()
                    return
                gp = event.globalPosition()
                if abs(gp.x() - press_g.x()) < 6:
                    event.accept()
                    return
                self._handed_off = True
                col = getattr(self._owner, "_boundary_action_col", None)
                self._owner.hide_boundary_actions()
                if col is not None:
                    handle = getattr(col, "_resize_handle", None)
                    if handle is not None and hasattr(handle, "begin_external_drag"):
                        handle.begin_external_drag(float(press_g.x()))
                event.accept()

            def mouseReleaseEvent(self, event) -> None:
                if event.button() != Qt.MouseButton.LeftButton:
                    super().mouseReleaseEvent(event)
                    return
                if getattr(self, "_handed_off", False):
                    self._press_gpos = None
                    self._press_on_action = False
                    event.accept()
                    return
                self._refresh_action_rects()
                pos = event.position().toPoint()
                if self._stow_left_rect is not None and self._stow_left_rect.contains(pos):
                    self._owner._on_boundary_stow_left_clicked()
                elif self._stow_right_rect is not None and self._stow_right_rect.contains(pos):
                    self._owner._on_boundary_stow_clicked()
                elif self._reset_rect is not None and self._reset_rect.contains(pos):
                    self._owner._on_boundary_reset_clicked()
                self._press_gpos = None
                self._press_on_action = False
                event.accept()

            def leaveEvent(self, event) -> None:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                QTimer.singleShot(40, self._owner._recheck_boundary_hover)
                super().leaveEvent(event)

            def contains_global(self, global_pos) -> bool:
                if not self.isVisible() or self._t <= 0.02:
                    return False
                return self.rect().contains(self.mapFromGlobal(global_pos))

        ov = _BoundaryInteractionOverlay(self)
        ov.hide()
        self._boundary_overlay = ov
        self._boundary_action_film = ov

    def update_boundary_actions(self, cx: int, top: int, bot: int, expand: float, col) -> None:
        if getattr(self, "_boundary_dragging", False):
            self.hide_boundary_actions()
            return
        ov = getattr(self, "_boundary_overlay", None)
        if ov is None:
            return
        self._boundary_action_col = col
        t = max(0.0, min(1.0, float(expand)))
        timer = getattr(self, "_boundary_hover_poll", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(80)
            timer.timeout.connect(self._recheck_boundary_hover)
            self._boundary_hover_poll = timer
        if t > 0.02 and not timer.isActive():
            timer.start()

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
            self._boundary_gap_lock = False
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

    def boundary_actions_contain_global(self, global_pos) -> bool:
        ov = getattr(self, "_boundary_overlay", None)
        if ov is not None and hasattr(ov, "contains_global"):
            if ov.contains_global(global_pos):
                return True
        if ov is not None and ov.isVisible() and float(getattr(ov, "_t", 0.0)) > 0.02:
            try:
                if hasattr(ov, "_refresh_action_rects"):
                    ov._refresh_action_rects()
                local = ov.mapFromGlobal(global_pos)
                stow = getattr(ov, "_stow_rect", None)
                reset = getattr(ov, "_reset_rect", None)
                if stow is not None and stow.contains(local):
                    return True
                if reset is not None and reset.contains(local):
                    return True
            except Exception:
                pass
        for b in (getattr(self, "_boundary_reset_btn", None), getattr(self, "_boundary_stow_btn", None)):
            if b is not None and b.isVisible():
                if b.rect().contains(b.mapFromGlobal(global_pos)):
                    return True
        return False

    def _recheck_boundary_hover(self) -> None:
        if getattr(self, "_boundary_dragging", False):
            return
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        if self.boundary_actions_contain_global(pos):
            return
        for col in getattr(self, "_columns", []) or []:
            h = getattr(col, "_resize_handle", None)
            if h is None or not h.isVisible():
                continue
            try:
                if h.rect().contains(h.mapFromGlobal(pos)):
                    return
            except Exception:
                pass
        self.hide_boundary_actions()
        for col in getattr(self, "_columns", []) or []:
            h = getattr(col, "_resize_handle", None)
            if h is None:
                continue
            try:
                h._actions_visible = False
                if float(getattr(h, "_expand", 0.0)) > 0.01:
                    h._show_actions(False)
                else:
                    h.set_hint(False)
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
        self._hold_edge_dock_for_ui(True)
        try:
            self._open_settings_dialog_impl()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "設定",
                    f"設定画面を開けませんでした:\n{exc}",
                )
            except Exception:
                pass
        finally:
            self._hold_edge_dock_for_ui(False)

    def _open_settings_dialog_impl(self) -> None:
        from PySide6.QtWidgets import (
            QDialog, QFormLayout, QDialogButtonBox, QCheckBox, QLineEdit,
            QVBoxLayout, QGroupBox, QRadioButton, QLabel, QHBoxLayout, QToolButton,
        )
        from PySide6.QtGui import QPainterPath, QRegion
        from PySide6.QtCore import QRectF, QObject, QEvent
        dlg = QDialog(self)
        dlg.setObjectName("mayotter_settings_dialog")
        dlg.setWindowTitle("設定")
        dlg.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dlg.setMinimumWidth(360)
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
        title_lbl.setStyleSheet("color:#f1f3f7; font-size:14px; font-weight:600;")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        close_tb = QToolButton()
        close_tb.setIcon(make_close_icon("#93a5c4", 12))
        close_tb.setIconSize(QSize(12, 12))
        close_tb.setFixedSize(24, 24)
        close_tb.setStyleSheet(
            "QToolButton { background:transparent; border:none; border-radius:4px; }"
            "QToolButton:hover { background:#1a2740; }"
        )
        close_tb.clicked.connect(dlg.reject)
        title_row.addWidget(close_tb)
        root.addLayout(title_row)

        dock_box = QGroupBox("Dock")
        dock_l = QVBoxLayout(dock_box)
        dock_l.setContentsMargins(8, 6, 8, 6)
        dock_l.setSpacing(2)
        aot = QCheckBox("Dockを常に最前面に表示")
        aot.setChecked(bool(self._edge_dock_always_on_top))
        dock_l.addWidget(aot)
        fs_guard = QCheckBox("フルスクリーン中はDockを無効化")
        fs_guard.setChecked(bool(getattr(self, "_edge_dock_disable_on_fullscreen", True)))
        fs_guard.setToolTip("ゲーム・全画面動画などでDockを前面に残しません。")
        dock_l.addWidget(fs_guard)
        unread_ind = QCheckBox("Dock未読通知インジケーター")
        unread_ind.setChecked(bool(getattr(self, "_dock_unread_indicator_enabled", True)))
        unread_ind.setToolTip("未読があるとき収納Dockに小さな通知アイコンを表示します。")
        dock_l.addWidget(unread_ind)

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

        web_box = QGroupBox("表示")
        web_form = QFormLayout(web_box)
        zoom = NoWheelSpinBox(); zoom.setRange(50, 150); zoom.setSingleStep(5)
        zoom.setSuffix(" %")
        zoom.setValue(int(self._edge_dock_zoom_percent))
        web_form.addRow("ページズーム", zoom)
        x_sc_off = QCheckBox("Xのキーボードショートカットを無効にする")
        x_sc_off.setChecked(bool(getattr(self, "_disable_x_keyboard_shortcuts", False)))
        x_sc_off.setToolTip(
            "x.com 上の j/k/n 等のショートカットを止めます。"
            "投稿・検索・DM の文字入力はそのまま使えます。"
        )
        x_sc_off.toggled.connect(self._set_disable_x_keyboard_shortcuts)
        web_form.addRow(x_sc_off)

        root.addWidget(dock_box)
        root.addWidget(lr_box)
        root.addWidget(tb_box)
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
            ad.setStyleSheet(
                "QDialog#mayotter_allowed_external_dialog {"
                " background:transparent; border:none; }"
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
                " background:#12151c; border:1px solid #2b3242; border-radius:10px; }"
            )
            outer.addWidget(surface)
            v = QVBoxLayout(surface)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(6)

            def _apply_round_mask():
                try:
                    from src.ui.url_overlay import rounded_overlay_mask
                    w, h = ad.width(), ad.height()
                    if w <= 0 or h <= 0:
                        return
                    ad.setMask(rounded_overlay_mask(w, h, 10))
                except Exception:
                    pass

            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_lbl = QLabel("許可された外部リンク")
            title_lbl.setStyleSheet("color:#f1f3f7; font-size:12px; font-weight:600;")
            title_row.addWidget(title_lbl, 1)
            close_tb = QToolButton()
            close_tb.setText("×")
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
            plus_btn.setText("＋")
            plus_btn.setStyleSheet(
                "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
                " border-radius:6px; padding:3px 10px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
            )
            minus_btn = QToolButton()
            minus_btn.setText("−")
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
                form_dlg.setStyleSheet(
                    "QDialog#mayotter_domain_add_dialog { background:transparent; border:none; }"
                )
                form_wrap = QVBoxLayout(form_dlg)
                form_wrap.setContentsMargins(0, 0, 0, 0)
                form_surface = QWidget(form_dlg)
                form_surface.setObjectName("mayotter_domain_add_surface")
                form_surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                form_surface.setStyleSheet(
                    "QWidget#mayotter_domain_add_surface {"
                    " background:#12151c; border:1px solid #2b3242; border-radius:10px; }"
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
                    from src.ui.url_overlay import rounded_overlay_mask
                    fw, fh = form_dlg.width(), form_dlg.height()
                    form_dlg.setMask(rounded_overlay_mask(fw, fh, 10))
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
        media_form.addRow(auto_norm)
        save_rec = QCheckBox("録音ファイルを保存")
        _save_on = True
        try:
            if self._settings_manager is not None:
                _save_on = bool(self._settings_manager.get_save_recorded_audio())
        except Exception:
            _save_on = True
        save_rec.setChecked(_save_on)
        save_rec_row = QHBoxLayout()
        save_rec_row.setContentsMargins(0, 0, 0, 0)
        save_rec_row.setSpacing(8)
        save_rec_row.addWidget(save_rec)
        mp4_hint = QLabel("※MP4形式")
        mp4_hint.setStyleSheet("color: #7f899a; font-size: 10px;")
        save_rec_row.addWidget(mp4_hint)
        save_rec_row.addStretch(1)
        media_form.addRow(save_rec_row)

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
        open_folder_btn.setIcon(make_folder_icon("#aeb6c5", 12))
        open_folder_btn.setIconSize(QSize(12, 12))
        open_folder_btn.setToolTip("フォルダを開く")
        open_folder_btn.setFixedSize(24, 24)
        open_folder_btn.setStyleSheet(
            "QToolButton { background:#1d2230; border:1px solid #2b3242; border-radius:6px; }"
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

        class _VisDropThumb(type(vis_thumb)):
            pass

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
        crop_folder_btn.setIcon(_mk_crop_folder("#aeb6c5", 12))
        crop_folder_btn.setIconSize(QSize(12, 12))
        crop_folder_btn.setToolTip("フォルダを開く")
        crop_folder_btn.setFixedSize(24, 24)
        crop_folder_btn.setStyleSheet(
            "QToolButton { background:#1d2230; border:1px solid #2b3242; border-radius:6px; }"
        )

        def _browse_crop_dir() -> None:
            from pathlib import Path as _P
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
        upd_l.addWidget(auto_upd)
        from src.core.version import APP_VERSION as _APP_VER
        ver_lbl = QLabel(f"現在のバージョン: {_APP_VER}")
        ver_lbl.setStyleSheet("color:#7f899a; font-size:11px; background:transparent;")
        upd_l.addWidget(ver_lbl)
        check_upd_btn = QToolButton()
        check_upd_btn.setText("今すぐ確認")
        check_upd_btn.setStyleSheet(
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:3px 8px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
        )

        check_upd_btn.clicked.connect(self.open_update_check)
        upd_l.addWidget(check_upd_btn)
        root.addWidget(upd_box)

        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(dlg)
        except Exception:
            pass

        root.addWidget(buttons)

        def _apply() -> None:
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

        def _settings_full_round_mask(width: int, height: int, radius: int = 10) -> QRegion:
            w = max(1, int(width))
            h = max(1, int(height))
            r = max(0, min(int(radius), w // 2, h // 2))
            if r <= 0:
                return QRegion(0, 0, w, h)
            region = QRegion(0, r, w, max(1, h - 2 * r))
            if w > 2 * r:
                region = region.united(QRegion(r, 0, w - 2 * r, r))
                region = region.united(QRegion(r, h - r, w - 2 * r, r))
            tl = QRegion(0, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse).intersected(QRegion(0, 0, r, r))
            tr = QRegion(w - 2 * r, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse).intersected(QRegion(w - r, 0, r, r))
            bl = QRegion(0, h - 2 * r, 2 * r, 2 * r, QRegion.RegionType.Ellipse).intersected(QRegion(0, h - r, r, r))
            br = QRegion(w - 2 * r, h - 2 * r, 2 * r, 2 * r, QRegion.RegionType.Ellipse).intersected(QRegion(w - r, h - r, r, r))
            return region.united(tl).united(tr).united(bl).united(br)

        def _apply_settings_round_mask() -> None:
            try:
                ww = max(1, dlg.width())
                hh = max(1, dlg.height())
                dlg.setMask(_settings_full_round_mask(ww, hh, 10))
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
        if self._settings_manager:
            self._settings_manager.save_edge_dock_enabled(self._edge_dock_enabled)
            self._settings_manager.save_edge_dock_direction(self._edge_dock_direction)
            self._settings_manager.save_edge_dock_column_count(self._edge_dock_column_count)
            if hasattr(self._settings_manager, "save_edge_dock_column_count_lr"):
                self._settings_manager.save_edge_dock_column_count_lr(self._edge_dock_column_count_lr)
                self._settings_manager.save_edge_dock_column_count_tb(self._edge_dock_column_count_tb)
            if hasattr(self._settings_manager, "save_normal_column_count"):
                self._settings_manager.save_normal_column_count(self._normal_column_count)
            if hasattr(self._settings_manager, "save_edge_dock_zoom_percent"):
                self._settings_manager.save_edge_dock_zoom_percent(self._edge_dock_zoom_percent)
            if hasattr(self._settings_manager, "save_edge_dock_always_on_top"):
                self._settings_manager.save_edge_dock_always_on_top(self._edge_dock_always_on_top)
            if hasattr(self._settings_manager, "save_edge_dock_disable_on_fullscreen"):
                self._settings_manager.save_edge_dock_disable_on_fullscreen(
                    bool(getattr(self, "_edge_dock_disable_on_fullscreen", True))
                )
            if hasattr(self._settings_manager, "save_edge_dock_unread_indicator"):
                self._settings_manager.save_edge_dock_unread_indicator(
                    bool(getattr(self, "_dock_unread_indicator_enabled", True))
                )
            self._settings_manager.set("edge_dock_width_lr", self._edge_dock_width_lr)
            self._settings_manager.set("edge_dock_height_lr", self._edge_dock_height_lr)
            self._settings_manager.set("edge_dock_width_tb", self._edge_dock_width_tb)
            self._settings_manager.set("edge_dock_height_tb", self._edge_dock_height_tb)
            self._settings_manager.set("edge_dock_panel_height_ratio", self._edge_dock_panel_height_ratio)
            self._settings_manager.set("edge_dock_edge_offset", self._edge_dock_edge_offset)
            self._settings_manager.set("edge_dock_monitor_index", getattr(self, '_edge_dock_monitor_index', 0))

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
            try:
                self._edge_dock_monitor_index = int(
                    self._settings_manager.get("edge_dock_monitor_index", 0) or 0
                )
            except (TypeError, ValueError):
                self._edge_dock_monitor_index = 0

    @staticmethod
    def _round_mask_region(width: int, height: int, radius: int = 10) -> QRegion:
        w = max(1, int(width))
        h = max(1, int(height))
        r = max(0, min(int(radius), w // 2, h // 2))
        if r <= 0:
            return QRegion(0, 0, w, h)

        region = QRegion(0, r, w, max(1, h - r))
        if w > 2 * r:
            region = region.united(QRegion(r, 0, w - 2 * r, r))
        tl = QRegion(0, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse)
        tl = tl.intersected(QRegion(0, 0, r, r))
        region = region.united(tl)
        tr = QRegion(w - 2 * r, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse)
        tr = tr.intersected(QRegion(w - r, 0, r, r))
        region = region.united(tr)
        return region

    def _dock_outer_round_region(self, width: int, height: int, radius: int = 12) -> QRegion:
        w = max(1, int(width))
        h = max(1, int(height))
        r = max(0, min(int(radius), w // 2, h // 2))
        edge = self._edge_dock_direction
        if r <= 0:
            return QRegion(0, 0, w, h)

        region = QRegion(0, 0, w, h)

        if edge == "right":
            region = region.subtracted(QRegion(0, 0, r, r))
            tl = QRegion(0, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse)
            region = region.united(tl.intersected(QRegion(0, 0, r, r)))
        elif edge == "left":
            region = region.subtracted(QRegion(w - r, 0, r, r))
            tr = QRegion(w - 2 * r, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse)
            region = region.united(tr.intersected(QRegion(w - r, 0, r, r)))
        elif edge == "top":
            region = QRegion(0, 0, w, h)
        else:
            region = QRegion(0, r, w, max(1, h - r))
            if w > 2 * r:
                region = region.united(QRegion(r, 0, w - 2 * r, r))
            tl = QRegion(0, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse)
            region = region.united(tl.intersected(QRegion(0, 0, r, r)))
            tr = QRegion(w - 2 * r, 0, 2 * r, 2 * r, QRegion.RegionType.Ellipse)
            region = region.united(tr.intersected(QRegion(w - r, 0, r, r)))
        return region

    def _apply_dock_shape_mask(self, w: int | None = None, h: int | None = None) -> None:
        if not self._edge_dock_enabled:
            return
        if not self.isVisible():
            return
        ww = int(w if w is not None else self.width())
        hh = int(h if h is not None else self.height())
        if ww < 2 or hh < 2:
            self.setMask(QRegion())
            self._dock_shape_mask_key = None
            return
        edge = self._edge_dock_direction
        if not self._edge_dock_revealed and not self._edge_dock_animating:
            radius = max(2, min(8, min(ww, hh) // 2))
        else:
            radius = max(4, min(12, min(ww, hh) // 2))
        key = (ww, hh, edge, radius)
        if getattr(self, "_dock_shape_mask_key", None) == key and not self.mask().isEmpty():
            return
        self._dock_shape_mask_key = key
        self._dock_shape_mask_wh = (ww, hh)

        self.setMask(self._dock_outer_round_region(ww, hh, min(radius, 10)))
        try:
            self._update_dock_notify_visual()
        except Exception:
            pass

    def _schedule_normal_window_mask(self) -> None:
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
        if getattr(self, "_edge_dock_enabled", False):
            return
        self._window_mask_pending = False
        self._window_mask_key = None
        self._update_window_mask()

    def _update_window_mask(self) -> None:
        if not self.isVisible() or self.isMaximized() or self.isFullScreen():
            if not self.mask().isEmpty():
                self.setMask(QRegion())
            self._window_mask_key = None
            return
        if self._edge_dock_enabled:
            self._apply_dock_shape_mask()
            return

        ww = max(1, int(self.width()))
        hh = max(1, int(self.height()))
        key = (ww, hh, "normal")
        if getattr(self, "_window_mask_key", None) == key and not self.mask().isEmpty():
            return
        self._window_mask_key = key
        self._window_mask_pending = False
        self.setMask(self._round_mask_region(ww, hh))

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

    def _dock_input_label(self, w) -> str:
        if w is None:
            return "none"
        on = ""
        try:
            on = str(w.objectName() or "")
        except Exception:
            pass
        mapping = {
            "add_twitter_btn": "+X",
            "add_column_btn": "+C",
            "download_icon_btn": "DownloadHistory",
            "record_btn": "Record",
            "settings_btn": "Settings",
            "edge_dock_toggle_btn": "DockToggle",
        }
        if on in mapping:
            return mapping[on]
        return on or type(w).__name__

    def _log_dock_input(self, phase: str, w, event=None) -> None:
        try:
            label = self._dock_input_label(w)
            gp = ""
            if event is not None:
                try:
                    p = event.globalPosition().toPoint()
                    gp = f" global=({p.x()},{p.y()})"
                except Exception:
                    pass
            print(
                f"[DockInput] {phase} object={label} class={type(w).__name__ if w else 'None'}"
                f"{gp} dock={getattr(self, '_edge_dock_direction', '?')}"
                f" collapsed={not bool(getattr(self, '_edge_dock_revealed', False))}"
                f" enabled={bool(w.isEnabled()) if w is not None else False}",
                flush=True,
            )
        except Exception:
            pass

    def _suspend_dock_popups(self) -> None:
        suspended: list[str] = []

        ov = getattr(self, "_column_add_overlay", None)
        if ov is not None and (ov.isVisible() or bool(getattr(ov, "_mayotter_fading_out", False))):
            try:
                QApplication.instance().removeEventFilter(ov)
            except Exception:
                pass
            try:
                ov._mayotter_fading_out = False
            except Exception:
                pass
            try:
                ov.hide()
            except Exception:
                pass
            suspended.append("column_add")
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
        if "column_add" in suspended:
            self._restore_column_add_overlay_suspended()
        if "download" in suspended:
            self._restore_download_overlay_suspended()
        if "service_menu" in suspended:
            self._restore_service_menu_suspended()

    def _restore_column_add_overlay_suspended(self) -> None:
        ov = getattr(self, "_column_add_overlay", None)
        if ov is None:
            return
        try:
            from src.ui.url_overlay import _promote_overlay_tool
            parent = self
            width = min(int(getattr(ov, "OVERLAY_WIDTH", 420) or 420), max(parent.width() - 40, 280))
            x = (parent.width() - width) // 2
            y = 44
            h = max(int(ov.height() or 0), max(int(ov.sizeHint().height() or 0), 100))
            ov.setFixedSize(width, h)
            ov.setGeometry(x, y, width, h)
            _promote_overlay_tool(ov, parent)
            try:
                from src.ui.theme import rounded_overlay_mask
            except Exception:
                rounded_overlay_mask = None
            try:
                from src.ui.url_overlay import rounded_overlay_mask as _rom
                ov.setMask(_rom(ov.width(), ov.height()))
            except Exception:
                pass
            ov.show()
            ov.raise_()
            try:
                QApplication.instance().installEventFilter(ov)
            except Exception:
                pass
        except Exception as e:
            pass

    def _restore_download_overlay_suspended(self) -> None:
        dov = getattr(self, "_download_overlay", None)
        if dov is None:
            return
        try:
            if hasattr(dov, "open_history"):
                self._download_closed_at = 0.0
                dov.open_history()
            else:
                dov.show()
        except Exception as e:
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
            menu.show()
            menu.raise_()
            try:
                QApplication.instance().installEventFilter(menu)
            except Exception:
                pass
        except Exception as e:
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
                    self._log_dock_input("PRESS", obj, event)
            elif obj in chrome and event.type() == QEvent.Type.MouseButtonRelease:
                if getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
                    self._log_dock_input("RELEASE", obj, event)
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
                sb_hit = False
                if estr and self._prefer_webview_scroll_over_resize(gp, local, estr):
                    sb_hit = True
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

        if self._point_on_restore_knob(x, y):
            return 0

        w = self.width()
        h = self.height()
        m = _RESIZE_MARGIN

        left = x < m
        right = x >= w - m
        top = y < m
        bottom = y >= h - m

        if getattr(self, "_edge_dock_enabled", False):
            dock = getattr(self, "_edge_dock_direction", "right")
            if dock == "left":
                left = False
            elif dock == "right":
                right = False
            elif dock == "top":
                top = False
            elif dock == "bottom":
                bottom = False

        if left and top:
            return _HTTOPLEFT
        if right and top:
            return _HTTOPRIGHT
        if left and bottom:
            return _HTBOTTOMLEFT
        if right and bottom:
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
                        ok = wh.startSystemResize(edges)
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
        self._edge_dock_dragging = True
        self._edge_dock_drag_origin = event.globalPosition().toPoint()
        self._edge_dock_drag_geom = self.geometry()
        if self._edge_detector:
            self._edge_detector.set_pinned_open(True)
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
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
            self.setGeometry(g)
            fw, fh = max(1, g.width()), max(1, g.height())
            self._store_live_size(fw, fh, dock)
            clip = getattr(self, "_edge_dock_clip", None)
            root = getattr(self, "_edge_dock_root", None)
            if clip is not None and clip.geometry() != QRect(0, 0, fw, fh):
                clip.setGeometry(0, 0, fw, fh)
            if root is not None and root.geometry() != QRect(0, 0, fw, fh):
                root.setGeometry(0, 0, fw, fh)
            t = 1.0 if self._edge_dock_revealed else float(getattr(self, "_edge_dock_reveal_progress", 0.0))
            self._apply_reveal_mask(t)
            self._apply_dock_shape_mask(fw, fh)
            if self._edge_dock_revealed:
                self._fit_columns()
            try:
                col_w = None
                visible = [c for c in getattr(self, "_columns", []) if c.isVisible()]
                if visible:
                    col_w = visible[0].get_width()
            except Exception:
                pass
            event.accept()
            return
        if self._edge_dock_dragging and self._edge_dock_drag_origin and self._edge_dock_drag_geom:
            delta = event.globalPosition().toPoint() - self._edge_dock_drag_origin
            self._follow_drag(self._edge_dock_drag_geom.topLeft() + delta)
            event.accept()
            return
        if self._edge_dock_enabled and self._edge_dock_revealed and not self._edge_dock_dragging and not self._edge_dock_resizing:
            self._update_resize_cursor(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._edge_dock_resizing:
            self._edge_dock_resizing = False
            self.releaseMouse()
            self._snap_to_dock_edge()
            edge = self._edge_dock_direction
            self._store_live_size(self.width(), self.height(), edge)
            self._dock_shape_mask_wh = None
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
                self._fit_columns()
            else:
                collapsed = self._collapsed_geometry()
                if self.geometry() != collapsed:
                    self.setGeometry(collapsed)
            if self._edge_detector:
                self._edge_detector.set_pinned_open(False)
            event.accept()
            return
        if self._edge_dock_dragging:
            self._edge_dock_dragging = False
            self.releaseMouse()
            if self._edge_detector:
                self._edge_detector.set_pinned_open(False)
            if self._edge_dock_revealed:
                self._edge_dock_profile_lock = True
                try:
                    full = self._expanded_geometry_for_edge(self._edge_dock_direction)
                    if self.geometry() != full:
                        self.setGeometry(full)
                    self._snap_to_dock_edge()
                    root = getattr(self, "_edge_dock_root", None)
                    clip = getattr(self, "_edge_dock_clip", None)
                    if root is not None:
                        root.setGeometry(0, 0, full.width(), full.height())
                    if clip is not None:
                        clip.setGeometry(0, 0, full.width(), full.height())
                    self._apply_reveal_mask(1.0)
                    self._fit_columns()
                    self._update_edge_dock_column_visibility()
                finally:
                    self._edge_dock_profile_lock = False
            self._dock_shape_mask_wh = None
            self._dock_shape_mask_key = None
            self._apply_dock_shape_mask()
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
            self._mode_active[self._layout_mode_key()] = column
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
            title = tab.title() if hasattr(tab, "title") else ""
            if not title and hasattr(tab, "get_current_url"):
                url = tab.get_current_url()
                if url:
                    title = url
            if not title:
                title = f"Tab {i + 1}"
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

    def _on_tab_reorder(self, from_index: int, to_index: int) -> None:
        if self._active_column is not None:
            self._active_column.move_tab(from_index, to_index)

    def _on_tab_title_changed(self) -> None:
        if self._active_column is not None:
            self._rebuild_strip()

    def _on_column_activated(self, column: AccountColumn) -> None:
        self._set_active_column(column)

    def _open_service_menu(self, grok: bool) -> None:
        self._log_dock_input("CLICK", getattr(self, "_add_twitter_btn", None))
        import time
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
        if (os.environ.get("MAYOTTER_DEBUG") or "").strip().lower() in (
            "1", "true", "yes", "on",
        ):
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

        target_store = self._grok_columns if grok else self._twitter_columns
        for col in target_store:
            if col.get_account_id() == account_id:
                if grok == self._grok_mode:
                    self._set_active_column(col)
                return

        acc_info = self._known_accounts.get(account_id)
        if not acc_info:
            return

        account = Account(
            account_id=account_id,
            display_name=acc_info.get("display_name", ""),
            initial_url=GROK_HOME_URL if grok else "https://x.com/",
            profile_path=acc_info.get("legacy_profile_path", "") or acc_info.get("profile_path", ""),
        )

        self._add_column(account)

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

        accounts = [a for a in self._settings_manager.get_accounts() if self._is_valid_saved_account(a)]
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
        if not column_configs and hasattr(self._settings_manager, "get_columns_for_mode"):
            for _mode in ("lr", "tb"):
                try:
                    alt = list(self._settings_manager.get_columns_for_mode(_mode) or [])
                except Exception:
                    alt = []
                if alt:
                    column_configs = alt
                    break
        try:
            column_configs.sort(key=lambda c: int(c.get("position", 0) or 0))
        except Exception:
            pass

        STAGGER_MS = 150
        loaded_index = 0
        self._restoring_session = True

        if column_configs:
            for col_conf in column_configs:
                aid = (col_conf.get("source_account_id") or "").strip()
                if not aid:
                    continue
                if aid not in self._known_accounts:
                    leg = (col_conf.get("profile_path") or "").strip()
                    self._known_accounts[aid] = {
                        "account_id": aid,
                        "display_name": col_conf.get("title", "") or aid[:8],
                        "initial_url": col_conf.get("source_url") or "https://x.com/",
                        "grok": "grok.com" in (col_conf.get("source_url") or ""),
                    }
                    if leg:
                        self._known_accounts[aid]["legacy_profile_path"] = leg
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
                    if col is not None and bool(col_conf.get("stowed")):
                        if not hasattr(self, "_pending_stow_ids") or self._pending_stow_ids is None:
                            self._pending_stow_ids = []
                        self._pending_stow_ids.append(col.get_column_id())
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
        QTimer.singleShot(0, self._fit_columns_after_restore)
        QTimer.singleShot(50, self._apply_persisted_stow_on_startup)

    def _seed_mode_packs_from_settings(self) -> None:
        if not self._settings_manager:
            return
        if not hasattr(self._settings_manager, "get_columns_for_mode"):
            return
        for mode in ("lr", "tb"):
            packs = self._service_packs()
            lst = packs.setdefault(mode, [])
            if lst:
                continue
            configs = self._settings_manager.get_columns_for_mode(mode) or []
            if not configs:
                continue
            try:
                configs = sorted(configs, key=lambda c: int(c.get("position", 0) or 0))
            except Exception:
                pass
            widths = {}
            if hasattr(self._settings_manager, "get_column_widths_for_mode"):
                widths = self._settings_manager.get_column_widths_for_mode(mode) or {}
            for col_conf in configs:
                aid = (col_conf.get("source_account_id") or "").strip()
                if not aid:
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
                if len(lst) > before:
                    col = lst[-1]
                    try:
                        tabs_raw = col_conf.get("tabs")
                        active_tab = int(col_conf.get("active_tab", 0) or 0)
                        if isinstance(tabs_raw, list) and tabs_raw:
                            self._restore_column_tabs(col, tabs_raw, active_tab)
                        if bool(col_conf.get("stowed")):
                            # Dock 等の mode 用。通常起動の _pending_stow_ids には混ぜない
                            if not hasattr(self, "_mode_stowed_columns") or self._mode_stowed_columns is None:
                                self._mode_stowed_columns = {"normal": [], "lr": [], "tb": []}
                            if col not in self._mode_stowed_columns.setdefault(mode, []):
                                self._mode_stowed_columns[mode].append(col)
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
                            col.set_width(w, emit_signal=False)
                        except Exception:
                            pass
            if mode == "lr" and lst:
                self._edge_dock_column_count_lr = max(1, len(lst))
            elif mode == "tb" and lst:
                self._edge_dock_column_count_tb = max(1, len(lst))

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
            QTimer.singleShot(1600, _hide)
        except Exception:
            self._dock_notify_busy = False

    def _toggle_download_history(self) -> None:
        self._log_dock_input("CLICK", getattr(self, "_download_icon_btn", None))
        import time as _time
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
                self._download_closed_at = _time.monotonic()
                return
            self._download_closed_at = 0.0
            ov.open_history()
            try:
                self._download_icon_btn.clear_completed()
            except Exception:
                pass
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda: setattr(self, "_download_toggling", False))

    def _go_home_focused(self) -> None:
        if self._active_column is not None:
            self._active_column.go_home()

    def _open_column_add_overlay(self) -> None:
        self._log_dock_input("CLICK", getattr(self, "_add_column_btn", None))
        import time as _time
        ov = self._column_add_overlay
        if ov is None:
            return
        if getattr(self, "_column_add_toggling", False):
            return
        self._column_add_toggling = True
        try:
            fading = bool(getattr(ov, "_mayotter_fading_out", False)) and ov.isVisible()
            vis = bool(ov.is_open())
            if vis or fading:
                ov.close_overlay()
                self._column_add_closed_at = _time.monotonic()
                return
            self._column_add_closed_at = 0.0
            accounts = {
                a["account_id"]: a
                for a in self._pickable_accounts(grok=self._grok_mode)
            }
            ov.open_for(accounts)
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda: setattr(self, "_column_add_toggling", False))

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
                self._win_max_btn.setIcon(make_restore_icon("#aeb6c5", 12))
                self._win_max_btn.setToolTip("元のサイズに戻す")
            else:
                self._win_max_btn.setIcon(make_maximize_icon("#aeb6c5", 12))
                self._win_max_btn.setToolTip("最大化")
        except Exception:
            pass

    def _toggle_maximized(self) -> None:
        if getattr(self, "_edge_dock_enabled", False):

            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_window_chrome_icons()

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
        if self._media_wide_view is not None:
            self._apply_media_wide_geometry()
        if not getattr(self, "_edge_dock_enabled", False):
            self._schedule_normal_window_mask()
        else:
            self._update_window_mask()
        os_sizing = bool(getattr(self, "_os_sizing", False))
        if (
            self._edge_dock_enabled
            and self._edge_dock_revealed
            and not self._edge_dock_animating
            and os_sizing
            and self.width() > self.EDGE_DOCK_INDICATOR_WIDTH * 4
        ):
            self._store_live_size(self.width(), self.height())
            self._update_chrome_by_window_width()
            return

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
            and self.width() > self.EDGE_DOCK_INDICATOR_WIDTH * 4
        ):
            self._store_live_size(self.width(), self.height())
        if getattr(self, "_edge_dock_resizing", False):
            self._update_chrome_by_window_width()
            return
        if not stably_collapsed:
            if not getattr(self, "_edge_dock_enabled", False):
                self._fit_columns()
            else:
                QTimer.singleShot(0, self._fit_columns)
        if getattr(self, "_stowed_columns", None):
            self._update_stow_restore_rail()
        self._update_chrome_by_window_width()
        if stably_collapsed and bool(getattr(self, "_dock_has_unread", False)):
            try:
                self._update_dock_notify_visual()
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
            self._fit_columns()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange and getattr(self, "_edge_dock_enabled", False):
            state = self.windowState()
            bad = Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized
            if state & bad:
                self.setWindowState(state & ~bad)
                if not self.isVisible():
                    self.show()
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._update_window_mask)

    def closeEvent(self, event) -> None:

        if not getattr(self, "_close_fade_done", False):
            event.ignore()
            self._close_fade_done = True
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

    def _hide_recording_overlay(self) -> None:
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
            import time as _time
            target = getattr(self, "_recording_target", None) or {}
            wv = target.get("webview")
            if wv is not None and getattr(wv, "_last_user_gesture_mono", None) is not None:
                self._attach_t0_mono = float(wv._last_user_gesture_mono)
            else:
                self._attach_t0_mono = None
            self._attach_t1_mono = _time.monotonic()
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
            self._record_btn.setIcon(make_stop_icon("#e66464", 14))
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
            import time as _time
            self._attach_t2_mono = _time.monotonic()
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
            import time as _time
            self._attach_t3_mono = _time.monotonic()
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
            import time as _time
            self._attach_t4_mono = _time.monotonic()
            self._attach_timing_log("T4_mp4_done", file_size=sz)
            self._attach_t5_mono = _time.monotonic()
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
            self._record_btn.setIcon(make_mic_icon("#9fb4d8", 16))
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
        import os
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
        dpr = 1.0
        try:
            dpr = float(webview.devicePixelRatioF())
        except Exception:
            try:
                dpr = float(webview.devicePixelRatio())
            except Exception:
                dpr = 1.0
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
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QToolButton,
            QWidget,
            QProgressBar,
        )
        from PySide6.QtCore import (
            QPropertyAnimation,
            QVariantAnimation,
            QEasingCurve,
            QTimer,
            QThread,
            Signal,
            QObject,
            Qt as _Qt,
        )

        try:
            from src.ui.theme import (
                POPOVER_OPEN_MS,
                POPOVER_CLOSE_MS,
                SURFACE,
                BORDER,
                TEXT,
                ACCENT,
                SURFACE_RAISED,
            )
        except Exception:
            POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
            SURFACE, BORDER, TEXT = "#12151c", "#2b3242", "#f1f3f7"
            ACCENT, SURFACE_RAISED = "#4a7ec7", "#1d2230"

        _btn_ss = (
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:4px 12px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
            "QToolButton:disabled { color:#5a6270; background:#151820; border:1px solid #2b3242; }"
        )

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

        ud = QDialog(self)
        self._update_flow_dialog = ud
        ud.setObjectName("mayotter_update_dialog")
        ud.setModal(True)
        ud.setWindowFlags(
            _Qt.WindowType.Dialog | _Qt.WindowType.FramelessWindowHint
        )
        ud.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ud.setAttribute(_Qt.WidgetAttribute.WA_StyledBackground, True)
        ud.setAttribute(_Qt.WidgetAttribute.WA_DeleteOnClose, True)
        ud.setStyleSheet(
            "QDialog#mayotter_update_dialog { background:transparent; border:none; }"
        )
        ud.setMinimumWidth(360)

        outer = QVBoxLayout(ud)
        outer.setContentsMargins(0, 0, 0, 0)
        surface = QWidget(ud)
        surface.setObjectName("mayotter_update_surface")
        surface.setAttribute(_Qt.WidgetAttribute.WA_StyledBackground, True)
        surface.setStyleSheet(
            f"QWidget#mayotter_update_surface {{"
            f" background:{SURFACE if SURFACE != '#12151c' else '#12151c'};"
            f" border:1px solid {BORDER}; border-radius:10px; }}"
        )
        outer.addWidget(surface)
        v = QVBoxLayout(surface)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)

        title = QLabel("アップデート")
        title.setStyleSheet(
            f"color:{TEXT}; font-size:14px; font-weight:600; background:transparent;"
        )
        v.addWidget(title)
        body = QLabel("確認しています…")
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{TEXT}; font-size:12px; background:transparent;")
        v.addWidget(body)

        prog_row = QHBoxLayout()
        prog_row.setContentsMargins(0, 2, 0, 0)
        prog_row.setSpacing(10)
        progress = QProgressBar()
        progress.setObjectName("mayotter_update_progress")
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setFixedHeight(12)
        progress.setMinimumWidth(180)
        progress.setStyleSheet(
            f"QProgressBar#mayotter_update_progress {{"
            f" background:{SURFACE_RAISED}; border:1px solid {BORDER};"
            f" border-radius:6px; text-align:center; }}"
            f"QProgressBar#mayotter_update_progress::chunk {{"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f"  stop:0 #3d6aa8, stop:0.45 {ACCENT}, stop:1 #6a9be0);"
            f" border-radius:5px; margin:1px; }}"
        )
        progress.hide()
        pct_lbl = QLabel("")
        pct_lbl.setObjectName("mayotter_update_pct")
        pct_lbl.hide()
        pct_lbl.setAlignment(_Qt.AlignmentFlag.AlignVCenter | _Qt.AlignmentFlag.AlignRight)
        pct_lbl.setStyleSheet(
            f"QLabel#mayotter_update_pct {{"
            f" color:{TEXT}; font-size:12px; font-weight:600;"
            f" background:transparent; min-width:40px; }}"
        )
        prog_row.addWidget(progress, 1)
        prog_row.addWidget(pct_lbl, 0)
        v.addLayout(prog_row)

        anim_state: dict = {"display": 0.0, "target": 0, "complete_hold": False}
        prog_anim = QVariantAnimation(ud)
        prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _apply_display_value(v) -> None:
            try:
                iv = int(round(float(v)))
                iv = max(0, min(100, iv))
                anim_state["display"] = float(iv)
                progress.setValue(iv)
                pct_lbl.setText(f"{iv}%")
            except Exception:
                pass

        prog_anim.valueChanged.connect(_apply_display_value)

        def _animate_to(target: int, *, duration_ms: int | None = None) -> None:
            target = max(0, min(100, int(target)))
            anim_state["target"] = target
            try:
                cur = int(round(float(anim_state.get("display", progress.value()))))
            except Exception:
                cur = progress.value()
            if abs(target - cur) < 1 and target < 100:
                _apply_display_value(target)
                return
            try:
                prog_anim.stop()
            except Exception:
                pass
            prog_anim.setStartValue(float(cur))
            prog_anim.setEndValue(float(target))
            if duration_ms is None:
                duration_ms = max(140, min(420, abs(target - cur) * 9))
            prog_anim.setDuration(int(duration_ms))
            prog_anim.start()

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        primary_btn = QToolButton()
        primary_btn.setText("はい")
        primary_btn.setStyleSheet(_btn_ss)
        primary_btn.hide()
        secondary_btn = QToolButton()
        secondary_btn.setText("いいえ")
        secondary_btn.setStyleSheet(_btn_ss)
        secondary_btn.setText("閉じる")
        btn_row.addWidget(primary_btn)
        btn_row.addWidget(secondary_btn)
        v.addLayout(btn_row)

        state: dict = {"busy": False, "info": None, "worker": None, "closing": False}

        def _relayout():
            try:
                ud.adjustSize()
            except Exception:
                pass

        def _finish_close():
            if state.get("closing_done"):
                return
            state["closing_done"] = True
            self._update_flow_busy = False
            try:
                w = state.get("worker")
                if w is not None:
                    try:
                        if w.isRunning():
                            w.requestInterruption()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                ud.hide()
                ud.deleteLater()
            except Exception:
                pass
            if getattr(self, "_update_flow_dialog", None) is ud:
                self._update_flow_dialog = None

        def _fade_close():
            if state.get("closing"):
                return
            state["closing"] = True
            try:
                anim = QPropertyAnimation(ud, b"windowOpacity", ud)
                anim.setDuration(int(POPOVER_CLOSE_MS))
                anim.setStartValue(float(ud.windowOpacity() or 1.0))
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.Type.InCubic)
                anim.finished.connect(_finish_close)
                anim.start()
                ud._mayotter_fade_anim = anim
                QTimer.singleShot(int(POPOVER_CLOSE_MS) + 100, _finish_close)
            except Exception:
                _finish_close()

        def _show_message(msg: str, *, closable: bool = True):
            try:
                prog_anim.stop()
            except Exception:
                pass
            body.setText(msg)
            progress.hide()
            pct_lbl.hide()
            primary_btn.hide()
            secondary_btn.setText("閉じる")
            secondary_btn.setEnabled(True)
            secondary_btn.show()
            try:
                secondary_btn.clicked.disconnect()
            except Exception:
                pass
            secondary_btn.clicked.connect(_fade_close)
            _relayout()

        def _on_progress(received: int, total):
            try:
                progress.setRange(0, 100)
                progress.show()
                pct_lbl.show()
                if total and total > 0:
                    pct = max(0, min(100, int(received * 100 / total)))
                    _animate_to(pct)
                else:
                    progress.setRange(0, 0)
                    mb = received / (1024 * 1024)
                    pct_lbl.setText(f"{mb:.1f} MB")
                    pct_lbl.setStyleSheet(
                        f"QLabel#mayotter_update_pct {{"
                        f" color:{TEXT}; font-size:12px; font-weight:600;"
                        f" background:transparent; min-width:56px; }}"
                    )
            except Exception:
                pass

        class _DlWorker(QThread):
            progress = Signal(int, object)
            ok = Signal(str)
            err = Signal(str)

            def __init__(self, url: str, sha: str | None):
                super().__init__()
                self._url = url
                self._sha = sha

            def run(self):
                try:
                    from src.core.updater import (
                        download_release_asset,
                        clear_update_tmp,
                    )

                    clear_update_tmp()

                    def _cb(received, total):
                        try:
                            self.progress.emit(int(received), total)
                        except Exception:
                            pass

                    path = download_release_asset(
                        self._url,
                        progress_callback=_cb,
                        expected_sha256=self._sha,
                    )
                    if path is None:
                        self.err.emit(
                            "ダウンロードまたは検証に失敗しました。"
                            "（SHA-256不一致・ネットワークエラーの可能性があります）"
                        )
                        return
                    self.ok.emit(str(path))
                except Exception as exc:
                    self.err.emit(f"ダウンロード中にエラーが発生しました。\n{exc}")

        def _start_download():
            info = state.get("info")
            if info is None or state.get("busy"):
                return
            if not getattr(info, "download_url", None):
                _show_message("アップデートファイルを取得できませんでした。")
                return
            state["busy"] = True
            self._update_flow_busy = True
            body.setText("ダウンロード中…")
            progress.setRange(0, 100)
            anim_state["display"] = 0.0
            anim_state["target"] = 0
            anim_state["complete_hold"] = False
            try:
                prog_anim.stop()
            except Exception:
                pass
            progress.setValue(0)
            pct_lbl.setText("0%")
            pct_lbl.setStyleSheet(
                f"QLabel#mayotter_update_pct {{"
                f" color:{TEXT}; font-size:12px; font-weight:600;"
                f" background:transparent; min-width:40px; }}"
            )
            progress.show()
            pct_lbl.show()
            primary_btn.hide()
            secondary_btn.hide()
            _relayout()

            worker = _DlWorker(
                info.download_url,
                getattr(info, "sha256", None),
            )
            state["worker"] = worker

            def _proceed_after_complete(path_str: str):
                try:
                    from pathlib import Path as _Path
                    from src.core.updater import (
                        mark_download_complete,
                        prepare_and_launch_self_update,
                    )
                    import sys

                    mark_download_complete(_Path(path_str), info)
                    frozen = bool(getattr(sys, "frozen", False))
                    if frozen and sys.platform.startswith("win"):
                        body.setText("更新を適用しています…")
                        _apply_display_value(100)
                        ok, msg = prepare_and_launch_self_update(_Path(path_str))
                        if not ok:
                            state["busy"] = False
                            self._update_flow_busy = False
                            _show_message(msg or "更新の適用に失敗しました。")
                            return
                        body.setText(msg)
                        progress.hide()
                        pct_lbl.hide()
                        primary_btn.hide()
                        secondary_btn.hide()
                        _relayout()
                        QTimer.singleShot(400, self.close)
                    else:
                        state["busy"] = False
                        self._update_flow_busy = False
                        _show_message(
                            "ダウンロードが完了しました。\n"
                            "（開発実行中は自動置換を行いません。"
                            "配布版では再起動して更新が適用されます）"
                        )
                except Exception as exc:
                    state["busy"] = False
                    self._update_flow_busy = False
                    _show_message(f"更新処理に失敗しました。\n{exc}")

            def _on_ok(path_str: str):
                try:
                    anim_state["complete_hold"] = True
                    _animate_to(100, duration_ms=220)

                    def _after_anim():
                        if state.get("closing"):
                            return
                        _proceed_after_complete(path_str)

                    QTimer.singleShot(280, _after_anim)
                except Exception:
                    _proceed_after_complete(path_str)

            def _on_err(msg: str):
                state["busy"] = False
                self._update_flow_busy = False
                _show_message(msg)

            worker.progress.connect(_on_progress)
            worker.ok.connect(_on_ok)
            worker.err.connect(_on_err)
            worker.start()

        def _on_yes():
            _start_download()

        def _on_no():
            if state.get("busy"):
                return
            _fade_close()

        def _run_check():
            try:
                from src.core.updater import check_for_update
                from pathlib import Path

                repo = ""
                try:
                    if self._settings_manager is not None and hasattr(
                        self._settings_manager, "get_github_repo"
                    ):
                        repo = self._settings_manager.get_github_repo()
                except Exception:
                    pass
                info = check_for_update(github_repo=repo)
                if info is None:
                    _show_message("新しいバージョンはありません。")
                    return
                state["info"] = info
                body.setText(
                    f"最新版を確認しました（{info.version}）。\n今すぐ更新しますか？"
                )
                progress.hide()
                pct_lbl.hide()
                secondary_btn.setText("いいえ")
                secondary_btn.setEnabled(True)
                primary_btn.setText("はい")
                primary_btn.show()
                primary_btn.setEnabled(True)
                try:
                    primary_btn.clicked.disconnect()
                except Exception:
                    pass
                try:
                    secondary_btn.clicked.disconnect()
                except Exception:
                    pass
                primary_btn.clicked.connect(_on_yes)
                secondary_btn.clicked.connect(_on_no)
                _relayout()
            except Exception:
                _show_message("アップデートの確認中にエラーが発生しました。")

        secondary_btn.clicked.connect(_fade_close)

        try:
            ud.adjustSize()
            geo = self.frameGeometry()
            dg = ud.frameGeometry()
            ud.move(
                geo.center().x() - dg.width() // 2,
                geo.center().y() - dg.height() // 2,
            )
        except Exception:
            pass

        try:
            ud.setWindowOpacity(0.0)
        except Exception:
            pass
        ud.show()
        ud.raise_()
        try:
            anim_in = QPropertyAnimation(ud, b"windowOpacity", ud)
            anim_in.setDuration(int(POPOVER_OPEN_MS))
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim_in.start()
            ud._mayotter_fade_anim = anim_in
        except Exception:
            try:
                ud.setWindowOpacity(1.0)
            except Exception:
                pass

        QTimer.singleShot(30, _run_check)

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
        column.resized.connect(lambda w: self._save_column_widths())
        column.enabled_changed.connect(lambda e: self._save_accounts())
        column.boundary_dragged.connect(lambda delta, c=column: self._on_boundary_dragged(c, delta))
        column.boundary_drag_finished.connect(self._on_boundary_drag_finished)
        column.stow_right_requested.connect(self._stow_columns_right_of)
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
            key = self._layout_mode_key()
        packs = self._service_packs()
        packs[key].append(column)
        self._columns = packs[key]
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
            self._update_boundary_visibility()
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

        if target_col is not None:
            if self._active_column is target_col:
                self._active_column = None
                self._clear_strip()

            self._scroll_layout.removeWidget(target_col)
            target_col.deleteLater()
            self._columns.pop(target_idx)

            for packs in (self._twitter_packs, self._grok_packs):
                for lst in packs.values():
                    if target_col in lst:
                        lst.remove(target_col)

        self._update_boundary_visibility()

        if self._columns and self._active_column is None:
            self._set_active_column(self._columns[0])

        try:
            self._save_columns()
        except Exception:
            pass
        self._save_accounts()

        self._sync_count_from_active_list()
        self._fit_columns()
        self._save_column_widths()
        self._update_boundary_visibility()

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
            return set(getattr(self, "_stowed_columns", None) or [])
        except Exception:
            return set()

    def _reorder_active_columns(self, column: AccountColumn | None = None) -> list:
        stowed = self._stowed_column_set()
        out = []
        for c in self._columns:
            if c in stowed and c is not column:
                continue
            out.append(c)
        return out

    def _reorder_index_from_global_x(
        self, column: AccountColumn, global_x: float, moving_right: bool
    ) -> int:
        stowed = self._stowed_column_set()
        active = [c for c in self._columns if c not in stowed or c is column]
        if column not in active:
            try:
                return self._columns.index(column)
            except ValueError:
                return 0
        others = [c for c in active if c is not column]
        vis_index = 0
        for other in others:
            try:
                left = int(other.mapToGlobal(other.rect().topLeft()).x())
                w = max(1, int(other.width()))
            except Exception:
                continue
            thresh = left + (w // 3 if moving_right else (2 * w) // 3)
            if thresh < float(global_x):
                vis_index += 1
        vis_index = max(0, min(vis_index, len(active) - 1))
        reordered_active = list(others)
        reordered_active.insert(vis_index, column)
        full = []
        ai = 0
        for c in self._columns:
            if c in stowed and c is not column:
                full.append(c)
            else:
                full.append(reordered_active[ai])
                ai += 1
        try:
            return full.index(column)
        except ValueError:
            return vis_index

    def _on_column_reorder_drag_moved(self, column: AccountColumn, global_x: float) -> None:
        if column not in self._columns:
            return
        if column in self._stowed_column_set():
            return
        if getattr(self, "_reorder_original", None) is None:
            self._reorder_original = list(self._columns)
            self._reorder_dragging = column
            try:
                from PySide6.QtWidgets import QApplication
                while QApplication.overrideCursor() is not None:
                    QApplication.restoreOverrideCursor()
                self._edge_cursor_forced = False
            except Exception:
                pass
            try:
                import os
                if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                    print(f"[REORDER] drag_start column={getattr(column, 'get_column_id', lambda: '?')()}", flush=True)
            except Exception:
                pass
            try:
                from PySide6.QtWidgets import QGraphicsOpacityEffect
                if getattr(column, "_reorder_opacity_effect", None) is None:
                    eff = QGraphicsOpacityEffect(column)
                    eff.setOpacity(0.85)
                    column.setGraphicsEffect(eff)
                    column._reorder_opacity_effect = eff
                else:
                    try:
                        column._reorder_opacity_effect.setOpacity(0.85)
                    except Exception:
                        pass
            except Exception:
                pass

        last_x = getattr(self, "_reorder_last_x", None)
        if last_x is None:
            moving_right = True
        else:
            moving_right = float(global_x) >= float(last_x)
        self._reorder_last_x = float(global_x)

        new_index = self._reorder_index_from_global_x(column, float(global_x), moving_right)
        if getattr(self, "_reorder_preview_index", None) == new_index:
            return
        self._reorder_preview_index = new_index
        self._reorder_columns_visual(column, new_index)

        self._ensure_column_insert_indicator()
        ind = self._column_insert_indicator
        host = self._scroll_content
        if host is None or not self._columns:
            return
        try:
            ref = self._columns[new_index]
            if not ref.isVisible():
                active = self._reorder_active_columns(column)
                if active:
                    ref = active[min(len(active) - 1, max(0, active.index(column) if column in active else 0))]
            local = host.mapFromGlobal(ref.mapToGlobal(ref.rect().topLeft()))
            ind.setParent(host)
            ind.setGeometry(local.x() - 1, 0, 2, max(1, host.height()))
            ind.show()
            ind.raise_()
        except Exception:
            pass

    def _reorder_columns_visual(self, column: AccountColumn, new_index: int) -> None:
        if column not in self._columns:
            return
        old_index = self._columns.index(column)
        n = len(self._columns)
        new_index = max(0, min(int(new_index), n - 1))
        if old_index == new_index:
            return
        widths = []
        try:
            widths = [max(1, c.width()) for c in self._columns]
        except Exception:
            widths = []
        self._columns.pop(old_index)
        self._columns.insert(new_index, column)
        if widths and len(widths) == n:
            w_moved = widths.pop(old_index)
            widths.insert(new_index, w_moved)
        try:
            key = self._layout_mode_key()
            packs = self._service_packs()
            if packs.get(key) is not self._columns:
                packs[key] = list(self._columns)
        except Exception:
            pass
        try:
            self._scroll_layout.removeWidget(column)
            self._scroll_layout.insertWidget(new_index, column)
            column.show()
            if widths and len(widths) == len(self._columns):
                for c, w in zip(self._columns, widths):
                    try:
                        c.set_width(int(w), emit_signal=False)
                    except Exception:
                        pass
            self._scroll_content.updateGeometry()
            self._scroll_layout.invalidate()
            self._scroll_layout.activate()
            if self._scroll is not None:
                self._scroll.viewport().update()
        except Exception:
            pass
        try:
            self._update_boundary_visibility()
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                ids = [getattr(c, "get_column_id", lambda: "?")() for c in self._columns]
                print(f"[REORDER] preview {old_index}->{new_index} order={ids}", flush=True)
        except Exception:
            pass

    def _on_column_reorder_drag_finished(self) -> None:
        ind = getattr(self, "_column_insert_indicator", None)
        if ind is not None:
            ind.hide()
        col = getattr(self, "_reorder_dragging", None)
        if col is not None:
            try:
                col.setGraphicsEffect(None)
                if hasattr(col, "_reorder_opacity_effect"):
                    col._reorder_opacity_effect = None
            except Exception:
                pass
        original = getattr(self, "_reorder_original", None)
        if original is not None and col is not None:
            try:
                import os
                if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                    print("[REORDER] finished cancel → restore original", flush=True)
            except Exception:
                pass
            original = list(original)
            if list(self._columns) != original:
                for i, c in enumerate(original):
                    if c not in self._columns:
                        continue
                    cur = self._columns.index(c)
                    if cur != i:
                        self._columns.pop(cur)
                        self._columns.insert(i, c)
                        try:
                            self._scroll_layout.removeWidget(c)
                            self._scroll_layout.insertWidget(i, c)
                        except Exception:
                            pass
                try:
                    self._update_boundary_visibility()
                except Exception:
                    pass
        self._reorder_original = None
        self._reorder_preview_index = None
        self._reorder_dragging = None
        self._reorder_last_x = None

    def _commit_column_reorder_at(self, column: AccountColumn, global_x) -> None:
        if column not in self._columns:
            return
        if getattr(self, "_reorder_original", None) is None and getattr(self, "_reorder_dragging", None) is None:
            try:
                import os
                if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                    print("[REORDER] commit skipped (no active drag session)", flush=True)
            except Exception:
                pass
            return
        try:
            import os
            if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                ids = [getattr(c, "get_column_id", lambda: "?")() for c in self._columns]
                print(f"[REORDER] commit start x={global_x} order={ids}", flush=True)
        except Exception:
            pass
        if global_x is not None:
            try:
                last_x = getattr(self, "_reorder_last_x", None)
                moving_right = True if last_x is None else (float(global_x) >= float(last_x))
                new_index = self._reorder_index_from_global_x(
                    column, float(global_x), moving_right
                )
                self._reorder_columns_visual(column, new_index)
            except Exception:
                pass
        key = self._layout_mode_key()
        packs = self._service_packs()
        packs[key] = list(self._columns)
        self._columns = packs[key]
        self._update_boundary_visibility()
        self._save_accounts()
        self._save_columns()
        self._reorder_original = None
        self._reorder_preview_index = None
        self._reorder_dragging = None
        try:
            column.setGraphicsEffect(None)
            if hasattr(column, "_reorder_opacity_effect"):
                column._reorder_opacity_effect = None
        except Exception:
            pass
        ind = getattr(self, "_column_insert_indicator", None)
        if ind is not None:
            ind.hide()
        try:
            import os
            if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                ids = [getattr(c, "get_column_id", lambda: "?")() for c in self._columns]
                print(f"[REORDER] commit done order={ids}", flush=True)
        except Exception:
            pass

    def _redistribute_equal_widths(self) -> None:
        if getattr(self, "_restoring_session", False):
            return
        visible = [c for c in self._columns if c.isVisible()]
        if not visible:
            return
        viewport_width = self._scroll.viewport().width() if self._scroll is not None else 0
        if viewport_width <= 0:
            viewport_width = max(1, self.width() - 8)
        n = len(visible)
        min_w = AccountColumn.MIN_WIDTH
        base = max(min_w, viewport_width // n)
        widths = [base] * n
        rem = viewport_width - sum(widths)
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
        for col, w in zip(visible, widths):
            col.set_width(w, emit_signal=False)
        if self._scroll_layout is not None:
            for col in visible:
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
        n = len(visible)
        equal_share = max(min_w, viewport_width // max(1, n))

        existing = []
        for col in visible:
            if col is new_col:
                continue
            try:
                live = int(col.get_width() or 0)
            except Exception:
                live = 0
            existing.append(float(live if live >= min_w else AccountColumn.DEFAULT_WIDTH))

        near_equal = True
        if existing:
            mean = sum(existing) / len(existing)
            if mean > 0:
                for v in existing:
                    if v > mean * 1.3 or v < mean * 0.7:
                        near_equal = False
                        break
            else:
                near_equal = True

        if near_equal or not existing:
            ratios = [float(equal_share)] * n
        else:
            ratios = []
            for col in visible:
                if col is new_col:
                    ratios.append(float(equal_share))
                else:
                    try:
                        live = int(col.get_width() or 0)
                    except Exception:
                        live = 0
                    ratios.append(float(live if live >= min_w else AccountColumn.DEFAULT_WIDTH))

        total = sum(ratios) or float(n)
        widths = [max(min_w, int(viewport_width * r / total)) for r in ratios]
        diff = viewport_width - sum(widths)
        for i in range(abs(diff)):
            if diff > 0:
                widths[i % n] += 1
            elif widths[n - 1 - (i % n)] > min_w:
                widths[n - 1 - (i % n)] -= 1
        for col, w in zip(visible, widths):
            col.set_width(w, emit_signal=False)
        if self._scroll_layout is not None:
            for col in visible:
                self._scroll_layout.setStretchFactor(col, 0)
        self._save_column_widths()

    def _reset_all_column_widths(self) -> None:
        self._redistribute_equal_widths()

    def _stow_columns_list(self, to_stow, visible, keep_visible=None) -> None:
        keep_visible = list(keep_visible or [])
        snap: dict = dict(getattr(self, "_stow_saved_widths", None) or {})
        pref = dict(getattr(self, "_preferred_widths", None) or {})
        for col in visible:
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
            key = self._layout_mode_key()
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
        to_stow = visible[: idx + 1]
        if not to_stow:
            return
        self._stow_columns_list(to_stow, visible, keep_visible=visible[idx + 1 :])

    def _stow_columns_right_of(self, boundary_col) -> None:
        if boundary_col is None:
            return
        visible = [c for c in self._columns if c.isVisible()]
        if boundary_col not in visible:
            return
        idx = visible.index(boundary_col)
        to_stow = visible[idx + 1 :]
        if not to_stow:
            return
        self._stow_columns_list(to_stow, visible, keep_visible=visible[: idx + 1])

    def _persist_stowed_state(self) -> None:
        if not self._settings_manager:
            return
        if getattr(self, "_restoring_session", False):
            return
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

    def _apply_persisted_stow_on_startup(self) -> None:
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
        pending = list(getattr(self, "_pending_stow_ids", None) or [])
        for cid in pending:
            col = by_id.get(cid)
            if col is not None and col not in stowed:
                stowed.append(col)
        for cid in legacy_ids:
            col = by_id.get(cid)
            if col is not None and col not in stowed:
                stowed.append(col)
        self._pending_stow_ids = []

        if not stowed:
            if legacy_ids and not pending:
                self._clear_persisted_stowed_state()
            return

        for col in stowed:
            try:
                col.hide()
            except Exception:
                pass
        self._stowed_columns = stowed
        self._stow_saved_widths = dict(widths) if widths else dict(getattr(self, "_stow_saved_widths", {}) or {})
        try:
            if not hasattr(self, "_mode_stowed_columns") or self._mode_stowed_columns is None:
                self._mode_stowed_columns = {"normal": [], "lr": [], "tb": []}
            if not hasattr(self, "_mode_stow_saved_widths") or self._mode_stow_saved_widths is None:
                self._mode_stow_saved_widths = {"normal": {}, "lr": {}, "tb": {}}
            key = self._layout_mode_key()
            self._mode_stowed_columns[key] = list(stowed)
            self._mode_stow_saved_widths[key] = dict(self._stow_saved_widths)
            self._bound_mode_key = key
        except Exception:
            pass
        self._fit_columns()
        self._update_boundary_visibility()
        self.hide_boundary_actions()
        self._update_stow_restore_rail()
        try:
            self._persist_stowed_state()
        except Exception:
            pass

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
            key = self._layout_mode_key()
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
        if not remaining and self._layout_mode_key() == "normal":
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
        if not snap:
            self._fit_columns()
            return
        visible = [c for c in self._columns if c.isVisible()]
        if not visible:
            return
        viewport_width = 0
        try:
            viewport_width = int(self._scroll.viewport().width())
        except Exception:
            viewport_width = 0
        if viewport_width <= 0:
            self._fit_columns()
            return
        min_w = AccountColumn.MIN_WIDTH
        ratios = []
        for col in visible:
            cid = col.get_column_id()
            if cid in snap and snap[cid] > 0:
                ratios.append(float(snap[cid]))
            else:
                try:
                    ratios.append(float(col.get_width() or col.width() or min_w))
                except Exception:
                    ratios.append(float(min_w))
        total = sum(ratios)
        if total <= 0:
            self._fit_columns()
            return
        widths = []
        for r in ratios:
            widths.append(max(min_w, int(viewport_width * r / total)))
        diff = viewport_width - sum(widths)
        n = len(widths)
        for i in range(abs(diff)):
            if diff > 0:
                widths[i % n] += 1
            elif diff < 0:
                idx = n - 1 - (i % n)
                if widths[idx] > min_w:
                    widths[idx] -= 1
        for col, w in zip(visible, widths):
            col.set_width(w, emit_signal=False)
        self._scroll_content.setMinimumWidth(0)
        content_h = max(1, self._scroll.viewport().height())
        self._scroll_content.resize(viewport_width, content_h)
        self._scroll_layout.invalidate()
        self._scroll_layout.activate()

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
        on = False
        try:
            gp = event.globalPosition().toPoint()
            local = self.mapFromGlobal(gp)
            on = self._point_on_restore_knob(local.x(), local.y())
        except Exception:
            on = False
        rail = getattr(self, "_stow_restore_rail", None)
        if rail is not None and hasattr(rail, "set_app_hover"):
            try:
                rail.set_app_hover(on)
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
            else:
                try:
                    if c.isVisible():
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

            class _StowRestoreKnob(QWidget):
                _VISUAL = 22
                _HIT = 30
                _ICON = 14
                _MARGIN = 6

                def __init__(self, owner, side: str = "right"):
                    super().__init__(owner)
                    self._owner = owner
                    self._side = "left" if side == "left" else "right"
                    self._hover = False
                    self._shape_t = 0.0
                    self._highlight = 0.0
                    self.setObjectName("stow_restore_knob")
                    self.setFixedSize(self._HIT, self._HIT)
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                    self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                    self.setMouseTracking(True)
                    try:
                        if self._side == "left":
                            from src.ui.icons import make_stow_right_icon
                            self._icon = make_stow_right_icon("#c5d0e6", self._ICON)
                        else:
                            from src.ui.icons import make_expand_left_icon
                            self._icon = make_expand_left_icon("#c5d0e6", self._ICON)
                    except Exception:
                        self._icon = None
                    try:
                        self.winId()
                    except Exception:
                        pass
                    self._shape_anim = QVariantAnimation(self)
                    self._shape_anim.setDuration(160)
                    self._shape_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    self._shape_anim.valueChanged.connect(self._on_shape_t)
                    self._shape_anim.finished.connect(self._on_shape_finished)
                    self._hl_phase = 0.0
                    self._hl_timer = QTimer(self)
                    self._hl_timer.setInterval(40)
                    self._hl_timer.timeout.connect(self._on_hl_tick)
                    self._hl_timer.start()

                def _on_shape_t(self, v) -> None:
                    try:
                        self._shape_t = float(v)
                    except Exception:
                        self._shape_t = 0.0
                    self.update()

                def _on_shape_finished(self) -> None:
                    pass

                def _on_hl_tick(self) -> None:
                    if self._hover or float(self._shape_t) > 0.15:
                        if self._highlight != 0.0:
                            self._highlight = 0.0
                            self.repaint()
                        return
                    import math
                    self._hl_phase = (self._hl_phase + 1.0 / 80.0) % 1.0
                    self._highlight = 0.5 - 0.5 * math.cos(2.0 * math.pi * self._hl_phase)
                    self.repaint()

                def _animate_shape(self, target: float) -> None:
                    self._shape_anim.stop()
                    self._shape_anim.setStartValue(float(self._shape_t))
                    self._shape_anim.setEndValue(float(target))
                    self._shape_anim.start()

                def set_app_hover(self, on: bool) -> None:
                    on = bool(on)
                    if on == self._hover:
                        return
                    self._hover = on
                    if on:
                        self._highlight = 0.0
                        self._animate_shape(1.0)
                    else:
                        self._animate_shape(0.0)
                        self._hl_phase = 0.0

                def enterEvent(self, event) -> None:
                    self.set_app_hover(True)
                    super().enterEvent(event)

                def leaveEvent(self, event) -> None:
                    self.set_app_hover(False)
                    super().leaveEvent(event)

                def mousePressEvent(self, event) -> None:
                    if event.button() == Qt.MouseButton.LeftButton:
                        event.accept()
                        side = getattr(self, "_side", "right")
                        self._owner._restore_stowed_columns(side=side)
                        return
                    super().mousePressEvent(event)

                def paintEvent(self, event) -> None:
                    from PySide6.QtGui import (
                        QPainter as _QP,
                        QPen as _QPen,
                        QColor as _QC,
                        QPainterPath as _QPP,
                    )
                    p = _QP(self)
                    try:
                        p.setRenderHint(_QP.RenderHint.Antialiasing, True)
                        p.setCompositionMode(
                            _QP.CompositionMode.CompositionMode_SourceOver
                        )
                        t = max(0.0, min(1.0, float(self._shape_t)))
                        hl = float(self._highlight) if t < 0.15 else 0.0
                        dim_f = (37, 43, 56)
                        lit_f = (78, 96, 130)
                        dim_e = (61, 70, 92)
                        lit_e = (120, 138, 175)
                        k = max(hl, t * 0.35)

                        def _lerp(a, b, u):
                            return tuple(
                                min(255, int(a[i] + (b[i] - a[i]) * u)) for i in range(3)
                            )

                        fr, fg, fb = _lerp(dim_f, lit_f, k)
                        er, eg, eb = _lerp(dim_e, lit_e, k)
                        face = _QC(fr, fg, fb)
                        edge = _QC(er, eg, eb)
                        s = float(self._VISUAL)
                        r = s / 2.0
                        if getattr(self, "_side", "right") == "left":
                            cx = t * r
                        else:
                            cx = (self.width() - 1.0) - t * r
                        cy = self.height() / 2.0
                        path = _QPP()
                        if t >= 0.995:
                            path.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
                        else:
                            span = 180.0 + 180.0 * t
                            if getattr(self, "_side", "right") == "left":
                                path.moveTo(cx, cy - r)
                                path.arcTo(cx - r, cy - r, 2 * r, 2 * r, 90.0, -span)
                            else:
                                path.moveTo(cx, cy - r)
                                path.arcTo(cx - r, cy - r, 2 * r, 2 * r, 90.0, span)
                            path.closeSubpath()
                        p.setPen(_QPen(edge, 1.2))
                        p.setBrush(face)
                        p.drawPath(path)
                        if t > 0.5:
                            icon = getattr(self, "_icon", None)
                            if icon is not None:
                                pm = icon.pixmap(self._ICON, self._ICON)
                                if not pm.isNull():
                                    p.setOpacity(min(1.0, (t - 0.5) / 0.5))
                                    p.drawPixmap(
                                        int(cx - self._ICON / 2),
                                        int(cy - self._ICON / 2),
                                        pm,
                                    )
                                    p.setOpacity(1.0)
                    except Exception:
                        pass
                    finally:
                        p.end()

                def _stow_y_like_boundary(self, host) -> int:
                    ctrl_bottom = 32
                    try:
                        tb = getattr(host, "_top_bar", None)
                        if tb is not None and tb.isVisible():
                            g = tb.geometry()
                            ctrl_bottom = int(g.y() + g.height())
                    except Exception:
                        pass
                    safe_min = ctrl_bottom + 16

                    try:
                        cols = getattr(host, "_columns", None) or []
                        for col in cols:
                            if col is None or not col.isVisible():
                                continue
                            wv = None
                            for name in ("_webview", "_view", "webview"):
                                wv = getattr(col, name, None)
                                if wv is not None:
                                    break
                            if wv is not None and hasattr(wv, "mapTo"):
                                pt = wv.mapTo(host, QPoint(0, 0))
                                return max(safe_min, int(pt.y()) + 8)
                            top = col.mapTo(host, QPoint(0, 0)).y()
                            return max(safe_min, int(top) + 36)
                    except Exception:
                        pass
                    return max(safe_min, ctrl_bottom + 40)

                def _reposition(self) -> None:
                    host = self._owner
                    # Dock 未展開時だけ隠す。展開中は通常と同じ配置へ進む
                    if getattr(host, "_edge_dock_enabled", False) and not getattr(
                        host, "_edge_dock_revealed", False
                    ):
                        try:
                            self.hide()
                            self.setGeometry(-2000, -2000, 1, 1)
                        except Exception:
                            pass
                        return
                    side = getattr(self, "_side", "right")
                    # 遅延呼び出し時に side 状態が変わっていても古い表示を出さない
                    try:
                        has_left, has_right = host._stow_side_flags()
                    except Exception:
                        has_left, has_right = False, False
                    if side == "left" and not has_left:
                        try:
                            self.hide()
                            self.setGeometry(-2000, -2000, 1, 1)
                        except Exception:
                            pass
                        return
                    if side != "left" and not has_right:
                        try:
                            self.hide()
                            self.setGeometry(-2000, -2000, 1, 1)
                        except Exception:
                            pass
                        return
                    self.setParent(host)
                    if side == "left":
                        x = 0
                    else:
                        x = max(0, host.width() - self._HIT)
                    y = self._stow_y_like_boundary(host)
                    y = min(y, max(8, host.height() - self._HIT - 8))
                    self.setGeometry(x, y, self._HIT, self._HIT)
                    self.setVisible(True)
                    self.show()
                    self.raise_()
                    try:
                        wid = int(self.winId())
                    except Exception:
                        wid = 0

            rail = _StowRestoreKnob(self, side="right")
            self._stow_restore_rail = rail
            self._StowRestoreKnobClass = _StowRestoreKnob
        rail = getattr(self, "_stow_restore_rail", None)
        if rail is None:
            return
        has_left, has_right = self._stow_side_flags()
        left_rail = getattr(self, "_stow_restore_rail_left", None)
        cls = getattr(self, "_StowRestoreKnobClass", None)
        if has_left and left_rail is None and cls is not None:
            left_rail = cls(self, side="left")
            self._stow_restore_rail_left = left_rail
        left_rail = getattr(self, "_stow_restore_rail_left", None)

        def _hide_rail(r) -> None:
            if r is None:
                return
            try:
                r.hide()
                r.setGeometry(-2000, -2000, 1, 1)
            except Exception:
                pass

        if not has:
            self._clear_restore_hand_cursor()
            _hide_rail(rail)
            _hide_rail(left_rail)
            return
        if has_right:
            rail._reposition()
            QTimer.singleShot(0, rail._reposition)
            QTimer.singleShot(100, rail._reposition)
        else:
            _hide_rail(rail)
        if has_left and left_rail is not None:
            left_rail._reposition()
            QTimer.singleShot(0, left_rail._reposition)
            QTimer.singleShot(100, left_rail._reposition)
        else:
            _hide_rail(left_rail)

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

    def _fit_columns(self) -> None:
        if self._media_wide_view is not None:
            self._apply_media_wide_geometry()
            return
        if getattr(self, "_edge_dock_enabled", False) and getattr(self, "_edge_dock_animating", False):
            return
        if getattr(self, "_boundary_pending", None) is not None:
            return
        if getattr(self, "_boundary_dragging", False):
            return
        visible = [c for c in self._columns if c.isVisible()]
        if not visible:
            n = min(self._active_column_count(), len(self._columns))
            visible = self._columns[:n] if n else []
        if not visible:
            return

        viewport_width = 0
        try:
            viewport_width = int(self._scroll.viewport().width())
        except Exception:
            viewport_width = 0
        # Dock 展開直後は viewport がまだ古い幅のことがある。scroll / root 幅で補う
        if getattr(self, "_edge_dock_enabled", False) and getattr(self, "_edge_dock_revealed", False):
            try:
                sw = int(self._scroll.width()) if self._scroll is not None else 0
            except Exception:
                sw = 0
            if sw > viewport_width:
                viewport_width = sw
            if viewport_width <= 0:
                root = getattr(self, "_edge_dock_root", None)
                if root is not None:
                    try:
                        viewport_width = max(1, int(root.width()))
                    except Exception:
                        pass
        if viewport_width <= 0:
            return

        n = len(visible)
        min_w = AccountColumn.MIN_WIDTH

        preferred = dict(getattr(self, "_preferred_widths", None) or {})
        saved = {}
        if self._settings_manager:
            mode = self._layout_mode_key()
            if hasattr(self._settings_manager, "get_column_widths_for_mode"):
                saved = self._settings_manager.get_column_widths_for_mode(mode) or {}
            else:
                saved = self._settings_manager.get_column_widths() or {}

        col_config_by_id = {conf.column_id: conf for conf in self._column_configs}

        ratios = []
        for col in visible:
            cid = col.get_column_id()
            aid = col.get_account_id()
            live_w = 0
            try:
                live_w = int(col.get_width() or 0)
            except Exception:
                live_w = 0
            if cid in preferred and preferred[cid] > 0:
                ratios.append(float(preferred[cid]))
            elif cid in saved and saved[cid] > 0:
                ratios.append(float(saved[cid]))
            elif aid in saved and saved[aid] > 0:
                ratios.append(float(saved[aid]))
            elif cid in col_config_by_id and col_config_by_id[cid].width > 0:
                ratios.append(float(col_config_by_id[cid].width))
            elif live_w >= AccountColumn.MIN_WIDTH:
                ratios.append(float(live_w))
            else:
                ratios.append(float(viewport_width) / n)

        total_ratio = sum(ratios)
        if total_ratio <= 0:
            total_ratio = n

        widths = []
        for r in ratios:
            w = max(min_w, int(viewport_width * r / total_ratio))
            widths.append(w)

        diff = viewport_width - sum(widths)
        for i in range(abs(diff)):
            if diff > 0:
                widths[i % n] += 1
            elif diff < 0:
                idx = n - 1 - (i % n)
                if widths[idx] > min_w:
                    widths[idx] -= 1

        for col, w in zip(visible, widths):
            col.set_width(w, emit_signal=False)

        self._scroll_content.setMinimumWidth(0)
        content_h = max(1, self._scroll.viewport().height())
        self._scroll_content.resize(viewport_width, content_h)
        self._scroll_layout.invalidate()
        self._scroll_layout.activate()
        self._update_boundary_visibility()

    def _update_boundary_visibility(self) -> None:
        visible = [c for c in self._columns if c.isVisible()]
        for col in self._columns:
            col.set_boundary_enabled(False)
            if hasattr(col, "_boundary_right_col"):
                col._boundary_right_col = None
        if len(visible) >= 2:
            # 可視カラムの geometry が決まってから境界を付ける
            try:
                self._scroll_layout.activate()
            except Exception:
                pass
        for i in range(max(0, len(visible) - 1)):
            left = visible[i]
            right = visible[i + 1]
            left._boundary_right_col = right
            left.set_boundary_enabled(True)
            if hasattr(left, "_position_resize_handles"):
                left._position_resize_handles()

    def _check_hibernation(self) -> None:
        for col in self._columns:
            for tab in col.webviews():
                if hasattr(tab, "maybe_freeze"):
                    tab.maybe_freeze()

    def _on_boundary_dragged(self, column: AccountColumn, delta: int) -> None:
        self._boundary_dragging = True
        left_col = column
        right_col = getattr(column, "_boundary_right_col", None)
        if right_col is None or right_col not in self._columns:
            visible = [c for c in self._columns if c.isVisible()]
            if column not in visible:
                return
            idx = visible.index(column)
            if idx >= len(visible) - 1:
                return
            right_col = visible[idx + 1]

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
        content = getattr(self, "_scroll_content", None)
        if content is not None and content.layout() is not None:
            content.layout().activate()

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
        self._save_column_widths()

    def _save_column_widths(self) -> None:
        if not self._settings_manager:
            return
        stowed = set()
        try:
            stowed = set(getattr(self, "_stowed_columns", None) or [])
        except Exception:
            stowed = set()
        pref = dict(getattr(self, "_preferred_widths", None) or {})
        snap = dict(getattr(self, "_stow_saved_widths", None) or {})
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
            if col in stowed:
                w = int(snap.get(cid) or pref.get(cid) or 0)
                if w <= 0:
                    try:
                        w = int(col.get_width() or 0)
                    except Exception:
                        w = 0
            elif cid in snap and int(snap.get(cid) or 0) > 0:
                w = int(snap[cid])
            else:
                try:
                    w = int(col.get_width() or 0)
                except Exception:
                    w = 0
                if w > 0:
                    pref[cid] = w
            if w > 0:
                widths[cid] = w
            if aid and w > 0:
                by_account.setdefault(aid, []).append(w)
        self._preferred_widths = pref
        try:
            key = self._layout_mode_key()
            if not hasattr(self, "_mode_preferred_widths") or self._mode_preferred_widths is None:
                self._mode_preferred_widths = {"normal": {}, "lr": {}, "tb": {}}
            self._mode_preferred_widths[key] = dict(pref)
        except Exception:
            pass
        for aid, ws in by_account.items():
            if len(ws) == 1 and ws[0] > 0:
                widths[aid] = ws[0]
        mode = self._layout_mode_key()
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
        reg = self._known_accounts.get(aid, {})
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
        stowed = False
        try:
            # 対象 mode の収納だけを見る（他 mode の収納を現在モードへ混ぜない）
            key = for_mode or self._layout_mode_key()
            if key == self._layout_mode_key():
                stowed = col in (getattr(self, "_stowed_columns", None) or [])
            else:
                stowed = col in (
                    (getattr(self, "_mode_stowed_columns", None) or {}).get(key) or []
                )
        except Exception:
            stowed = False
        width_out = max(1, int(col.get_width() or 0))
        try:
            snap = getattr(self, "_stow_saved_widths", None) or {}
            if cid in snap and int(snap[cid]) > 0:
                width_out = int(snap[cid])
        except Exception:
            pass
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
            "stowed": bool(stowed),
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

        try:
            key = self._layout_mode_key()
            packs = self._service_packs()
            packs[key] = list(self._columns)
        except Exception:
            packs = self._service_packs()

        for mode in ("normal", "lr", "tb"):
            cols = list((packs or {}).get(mode) or [])
            if mode == self._layout_mode_key():
                cols = list(self._columns)
            if not cols and mode != "normal":
                continue
            data = _pack_to_list(cols, mode)
            try:
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
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QWidget,
        )
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer, QRectF
        from PySide6.QtGui import QPainterPath, QRegion
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

        dlg = QDialog(self)
        dlg.setObjectName("mayotter_external_confirm_dialog")
        dlg.setModal(True)
        dlg.setWindowTitle("外部サイト")
        dlg.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            apply_overlay_theme(dlg)
        except Exception:
            pass
        dlg.setStyleSheet(
            "QDialog#mayotter_external_confirm_dialog {"
            " background:transparent; border:none; }"
        )

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        surface = QWidget(dlg)
        surface.setObjectName("mayotter_external_confirm_surface")
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        surface.setStyleSheet(
            f"QWidget#mayotter_external_confirm_surface {{"
            f" background:{SURFACE}; border:1px solid {BORDER};"
            f" border-radius:{RADIUS_MD}px; }}"
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
            close_tb.setIcon(make_close_icon("#93a5c4", 12))
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

        url_lbl = QLabel(url)
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

        state = {"choice": "cancel", "finished": False}

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

        def _clear_pending():
            try:
                if getattr(self, "_external_confirm_dialog", None) is dlg:
                    self._external_confirm_dialog = None
            except Exception:
                pass

        def _finish_close():
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
            _clear_pending()
            try:
                dlg.hide()
                dlg.deleteLater()
            except Exception:
                pass

        def _apply_choice(choice: str):
            if state["finished"]:
                return
            state["finished"] = True
            state["choice"] = choice
            if choice == "browser":
                try:
                    open_in_default_browser(url)
                except Exception:
                    pass
            elif choice == "app":
                self._open_confirmed_external_in_app(url, page_ref)

        def _fade_close(choice: str):
            if getattr(dlg, "_mayotter_fading_out", False):
                return
            if getattr(dlg, "_mayotter_done", False):
                return
            dlg._mayotter_fading_out = True
            _apply_choice(choice)
            try:
                anim = QPropertyAnimation(dlg, b"windowOpacity", dlg)
                anim.setDuration(int(POPOVER_CLOSE_MS))
                anim.setStartValue(float(dlg.windowOpacity() or 1.0))
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.Type.InCubic)
                anim.finished.connect(_finish_close)
                anim.start()
                dlg._mayotter_fade_anim = anim
                QTimer.singleShot(int(POPOVER_CLOSE_MS) + 80, _finish_close)
            except Exception:
                _finish_close()

        close_tb.clicked.connect(lambda: _fade_close("cancel"))
        btn_cancel.clicked.connect(lambda: _fade_close("cancel"))
        btn_browser.clicked.connect(lambda: _fade_close("browser"))
        btn_app.clicked.connect(lambda: _fade_close("app"))
        dlg.reject = lambda *a, **k: _fade_close("cancel")
        dlg.accept = lambda *a, **k: _fade_close(state.get("choice") or "cancel")

        def _on_destroyed(*_a):
            _clear_pending()

        try:
            dlg.destroyed.connect(_on_destroyed)
        except Exception:
            pass

        dlg.resize(420, 200)
        try:
            dlg.adjustSize()
        except Exception:
            pass
        _apply_round_mask()

        self._external_confirm_dialog = dlg
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

    def _open_confirmed_external_in_app(self, url: str, page=None) -> None:
        from PySide6.QtCore import QUrl
        from src.browser.webview import MayotterPage, XWebView

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
        tabs = list(tabs or [])
        if not tabs:
            return
        norm = []
        for t in tabs:
            if isinstance(t, dict):
                u = (t.get("url") or "").strip()
            else:
                u = (str(t) or "").strip()
            if u.startswith("about:") or u.startswith("data:"):
                u = ""
            norm.append(u)
        if not any(norm):
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
        idx = max(0, min(idx, max(0, len(norm) - 1)))

        for i, url in enumerate(norm[1:], start=1):
            try:
                webview = XWebView(profile)
                if hasattr(webview, "download_progress"):
                    webview.download_progress.connect(self._on_download_progress)
                column.add_tab_view(webview)
                if url:
                    if i == idx:
                        if defer_load_ms:
                            from PySide6.QtCore import QTimer
                            delay = int(defer_load_ms) + i * 50
                            QTimer.singleShot(
                                delay,
                                lambda w=webview, u=url: w.load_url(u, restore=True),
                            )
                        else:
                            webview.load_url(url, restore=True)
                    else:
                        webview._pending_restore_url = url
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
