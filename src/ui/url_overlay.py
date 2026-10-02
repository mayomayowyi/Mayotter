

from __future__ import annotations

import math
import time
from PySide6.QtCore import Qt, QEvent, Signal, QTimer, QRectF, QSize, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QColor, QPen, QBrush, QFont, QRegion
from src.ui.icons import (
    make_close_icon,
    make_folder_icon,
    make_trash_icon,
    make_file_open_icon,
    make_download_icon,
    make_forward_icon,
    _COLOR_SECONDARY,
    _COLOR_DANGER,
    _COLOR_ACCENT_SOFT,
    _COLOR_TEXT_SECONDARY,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProxyStyle,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.browser.webview import normalize_user_input_url
from src.ui.theme import themed_qcolor, color as theme_color

def rounded_overlay_mask(width: int, height: int, radius: int = 8) -> QRegion:
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

def _apply_smooth_overlay_shape(widget: QWidget) -> None:
    """角は DWM に任せる。QRegion は DWM の角丸が使えない環境のときだけ使う。"""
    try:
        from src.ui.window_polish import prepare_popup_chrome, native_rounding_available
        if native_rounding_available():
            widget.clearMask()
            if prepare_popup_chrome(widget, corner="round"):
                return
    except Exception:
        pass
    try:
        widget.setProperty("mayotterNativeRounded", False)
        widget.setMask(rounded_overlay_mask(widget.width(), widget.height()))
    except Exception:
        pass


def _overlay_outside_press_should_close(overlay, event, trigger_names: set[str]) -> bool:
    if not isinstance(event, QMouseEvent):
        return False
    if event.button() != Qt.MouseButton.LeftButton:
        return False
    try:
        gp = event.globalPosition().toPoint()
    except Exception:
        return False
    try:
        if overlay.rect().contains(overlay.mapFromGlobal(gp)):
            return False
    except Exception:
        pass
    try:
        w = QApplication.widgetAt(gp)
    except Exception:
        w = None
    cur = w
    while cur is not None:
        try:
            if cur is overlay or overlay.isAncestorOf(cur):
                return False
        except Exception:
            pass
        try:
            on = str(cur.objectName() or "")
        except Exception:
            on = ""
        if on in trigger_names:
            return False
        try:
            cur = cur.parentWidget()
        except Exception:
            break
    return True


def _promote_overlay_tool(widget: QWidget, parent: QWidget | None) -> None:
    from PySide6.QtCore import QPoint
    geo = widget.geometry()
    if parent is not None:
        try:
            tl = parent.mapToGlobal(geo.topLeft())
        except Exception:
            tl = QPoint(geo.x(), geo.y())
    else:
        tl = QPoint(geo.x(), geo.y())
    w, h = int(geo.width()), int(geo.height())
    widget._mayotter_tool_parent = parent
    try:
        widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)
        # このオーバーレイは不透明な SURFACE を自前で塗る。ウィンドウを半透明にすると
        # Windows ではポップアップ全体からデスクトップが透けることがあるので、
        # 半透明は専用の外枠と内側サーフェスを持つダイアログだけに限る。
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
    except Exception:
        pass
    # IME
    flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
    parent_topmost = False
    if parent is not None:
        try:
            if bool(parent.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
                parent_topmost = True
        except Exception:
            pass
        try:
            ph = parent.windowHandle()
            if ph is not None and bool(ph.flags() & Qt.WindowType.WindowStaysOnTopHint):
                parent_topmost = True
        except Exception:
            pass
    if parent_topmost:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    widget.setWindowFlags(flags)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setFixedSize(w, h)
    widget.setGeometry(tl.x(), tl.y(), w, h)
    if parent is not None:
        try:
            _ = parent.winId()
            _ = widget.winId()
            wh = widget.windowHandle()
            ph = parent.windowHandle()
            if wh is not None and ph is not None:
                wh.setTransientParent(ph)
        except Exception:
            pass


def _demote_overlay_child(widget: QWidget) -> None:
    parent = getattr(widget, "_mayotter_tool_parent", None)
    if parent is None:
        return
    try:
        widget.setParent(parent)
        widget.setWindowFlags(Qt.WindowType.Widget)
        widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.hide()
    except Exception:
        pass
    _hide_native_descendants(widget)


def _hide_native_descendants(widget: QWidget) -> None:
    """再親子化後、子孫のネイティブ HWND が表示のまま残り、閉じたはずの内容が透けて見えるのを防ぐ。

    Qt 側は非表示扱いなので、次に show されるときは Qt が改めて表示する。
    """
    try:
        import ctypes
        hide = ctypes.windll.user32.ShowWindow
        for child in widget.findChildren(QWidget):
            hwnd = int(child.internalWinId() or 0)
            if hwnd:
                hide(hwnd, 0)
    except Exception:
        pass

def _overlay_close(widget, *, clear=None) -> None:
    try:
        QApplication.instance().removeEventFilter(widget)
    except Exception:
        pass
    try:
        from src.ui.theme import menu_dropdown_hide

        def _after():
            if callable(clear):
                try:
                    clear()
                except Exception:
                    pass

        menu_dropdown_hide(widget, on_finished=_after if clear else None)
    except Exception:
        try:
            widget.hide()
        except Exception:
            pass
        if callable(clear):
            try:
                clear()
            except Exception:
                pass

def install_dark_lineedit_menu(line_edit) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu, QApplication
    from PySide6.QtGui import QAction

    def _style(menu):
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
                "QMenu::item:disabled { color:#7f899a; }"
            )

    def _show(pos, le=line_edit):
        menu = QMenu(le)
        _style(menu)
        text = le.text() or ""
        sel = ""
        try:
            sel = le.selectedText() or ""
        except Exception:
            pass
        clip = ""
        try:
            clip = QApplication.clipboard().text() or ""
        except Exception:
            pass
        can_edit = not le.isReadOnly()
        has_sel = bool(sel)
        has_text = bool(text)
        undo_ok = can_edit and bool(getattr(le, "isUndoAvailable", lambda: False)())
        redo_ok = can_edit and bool(getattr(le, "isRedoAvailable", lambda: False)())

        act_undo = QAction("元に戻す", menu)
        act_redo = QAction("やり直す", menu)
        act_cut = QAction("切り取り", menu)
        act_copy = QAction("コピー", menu)
        act_paste = QAction("貼り付け", menu)
        act_sel = QAction("すべて選択", menu)

        act_undo.setEnabled(undo_ok)
        act_redo.setEnabled(redo_ok)
        act_cut.setEnabled(can_edit and has_sel)
        act_copy.setEnabled(has_sel or has_text)
        act_paste.setEnabled(can_edit and bool(clip))
        act_sel.setEnabled(has_text)

        act_undo.triggered.connect(lambda _checked=False, w=le: w.undo())
        act_redo.triggered.connect(lambda _checked=False, w=le: w.redo())
        act_cut.triggered.connect(lambda _checked=False, w=le: w.cut())
        act_copy.triggered.connect(
            lambda _checked=False, w=le: QApplication.clipboard().setText(
                (w.selectedText() or w.text() or "")
            )
        )
        act_paste.triggered.connect(lambda _checked=False, w=le: w.paste())
        act_sel.triggered.connect(lambda _checked=False, w=le: w.selectAll())

        menu.addAction(act_undo)
        menu.addAction(act_redo)
        menu.addSeparator()
        menu.addAction(act_cut)
        menu.addAction(act_copy)
        menu.addAction(act_paste)
        menu.addSeparator()
        menu.addAction(act_sel)
        menu.exec(le.mapToGlobal(pos))

    line_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    line_edit.customContextMenuRequested.connect(_show)

class UrlOverlay(QWidget):

    OVERLAY_WIDTH = 560

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("url_overlay")
        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(self)
        except Exception:
            pass

        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setObjectName("url_overlay_input")
        self._input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self._input.setMinimumHeight(28)
        self._input.returnPressed.connect(self._navigate)
        self._input.installEventFilter(self)
        install_dark_lineedit_menu(self._input)
        row.addWidget(self._input, 1)

        self._go_btn = QToolButton()
        self._go_btn.setObjectName("url_go_btn")
        self._go_btn.setIcon(make_forward_icon(_COLOR_SECONDARY, 14))
        self._go_btn.setIconSize(QSize(14, 14))
        self._go_btn.setFixedSize(28, 28)
        self._go_btn.setToolTip("移動")
        self._go_btn.clicked.connect(self._navigate)
        row.addWidget(self._go_btn)

        layout.addLayout(row)

        self.hide()

    def open_for(self, column) -> None:
        self._column = column
        self._input.setText(column.get_current_tab_url())
        parent = self.parentWidget()
        if parent is not None:
            width = min(self.OVERLAY_WIDTH, max(parent.width() - 40, 240))
            x = (parent.width() - width) // 2
            y = 44
            try:
                self.ensurePolished()
            except Exception:
                pass
            h = max(int(self.sizeHint().height() or 0), 40)
            self.setFixedSize(width, h)
            self.setGeometry(x, y, width, h)
        _apply_smooth_overlay_shape(self)
        _promote_overlay_tool(self, parent)
        _apply_smooth_overlay_shape(self)
        try:
            from src.ui.theme import popover_show
            popover_show(self)
        except Exception:
            self.show()
            self.raise_()
        try:
            self.activateWindow()
        except Exception:
            pass
        self._input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)
        self._input.selectAll()
        QApplication.instance().installEventFilter(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _apply_smooth_overlay_shape(self)

    def close_overlay(self) -> None:
        def _clear():
            self._column = None
            try:
                _demote_overlay_child(self)
            except Exception:
                pass
        _overlay_close(self, clear=_clear)

    def is_open(self) -> bool:
        return self.isVisible()

    def eventFilter(self, obj, event: QEvent) -> bool:

        etype = event.type()
        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close_overlay()
                return True
        elif etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                if _overlay_outside_press_should_close(self, event, {"url_bar"}):
                    self.close_overlay()
        return False

    def _navigate(self) -> None:
        url = normalize_user_input_url(self._input.text())
        if url and self._column is not None:
            self._column.navigate(url)
        self.close_overlay()

class TextPromptOverlay(QWidget):

    OVERLAY_WIDTH = 360

    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("text_prompt_overlay")
        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(self)
        except Exception:
            pass

        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self._title_label = QLabel()
        self._title_label.setObjectName("text_prompt_title")
        layout.addWidget(self._title_label)

        self._input = QLineEdit()
        self._input.setObjectName("url_overlay_input")
        self._input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self._input.setMinimumHeight(24)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._confirm)
        self._input.installEventFilter(self)
        install_dark_lineedit_menu(self._input)
        layout.addWidget(self._input)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        self._cancel_btn = QPushButton("キャンセル")
        self._cancel_btn.setObjectName("text_prompt_cancel")
        self._cancel_btn.clicked.connect(self.close_overlay)
        row.addWidget(self._cancel_btn)
        self._ok_btn = QPushButton("保存")
        self._ok_btn.setObjectName("text_prompt_ok")
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self._confirm)
        row.addWidget(self._ok_btn)
        layout.addLayout(row)

        self.hide()

    def open_prompt(
        self, title: str, initial: str = "", ok_text: str = "保存", allow_empty: bool = False
    ) -> None:
        self._allow_empty = bool(allow_empty)
        self._title_label.setText(title)
        self._ok_btn.setText(ok_text)
        self._input.setText(initial)
        try:
            self._ok_btn.setEnabled(bool((initial or "").strip()) or self._allow_empty)
        except Exception:
            pass
        parent = self.parentWidget()
        if parent is not None:
            width = min(self.OVERLAY_WIDTH, max(parent.width() - 40, 240))
            x = (parent.width() - width) // 2
            y = 44
            try:
                self.ensurePolished()
                self.adjustSize()
            except Exception:
                pass
            h = max(int(self.sizeHint().height() or 0), 80)
            self.setFixedSize(width, h)
            self.setGeometry(x, y, width, h)
        _apply_smooth_overlay_shape(self)
        _promote_overlay_tool(self, parent)
        _apply_smooth_overlay_shape(self)
        try:
            from src.ui.theme import popover_show
            popover_show(self)
        except Exception:
            self.show()
            self.raise_()
        try:
            self.activateWindow()
        except Exception:
            pass
        self._input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)
        self._input.selectAll()
        QApplication.instance().installEventFilter(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _apply_smooth_overlay_shape(self)

    def close_overlay(self) -> None:
        def _clear():
            try:
                _demote_overlay_child(self)
            except Exception:
                pass
        _overlay_close(self, clear=_clear)

    def is_open(self) -> bool:
        return self.isVisible()

    def eventFilter(self, obj, event: QEvent) -> bool:

        etype = event.type()
        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close_overlay()
                return True
        elif etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if (event.button() == Qt.MouseButton.LeftButton and
                    not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint()))):
                self.close_overlay()
        return False

    def _on_text_changed(self, text: str) -> None:
        allow_empty = bool(getattr(self, "_allow_empty", False))
        self._ok_btn.setEnabled(bool(text.strip()) or allow_empty)

    def _confirm(self) -> None:
        value = self._input.text().strip()
        allow_empty = bool(getattr(self, "_allow_empty", False))
        if not value and not allow_empty:
            return
        self.close_overlay()
        self.accepted.emit(value)

class _NoComboArrowStyle(QProxyStyle):

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorArrowDown and isinstance(
            widget, QComboBox
        ):
            return
        super().drawPrimitive(element, option, painter, widget)

    def drawComplexControl(self, control, option, painter, widget=None):
        if control == QStyle.ComplexControl.CC_ComboBox and widget is not None:
            opt = QStyleOptionComboBox()
            if isinstance(option, QStyleOptionComboBox):
                opt = QStyleOptionComboBox(option)
            else:
                return super().drawComplexControl(control, option, painter, widget)
            try:
                opt.subControls = (
                    opt.subControls
                    & ~QStyle.SubControl.SC_ComboBoxArrow
                )
            except Exception:
                pass
            return super().drawComplexControl(control, opt, painter, widget)
        return super().drawComplexControl(control, option, painter, widget)

class AccountComboBox(QComboBox):

    ARROW_ZONE = 22

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("column_add_combo")
        self.setStyle(_NoComboArrowStyle(self.style()))
        self._list_popup: QFrame | None = None
        self.setStyleSheet(
            "QComboBox#column_add_combo {"
            "  background-color: #141e30;"
            "  border: 1px solid #1d2d44;"
            "  border-radius: 6px;"
            "  padding: 2px 22px 2px 6px;"
            "  color: #eaf1fb;"
            "  min-height: 24px;"
            "}"
            "QComboBox#column_add_combo::drop-down {"
            "  border: none;"
            "  width: 28px;"
            "}"
            "QComboBox#column_add_combo::down-arrow {"
            "  image: none; border: none; width: 0px; height: 0px;"
            "}"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        from PySide6.QtGui import QPainter, QPen
        from PySide6.QtCore import Qt as _Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        div_x = self.width() - self.ARROW_ZONE
        p.fillRect(div_x, 1, self.ARROW_ZONE - 1, self.height() - 2, themed_qcolor("#141e30"))
        p.setPen(QPen(themed_qcolor("#1d2d44"), 1))
        p.drawLine(div_x, 6, div_x, self.height() - 6)
        p.setPen(
            QPen(
                themed_qcolor("#9fb4d8"),
                1.6,
                _Qt.PenStyle.SolidLine,
                _Qt.PenCapStyle.RoundCap,
                _Qt.PenJoinStyle.RoundJoin,
            )
        )
        cx = self.width() - self.ARROW_ZONE // 2
        cy = self.height() // 2
        p.drawLine(cx - 5, cy - 2, cx, cy + 3)
        p.drawLine(cx + 5, cy - 2, cx, cy + 3)
        p.end()

    def mousePressEvent(self, event) -> None:
        import time as _time
        from PySide6.QtCore import Qt as _Qt
        if event.button() == _Qt.MouseButton.LeftButton:
            pop = self._list_popup
            if pop is not None and (
                pop.isVisible() or getattr(pop, "_mayotter_fading_out", False)
            ):
                self.hidePopup()
                self._popup_closed_at = _time.monotonic()
                event.accept()
                return

            if _time.monotonic() - float(getattr(self, "_popup_closed_at", 0.0) or 0.0) < 0.35:
                event.accept()
                return
            try:
                self.setFocus(_Qt.FocusReason.MouseFocusReason)
            except Exception:
                pass
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def showPopup(self) -> None:
        if self.count() <= 0:
            return
        import time as _time
        pop = self._list_popup
        if pop is not None and pop.isVisible() and not getattr(pop, "_mayotter_fading_out", False):
            self.hidePopup()
            return

        if _time.monotonic() - float(getattr(self, "_popup_closed_at", 0.0) or 0.0) < 0.28:
            return
        from PySide6.QtWidgets import QSizePolicy, QDialog
        from PySide6.QtCore import QSize as _QSize, QPoint as _QPoint
        if self._list_popup is None:
            owner = self.window()
            embedded_popup = isinstance(owner, QDialog)
            if embedded_popup:
                # QDialog.exec() 中に別 top-level の Tool を出すと、Windows では
                # modal blocker 側に入力が吸われて警告音だけ鳴ることがある。
                # 設定画面では dialog 内の通常 child として重ね、modal 境界を跨がない。
                pop = QFrame(owner)
            else:
                flags = (
                    Qt.WindowType.Tool
                    | Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.NoDropShadowWindowHint
                )
                try:
                    if bool(owner.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
                        flags |= Qt.WindowType.WindowStaysOnTopHint
                except Exception:
                    pass
                try:
                    handle = owner.windowHandle()
                    if handle is not None and bool(
                        handle.flags() & Qt.WindowType.WindowStaysOnTopHint
                    ):
                        flags |= Qt.WindowType.WindowStaysOnTopHint
                except Exception:
                    pass
                pop = QFrame(owner, flags)
                try:
                    _ = owner.winId()
                    _ = pop.winId()
                    wh = pop.windowHandle()
                    oh = owner.windowHandle()
                    if wh is not None and oh is not None:
                        wh.setTransientParent(oh)
                except Exception:
                    pass
            pop._mayotter_embedded_popup = embedded_popup
            pop.setObjectName("account_combo_popover")
            pop.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

            def _pop_set_visible(visible, _pop=pop):
                if (not visible) and _pop.isVisible() and not getattr(_pop, "_mayotter_allow_hide", False):
                    if getattr(_pop, "_mayotter_fading_out", False):
                        return
                    _pop._mayotter_fading_out = True
                    try:
                        from src.ui.theme import menu_dropdown_hide

                        def _after():
                            _pop._mayotter_fading_out = False
                            _pop._mayotter_allow_hide = True
                            try:
                                QFrame.setVisible(_pop, False)
                            finally:
                                _pop._mayotter_allow_hide = False
                            try:
                                import time as _t
                                self._popup_closed_at = _t.monotonic()
                            except Exception:
                                pass

                        menu_dropdown_hide(_pop, on_finished=_after)
                    except Exception:
                        _pop._mayotter_fading_out = False
                        _pop._mayotter_allow_hide = True
                        try:
                            QFrame.setVisible(_pop, False)
                        finally:
                            _pop._mayotter_allow_hide = False
                    return
                QFrame.setVisible(_pop, visible)

            pop.setVisible = _pop_set_visible
            pop.setStyleSheet(
                "QFrame#account_combo_popover {"
                "  background-color: #181c26;"
                "  border: 1px solid #2b3242;"
                "  border-radius: 8px;"
                "}"
                "QFrame#account_combo_popover[mayotterNativeRounded=\"true\"] {"
                "  border-radius: 0px;"
                "}"
                "QListWidget#account_combo_list {"
                "  background: transparent; border: none; color: #f1f3f7;"
                "  outline: none; padding: 2px;"
                "}"
                "QListWidget#account_combo_list::item {"
                "  padding: 5px 10px; border-radius: 4px;"
                "}"
                "QListWidget#account_combo_list::item:selected,"
                "QListWidget#account_combo_list::item:hover {"
                "  background: rgba(148,178,230,0.18);"
                "}"
                "QScrollBar:vertical {"
                "  background: transparent; width: 6px; margin: 4px 1px 4px 0;"
                "  border: none;"
                "}"
                "QScrollBar::handle:vertical {"
                "  background: #3a4458; min-height: 20px; border-radius: 3px;"
                "}"
                "QScrollBar::handle:vertical:hover { background: #51607a; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
                "  height: 0; background: none; border: none;"
                "}"
                "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
                "  background: none;"
                "}"
            )
            lay = QVBoxLayout(pop)
            lay.setContentsMargins(3, 3, 3, 3)
            lay.setSpacing(0)
            lst = QListWidget(pop)
            lst.setObjectName("account_combo_list")
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lst.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lst.setUniformItemSizes(True)
            lst.itemClicked.connect(self._on_popover_item)
            lay.addWidget(lst)
            self._list_popup = pop
            self._list_widget = lst
        lst = self._list_widget
        lst.clear()
        row_h = 26
        w = max(int(self.width()), 180)
        for i in range(self.count()):
            item = QListWidgetItem(self.itemText(i))
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(_QSize(w - 12, row_h))
            lst.addItem(item)
        cur = self.currentIndex()
        if 0 <= cur < lst.count():
            lst.setCurrentRow(cur)

        n = max(1, self.count())
        content_h = n * row_h + 4
        gp = self.mapToGlobal(self.rect().bottomLeft())
        try:
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.screenAt(gp) or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else None
            if avail is not None:
                max_h = max(row_h * 3, int(avail.bottom() - gp.y() - 14))
            else:
                max_h = row_h * 14
        except Exception:
            max_h = row_h * 14
        list_h = min(content_h, max_h)
        h = list_h + 6
        lst.setFixedHeight(list_h)

        self._list_popup.setFixedSize(w, h)
        if not getattr(self._list_popup, "_mayotter_embedded_popup", False):
            owner = self.window()
            flags = (
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.NoDropShadowWindowHint
            )
            try:
                if bool(owner.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
                    flags |= Qt.WindowType.WindowStaysOnTopHint
            except Exception:
                pass
            try:
                handle = owner.windowHandle()
                if handle is not None and bool(
                    handle.flags() & Qt.WindowType.WindowStaysOnTopHint
                ):
                    flags |= Qt.WindowType.WindowStaysOnTopHint
            except Exception:
                pass
            try:
                if self._list_popup.windowFlags() != flags:
                    geo = self._list_popup.geometry()
                    self._list_popup.setWindowFlags(flags)
                    self._list_popup.setGeometry(geo)
                _ = owner.winId()
                _ = self._list_popup.winId()
                wh = self._list_popup.windowHandle()
                oh = owner.windowHandle()
                if wh is not None and oh is not None:
                    wh.setTransientParent(oh)
            except Exception:
                pass
        ax, ay = int(gp.x()), int(gp.y() + 2)
        if getattr(self._list_popup, "_mayotter_embedded_popup", False):
            owner = self._list_popup.parentWidget()
            if owner is not None:
                local = owner.mapFromGlobal(_QPoint(ax, ay))
                self._list_popup.move(local)
                self._list_popup._locked_xy = (int(local.x()), int(local.y()))
            else:
                self._list_popup.move(ax, ay)
                self._list_popup._locked_xy = (ax, ay)
            try:
                self._list_popup.setMask(rounded_overlay_mask(w, h))
            except Exception:
                pass
        else:
            self._list_popup.move(ax, ay)
            self._list_popup._locked_xy = (ax, ay)
            try:
                _apply_smooth_overlay_shape(self._list_popup)
            except Exception:
                pass
        try:
            from src.ui.theme import popover_show
            popover_show(self._list_popup)
        except Exception:
            self._list_popup.show()
            self._list_popup.raise_()
        self._install_popup_outside_filter()

    def hidePopup(self) -> None:
        import time as _time
        pop = self._list_popup
        if pop is None:
            return
        if getattr(pop, "_mayotter_fading_out", False):
            return
        if not pop.isVisible():
            return

        def _mark_closed():
            self._popup_closed_at = _time.monotonic()
            self._remove_popup_outside_filter()

        try:
            from src.ui.theme import popover_hide
            pop._mayotter_fading_out = True
            popover_hide(pop, on_finished=_mark_closed)
        except Exception:
            try:
                pop._mayotter_allow_hide = True
                pop.hide()
            finally:
                pop._mayotter_allow_hide = False
                pop._mayotter_fading_out = False
            _mark_closed()

    def _install_popup_outside_filter(self) -> None:
        try:
            from PySide6.QtCore import QObject, QEvent
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return
            old = getattr(self, "_popup_outside_filter", None)
            if old is not None:
                try:
                    app.removeEventFilter(old)
                except Exception:
                    pass

            combo = self

            class _OutsideFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() != QEvent.Type.MouseButtonPress:
                        return False
                    pop = getattr(combo, "_list_popup", None)
                    if pop is None or not pop.isVisible():
                        return False
                    if getattr(pop, "_mayotter_fading_out", False):
                        return False
                    try:
                        gp = event.globalPosition().toPoint()
                    except Exception:
                        try:
                            gp = event.globalPos()
                        except Exception:
                            return False
                    try:
                        if pop.rect().contains(pop.mapFromGlobal(gp)):
                            return False
                        if combo.rect().contains(combo.mapFromGlobal(gp)):
                            return False
                    except Exception:
                        return False
                    combo.hidePopup()
                    return False

            filt = _OutsideFilter(self)
            self._popup_outside_filter = filt
            app.installEventFilter(filt)
        except Exception:
            pass

    def _remove_popup_outside_filter(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            old = getattr(self, "_popup_outside_filter", None)
            if app is not None and old is not None:
                app.removeEventFilter(old)
            self._popup_outside_filter = None
        except Exception:
            pass

    def _on_popover_item(self, item) -> None:
        if item is None:
            return
        try:
            idx = int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            idx = -1
        if 0 <= idx < self.count():
            self.setCurrentIndex(idx)
        self.hidePopup()

    def refresh_theme(self) -> None:
        self.setStyleSheet(
            "QComboBox#column_add_combo {"
            f"  background-color: {theme_color('SURFACE_SUNKEN')};"
            f"  border: 1px solid {theme_color('BORDER')};"
            f"  border-radius: 6px;"
            f"  padding: 2px 22px 2px 6px;"
            f"  color: {theme_color('TEXT')};"
            f"  min-height: 24px;"
            "}"
            "QComboBox#column_add_combo::drop-down {"
            "  border: none;"
            "  width: 28px;"
            "}"
            "QComboBox#column_add_combo::down-arrow {"
            "  image: none; border: none; width: 0px; height: 0px;"
            "}"
        )
        self.update()

class ColumnAddOverlay(QWidget):

    OVERLAY_WIDTH = 380

    column_added = Signal(object)
    closed = Signal()

    _SOURCE_TYPE_DEFS: list[tuple[str, str]] = [
        ("home", "ホーム"),
        ("notifications", "通知"),
        ("favorites", "お気に入り"),
        ("profile", "プロフィール"),
        ("lists", "リスト"),
        ("search", "検索"),
        ("direct_messages", "DM"),
        ("grok", "Grok"),
        ("scheduled", "予約"),
        ("unsent", "未送信"),
    ]

    _INPUT_PLACEHOLDERS: dict[str, str] = {
        "search": "検索キーワード",
    }

    _INPUT_LABELS: dict[str, str] = {
        "search": "キーワード:",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("column_add_overlay")
        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(self)
        except Exception:
            pass

        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self._title_label = QLabel("カラムを追加")
        self._title_label.setObjectName("text_prompt_title")
        layout.addWidget(self._title_label)

        acct_row = QHBoxLayout()
        acct_row.setSpacing(6)
        acct_label = QLabel("アカウント:")
        acct_row.addWidget(acct_label)
        self._account_combo = AccountComboBox()
        acct_row.addWidget(self._account_combo, 1)
        layout.addLayout(acct_row)

        type_label = QLabel("情報源:")
        layout.addWidget(type_label)
        self._type_buttons: dict[str, QPushButton] = {}
        type_grid = QGridLayout()
        type_grid.setSpacing(4)
        for i, (stype, label) in enumerate(self._SOURCE_TYPE_DEFS):
            btn = QPushButton(label)
            btn.setObjectName("column_add_type_btn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, t=stype: self._set_source_type(t))
            type_grid.addWidget(btn, i // 4, i % 4)
            self._type_buttons[stype] = btn

        try:
            from src.ui.theme import SURFACE, BORDER, TEXT, TEXT_MUTED, ACCENT, SURFACE_RAISED
            type_style = (
                "QPushButton#column_add_type_btn {"
                f" background-color: {SURFACE}; color: {TEXT_MUTED};"
                f" border: 1px solid {BORDER}; border-radius: 6px;"
                " padding: 4px 6px; font-size: 11px;"
                " min-height: 22px; max-height: 22px;"
                " outline: none; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:hover {"
                f" background-color: {SURFACE_RAISED}; color: {TEXT};"
                f" border: 1px solid {BORDER}; border-radius: 6px;"
                " padding: 4px 6px; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:checked {"
                f" color: {TEXT}; background-color: rgba(29,155,240,0.22);"
                f" border: 1px solid {ACCENT}; border-radius: 6px; font-weight: 600;"
                " padding: 4px 6px; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:checked:hover {"
                f" color: {TEXT}; background-color: rgba(29,155,240,0.30);"
                f" border: 1px solid {ACCENT}; border-radius: 6px; font-weight: 600;"
                " padding: 4px 6px; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:pressed {"
                f" background-color: {BORDER}; border-radius: 6px;"
                f" border: 1px solid {BORDER}; padding: 4px 6px; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:checked:pressed {"
                f" background-color: rgba(29,155,240,0.34); border-radius: 6px;"
                f" border: 1px solid {ACCENT}; font-weight: 600;"
                " padding: 4px 6px; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:focus {"
                f" outline: none; border: 1px solid {BORDER}; border-radius: 6px;"
                " padding: 4px 6px; margin: 0px;"
                "}"
                "QPushButton#column_add_type_btn:checked:focus {"
                f" outline: none; border: 1px solid {ACCENT}; border-radius: 6px;"
                " padding: 4px 6px; margin: 0px;"
                "}"
            )
            for btn in self._type_buttons.values():
                btn.setStyleSheet(type_style)
                btn.setFlat(True)
                btn.setAutoDefault(False)
                btn.setDefault(False)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                btn.setAutoFillBackground(False)
        except Exception:
            pass
        layout.addLayout(type_grid)

        self._input_row = QHBoxLayout()
        self._input_row.setSpacing(6)
        self._input_label = QLabel("")
        self._input_row.addWidget(self._input_label)
        self._dynamic_input = QLineEdit()
        self._dynamic_input.setObjectName("url_overlay_input")
        self._dynamic_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._dynamic_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        install_dark_lineedit_menu(self._dynamic_input)
        self._dynamic_input.setMinimumHeight(24)
        self._input_row.addWidget(self._dynamic_input, 1)
        self._input_row_widget = QWidget()
        self._input_row_widget.setLayout(self._input_row)
        self._filter_panel = self._build_inline_filter_panel()
        self._search_body = QWidget()
        self._search_body.setObjectName("column_add_search_body")
        _body_lay = QVBoxLayout(self._search_body)
        _body_lay.setContentsMargins(0, 0, 0, 0)
        _body_lay.setSpacing(4)
        _body_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        _body_lay.addWidget(self._input_row_widget)
        _body_lay.addWidget(self._filter_panel)
        self._input_row_widget.show()
        self._filter_panel.show()
        self._search_body.setMinimumHeight(0)
        self._search_body.setMaximumHeight(0)
        self._search_body.setFixedHeight(0)
        layout.addWidget(self._search_body)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("キャンセル")
        self._cancel_btn.setObjectName("text_prompt_cancel")
        self._cancel_btn.clicked.connect(self.close_overlay)
        btn_row.addWidget(self._cancel_btn)
        self._ok_btn = QPushButton("追加")
        self._ok_btn.setObjectName("text_prompt_ok")
        self._ok_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self._ok_btn)
        layout.addLayout(btn_row)

        self._source_type = "home"
        self._accounts: dict[str, dict] = {}
        self._dynamic_input.textChanged.connect(self._on_input_changed)
        self.hide()

    def open_for(self, accounts: dict[str, dict]) -> None:
        self._accounts = {}
        self._account_combo.clear()

        for aid, info in accounts.items():
            name = info.get("display_name")
            if not name:
                continue
            self._accounts[aid] = info
            self._account_combo.addItem(name, aid)

        self._source_type = "home"
        self._refresh_presets()
        for stype, btn in self._type_buttons.items():
            btn.setChecked(stype == "home")
        try:
            self._search_body.setFixedHeight(0)
            self._search_body.setMaximumHeight(0)
            self._search_body.clearMask()
        except Exception:
            pass
        try:
            self.ensurePolished()
            if self.layout() is not None:
                self.layout().activate()
        except Exception:
            pass

        parent = self.parentWidget()
        if parent is not None:
            width = min(self.OVERLAY_WIDTH, max(parent.width() - 40, 280))
            x = (parent.width() - width) // 2
            y = 44
            try:
                ch = max(22, int(self._account_combo.sizeHint().height() or 24))
                self._account_combo.setFixedHeight(ch)
            except Exception:
                pass
            try:
                self.ensurePolished()
                if self.layout() is not None:
                    self.layout().activate()
            except Exception:
                pass
            h = max(int(self.sizeHint().height() or 0), 100)
            self._home_base_height = h
            self._search_full_h = h + int(self._search_body_target_h())
            self.setFixedSize(width, h)
            self.setGeometry(x, y, width, h)
            self._locked_local_xy = (int(x), int(y))
            self._locked_xy = (int(x), int(y))
        _apply_smooth_overlay_shape(self)

        _promote_overlay_tool(self, parent)
        self._locked_xy = (int(self.x()), int(self.y()))
        _apply_smooth_overlay_shape(self)
        try:
            from src.ui.theme import popover_show
            popover_show(self)
        except Exception:
            self.show()
            self.raise_()
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass
        try:
            self.activateWindow()
        except Exception:
            pass
        self._account_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._account_combo.setFocus(Qt.FocusReason.OtherFocusReason)
        try:
            self._dynamic_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._dynamic_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        except Exception:
            pass
        from PySide6.QtCore import QTimer as _QTimer
        def _install_outside_filter(w=self):
            try:
                QApplication.instance().installEventFilter(w)
            except Exception:
                pass
        _QTimer.singleShot(0, _install_outside_filter)
        try:
            from PySide6.QtCore import QTimer
            def _chk(ms, w=self):
                try:
                    if w.isVisible() and float(w.windowOpacity()) < 0.5:
                        w.setWindowOpacity(1.0)
                        w.raise_()
                except Exception:
                    pass
            QTimer.singleShot(50, lambda: _chk(50))
            QTimer.singleShot(150, lambda: _chk(150))
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

        _apply_smooth_overlay_shape(self)

    def leaveEvent(self, event) -> None:

        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QEvent
            for btn in getattr(self, "_type_buttons", {}).values():
                try:
                    btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    st = btn.style()
                    if st is not None:
                        st.unpolish(btn)
                        st.polish(btn)
                    QApplication.sendEvent(btn, QEvent(QEvent.Type.Leave))
                    btn.update()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            super().leaveEvent(event)
        except Exception:
            pass

    def close_overlay(self, checked=False, *, immediate: bool = False) -> None:
        # 検索展開/収納アニメが残っていると、閉じた後も tick が geometry や
        # ネイティブ化を触り、再親子化済みのウィジェットが左上に点滅する
        card_anim = getattr(self, "_card_anim", None)
        if card_anim is not None:
            try:
                card_anim.blockSignals(True)
                card_anim.stop()
            except Exception:
                pass
            self._card_anim = None
        combo = getattr(self, "_account_combo", None)
        if combo is not None:
            try:
                combo._remove_popup_outside_filter()
            except Exception:
                pass
            pop = getattr(combo, "_list_popup", None)
            if pop is not None:
                for attr in (
                    "_mayotter_hide_anim",
                    "_mayotter_show_anim",
                    "_mayotter_show_group",
                    "_mayotter_hide_group",
                ):
                    anim = getattr(pop, attr, None)
                    if anim is not None:
                        try:
                            anim.stop()
                        except Exception:
                            pass
                try:
                    pop._mayotter_fading_out = False
                    pop._mayotter_allow_hide = True
                    QFrame.setVisible(pop, False)
                    pop.setWindowOpacity(1.0)
                    pop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                except Exception:
                    pass
                finally:
                    try:
                        pop._mayotter_allow_hide = False
                    except Exception:
                        pass
            try:
                import time as _t
                combo._popup_closed_at = _t.monotonic()
            except Exception:
                pass

        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        try:
            self._locked_xy = (self.x(), self.y())
            self.setFixedSize(self.width(), self.height())
        except Exception:
            pass

        finished = False

        def _after():
            nonlocal finished
            if finished:
                return
            finished = True
            try:
                self.hide()
                self.setWindowOpacity(1.0)
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self._mayotter_fading_out = False
            except Exception:
                pass
            try:
                _demote_overlay_child(self)
            except Exception:
                pass
            try:
                self.closed.emit()
            except Exception:
                pass

        if immediate:
            for attr in (
                "_mayotter_hide_anim",
                "_mayotter_show_anim",
                "_mayotter_show_group",
                "_mayotter_hide_group",
            ):
                anim = getattr(self, attr, None)
                if anim is not None:
                    try:
                        anim.stop()
                    except Exception:
                        pass
            _after()
            return

        try:
            from src.ui.theme import menu_dropdown_hide
            menu_dropdown_hide(self, on_finished=_after)
        except Exception:
            _after()

    def is_open(self) -> bool:
        return self.isVisible()

    def eventFilter(self, obj, event: QEvent) -> bool:
        etype = event.type()
        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close_overlay()
                return True
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                if self._ok_btn.isEnabled():
                    self._confirm()
                    return True
        elif etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                try:
                    pop = getattr(self._account_combo, "_list_popup", None)
                    gp = event.globalPosition().toPoint()
                    if pop is not None and pop.isVisible() and pop.rect().contains(
                        pop.mapFromGlobal(gp)
                    ):
                        return False
                except Exception:
                    pass
                if _overlay_outside_press_should_close(
                    self, event, {"add_column_btn"}
                ):
                    self.close_overlay()
        return False

    def _set_source_type(self, source_type: str) -> None:
        from src.core.models import source_type_needs_input

        prev = getattr(self, "_source_type", "home")
        self._source_type = source_type

        for stype, btn in self._type_buttons.items():
            btn.setChecked(stype == source_type)

        needs_input = source_type_needs_input(source_type)
        was_input = source_type_needs_input(prev)

        if needs_input:
            self._input_label.setText(self._INPUT_LABELS.get(source_type, "入力:"))
            self._dynamic_input.setPlaceholderText(self._INPUT_PLACEHOLDERS.get(source_type, ""))
            if not was_input:
                self._dynamic_input.clear()

            inner_w = max(80, self.width() - 20)
            try:
                self._input_row_widget.setMaximumWidth(inner_w)
                self._dynamic_input.setMaximumWidth(max(60, inner_w - 100))
            except Exception:
                pass
            if not was_input:
                self._card_resize_open_search()
            elif not self._card_anim_running():
                # 展開アニメ中の再クリックで即フルサイズにすると、アニメの更新と交互に
                # 高さが振れて点滅する。アニメ中は何もしない。
                try:
                    bh = int(self._search_body_target_h())
                    self._ensure_search_body_content_full()
                    self._search_body.setFixedHeight(bh)
                    self._search_body.setMinimumHeight(bh)
                    self._search_body.setMaximumHeight(bh)
                    self._search_body.clearMask()
                except Exception:
                    pass
                self._dynamic_input.setFocus(Qt.FocusReason.OtherFocusReason)
                self._apply_search_geometry(force_full=True, include_filter=True)
        else:

            if was_input:
                self._card_resize_close_search()
            elif not self._card_anim_running():
                # 収納アニメ中に別ボタンを押したときは、アニメに任せる（即時に畳むと点滅する）
                try:
                    self._search_body.setFixedHeight(0)
                    self._search_body.setMaximumHeight(0)
                    self._search_body.clearMask()
                except Exception:
                    pass
                self._adjust_height()

        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QEvent
            for btn in self._type_buttons.values():
                try:
                    btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    QApplication.sendEvent(btn, QEvent(QEvent.Type.Leave))
                    btn.update()
                except Exception:
                    pass
        except Exception:
            pass

    def _card_anim_running(self) -> bool:
        anim = getattr(self, "_card_anim", None)
        return anim is not None and anim.state() == anim.State.Running

    def _ensure_search_body_content_full(self) -> None:
        try:
            ei = int(self._SEARCH_INPUT_ROW_H)
            ef = int(self._SEARCH_FILTER_H)
            self._input_row_widget.setFixedHeight(ei)
            self._input_row_widget.setMinimumHeight(ei)
            self._input_row_widget.setMaximumHeight(ei)
            self._dynamic_input.setMinimumHeight(24)
            self._dynamic_input.setMaximumHeight(16777215)
            self._input_label.setMinimumHeight(0)
            self._input_label.setMaximumHeight(16777215)
            self._filter_panel.setFixedHeight(ef)
            self._filter_panel.setMinimumHeight(ef)
            self._filter_panel.setMaximumHeight(ef)
            self._input_row_widget.show()
            self._input_label.show()
            self._dynamic_input.show()
            self._filter_panel.show()
        except Exception:
            pass

    def _apply_search_card_progress(self, t: float, *, end_input: float = 0.0, end_filter: float = 0.0) -> None:
        t = max(0.0, min(1.0, float(t)))
        full_body = int(self._search_body_target_h())
        bh = max(0, int(round(full_body * t)))
        try:
            self._search_body.setMinimumHeight(0)
            self._search_body.setMaximumHeight(bh)
            self._search_body.setFixedHeight(bh)
            self._search_body.clearMask()
        except Exception:
            pass
        self._apply_search_geometry(progress=t, include_filter=True)

    def _card_resize_open_search(self) -> None:
        from PySide6.QtCore import QVariantAnimation, QEasingCurve

        anim = getattr(self, "_card_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass

        self._input_label.setText(self._INPUT_LABELS.get("search", "キーワード:"))
        self._dynamic_input.setPlaceholderText(
            self._INPUT_PLACEHOLDERS.get("search", "検索キーワード")
        )
        try:
            self._dynamic_input.clearFocus()
        except Exception:
            pass

        full_body = float(self._search_body_target_h())
        base = float(getattr(self, "_home_base_height", 0) or 0)
        full_card = float(getattr(self, "_search_full_h", 0) or (base + full_body))
        try:
            cur_h = float(self.height() or 0)
        except Exception:
            cur_h = base
        if full_card > base and cur_h > base + 1:
            start_t = max(0.0, min(1.0, (cur_h - base) / (full_card - base)))
        else:
            start_t = 0.0

        self._ensure_search_body_content_full()
        self._apply_search_card_progress(start_t)

        anim = QVariantAnimation(self)
        anim.setDuration(240)
        anim.setStartValue(start_t)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_val(v):
            try:
                self._apply_search_card_progress(float(v))
            except Exception:
                pass

        def _on_done():
            try:
                bh = int(self._search_body_target_h())
                self._ensure_search_body_content_full()
                self._search_body.setFixedHeight(bh)
                self._search_body.setMinimumHeight(bh)
                self._search_body.setMaximumHeight(bh)
                self._search_body.clearMask()
            except Exception:
                pass
            self._apply_search_geometry(force_full=True, include_filter=True)
            try:
                self._dynamic_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                self._dynamic_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
                self._dynamic_input.setFocus(Qt.FocusReason.OtherFocusReason)
            except Exception:
                pass
            self._card_anim = None

        anim.valueChanged.connect(_on_val)
        anim.finished.connect(_on_done)
        self._card_anim = anim
        anim.start()

    def _card_resize_close_search(self) -> None:
        from PySide6.QtCore import QVariantAnimation, QEasingCurve

        anim = getattr(self, "_card_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass

        full_body = float(self._search_body_target_h())
        base = float(getattr(self, "_home_base_height", 0) or 0)
        full_card = float(getattr(self, "_search_full_h", 0) or (base + full_body))
        try:
            cur_h = float(self.height() or 0)
        except Exception:
            cur_h = base
        if full_card > base and cur_h > base + 1:
            start_t = max(0.0, min(1.0, (cur_h - base) / (full_card - base)))
        else:
            start_t = 0.0
        if start_t <= 0.0:
            try:
                self._search_body.setFixedHeight(0)
                self._search_body.setMaximumHeight(0)
                self._search_body.clearMask()
            except Exception:
                pass
            self._adjust_height()
            self._card_anim = None
            return

        try:
            self._dynamic_input.clearFocus()
        except Exception:
            pass

        self._ensure_search_body_content_full()
        self._apply_search_card_progress(start_t)

        anim = QVariantAnimation(self)
        anim.setDuration(240)
        anim.setStartValue(start_t)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def _on_val(v):
            try:
                self._apply_search_card_progress(float(v))
            except Exception:
                pass

        def _on_done():
            try:
                self._search_body.setFixedHeight(0)
                self._search_body.setMinimumHeight(0)
                self._search_body.setMaximumHeight(0)
                self._search_body.clearMask()
            except Exception:
                pass
            self._adjust_height()
            self._card_anim = None

        anim.valueChanged.connect(_on_val)
        anim.finished.connect(_on_done)
        self._card_anim = anim
        anim.start()

    def _apply_search_geometry(
        self,
        *,
        force_full: bool = False,
        progress: float | None = None,
        include_filter: bool | None = None,
    ) -> None:
        base = int(getattr(self, "_home_base_height", 0) or 0)
        if base < 80:
            base = max(100, int(self.height() or 0))
            self._home_base_height = base
        body = int(self._search_body_target_h())
        full = int(getattr(self, "_search_full_h", 0) or 0)
        if full < base + body:
            full = base + body
            self._search_full_h = full

        if force_full:
            h = full
        elif progress is not None:
            tval = max(0.0, min(1.0, float(progress)))
            h = full if tval >= 0.999 else int(base + (full - base) * tval)
        else:
            h = full

        try:
            parent = self.parentWidget()
            if parent is not None and not force_full:
                local_y = int(getattr(self, "_locked_local_xy", (0, 44))[1])
                max_h = max(100, int(parent.height()) - local_y - 12)
                h = min(h, max_h)
        except Exception:
            pass

        geo = self.geometry()
        w = int(geo.width())
        if getattr(self, "_locked_xy", None):
            x, y = self._locked_xy
        else:
            x, y = int(geo.x()), int(geo.y())
            self._locked_xy = (x, y)
        self.setFixedSize(w, h)
        if int(self.x()) != int(x) or int(self.y()) != int(y):
            self.move(int(x), int(y))
        try:
            _apply_smooth_overlay_shape(self)
        except Exception:
            pass

    def _adjust_height(self) -> None:

        try:
            combo = getattr(self, "_account_combo", None)
            pop = getattr(combo, "_list_popup", None) if combo is not None else None
            if pop is not None and pop.isVisible():
                pop._mayotter_allow_hide = True
                try:
                    from PySide6.QtWidgets import QFrame
                    QFrame.setVisible(pop, False)
                finally:
                    pop._mayotter_allow_hide = False
        except Exception:
            pass
        try:
            from src.core.models import source_type_needs_input
            is_search = source_type_needs_input(getattr(self, "_source_type", "home"))
        except Exception:
            is_search = False

        if not is_search:
            try:
                self.ensurePolished()
                if self.layout() is not None:
                    self.layout().activate()
            except Exception:
                pass
        geo = self.geometry()
        x, y, w = int(geo.x()), int(geo.y()), int(geo.width())
        try:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        except Exception:
            pass

        if is_search:
            try:
                cur_b = int(self._search_body.height() or 0)
            except Exception:
                cur_b = 0
            body_t = int(self._search_body_target_h())
            prog = min(1.0, cur_b / float(body_t)) if body_t > 0 else 1.0
            self._apply_search_geometry(progress=prog)
            return
        else:
            base = int(getattr(self, "_home_base_height", 0) or 0)
            if base >= 80:
                h = base
            else:
                h = max(int(self.sizeHint().height() or 0), 100)

        if getattr(self, "_locked_xy", None):
            x, y = self._locked_xy
        self.setFixedSize(w, h)
        self.setGeometry(x, y, w, h)
        self._locked_xy = (x, y)
        try:
            _apply_smooth_overlay_shape(self)
        except Exception:
            pass
        try:
            for btn in self._type_buttons.values():
                btn.update()
        except Exception:
            pass

    def _on_input_changed(self, text: str) -> None:
        return

    _SEARCH_OP_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
        (
            "投稿者",
            [
                ("from:", "from: @ユーザー名", "指定したユーザーの投稿"),
                ("to:", "to: @ユーザー名", "指定したユーザーへの投稿"),
                ("@", "@ユーザー名", "ユーザーへのメンション"),
                ("list:", "list: リストID", "指定したリストの投稿"),
            ],
        ),
        (
            "期間",
            [
                ("since:", "since: YYYY/MM/DD", "指定した日付以降"),
                ("until:", "until: YYYY/MM/DD", "指定した日付以前"),
            ],
        ),
        (
            "メディア",
            [
                ("filter:media", "filter:media", "画像・動画あり"),
                ("filter:images", "filter:images", "画像付きの投稿"),
                ("filter:videos", "filter:videos", "動画を含む投稿"),
                ("filter:links", "filter:links", "リンクあり"),
            ],
        ),
        (
            "投稿属性",
            [
                ("filter:replies", "filter:replies", "返信のみ"),
                ("-filter:replies", "-filter:replies", "返信を除外"),
                ("filter:native_video", "filter:native_video", "X内の動画"),
                ("filter:verified", "filter:verified", "認証アカウント"),
                ("filter:news", "filter:news", "ニュースリンク"),
            ],
        ),
        (
            "反応数",
            [
                ("min_faves:", "min_faves: n", "指定した数以上のいいね"),
                ("min_retweets:", "min_retweets: n", "指定した数以上のリポスト"),
                ("min_replies:", "min_replies: n", "指定した数以上の返信"),
            ],
        ),
    ]

    def _build_inline_filter_panel(self) -> QWidget:
        from src.ui.theme import SURFACE_RAISED, BORDER, TEXT, TEXT_MUTED, ACCENT
        from PySide6.QtWidgets import QSizePolicy

        panel = QWidget()
        panel.setObjectName("column_add_filter_panel")
        lay = QVBoxLayout(panel)

        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        chip_ss = (
            "QPushButton {"
            f" background:{SURFACE_RAISED}; color:{TEXT}; border:1px solid {BORDER};"
            " border-radius:4px; padding:1px 5px; font-size:10px;"
            " min-height:20px; max-height:20px;"
            "}"
            "QPushButton:hover {"
            f" border:1px solid {ACCENT}; background:rgba(29,155,240,0.18);"
            "}"
            "QPushButton:pressed {"
            f" background:{BORDER};"
            "}"
        )
        for title, ops in self._SEARCH_OP_GROUPS:
            lab = QLabel(title)
            lab.setStyleSheet(f"color:{TEXT_MUTED}; font-size:9px; padding:0;")
            lab.setFixedHeight(12)
            lay.addWidget(lab)
            row = QHBoxLayout()
            row.setSpacing(3)
            row.setContentsMargins(0, 0, 0, 0)
            for token, label, tip in ops:
                b = QPushButton(label)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(tip)
                b.setStyleSheet(chip_ss)
                b.setFlat(True)
                b.setFixedHeight(20)
                b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                b.clicked.connect(lambda _=False, t=token: self._insert_search_operator(t))
                # 行の余白は各チップの文字幅に比例して配り、右端をそろえる
                row.addWidget(b, max(1, b.sizeHint().width()))
            lay.addLayout(row)

        # 保存した検索条件の行（選択・保存・削除）
        preset_row = QHBoxLayout()
        preset_row.setSpacing(3)
        preset_row.setContentsMargins(0, 0, 0, 0)
        self._preset_combo = AccountComboBox(panel)
        self._preset_combo.setFixedHeight(30)
        self._preset_combo.activated.connect(self._on_preset_selected)
        preset_row.addWidget(self._preset_combo, 1)
        for text, tip, slot in (
            ("保存", "今の検索条件を保存", self._save_current_search),
            ("削除", "選んだ保存済み検索を削除", self._delete_selected_search),
        ):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(chip_ss)
            b.setFlat(True)
            b.setFixedHeight(20)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, f=slot: f())
            preset_row.addWidget(b)
        lay.addLayout(preset_row)

        fh = lay.sizeHint().height()
        self._SEARCH_FILTER_H = fh
        panel.setFixedHeight(fh)
        panel.setMinimumHeight(fh)
        panel.setMaximumHeight(fh)
        return panel

    _SEARCH_INPUT_ROW_H = 36
    _SEARCH_FILTER_H = 202
    _SEARCH_BODY_GAP = 4

    def _search_body_target_h(self) -> int:
        return int(self._SEARCH_INPUT_ROW_H) + int(self._SEARCH_FILTER_H) + int(self._SEARCH_BODY_GAP)

    def set_saved_searches_store(self, getter, setter) -> None:
        """保存した検索条件の読み書き先（設定）を受け取る。"""
        self._saved_searches_get = getter
        self._saved_searches_set = setter
        self._refresh_presets()

    def _saved_searches(self) -> list[dict]:
        getter = getattr(self, "_saved_searches_get", None)
        try:
            return list(getter() or []) if callable(getter) else []
        except Exception:
            return []

    def _refresh_presets(self, select_name: str = "") -> None:
        combo = getattr(self, "_preset_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("保存した検索…", "")
        for item in self._saved_searches():
            combo.addItem(item["name"], item["query"])
        if select_name:
            idx = combo.findText(select_name)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        query = self._preset_combo.itemData(index)
        if query:
            self._dynamic_input.setText(str(query))
            self._dynamic_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _save_current_search(self) -> None:
        query = self._dynamic_input.text().strip()
        setter = getattr(self, "_saved_searches_set", None)
        if not query or not callable(setter):
            return
        items = self._saved_searches()
        if any(i["query"] == query for i in items):
            self._refresh_presets(next(i["name"] for i in items if i["query"] == query))
            return
        name = query if len(query) <= 24 else query[:24] + "…"
        base, n = name, 2
        while any(i["name"] == name for i in items):
            name = f"{base} ({n})"
            n += 1
        items.append({"name": name, "query": query})
        try:
            setter(items)
        except Exception:
            return
        self._refresh_presets(name)

    def _delete_selected_search(self) -> None:
        idx = self._preset_combo.currentIndex()
        setter = getattr(self, "_saved_searches_set", None)
        if idx <= 0 or not callable(setter):
            return
        name = self._preset_combo.currentText()
        items = [i for i in self._saved_searches() if i["name"] != name]
        try:
            setter(items)
        except Exception:
            return
        self._refresh_presets()

    def _insert_search_operator(self, token: str) -> None:
        edit = self._dynamic_input
        try:
            text = edit.text()
            pos = edit.cursorPosition()
            prefix = ""
            if pos > 0 and not text[pos - 1].isspace():
                prefix = " "
            insert = prefix + token
            new_text = text[:pos] + insert + text[pos:]
            edit.setText(new_text)
            edit.setCursorPosition(pos + len(insert))
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def _confirm(self) -> None:
        from src.core.models import Column, default_column_title, resolve_source_url, source_type_needs_input

        idx = self._account_combo.currentIndex()
        if idx < 0:
            return
        account_id = self._account_combo.currentData()
        info = self._accounts.get(account_id, {})
        initial_url = info.get("initial_url", "https://x.com/")

        from src.core.models import migrate_column_type
        stype = migrate_column_type(self._source_type)

        source_url = ""
        if source_type_needs_input(stype) or stype == "url":
            source_url = self._dynamic_input.text().strip()
            if not source_url:
                return

        url = resolve_source_url(stype, initial_url, source_url)
        if stype == "profile" and not url:
            url = ""
        title = default_column_title(stype, info.get("display_name", ""), source_url or url)

        column = Column(
            column_type=stype,
            source_account_id=account_id,
            source_url=url,
            title=title,
        )
        self.close_overlay()
        self.column_added.emit(column)

class ConfirmOverlay(QWidget):

    OVERLAY_WIDTH = 360

    accepted = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("confirm_overlay")
        try:
            from src.ui.theme import apply_overlay_theme
            apply_overlay_theme(self)
        except Exception:
            pass

        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._message_label = QLabel()
        self._message_label.setObjectName("confirm_message")
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        self._dont_show_checkbox = QCheckBox("今後この確認を表示しない")
        self._dont_show_checkbox.setObjectName("confirm_dont_show")
        layout.addWidget(self._dont_show_checkbox)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        self._cancel_btn = QPushButton("キャンセル")
        self._cancel_btn.setObjectName("confirm_cancel")
        self._cancel_btn.clicked.connect(self._reject)
        row.addWidget(self._cancel_btn)
        self._ok_btn = QPushButton("削除")
        self._ok_btn.setObjectName("confirm_delete")
        self._ok_btn.clicked.connect(self._accept)
        row.addWidget(self._ok_btn)
        layout.addLayout(row)

        self.hide()

    def open_confirm(self, message: str, dont_show_key: str | None = None) -> None:
        self._message_label.setText(message)
        self._dont_show_checkbox.setChecked(False)
        parent = self.parentWidget()
        if parent is not None:
            width = min(self.OVERLAY_WIDTH, max(parent.width() - 40, 280))
            x = (parent.width() - width) // 2
            y = 44
            self.setGeometry(x, y, width, self.sizeHint().height())
        _apply_smooth_overlay_shape(self)
        try:
            from src.ui.theme import popover_show
            popover_show(self)
        except Exception:
            self.show()
            self.raise_()
        self._cancel_btn.setFocus()
        QApplication.instance().installEventFilter(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _apply_smooth_overlay_shape(self)

    def close_overlay(self) -> None:
        _overlay_close(self)

    def is_open(self) -> bool:
        return self.isVisible()

    def eventFilter(self, obj, event: QEvent) -> bool:
        etype = event.type()
        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close_overlay()
                return True
        elif etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):
                self.close_overlay()
        return False

    def _accept(self) -> None:
        self.close_overlay()
        self.accepted.emit(True)

    def _reject(self) -> None:
        self.close_overlay()
        self.accepted.emit(False)

class DownloadItem:

    def __init__(
        self,
        file_path: str,
        file_name: str,
        mime_type: str = "",
        status: str = "completed",
        progress: float = 1.0,
    ) -> None:
        self.file_path = file_path
        self.file_name = file_name
        self.mime_type = mime_type
        self.status = status
        self.progress = progress
        self.timestamp = time.time()
        self.download_id: str = ""
        self.bytes_received: int = 0
        self.size_unknown: bool = False
        # progress < -1 → 不定形 (sentinel = -(1 + bytes_received))
        if isinstance(progress, (int, float)) and progress < -1.0:
            self.size_unknown = True
            self.bytes_received = max(0, int(-(progress) - 1.0))
            self.progress = -1.0

    def display_name(self) -> str:
        return self.file_name

    def status_label(self) -> str:
        s = (self.status or "").lower()
        if s in ("started", "progress"):
            if self.size_unknown or (isinstance(self.progress, (int, float)) and self.progress < 0):
                br = int(getattr(self, "bytes_received", 0) or 0)
                if br >= 1024 * 1024:
                    return f"ダウンロード中… {br / (1024 * 1024):.1f} MB 受信中"
                if br >= 1024:
                    return f"ダウンロード中… {br / 1024:.0f} KB 受信中"
                if br > 0:
                    return f"ダウンロード中… {br} B 受信中"
                return "ダウンロード中…"
            pct = int(max(0.0, min(1.0, float(self.progress))) * 100)
            return f"ダウンロード中… {pct}%"
        if s == "completed":
            return "完了"
        if s == "cancelled":
            return "キャンセル"
        if s == "failed":
            return "失敗"
        return s or ""


class _DownloadBar(QWidget):
    """ダウンロード行の細い進捗バー。

    受信は粒度が粗いので、表示値を目標値へなめらかに追わせる。
    サイズ不明（目標 < 0）のときは往復する帯で「動いている」ことだけ示す。
    """

    shown = Signal(float)  # 表示中の値（0..1）。パーセント表示の追従用

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(4)
        self._shown = 0.0
        self._target = 0.0
        self._busy = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_target(self, value: float) -> None:
        if value < 0.0:
            self._busy = True
        else:
            self._busy = False
            self._target = max(0.0, min(1.0, float(value)))
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        if self._busy:
            self._phase = (self._phase + 0.012) % 1.0
        else:
            diff = self._target - self._shown
            if abs(diff) < 0.002:
                self._shown = self._target
                self._timer.stop()
            else:
                self._shown += diff * 0.2
            self.shown.emit(self._shown)
        self.update()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._busy or abs(self._target - self._shown) >= 0.002:
            self._timer.start()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        track = QColor(theme_color("BORDER"))
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        fill = QColor(theme_color("ACCENT"))
        p.setBrush(fill)
        if self._busy:
            seg = w * 0.3
            # 0→1→0 の往復
            t = self._phase * 2.0
            t = t if t <= 1.0 else 2.0 - t
            x = (w - seg) * t
            p.drawRoundedRect(QRectF(x, 0, seg, h), h / 2, h / 2)
        elif self._shown > 0.0:
            p.drawRoundedRect(QRectF(0, 0, max(h, w * self._shown), h), h / 2, h / 2)
        p.end()


class DownloadOverlay(QWidget):

    OVERLAY_WIDTH = 360
    MAX_ITEMS = 50
    history_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("download_overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            from src.ui.theme import overlay_stylesheet
            self.setStyleSheet(overlay_stylesheet())
        except Exception:
            pass

        layout = QVBoxLayout(self)

        layout.setContentsMargins(10, 4, 10, 8)
        layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        title = QLabel("ダウンロード履歴")
        title.setObjectName("download_overlay_title")
        title_row.addWidget(title, 1)
        close_btn = QToolButton()
        close_btn.setObjectName("download_overlay_close")
        close_btn.setText("")
        close_btn.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 12))
        close_btn.setIconSize(QSize(12, 12))
        close_btn.setToolTip("閉じる")
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.close_overlay)
        title_row.addWidget(close_btn, 0)

        layout.addLayout(title_row)

        self._list = QListWidget()
        self._list.setObjectName("download_overlay_list")
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setFrameShape(QFrame.Shape.NoFrame)

        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setSpacing(4)
        self._list.setUniformItemSizes(True)
        try:
            self._list.setProperty("showDecorationSelected", False)
        except Exception:
            pass
        self._list.setStyleSheet(
            self._list.styleSheet()
            + f"""
            QListWidget#download_overlay_list {{
              background: transparent;
              border: none;
              outline: none;
            }}
            QListWidget#download_overlay_list::item {{
              background: transparent;
              border: none;
              margin: 0px;
              padding: 0px;
            }}
            """
        )
        self._list.viewport().setAutoFillBackground(False)
        self._list.setSpacing(0)
        layout.addWidget(self._list)

        self.hide()

    def add_download(self, item: DownloadItem) -> None:
        did = getattr(item, "download_id", "") or ""
        if did:
            for i in range(self._list.count()):
                list_item = self._list.item(i)
                data = list_item.data(Qt.ItemDataRole.UserRole)
                if data is not None and getattr(data, "download_id", "") == did:
                    data.file_path = item.file_path or data.file_path
                    data.file_name = item.file_name or data.file_name
                    data.status = item.status
                    data.progress = item.progress
                    data.size_unknown = item.size_unknown
                    data.bytes_received = item.bytes_received
                    row = self._list.itemWidget(list_item)
                    if row is not None:
                        self._sync_row_progress(row, data)
                    return

        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, item)

        item_widget = self._create_item_widget(item)
        from PySide6.QtCore import QSize as _QS
        fixed_h = 64
        try:
            item_widget.setFixedHeight(fixed_h)
        except Exception:
            pass

        list_item.setSizeHint(_QS(max(item_widget.sizeHint().width(), 200), fixed_h))

        list_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._list.insertItem(0, list_item)
        self._list.setItemWidget(list_item, item_widget)

        while self._list.count() > self.MAX_ITEMS:
            self._list.takeItem(self._list.count() - 1)

    def export_history(self) -> list[dict]:
        out = []
        for i in range(self._list.count()):
            list_item = self._list.item(i)
            data = list_item.data(Qt.ItemDataRole.UserRole)
            if data is None:
                continue
            out.append({
                "file_path": getattr(data, "file_path", ""),
                "file_name": getattr(data, "file_name", ""),
                "mime_type": getattr(data, "mime_type", ""),
                "timestamp": getattr(data, "timestamp", 0),
            })
        return out

    def _create_item_widget(self, item: DownloadItem) -> QWidget:
        from src.ui.theme import TEXT, TEXT_MUTED

        widget = QWidget()
        widget.setObjectName("download_item_row")
        layout = QVBoxLayout(widget)

        layout.setContentsMargins(6, 3, 6, 4)
        layout.setSpacing(2)
        widget._download_item = item
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        try:
            from src.ui.theme import RADIUS_MD
            _rr = int(RADIUS_MD)
        except Exception:
            _rr = 8
        widget.setStyleSheet(
            "QWidget#download_item_row {"
            "  background-color: transparent;"
            f"  border: 1px solid transparent;"
            f"  border-radius: {_rr}px;"
            "  margin: 0px; padding: 0px;"
            "}"
            "QWidget#download_item_row:hover {"
            "  background-color: rgba(148, 178, 230, 0.12);"
            f"  border: 1px solid transparent;"
            f"  border-radius: {_rr}px;"
            "  margin: 0px; padding: 0px;"
            "}"
        )

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        name_label = QLabel(item.file_name)
        name_label.setObjectName("download_item_name")
        name_label.setStyleSheet(
            f"color: {TEXT}; font-size: 12px; font-weight: 500; background: transparent;"
        )
        name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        name_label.setCursor(Qt.CursorShape.PointingHandCursor)
        name_label.mousePressEvent = (
            lambda e, it=item: self._open_file(it)
            if e.button() == Qt.MouseButton.LeftButton
            else None
        )
        top.addWidget(name_label, 1)

        close_row_btn = QToolButton()
        close_row_btn.setObjectName("download_item_close")
        close_row_btn.setText("")
        close_row_btn.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 10))
        close_row_btn.setIconSize(QSize(10, 10))
        close_row_btn.setFixedSize(20, 20)
        close_row_btn.setToolTip("履歴から削除")
        close_row_btn.setStyleSheet(
            "QToolButton { background:transparent; border:none; border-radius:4px; }"
            "QToolButton:hover { background:transparent; border:none; }"
        )
        close_row_btn.clicked.connect(lambda: self._remove_from_history(item))
        top.addWidget(close_row_btn, 0)
        layout.addLayout(top)

        status_label = QLabel(item.status_label())
        status_label.setObjectName("download_item_status")
        status_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        widget._status_label = status_label

        bar = _DownloadBar()
        bar.shown.connect(lambda v, w=widget: self._on_bar_shown(w, v))
        layout.addWidget(bar)
        widget._progress_bar = bar

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        def _mk_btn(icon, tip, slot, danger=False):
            b = QToolButton()
            b.setObjectName("download_action_btn_danger" if danger else "download_action_btn")
            b.setIcon(icon)
            b.setIconSize(QSize(12, 12))
            b.setFixedSize(24, 24)
            b.setToolTip(tip)

            b.setStyleSheet(
                "QToolButton { background: transparent; border: 1px solid transparent;"
                " border-radius: 5px; padding: 0px; margin: 0px; }"
                "QToolButton:hover { background: rgba(148,178,230,0.14);"
                " border: 1px solid transparent; border-radius: 5px; }"
                "QToolButton#download_action_btn_danger:hover {"
                " background: rgba(230,100,100,0.16);"
                " border: 1px solid transparent; border-radius: 5px; }"
            )
            b.clicked.connect(slot)
            return b

        action_btns = [
            _mk_btn(
                make_file_open_icon(_COLOR_SECONDARY, 12), "ファイルを開く",
                lambda: self._open_file(item)),
            _mk_btn(
                make_folder_icon(_COLOR_SECONDARY, 12), "フォルダを開く",
                lambda: self._open_folder(item)),
            _mk_btn(
                make_trash_icon(_COLOR_DANGER, 12), "ファイルを削除",
                lambda: self._delete_file_and_history(item), danger=True),
        ]
        for b in action_btns:
            btn_row.addWidget(b)
        widget._action_btns = action_btns
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        status_row.addWidget(status_label, 1)
        status_row.addLayout(btn_row)
        layout.addLayout(status_row)
        widget.setMinimumHeight(56)
        self._sync_row_progress(widget, item, animate=False)
        return widget

    @staticmethod
    def _is_downloading(item) -> bool:
        return (item.status or "").lower() in ("started", "progress")

    def _sync_row_progress(self, row: QWidget, item, *, animate: bool = True) -> None:
        """行の状態（バー・％・操作ボタン）を item に合わせる。"""
        bar = getattr(row, "_progress_bar", None)
        label = getattr(row, "_status_label", None)
        busy = self._is_downloading(item)
        if bar is not None:
            bar.setVisible(busy)
            if busy:
                if item.size_unknown or item.progress < 0:
                    bar.set_target(-1.0)
                else:
                    bar.set_target(item.progress)
                    if not animate:
                        bar._shown = bar._target
        # 受信中のファイルは開く・削除の対象にならないので隠す
        for b in getattr(row, "_action_btns", []):
            b.setVisible(not busy)
        if label is not None:
            if busy and not (item.size_unknown or item.progress < 0) and bar is not None:
                label.setText(f"ダウンロード中… {int(round(bar._shown * 100))}%")
            else:
                label.setText(item.status_label())

    def _on_bar_shown(self, row: QWidget, value: float) -> None:
        """バーの表示値に合わせて ％ を進める（受信イベントの粒度が粗くても数字が動く）。"""
        item = getattr(row, "_download_item", None)
        label = getattr(row, "_status_label", None)
        if item is None or label is None or not self._is_downloading(item):
            return
        if item.size_unknown or item.progress < 0:
            return
        label.setText(f"ダウンロード中… {int(round(value * 100))}%")

    def _on_item_double_clicked(self, list_item) -> None:
        row = self._list.itemWidget(list_item) if list_item is not None else None
        item = getattr(row, "_download_item", None) if row is not None else None
        if item is not None:
            self._open_file(item)

    def _open_file(self, item: DownloadItem) -> None:

        import os
        import sys
        if not os.path.exists(item.file_path):
            return
        try:
            if sys.platform == "win32":
                os.startfile(item.file_path)
            else:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                kw = {}
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    kw["creationflags"] = subprocess.CREATE_NO_WINDOW
                subprocess.Popen([opener, item.file_path], shell=False, **kw)
        except OSError:
            pass
        self.close_overlay()

    def _open_folder(self, item: DownloadItem) -> None:
        import os
        if not os.path.exists(item.file_path):
            return
        import subprocess
        try:
            kw = {}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                ["explorer", "/select,", item.file_path],
                shell=False,
                **kw,
            )
        except OSError:
            pass
        self.close_overlay()

    def _remove_list_entry(self, item: DownloadItem) -> None:
        for i in range(self._list.count()):
            list_item = self._list.item(i)
            data = list_item.data(Qt.ItemDataRole.UserRole)
            if data is item:
                self._list.takeItem(i)
                break

    def _remove_from_history(self, item: DownloadItem) -> None:
        self._remove_list_entry(item)
        try:
            self.history_changed.emit()
        except Exception:
            pass

    def _delete_file_and_history(self, item: DownloadItem) -> None:
        import os
        try:
            if os.path.exists(item.file_path):
                os.remove(item.file_path)
        except OSError:
            pass
        self._remove_list_entry(item)
        try:
            self.history_changed.emit()
        except Exception:
            pass

    def open_history(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            width = min(self.OVERLAY_WIDTH, max(parent.width() - 40, 280))
            x = parent.width() - width - 12
            y = 44
            h = min(400, max(self.sizeHint().height(), 120))
            self.setGeometry(x, y, width, h)
            self.setFixedSize(width, h)
        self._apply_rounded_mask()
        _promote_overlay_tool(self, parent)
        self._apply_rounded_mask()
        try:
            from src.ui.theme import popover_show
            popover_show(self)
        except Exception:
            self.show()
            self.raise_()
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass
        from PySide6.QtCore import QTimer as _QTimer
        def _install_outside_filter(w=self):
            try:
                QApplication.instance().installEventFilter(w)
            except Exception:
                pass
        _QTimer.singleShot(0, _install_outside_filter)
        try:
            from PySide6.QtCore import QTimer
            def _chk(ms, w=self):
                try:
                    if w.isVisible() and float(w.windowOpacity()) < 0.5:
                        w.setWindowOpacity(1.0)
                        w.raise_()
                except Exception:
                    pass
            QTimer.singleShot(50, lambda: _chk(50))
            QTimer.singleShot(150, lambda: _chk(150))
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_rounded_mask()

    def _apply_rounded_mask(self) -> None:
        _apply_smooth_overlay_shape(self)

    def close_overlay(self) -> None:
        def _after():
            try:
                _demote_overlay_child(self)
            except Exception:
                pass
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        try:
            from src.ui.theme import menu_dropdown_hide
            menu_dropdown_hide(self, on_finished=_after)
        except Exception:
            _after()
            try:
                self.hide()
            except Exception:
                pass

    def is_open(self) -> bool:
        return self.isVisible()

    def eventFilter(self, obj, event: QEvent) -> bool:
        etype = event.type()
        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close_overlay()
                return True
        elif etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                if _overlay_outside_press_should_close(
                    self, event, {"download_icon_btn"}
                ):
                    self.close_overlay()
        return False

class DownloadIconButton(QPushButton):
    """ダウンロード履歴ボタン。受信中は進捗リング、完了時は波紋とチェックで知らせる。

    表示は時間ベースで滑らかに動かす（受信イベントの粒度が粗くても、リングは連続して進む）。
    """

    _RING_D = 18.0  # リングの直径（ボタンは 28x24）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("download_icon_btn")
        self.setFixedWidth(28)
        self.setFixedHeight(24)
        self.setToolTip("ダウンロード履歴")

        # アイコンは paintEvent で不透明度を変えながら自前で描く
        self._icon = make_download_icon(_COLOR_ACCENT_SOFT, 14)

        self._progress = 0.0          # 表示中の進捗（0..1）
        self._target_progress = 0.0
        self._active = False          # 受信中
        self._indeterminate = False
        self._spin = 0.0              # 不定形のときの回転角（度）
        self._completed_count = 0
        self._badge_scale = 1.0

        self._done_t = -1.0           # 完了演出の経過秒（負なら演出なし）
        self._ring_a = 0.0            # リングの表示度（フェードイン/アウト）
        self._icon_a = 1.0            # アイコンの不透明度（なめらかに追従）
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ---- 外部 API（既存の呼び出し口を維持） -------------------------------
    def set_progress(self, progress: float) -> None:
        if progress is not None and float(progress) < 0.0:
            self._indeterminate = True
        else:
            self._indeterminate = False
            self._target_progress = max(0.0, min(1.0, float(progress or 0.0)))
        self._active = True
        self._done_t = -1.0
        self._start()

    def increment_completed(self) -> None:
        self._completed_count += 1
        self._badge_scale = 0.6
        self._indeterminate = False
        self._target_progress = 1.0
        self._active = True
        self._done_t = 0.0
        self._start()

    def clear_completed(self) -> None:
        self._completed_count = 0
        self._reset()
        self.update()

    def reset_progress(self) -> None:
        self._reset()
        self.update()

    def refresh_theme(self) -> None:
        self._icon = make_download_icon(_COLOR_ACCENT_SOFT, 14)
        self.update()

    # ---- 内部 -------------------------------------------------------------
    def _reset(self) -> None:
        # リングはフェードアウトしてから消す（値は消えきるまで保持）
        if self._done_t > 1.2:
            self._ring_a = 0.0  # 完了演出の終盤でリングはもう消えている
        self._active = False
        self._indeterminate = False
        self._done_t = -1.0
        self._icon_a = 1.0
        self._start()

    def _start(self) -> None:
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = max(0.0, min(0.1, now - self._last))
        self._last = now
        busy = False

        if self._indeterminate:
            self._spin = (self._spin + 300.0 * dt) % 360.0
            busy = True
        else:
            diff = self._target_progress - self._progress
            if abs(diff) > 0.0005:
                # 指数平滑。受信が飛び飛びでもリングは連続して追いかける
                self._progress += diff * (1.0 - math.exp(-dt * 9.0))
                busy = True
            else:
                self._progress = self._target_progress

        if self._done_t >= 0.0:
            # リングが一周してから完了演出へ進める
            if self._progress >= 0.985:
                self._done_t += dt
            busy = True
            if self._done_t > 1.7:
                self._reset()
                busy = False

        if self._badge_scale < 1.0:
            self._badge_scale = min(1.0, self._badge_scale + dt * 5.0)
            busy = True

        fade = 5.0 * dt
        want_ring = 1.0 if self._active else 0.0
        if self._ring_a < want_ring:
            self._ring_a = min(want_ring, self._ring_a + fade)
            busy = True
        elif self._ring_a > want_ring:
            self._ring_a = max(want_ring, self._ring_a - fade)
            busy = True
            if self._ring_a <= 0.0:
                self._progress = self._target_progress = 0.0
        want_icon = 0.55 if self._active else 1.0
        if self._done_t < 0.0 and abs(self._icon_a - want_icon) > 0.005:
            self._icon_a += (want_icon - self._icon_a) * (1.0 - math.exp(-dt * 10.0))
            busy = True

        if not busy and not self._active:
            self._timer.stop()
        elif not busy and self._active and self._done_t < 0.0 and abs(self._target_progress - self._progress) <= 0.0005:
            # 受信中でイベント待ちのときは止める（次の set_progress で再開）
            self._timer.stop()
        self.update()

    @staticmethod
    def _ease_out(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # 背景・ホバー（QSS）
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        d = self._RING_D
        ring = QRectF(cx - d / 2.0, cy - d / 2.0, d, d)

        accent = QColor(theme_color("ACCENT"))
        success = QColor(theme_color("SUCCESS"))
        track = QColor(theme_color("BORDER"))
        done = self._done_t
        # 完了演出の区間: 0〜0.25 色が成功色へ + 波紋 / 0.15〜0.55 チェック / 1.2〜1.7 アイコンへ戻す
        k_color = self._ease_out(done / 0.25) if done >= 0.0 else 0.0
        k_check = self._ease_out((done - 0.15) / 0.4) if done >= 0.0 else 0.0
        k_back = self._ease_out((done - 1.2) / 0.5) if done >= 0.0 else 0.0
        check_vis = k_check * (1.0 - k_back)

        # アイコン（受信中はやや沈ませ、チェックが出る間は消す）
        icon_alpha = self._icon_a
        if done >= 0.0:
            icon_alpha = max(0.0, min(1.0, 0.55 * (1.0 - k_check) * (1.0 - k_back) + k_back))
        p.save()
        p.setOpacity(icon_alpha)
        pm = self._icon.pixmap(QSize(14, 14))
        p.drawPixmap(int(cx - 7), int(cy - 7), pm)
        p.restore()

        if self._ring_a > 0.003:
            ring_alpha = self._ring_a * (1.0 - k_back)
            tc = QColor(track)
            tc.setAlpha(int(150 * ring_alpha))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tc, 2.0))
            p.drawEllipse(ring)

            col = QColor(accent)
            if done >= 0.0:
                col = QColor(
                    int(accent.red() + (success.red() - accent.red()) * k_color),
                    int(accent.green() + (success.green() - accent.green()) * k_color),
                    int(accent.blue() + (success.blue() - accent.blue()) * k_color),
                )
            col.setAlpha(int(255 * ring_alpha))
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            if self._indeterminate:
                p.drawArc(ring, int((90.0 - self._spin) * 16), int(-100 * 16))
            elif self._progress > 0.004:
                p.drawArc(ring, 90 * 16, int(-min(1.0, self._progress) * 360 * 16))

        if done >= 0.0 and done < 0.7:
            # 波紋: 完了の瞬間にリングの外へ広がって消える
            t = done / 0.7
            e = self._ease_out(t)
            rc = QColor(success)
            rc.setAlpha(int(140 * (1.0 - t)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(rc, 1.6))
            r = d / 2.0 + 0.5 + 2.5 * e  # ボタン高(24)に収まる範囲まで
            p.drawEllipse(QPointF(cx, cy), r, r)

        if check_vis > 0.01:
            cc = QColor(success)
            cc.setAlpha(int(255 * check_vis))
            p.setPen(QPen(cc, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p1, p2, p3 = QPointF(cx - 4.2, cy + 0.2), QPointF(cx - 1.2, cy + 3.4), QPointF(cx + 4.6, cy - 3.2)
            if k_check < 0.45:
                s = k_check / 0.45
                p.drawLine(p1, QPointF(p1.x() + (p2.x() - p1.x()) * s, p1.y() + (p2.y() - p1.y()) * s))
            else:
                s = (k_check - 0.45) / 0.55
                p.drawLine(p1, p2)
                p.drawLine(p2, QPointF(p2.x() + (p3.x() - p2.x()) * s, p2.y() + (p3.y() - p2.y()) * s))

        if self._completed_count > 0:
            badge_text = str(self._completed_count if self._completed_count < 10 else "9+")
            font = QFont()
            font.setPixelSize(9)
            font.setBold(True)
            p.setFont(font)
            fm = p.fontMetrics()
            bw = max(14.0, float(fm.boundingRect(badge_text).width() + 6))
            bh = max(14.0, float(fm.boundingRect(badge_text).height() + 2))
            badge_rect = QRectF(self.width() - bw - 2, 1, bw, bh)
            p.save()
            bc = badge_rect.center()
            bs = self._badge_scale
            if abs(bs - 1.0) > 0.01:
                # 小さく出てから弾んで大きくなる
                s2 = bs + 0.18 * math.sin(bs * math.pi)
                p.translate(bc)
                p.scale(s2, s2)
                p.translate(-bc)
            p.setBrush(QBrush(themed_qcolor("#3d6aa8")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(badge_rect, 7, 7)
            p.setPen(QPen(themed_qcolor("#f1f3f7")))
            p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
            p.restore()
