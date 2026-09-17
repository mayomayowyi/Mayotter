from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QFrame,
    QPushButton,
    QSizePolicy,
    QLabel,
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    QSize, Qt, Signal, QEvent, QTimer, QPoint, QPointF, QRectF,
    QEasingCurve, QVariantAnimation,
)
from PySide6.QtGui import (
    QMouseEvent, QResizeEvent, QColor, QIcon, QPainter,
    QPen, QPainterPath, QPaintEvent, QFont, QFontMetrics,
)

from src.browser.webview import XWebView
from src.ui.icons import (
    make_home_icon,
    make_back_icon,
    make_forward_icon,
    make_chevron_down_icon,
    make_expand_h_icon,
)

_INTERNAL_ID_RE = re.compile(r"^[0-9a-f]{8}$")

class _UrlBar(QLineEdit):

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_url_context_menu)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def _style_menu(self, menu) -> None:
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
                "QMenu::item:selected { background:rgba(148,178,230,0.18); color:#f1f3f7; }"
                "QMenu::item:disabled { color:#7f899a; }"
            )

    def _show_url_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu, QApplication
        from PySide6.QtGui import QAction
        menu = QMenu(self)
        self._style_menu(menu)
        text = self.text() or ""
        sel = self.selectedText() or ""
        clip = ""
        try:
            clip = QApplication.clipboard().text() or ""
        except Exception:
            pass
        can_edit = not self.isReadOnly()
        has_sel = bool(sel)
        has_text = bool(text.strip())
        act_undo = QAction("元に戻す", menu)
        act_redo = QAction("やり直す", menu)
        act_cut = QAction("切り取り", menu)
        act_copy = QAction("コピー", menu)
        act_paste = QAction("貼り付けて検索", menu)
        act_sel = QAction("すべて選択", menu)
        act_undo.setEnabled(can_edit and bool(getattr(self, "isUndoAvailable", lambda: False)()))
        act_redo.setEnabled(can_edit and bool(getattr(self, "isRedoAvailable", lambda: False)()))
        act_cut.setEnabled(can_edit and has_sel)
        act_copy.setEnabled(has_sel or has_text)
        act_paste.setEnabled(bool(clip.strip()))
        act_sel.setEnabled(has_text)
        act_undo.triggered.connect(lambda _checked=False: self.undo())
        act_redo.triggered.connect(lambda _checked=False: self.redo())
        act_cut.triggered.connect(lambda _checked=False: self.cut())
        act_copy.triggered.connect(lambda _checked=False: self._copy_url_text())
        act_paste.triggered.connect(lambda _checked=False: self._paste_url_text())
        act_sel.triggered.connect(lambda _checked=False: self.selectAll())
        menu.addAction(act_undo)
        menu.addAction(act_redo)
        menu.addSeparator()
        menu.addAction(act_cut)
        menu.addAction(act_copy)
        menu.addAction(act_paste)
        menu.addSeparator()
        menu.addAction(act_sel)
        menu.exec(self.mapToGlobal(pos))

    def _copy_url_text(self) -> None:
        from PySide6.QtWidgets import QApplication
        text = self.selectedText()
        if not text:
            text = self.text()
        if text:
            QApplication.clipboard().setText(text)

    def _paste_url_text(self) -> None:
        from PySide6.QtWidgets import QApplication
        from src.browser.webview import normalize_user_input_url
        clip = (QApplication.clipboard().text() or "").strip()
        if not clip:
            return
        url = normalize_user_input_url(clip)
        if not url:
            return
        col = self.parentWidget()
        while col is not None and not hasattr(col, "navigate"):
            col = col.parentWidget()
        if col is not None:
            col.navigate(url)

class _SharedUiHoverStrip(QWidget):
    """共有UI（←→🔁）用の透明ホバー帯。境界の2pxリサイズとは別。"""

    WIDTH = 8

    def __init__(self, parent: QWidget, column: "AccountColumn") -> None:
        super().__init__(parent)
        self._column = column
        self.setObjectName("shared_ui_hover_strip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        self._release_gen = 0

    def paintEvent(self, event) -> None:
        return

    def enterEvent(self, event) -> None:
        win = self.window()
        if win is not None and getattr(win, "_boundary_dragging", False):
            super().enterEvent(event)
            return
        self._release_gen += 1
        h = getattr(self._column, "_resize_handle", None)
        if h is not None and h.isVisible():
            try:
                h._show_actions(True)
            except Exception:
                pass
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._release_gen += 1
        gen = self._release_gen
        QTimer.singleShot(30, lambda g=gen: self._maybe_release_shared_ui(g))
        super().leaveEvent(event)

    def _maybe_release_shared_ui(self, gen: int = 0) -> None:
        if gen and gen != getattr(self, "_release_gen", 0):
            return
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        h = getattr(self._column, "_resize_handle", None)
        if h is not None and h.isVisible():
            try:
                if h.rect().contains(h.mapFromGlobal(pos)):
                    return
            except Exception:
                pass
        try:
            if self.isVisible() and self.rect().contains(self.mapFromGlobal(pos)):
                return
        except Exception:
            pass
        win = self.window()
        on_knob = getattr(win, "boundary_action_knobs_contain_global", None) if win is not None else None
        if callable(on_knob) and on_knob(pos):
            return
        if h is not None:
            try:
                h._show_actions(False)
            except Exception:
                pass


class _BoundaryHintBar(QWidget):
    """通常境界の hover ハイライト専用バー。

    通常時は何も描かず（親の暗い背景＝既存の藍色相当が透ける）。
    hover 時だけ薄い青を paintEvent で描く。stylesheet に頼らないことで、
    leave 後に色が残る残像を防ぐ。
    """

    def __init__(self, handle: QWidget) -> None:
        super().__init__(handle)
        self._handle = handle
        self.setObjectName("boundary_hint_bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        # 親ハンドルと同じ resize 可能判定 → SizeHor（子が Arrow に戻さない）
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        # グローバル stylesheet の background 指定を無効化
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event) -> None:
        # 毎フレーム Source で塗り直す（非 hover 時は透明クリア＝残像防止）
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        active = bool(getattr(self._handle, "_hint", False))
        if active:
            p.fillRect(self.rect(), QColor(122, 158, 218, 46))  # ≈ rgba(122,158,218,0.18)
        else:
            p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.end()


class _BoundaryHandle(QWidget):

    stow_right_clicked = Signal()
    reset_widths_clicked = Signal()

    # 通常境界の visual / resize hit は常に 2px（共有UI hover 幅とは分離）
    _IDLE_WIDTH = 2
    _RESIZE_HIT_HALF = 1

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("column_resize_handle")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setMouseTracking(True)
        self.setFixedWidth(self._IDLE_WIDTH)
        self._hint = False
        self._bar = _BoundaryHintBar(self)
        self._active = False
        self._actions_visible = False
        self._expand = 0.0
        self._btn_reset = None
        self._btn_stow = None

        self._expand_anim = QVariantAnimation(self)
        self._expand_anim.setDuration(180)
        self._expand_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._expand_anim.valueChanged.connect(self._on_expand_changed)
        self._expand_anim.finished.connect(self._on_expand_finished)
        # 最後に確定した hover 目標（True→1.0 / False→0.0）。半透明停止を防ぐ。
        self._expand_target = 0.0

    def _on_expand_changed(self, value) -> None:
        try:
            self._expand = float(value)
        except (TypeError, ValueError):
            self._expand = 0.0
        self._apply_expand_layout()

    def set_hint(self, active: bool) -> None:
        """青ハイライトの唯一の書き込み口。

        state を更新したうえで _bar を再 paint する。
        色は stylesheet ではなく _BoundaryHintBar.paintEvent が描く。
        """
        active = bool(active)
        changed = active != self._hint
        self._hint = active
        # 互換のため property も更新（stylesheet 側は transparent 固定）
        try:
            self.setProperty("hint", active)
        except Exception:
            pass
        if changed or not active:
            try:
                self._bar.update()
                self.update()
            except Exception:
                pass
        if active:
            win = self.window()
            ensure = getattr(win, "_ensure_boundary_hover_poll", None) if win is not None else None
            if callable(ensure):
                try:
                    ensure()
                except Exception:
                    pass

    def _position_bar(self) -> None:
        # 通常境界: ハンドル実幅(=2px)全体が visual + resize hit
        # 個別収納フル幅: 中央ヒント線なし
        owner = self._owner_column()
        stowed = owner is not None and getattr(
            owner, "is_individually_stowed", lambda: False
        )()
        if stowed:
            try:
                self._bar.hide()
            except Exception:
                pass
            if self._actions_visible:
                self._apply_expand_layout()
            return
        try:
            self._bar.show()
        except Exception:
            pass
        bw = max(1, min(2, self.width()))
        self._bar.setGeometry(0, 0, bw, self.height())
        if self._actions_visible:
            self._apply_expand_layout()

    def _local_in_resize_hit(self, local_x: int | float) -> bool:
        """通常境界の resize 判定: ハンドル内全体（幅 2px）。"""
        try:
            x = int(local_x)
            return 0 <= x < max(1, self.width())
        except Exception:
            return False

    def _boundary_pivot_in_window(self):
        win = self.window()
        if win is None:
            return None
        owner = self._owner_column()
        # 個別収納: 横は隣接する連続収納領域の左右端中点、縦は通常境界と同じ body
        if owner is not None and getattr(owner, "is_individually_stowed", lambda: False)():
            left_edge_col = owner
            right_edge_col = owner
            ordered = None
            try:
                cols = getattr(win, "_columns", None)
                if cols:
                    ordered = [c for c in cols if c.isVisible()]
            except Exception:
                ordered = None
            if ordered:
                try:
                    idx = ordered.index(owner)
                except ValueError:
                    idx = -1
                if idx >= 0:
                    li = idx
                    while li > 0 and getattr(
                        ordered[li - 1], "is_individually_stowed", lambda: False
                    )():
                        li -= 1
                    ri = idx
                    while ri < len(ordered) - 1 and getattr(
                        ordered[ri + 1], "is_individually_stowed", lambda: False
                    )():
                        ri += 1
                    left_edge_col = ordered[li]
                    right_edge_col = ordered[ri]
            # QRect.center() は偶数幅で 1px 左に寄るため、左右端から中点を取る
            left_pt = left_edge_col.mapTo(win, QPoint(0, 0))
            right_pt = right_edge_col.mapTo(win, QPoint(right_edge_col.width(), 0))
            cx = (int(left_pt.x()) + int(right_pt.x())) // 2
            body = None
            left = getattr(owner, "_boundary_left_col", None)
            if left is not None:
                body = getattr(left, "_body", None)
            if body is None or body.height() <= 0:
                right = getattr(owner, "_boundary_right_col", None)
                if right is not None:
                    body = getattr(right, "_body", None)
            if body is not None and body.height() > 0:
                top_pt = body.mapTo(win, body.rect().topLeft())
                bot_pt = body.mapTo(win, body.rect().bottomLeft())
                return win, cx, int(top_pt.y()), int(bot_pt.y())
            top = self.mapTo(win, self.rect().topLeft())
            bot = self.mapTo(win, self.rect().bottomLeft())
            return win, cx, int(top.y()), int(bot.y())
        edge = self.mapTo(win, self.rect().topRight())
        bot = self.mapTo(win, self.rect().bottomRight())
        return win, int(edge.x()), int(edge.y()), int(bot.y())

    def _apply_expand_layout(self) -> None:
        pivot = self._boundary_pivot_in_window()
        if pivot is None:
            return
        win, cx, top, bot = pivot
        fn = getattr(win, "update_boundary_actions", None)
        if callable(fn):
            fn(cx, top, bot, float(self._expand), self._owner_column())

    def _position_action_buttons(self) -> None:
        self._apply_expand_layout()

    def _animate_expand(self, target: float) -> None:
        """現在 opacity から target へ。途中で stop して新 target へ切り替えてよい。"""
        target = 1.0 if float(target) >= 0.5 else 0.0
        self._expand_target = target
        self._expand_gen = int(getattr(self, "_expand_gen", 0) or 0) + 1
        gen = self._expand_gen
        try:
            self._expand_anim.stop()
        except Exception:
            pass
        try:
            cur = float(self._expand)
        except (TypeError, ValueError):
            cur = 0.0
        if abs(cur - target) < 0.01:
            self._expand = target
            self._apply_expand_layout()
            self._finalize_expand_state(gen)
            return
        self._expand_anim.setStartValue(cur)
        self._expand_anim.setEndValue(target)
        # finished 時に gen を照合して古い callback を無視
        self._expand_anim_gen = gen
        self._expand_anim.start()

    def _show_actions(self, show: bool) -> None:
        if self._active:
            show = False
        show = bool(show)
        self._actions_visible = show
        self._expand_target = 1.0 if show else 0.0
        if show:
            self.set_hint(True)
            self._animate_expand(1.0)
        else:
            self.set_hint(False)
            self._animate_expand(0.0)

    def _finalize_expand_state(self, gen: int | None = None) -> None:
        """アニメ終了時に target へ明示 set。半透明の残留を禁止。"""
        if gen is not None and gen != getattr(self, "_expand_gen", None):
            return
        want_show = bool(self._actions_visible)
        try:
            target = float(getattr(self, "_expand_target", 1.0 if want_show else 0.0))
        except (TypeError, ValueError):
            target = 1.0 if want_show else 0.0
        # hover 状態と target を一致させる
        target = 1.0 if want_show else 0.0
        self._expand_target = target
        self._expand = target
        self._apply_expand_layout()
        if want_show:
            return
        self.set_hint(False)
        win = self.window()
        owner = self._owner_column()
        # owner 不一致でも t=0 を反映済み。共有 overlay は owner 一致時に閉じる
        if win is not None and getattr(win, "_boundary_action_col", None) is owner:
            hide = getattr(win, "hide_boundary_actions", None)
            if callable(hide):
                try:
                    hide()
                except Exception:
                    pass

    def _on_expand_finished(self) -> None:
        self._finalize_expand_state(getattr(self, "_expand_anim_gen", None))

    def _hide_hint_now(self) -> None:
        """青ヒントとアクションを即クリア。共有overlayは自分がownerのときだけ閉じる。"""
        try:
            self._expand_anim.stop()
        except Exception:
            pass
        self._actions_visible = False
        self._expand = 0.0
        self.set_hint(False)
        win = self.window()
        owner = self._owner_column()
        if win is not None and getattr(win, "_boundary_action_col", None) is owner:
            hide = getattr(win, "hide_boundary_actions", None)
            if callable(hide):
                try:
                    hide()
                except Exception:
                    pass

    def _clear_other_boundary_hints(self) -> None:
        """他ハンドルのローカル hint/expand だけ消す（共有 overlay は触らない）。"""
        win = self.window()
        cols = getattr(win, "_columns", None) if win is not None else None
        if not cols:
            return
        for c in cols:
            h = getattr(c, "_resize_handle", None)
            if h is None or h is self:
                continue
            try:
                if getattr(h, "_hint", False) or getattr(h, "_actions_visible", False):
                    try:
                        h._expand_anim.stop()
                    except Exception:
                        pass
                    h._actions_visible = False
                    h._expand = 0.0
                    h.set_hint(False)
            except Exception:
                pass

    def enterEvent(self, event) -> None:
        if self._active:
            super().enterEvent(event)
            return
        win = self.window()
        if win is not None and getattr(win, "_boundary_dragging", False):
            super().enterEvent(event)
            return
        owner = self._owner_column()
        stowed = owner is not None and getattr(
            owner, "is_individually_stowed", lambda: False
        )()
        if stowed:
            # 収納領域全体: SizeHor + 共有UI。個別展開↔はカラム側。
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            sync = getattr(win, "_sync_column_resize_cursor", None) if win is not None else None
            if callable(sync):
                try:
                    sync()
                except Exception:
                    pass
            self._ensure_stowed_shared_ui()
            super().enterEvent(event)
            return
        # 通常 2px handle 上 = resize 可能 → SizeHor。共有UI も表示
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        sync = getattr(win, "_sync_column_resize_cursor", None) if win is not None else None
        if callable(sync):
            try:
                sync()
            except Exception:
                pass
        self._clear_other_boundary_hints()
        if not self._actions_visible:
            self.set_hint(True)
            self._show_actions(True)
        super().enterEvent(event)

    def _ensure_stowed_shared_ui(self) -> None:
        """収納領域上の共有UI。既に出ているなら hide/show し直さない。"""
        if self._active:
            return
        win = self.window()
        if win is not None and getattr(win, "_boundary_dragging", False):
            return
        owner = self._owner_column()
        left = getattr(owner, "_boundary_left_col", None) if owner is not None else None
        right = getattr(owner, "_boundary_right_col", None) if owner is not None else None
        # 同一収納領域のどれかで既に共有UIが出ていれば、それを維持（再 show しない）
        cols = getattr(win, "_columns", None) if win is not None else None
        if cols and left is not None and right is not None:
            for c in cols:
                try:
                    if not getattr(c, "is_individually_stowed", lambda: False)():
                        continue
                    if getattr(c, "_boundary_left_col", None) is not left:
                        continue
                    if getattr(c, "_boundary_right_col", None) is not right:
                        continue
                    h = getattr(c, "_resize_handle", None)
                    if h is None:
                        continue
                    if getattr(h, "_actions_visible", False) and float(getattr(h, "_expand", 0.0)) > 0.5:
                        # このハンドルをアクティブ owner として layout だけ同期
                        if not self._actions_visible:
                            self._actions_visible = True
                            self._expand = float(h._expand)
                            self._apply_expand_layout()
                        return
                except Exception:
                    continue
        if self._actions_visible and float(getattr(self, "_expand", 0.0)) > 0.5:
            return
        self._show_actions(True)

    def _cursor_on_boundary_session(self) -> bool:
        """session 内: 2px handle / Shared strip / 実ボタン上。overlay 64px 全体は除外。"""
        if self._active:
            return True
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        try:
            if self.rect().contains(self.mapFromGlobal(pos)):
                return True
        except Exception:
            pass
        owner = self._owner_column()
        if owner is not None:
            strip = getattr(owner, "_shared_ui_hover_strip", None)
            if strip is not None and strip.isVisible():
                try:
                    if strip.rect().contains(strip.mapFromGlobal(pos)):
                        return True
                except Exception:
                    pass
        win = self.window()
        if win is None:
            return False
        if getattr(win, "_boundary_action_col", None) is not owner:
            return False
        # 実ボタン矩形のみ（64px overlay 全体では session 維持しない）
        over = getattr(win, "boundary_action_knobs_contain_global", None)
        try:
            if callable(over) and over(pos):
                return True
        except Exception:
            pass
        return False

    def leaveEvent(self, event) -> None:
        # leave で Arrow に落とさない。隣接 resize 領域へ移る瞬間も SizeHor 維持。
        win = self.window()
        sync = getattr(win, "_sync_column_resize_cursor", None) if win is not None else None
        if callable(sync):
            try:
                sync()
            except Exception:
                pass
        owner = self._owner_column()
        stowed = owner is not None and getattr(
            owner, "is_individually_stowed", lambda: False
        )()
        if stowed:
            # 同じ収納領域（同一 left/right 通常カラム）内なら共有UIを維持
            QTimer.singleShot(0, self._maybe_hide_stowed_shared_ui)
            super().leaveEvent(event)
            return
        # handle → overlay への移動では session を終了しない。
        QTimer.singleShot(30, self._maybe_hide_actions)
        super().leaveEvent(event)

    def _maybe_hide_stowed_shared_ui(self) -> None:
        if self._active:
            return
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        owner = self._owner_column()
        left = getattr(owner, "_boundary_left_col", None) if owner is not None else None
        right = getattr(owner, "_boundary_right_col", None) if owner is not None else None
        win = self.window()
        # 同一収納領域の他スロット上なら共有UI維持
        cols = getattr(win, "_columns", None) if win is not None else None
        if cols and left is not None and right is not None:
            for c in cols:
                try:
                    if not getattr(c, "is_individually_stowed", lambda: False)():
                        continue
                    if getattr(c, "_boundary_left_col", None) is not left:
                        continue
                    if getattr(c, "_boundary_right_col", None) is not right:
                        continue
                    h = getattr(c, "_resize_handle", None)
                    if h is not None and h.isVisible():
                        if h.rect().contains(h.mapFromGlobal(pos)):
                            return
                    if c.rect().contains(c.mapFromGlobal(pos)):
                        return
                except Exception:
                    continue
        over = getattr(win, "boundary_actions_contain_global", None) if win is not None else None
        if callable(over) and over(pos):
            return
        self._hide_hint_now()

    def _maybe_hide_actions(self) -> None:
        if self._active:
            return
        if self._cursor_on_boundary_session():
            return
        self._hide_hint_now()

    _WINDOW_EDGE_MARGIN = 2

    def _yield_to_window_resize(self, event: QMouseEvent) -> bool:
        top = self.window()
        if top is None:
            return False
        if getattr(top, "_edge_dock_enabled", False) and getattr(top, "_edge_dock_revealed", False):
            return False
        local = top.mapFromGlobal(event.globalPosition().toPoint())
        m = self._WINDOW_EDGE_MARGIN
        near_edge = (
            local.x() < m or local.x() >= top.width() - m
            or local.y() < m or local.y() >= top.height() - m
        )
        if not near_edge:
            return False
        wh = top.windowHandle()
        if wh is None:
            return False
        edges = Qt.Edges(0)
        if local.x() < m:
            edges |= Qt.Edge.LeftEdge
        elif local.x() >= top.width() - m:
            edges |= Qt.Edge.RightEdge
        if local.y() < m:
            edges |= Qt.Edge.TopEdge
        elif local.y() >= top.height() - m:
            edges |= Qt.Edge.BottomEdge
        wh.startSystemResize(edges)
        return True

    def _try_boundary_action_click(self, event: QMouseEvent) -> bool:
        win = self.window()
        if win is None:
            return False
        ov = getattr(win, "_boundary_overlay", None)
        if ov is None or not ov.isVisible() or float(getattr(ov, "_t", 0.0)) <= 0.02:
            return False
        try:
            if hasattr(ov, "_refresh_action_rects"):
                ov._refresh_action_rects()
            local = ov.mapFromGlobal(event.globalPosition().toPoint())
            stow_left = getattr(ov, "_stow_left_rect", None)
            stow_right = getattr(ov, "_stow_right_rect", None) or getattr(ov, "_stow_rect", None)
            reset = getattr(ov, "_reset_rect", None)
            if stow_left is not None and stow_left.contains(local):
                fn = getattr(win, "_on_boundary_stow_left_clicked", None)
                if callable(fn):
                    fn()
                return True
            if stow_right is not None and stow_right.contains(local):
                fn = getattr(win, "_on_boundary_stow_clicked", None)
                if callable(fn):
                    fn()
                return True
            if reset is not None and reset.contains(local):
                fn = getattr(win, "_on_boundary_reset_clicked", None)
                if callable(fn):
                    fn()
                return True
        except Exception:
            return False
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._yield_to_window_resize(event):
                event.accept()
                return
            if self._try_boundary_action_click(event):
                event.accept()
                return
            owner = self._owner_column()
            stowed = owner is not None and getattr(
                owner, "is_individually_stowed", lambda: False
            )()
            # 通常境界: resize 開始は中央 2px のみ（共有UI hover 幅とは分離）
            # 個別収納: スロット全体で同一カラム幅調整を開始できる。
            if not stowed:
                local_x = event.position().toPoint().x()
                if not self._local_in_resize_hit(local_x):
                    event.accept()
                    return
            self._active = True
            self._expand_anim.stop()
            self._actions_visible = False
            self._expand = 0.0
            win = self.window()
            # ドラッグ中は共有UI・展開↔・hover をすべて抑制
            hide = getattr(win, "hide_boundary_actions", None) if win is not None else None
            if callable(hide):
                hide()
            suppress = getattr(win, "_suppress_all_boundary_hover_ui", None)
            if callable(suppress):
                suppress()
            self.set_hint(False)
            self._position_bar()
            self._press_x = event.globalPosition().x()
            self.raise_()
            self.setProperty("dragging", True)
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def begin_external_drag(self, global_x: float) -> None:
        self._active = True
        self._expand_anim.stop()
        self._actions_visible = False
        self._expand = 0.0
        win = self.window()
        hide = getattr(win, "hide_boundary_actions", None) if win is not None else None
        if callable(hide):
            hide()
        suppress = getattr(win, "_suppress_all_boundary_hover_ui", None)
        if callable(suppress):
            suppress()
        self.set_hint(False)
        self._position_bar()
        self._press_x = float(global_x)
        self.raise_()
        self.setProperty("dragging", True)
        self.grabMouse()

    def _owner_column(self):
        w = self.parentWidget()
        while w is not None:
            if type(w).__name__ == "AccountColumn":
                return w
            w = w.parentWidget()
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._active and event.buttons() & Qt.MouseButton.LeftButton:
            delta = int(event.globalPosition().x() - self._press_x)
            col = self._owner_column()
            if col is not None:
                col.boundary_dragged.emit(delta)
            event.accept()
            return
        if self._try_boundary_action_hover_cursor(event):
            event.accept()
            return
        # この handle 上 = resize 可能 → SizeHor（通常は 2px、収納はフル幅）
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        super().mouseMoveEvent(event)

    def _try_boundary_action_hover_cursor(self, event: QMouseEvent) -> bool:
        win = self.window()
        if win is None:
            return False
        ov = getattr(win, "_boundary_overlay", None)
        if ov is None or not ov.isVisible() or float(getattr(ov, "_t", 0.0)) <= 0.02:
            return False
        try:
            if hasattr(ov, "_refresh_action_rects"):
                ov._refresh_action_rects()
            local = ov.mapFromGlobal(event.globalPosition().toPoint())
            stow_left = getattr(ov, "_stow_left_rect", None)
            stow_right = getattr(ov, "_stow_right_rect", None) or getattr(ov, "_stow_rect", None)
            reset = getattr(ov, "_reset_rect", None)
            if (
                (stow_left is not None and stow_left.contains(local))
                or (stow_right is not None and stow_right.contains(local))
                or (reset is not None and reset.contains(local))
            ):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return True
        except Exception:
            pass
        return False

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._active and event.button() == Qt.MouseButton.LeftButton:
            self._active = False
            self.setProperty("dragging", False)
            self.set_hint(False)
            self.releaseMouse()
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            col = self._owner_column()
            if col is not None:
                col.boundary_drag_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # 収納同士の 1px 区切りは親カラム paint が描くが、フル幅ハンドルが
        # 覆うため左端に同じ 1px を描く（hit ではない・hover ではない）
        owner = self._owner_column()
        if owner is None:
            return
        if not getattr(owner, "is_individually_stowed", lambda: False)():
            return
        left_fn = getattr(owner, "_left_stowed_neighbor", None)
        if not callable(left_fn) or left_fn() is None:
            return
        p = QPainter(self)
        p.fillRect(0, 0, 1, max(1, self.height()), QColor("#2a3140"))
        p.end()

class _ColumnDragHandle(QWidget):

    REORDER_START_DISTANCE = 8

    pressed_drag = Signal()
    moved_drag = Signal(float)
    released_drag = Signal(float)
    cancelled_drag = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("col_drag_handle")
        self.setFixedSize(20, 28)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("ドラッグしてカラムを並べ替え")
        self._pressed = False
        self._dragging = False
        self._press_x = 0.0
        self._press_y = 0.0
        try:
            from src.ui.icons import make_column_grip_icon
            self._icon = make_column_grip_icon("#9fb4d8", 16)
            self._icon_active = make_column_grip_icon("#eaf1fb", 16)
        except Exception:
            self._icon = None
            self._icon_active = None
        self.setFixedSize(20, 28)
        self.setStyleSheet(
            "QWidget#col_drag_handle { background: transparent; border: 1px solid transparent; border-radius: 4px; }"
            "QWidget#col_drag_handle:hover { background: rgba(148,178,230,0.18); border: 1px solid #3d6a9e; }"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        icon = None
        if self._dragging and getattr(self, "_icon_active", None) is not None:
            icon = self._icon_active
        else:
            icon = self._icon
        if icon is None:
            return
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        pm = icon.pixmap(16, 16)
        x = (self.width() - pm.width()) // 2
        y = (self.height() - pm.height()) // 2
        p.drawPixmap(x, y, pm)
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            gp = event.globalPosition()
            self._pressed = True
            self._dragging = False
            self._press_x = float(gp.x())
            self._press_y = float(gp.y())
            self.grabMouse()
            self.pressed_drag.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._pressed:
            super().mouseMoveEvent(event)
            return
        gp = event.globalPosition()
        gx = float(gp.x())
        gy = float(gp.y())
        if not self._dragging:
            dx = abs(gx - self._press_x)
            dy = abs(gy - self._press_y)
            if max(dx, dy) < self.REORDER_START_DISTANCE:
                event.accept()
                return
            self._dragging = True
        self.moved_drag.emit(gx)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._pressed = False
            self._dragging = False
            try:
                self.releaseMouse()
            except Exception:
                pass
            gx = float(event.globalPosition().x())
            if was_dragging:
                self.released_drag.emit(gx)
            else:
                self.cancelled_drag.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

class RefreshMotionButton(QToolButton):

    _IDLE = 0
    _PRESS = 1
    _FLOW = 2
    _REFRESHING = 3
    _COMPLETING = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setObjectName("reload_btn")
        self.setToolTip("再読み込み")
        self.setText("")
        self.setIcon(QIcon())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._state = self._IDLE
        self._phase = 0.0
        self._press_t = 0.0
        self._flow_t = 0.0
        self._complete_t = 0.0
        self._load_active = False
        self._load_started_at = 0.0
        self._min_refresh_ms = 220.0
        self._pending_complete = False
        self._load_gen = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self.clicked.connect(self._on_clicked_motion)

    def bind_webview(self, wv) -> None:
        prev = getattr(self, "_bound_wv", None)
        if prev is not None and prev is not wv:
            for sig, slot in (
                ("loadStarted", self.on_load_started),
                ("loadFinished", self.on_load_finished),
            ):
                try:
                    getattr(prev, sig).disconnect(slot)
                except Exception:
                    pass
        self._bound_wv = wv
        if wv is None:
            return
        try:
            wv.loadStarted.connect(self.on_load_started)
        except Exception:
            pass
        try:
            wv.loadFinished.connect(self.on_load_finished)
        except Exception:
            pass

    def _on_clicked_motion(self) -> None:
        if self._state in (self._REFRESHING, self._FLOW):
            self._enter_press()
            return
        self._enter_press()

    def _enter_press(self) -> None:
        self._state = self._PRESS
        self._press_t = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def on_load_started(self) -> None:
        import time as _t
        self._load_gen += 1
        self._load_active = True
        self._pending_complete = False
        self._load_started_at = _t.monotonic()
        if self._state in (self._IDLE, self._PRESS, self._COMPLETING):
            self._state = self._FLOW
            self._flow_t = 0.0
        elif self._state != self._REFRESHING:
            self._state = self._REFRESHING
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def on_load_finished(self, _ok: bool = True) -> None:
        import time as _t
        gen = int(self._load_gen)
        self._load_active = False
        if self._state in (self._IDLE,):
            return
        elapsed = (_t.monotonic() - self._load_started_at) * 1000.0
        if elapsed < self._min_refresh_ms and self._state in (
            self._FLOW, self._REFRESHING, self._PRESS
        ):
            self._pending_complete = True
            remain = max(0, int(self._min_refresh_ms - elapsed))
            QTimer.singleShot(remain, lambda g=gen: self._begin_complete_for(g))
            return
        self._begin_complete_for(gen)

    def _begin_complete_for(self, gen: int) -> None:
        if gen != int(self._load_gen):
            return
        if self._load_active:
            return
        self._begin_complete()

    def _begin_complete(self) -> None:
        if self._load_active:
            return
        self._pending_complete = False
        self._state = self._COMPLETING
        self._complete_t = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _on_tick(self) -> None:
        dt = 0.016
        st = self._state
        if st == self._PRESS:
            self._press_t += dt
            if self._press_t >= 0.07:
                if self._load_active:
                    self._state = self._FLOW
                    self._flow_t = 0.0
                else:
                    self._state = self._FLOW
                    self._flow_t = 0.0
        elif st == self._FLOW:
            self._flow_t += dt
            if self._flow_t >= 0.22:
                self._state = self._REFRESHING
                self._phase = 0.0
        elif st == self._REFRESHING:
            self._phase = (self._phase + dt / 1.15) % 1.0
            if self._pending_complete and not self._load_active:
                self._begin_complete()
                return
        elif st == self._COMPLETING:
            self._complete_t += dt
            if self._complete_t >= 0.16:
                self._state = self._IDLE
                self._phase = 0.0
                self._timer.stop()
        else:
            self._timer.stop()
            return
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = min(self.width(), self.height()) * 0.22
        idle_c = QColor("#aeb6c5")
        accent = QColor("#4a7ec7")
        bright = QColor("#7aa3d9")

        st = self._state
        if st == self._IDLE:
            self._draw_refresh_icon(p, cx, cy, r, idle_c, full=True)
        elif st == self._PRESS:
            k = 1.0 - 0.06 * min(1.0, self._press_t / 0.07)
            self._draw_refresh_icon(p, cx, cy, r * k, idle_c, full=True, pen_w=1.35)
        elif st == self._FLOW:
            t = min(1.0, self._flow_t / 0.22)
            te = 1.0 - (1.0 - t) ** 3
            self._draw_flowing_arc(p, cx, cy, r, accent, te, head=0.35 + 0.25 * te)
        elif st == self._REFRESHING:
            import math
            ph = self._phase
            breath = 0.5 + 0.5 * math.sin(ph * math.pi * 2)
            head = 0.28 + 0.22 * breath
            gap = 0.18 + 0.12 * (1.0 - breath)
            self._draw_flowing_arc(
                p, cx, cy, r, accent, ph, head=head, gap=gap, pen_w=1.55
            )
        elif st == self._COMPLETING:
            t = min(1.0, self._complete_t / 0.16)
            te = 1.0 - (1.0 - t) ** 2
            if te < 0.55:
                self._draw_flowing_arc(
                    p, cx, cy, r, bright, 0.15 + 0.5 * te, head=0.55, gap=0.08, pen_w=1.7
                )
            else:
                self._draw_refresh_icon(p, cx, cy, r, idle_c, full=True, pen_w=1.5)
        p.end()

    def _draw_refresh_icon(
        self, p: QPainter, cx: float, cy: float, r: float, color: QColor,
        *, full: bool = True, pen_w: float = 1.45,
    ) -> None:
        import math
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.drawArc(rect, int(40 * 16), int(140 * 16))
        p.drawArc(rect, int(220 * 16), int(140 * 16))
        self._arrow_tip(p, cx, cy, r, math.radians(40 + 140), color, pen_w)
        self._arrow_tip(p, cx, cy, r, math.radians(220 + 140), color, pen_w)

    def _arrow_tip(
        self, p: QPainter, cx: float, cy: float, r: float, angle: float, color: QColor, pen_w: float
    ) -> None:
        import math
        x = cx + r * math.cos(angle)
        y = cy - r * math.sin(angle)
        tx, ty = -math.sin(angle), -math.cos(angle)
        nx, ny = math.cos(angle), -math.sin(angle)
        s = max(2.2, pen_w * 1.6)
        path = QPainterPath()
        path.moveTo(x - tx * s + nx * s * 0.35, y - ty * s + ny * s * 0.35)
        path.lineTo(x, y)
        path.lineTo(x - tx * s - nx * s * 0.35, y - ty * s - ny * s * 0.35)
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_flowing_arc(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        r: float,
        color: QColor,
        phase: float,
        *,
        head: float = 0.4,
        gap: float = 0.2,
        pen_w: float = 1.55,
    ) -> None:
        import math
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        start_deg = (phase * 360.0) % 360.0
        span = max(40.0, min(300.0, head * 360.0))
        trail = max(20.0, span * 0.45)
        gap_deg = max(12.0, gap * 360.0)
        c2 = QColor(color)
        c2.setAlpha(160)
        p.drawArc(rect, int(start_deg * 16), int(-span * 16))
        pen2 = QPen(c2, max(1.1, pen_w * 0.85), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        p.drawArc(rect, int((start_deg + span + gap_deg) * 16), int(-trail * 16))
        head_a = math.radians(start_deg)
        hx = cx + r * math.cos(head_a)
        hy = cy - r * math.sin(head_a)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(hx, hy), pen_w * 0.85, pen_w * 0.85)

class AccountColumn(QWidget):

    closed = Signal()
    resized = Signal(int)
    enabled_changed = Signal(bool)
    boundary_dragged = Signal(int)
    boundary_drag_finished = Signal()
    stow_right_requested = Signal(object)
    stow_self_requested = Signal(object)
    restore_self_requested = Signal(object)
    reset_widths_requested = Signal()
    reorder_requested = Signal(float)
    reorder_drag_moved = Signal(float)
    reorder_drag_finished = Signal()
    activated = Signal()
    tabs_changed = Signal()
    current_tab_changed = Signal(int)
    tab_title_changed = Signal()
    new_tab_requested = Signal(str)
    url_edit_requested = Signal()

    RESIZE_HANDLE_WIDTH = 2
    MIN_WIDTH = 200
    STOWED_WIDTH = 10
    DEFAULT_WIDTH = 400
    LONG_PRESS_MS = 500
    DRAG_ABORT_PX = 8

    def __init__(
        self,
        account_id: str,
        display_name: str,
        webview: XWebView,
        width: int = DEFAULT_WIDTH,
        enabled: bool = True,
        initial_url: str = "",
        column_id: str = "",
        column_type: str = "home",
        title: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._account_id = account_id
        self._display_name = (display_name or "").strip()
        if column_id:
            self._column_id = str(column_id)
        else:
            from uuid import uuid4
            self._column_id = f"col_{account_id}_{uuid4().hex[:10]}"
        self._column_type = column_type
        self._title = title
        self._webview = webview
        self._tabs: list[XWebView] = [webview]
        self._current_tab = 0
        self._current_web_url = ""
        self._enabled = enabled
        self._initial_url = initial_url
        self._loaded_once = False

        self.setMinimumWidth(self.MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._current_width = width
        self.set_width(width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav_frame = QFrame()
        nav_frame.setObjectName("column_nav")
        nav_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        nav_bar = QHBoxLayout(nav_frame)
        nav_bar.setContentsMargins(2, 2, 2, 2)
        nav_bar.setSpacing(2)

        self._back_btn = QToolButton()
        self._back_btn.setIcon(make_back_icon("#aeb6c5", 14))
        self._back_btn.setIconSize(QSize(14, 14))
        self._back_btn.setText("")
        self._back_btn.setFixedSize(26, 26)
        self._back_btn.setObjectName("back_btn")
        self._back_btn.setToolTip("戻る")
        self._back_btn.clicked.connect(self._on_back)
        nav_bar.addWidget(self._back_btn)

        self._forward_btn = QToolButton()
        self._forward_btn.setIcon(make_forward_icon("#aeb6c5", 14))
        self._forward_btn.setIconSize(QSize(14, 14))
        self._forward_btn.setText("")
        self._forward_btn.setFixedSize(26, 26)
        self._forward_btn.setObjectName("forward_btn")
        self._forward_btn.setToolTip("進む")
        self._forward_btn.clicked.connect(self._on_forward)
        nav_bar.addWidget(self._forward_btn)
        self._nav_hist_bound_page = None

        self._reload_btn = RefreshMotionButton(self)
        self._reload_btn.clicked.connect(self._on_reload)
        nav_bar.addWidget(self._reload_btn)

        self._home_btn = QToolButton()
        self._home_btn.setIcon(make_home_icon("#aeb6c5", 16))
        self._home_btn.setIconSize(QSize(16, 16))
        self._home_btn.setText("")
        self._home_btn.setFixedSize(26, 26)
        self._home_btn.setObjectName("home_btn")
        self._home_btn.setToolTip("初期ページへ戻る")
        self._home_btn.clicked.connect(self.go_home)
        nav_bar.addWidget(self._home_btn)

        self._col_drag_handle = _ColumnDragHandle(self)
        self._col_drag_handle.pressed_drag.connect(self._on_col_grip_pressed)
        self._col_drag_handle.moved_drag.connect(self._on_col_grip_moved)
        self._col_drag_handle.released_drag.connect(self._on_col_grip_released)
        self._col_drag_handle.cancelled_drag.connect(self._on_col_grip_cancelled)
        nav_bar.addWidget(self._col_drag_handle, 0)

        self._stow_btn = QToolButton()
        self._stow_btn.setIcon(make_chevron_down_icon("#aeb6c5", 14))
        self._stow_btn.setIconSize(QSize(14, 14))
        self._stow_btn.setText("")
        self._stow_btn.setFixedSize(26, 26)
        self._stow_btn.setObjectName("stow_self_btn")
        self._stow_btn.setToolTip("このカラムを収納")
        self._stow_btn.setAutoRaise(True)
        self._stow_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stow_btn.clicked.connect(self._on_stow_self_clicked)
        nav_bar.addWidget(self._stow_btn)

        self._url_bar = _UrlBar()
        self._url_bar.setObjectName("url_bar")
        self._url_bar.setPlaceholderText("URL または検索キーワード")
        self._url_bar.setMinimumHeight(26)
        self._url_bar.clicked.connect(self.url_edit_requested)
        nav_bar.addWidget(self._url_bar, 1)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setObjectName("close_btn")
        close_btn.setToolTip("カラムを閉じる")
        close_btn.clicked.connect(self._on_close)
        nav_bar.addWidget(close_btn)
        self._close_btn = close_btn

        layout.addWidget(nav_frame)

        self._body = QWidget(self)
        self._body.setObjectName("column_body")
        try:
            from PySide6.QtGui import QColor
            self._body.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            self._body.setAutoFillBackground(True)
            bp = self._body.palette()
            bp.setColor(self._body.backgroundRole(), QColor("#0b111f"))
            self._body.setPalette(bp)
        except Exception:
            pass
        body_row = QHBoxLayout(self._body)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)
        body_row.addWidget(webview, 1)
        self._resize_handle = _BoundaryHandle(self._body)
        self._resize_handle.setFixedWidth(AccountColumn.RESIZE_HANDLE_WIDTH)
        self._resize_handle.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._resize_handle.stow_right_clicked.connect(
            lambda: self.stow_right_requested.emit(self)
        )
        self._resize_handle.reset_widths_clicked.connect(self.reset_widths_requested.emit)
        self._resize_handle.hide()
        body_row.addWidget(self._resize_handle, 0)
        # 共有UI専用の透明ホバー帯（resize 2px とは別。描画なし）
        self._shared_ui_hover_strip = _SharedUiHoverStrip(self._body, self)
        self._shared_ui_hover_strip.hide()
        layout.addWidget(self._body, 1)

        for nav_btn in (
            self._back_btn,
            self._forward_btn,
            self._reload_btn,
            self._home_btn,
            close_btn,
        ):
            nav_btn.pressed.connect(self.activated)
        # stow は pressed→activated でレイアウトが動くと clicked が落ちるので入れない

        self._individually_stowed = False
        self._stowed_restore_btn = None

        if hasattr(webview, 'url_changed'):
            webview.url_changed.connect(
                lambda url, w=webview: self._on_webview_url_changed(w, url)
            )
        if hasattr(webview, 'pressed'):
            webview.pressed.connect(self.activated)
        if hasattr(webview, 'titleChanged'):
            webview.titleChanged.connect(lambda *_: self.tab_title_changed.emit())
        webview.tab_opener = self.new_tab_requested.emit
        try:
            self._reload_btn.bind_webview(webview)
        except Exception:
            pass
        try:
            self._bind_nav_history(webview)
        except Exception:
            pass

        self._drag_armed = False
        self._drag_press_x = 0.0
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(self.LONG_PRESS_MS)
        self._drag_timer.timeout.connect(self._arm_drag)
        self._nav_frame = nav_frame
        self._profile_resolve_attempted = False
        self._profile_resolve_retries = 0
        self._profile_state = "IDLE"
        self._profile_tried_settings = False
        self._profile_waiting_self_redirect = False
        self._resolve_request_id = 0
        self._lists_resolved_url = ""
        self._nav_target_lock = ""
        if self._column_type == "profile":
            QTimer.singleShot(0, self._bootstrap_profile)
        elif self._column_type == "lists":
            QTimer.singleShot(0, self._bootstrap_lists)

    def add_tab_view(self, webview) -> int:
        if webview in self._tabs:
            return self._tabs.index(webview)
        self._tabs.append(webview)
        body_lay = self._body.layout()
        if body_lay is not None:
            body_lay.insertWidget(max(0, body_lay.count() - 1), webview, 1)
        else:
            self.layout().addWidget(webview, 1)
        webview.hide()
        if hasattr(webview, 'url_changed'):
            webview.url_changed.connect(
                lambda url, w=webview: self._on_webview_url_changed(w, url)
            )
        if hasattr(webview, 'pressed'):
            webview.pressed.connect(self.activated)
        if hasattr(webview, 'titleChanged'):
            webview.titleChanged.connect(lambda *_: self.tab_title_changed.emit())
        webview.tab_opener = self.new_tab_requested.emit
        index = len(self._tabs) - 1
        self.set_current_tab(index)
        self.tabs_changed.emit()
        self.activated.emit()
        return index

    def set_current_tab(self, index: int) -> None:
        if not (0 <= index < len(self._tabs)):
            return
        previous = self._current_tab
        self._current_tab = index
        for i, tab in enumerate(self._tabs):
            tab.setVisible(i == index)
        active = self._tabs[index]
        try:
            active.raise_()
        except Exception:
            pass
        pending = getattr(active, "_pending_restore_url", None)
        if pending:
            try:
                active._pending_restore_url = None
            except Exception:
                pass
            try:
                active.load_url(str(pending), restore=True)
            except TypeError:
                try:
                    active.load_url(str(pending))
                except Exception:
                    pass
            except Exception:
                pass
        url_getter = getattr(active, "get_current_url", None)
        self._on_url_changed(url_getter() if callable(url_getter) else "")
        if previous != index:
            self.current_tab_changed.emit(index)
        try:
            self._reload_btn.bind_webview(active)
        except Exception:
            pass
        try:
            self._bind_nav_history(active)
        except Exception:
            pass

    def _bind_nav_history(self, wv) -> None:
        prev_page = getattr(self, "_nav_hist_bound_page", None)
        page = None
        try:
            page = wv.page() if wv is not None else None
        except Exception:
            page = None
        if prev_page is not None and prev_page is not page:
            try:
                hist = prev_page.history()
                hist.historyChanged.disconnect(self._update_nav_history_buttons)
            except Exception:
                pass
            try:
                prev_page.urlChanged.disconnect(self._update_nav_history_buttons)
            except Exception:
                pass
        self._nav_hist_bound_page = page
        if page is None:
            self._update_nav_history_buttons()
            return
        try:
            hist = page.history()
            hist.historyChanged.connect(self._update_nav_history_buttons)
        except Exception:
            pass
        try:
            page.urlChanged.connect(self._update_nav_history_buttons)
        except Exception:
            pass
        self._update_nav_history_buttons()

    def _update_nav_history_buttons(self, *_args) -> None:
        can_back = False
        can_fwd = False
        try:
            wv = self.current_webview()
            page = wv.page() if wv is not None else None
            if page is not None:
                hist = page.history()
                can_back = bool(hist.canGoBack())
                can_fwd = bool(hist.canGoForward())
        except Exception:
            pass
        on = "#aeb6c5"
        off = "#5c6474"
        try:
            self._back_btn.setIcon(make_back_icon(on if can_back else off, 14))
            self._forward_btn.setIcon(make_forward_icon(on if can_fwd else off, 14))
        except Exception:
            pass

    def _enforce_single_visible_tab(self) -> None:
        if not self._tabs:
            return
        idx = self._current_tab if 0 <= self._current_tab < len(self._tabs) else 0
        self._current_tab = idx
        for i, tab in enumerate(self._tabs):
            want = i == idx
            tab.setVisible(want)
        try:
            self._tabs[idx].raise_()
        except Exception:
            pass

    def close_tab(self, index: int) -> None:
        if not (0 <= index < len(self._tabs)):
            return
        closing_last = len(self._tabs) == 1
        if closing_last:
            self.closed.emit()
            return
        tab = self._tabs.pop(index)
        body_lay = self._body.layout() if getattr(self, "_body", None) is not None else None
        if body_lay is not None:
            body_lay.removeWidget(tab)
        else:
            self.layout().removeWidget(tab)
        tab.hide()
        tab.deleteLater()
        if self._current_tab >= len(self._tabs):
            self._current_tab = len(self._tabs) - 1
        elif self._current_tab > index:
            self._current_tab -= 1
        self.set_current_tab(self._current_tab)
        self.tabs_changed.emit()

    def move_tab(self, from_index: int, to_index: int) -> None:
        count = len(self._tabs)
        if not (0 <= from_index < count):
            return
        to_index = max(0, min(to_index, count - 1))
        if to_index == from_index:
            return
        tab = self._tabs.pop(from_index)
        self._tabs.insert(to_index, tab)
        if self._current_tab == from_index:
            self._current_tab = to_index
        elif from_index < self._current_tab <= to_index:
            self._current_tab -= 1
        elif to_index <= self._current_tab < from_index:
            self._current_tab += 1
        self.tabs_changed.emit()

    def current_webview(self) -> XWebView:
        return self._tabs[self._current_tab]

    def get_tab_count(self) -> int:
        return len(self._tabs)

    def export_tabs_state(self) -> dict:
        tabs_out = []
        for wv in list(self._tabs):
            url = ""
            try:
                getter = getattr(wv, "get_current_url", None)
                if callable(getter):
                    url = (getter() or "").strip()
                if not url and hasattr(wv, "url") and callable(wv.url):
                    u = wv.url()
                    url = (u.toString() if hasattr(u, "toString") else str(u) or "").strip()
            except Exception:
                url = ""
            if not url or url.startswith("about:") or url.startswith("data:"):
                url = (getattr(self, "_initial_url", None) or "") if not tabs_out else ""
            tabs_out.append({"url": url or ""})
        active = int(getattr(self, "_current_tab", 0) or 0)
        if tabs_out:
            active = max(0, min(active, len(tabs_out) - 1))
        else:
            active = 0
            tabs_out = [{"url": (self._initial_url or "").strip()}]
        return {"tabs": tabs_out, "active_tab": active}

    def get_current_tab_url(self) -> str:
        live = ""
        try:
            wv = self.current_webview()
            if wv is not None:
                getter = getattr(wv, "get_current_url", None)
                if callable(getter):
                    live = (getter() or "").strip()
                if not live and hasattr(wv, "url") and callable(wv.url):
                    try:
                        u = wv.url()
                        live = u.toString() if hasattr(u, "toString") else str(u)
                        live = (live or "").strip()
                    except Exception:
                        live = ""
        except Exception:
            live = ""
        if live and live not in ("about:blank", "data:"):
            self._current_web_url = live
            return live
        cur = (self._current_web_url or "").strip()
        if cur:
            return cur
        return (self._initial_url or "").strip()

    def tab_views(self) -> list:
        return list(self._tabs)

    def tab_count(self) -> int:
        return len(self._tabs)

    def webviews(self) -> list[XWebView]:
        return list(self._tabs)

    def navigate(self, url: str) -> None:
        if self._enabled:
            self.current_webview().load_url(url)

    def _on_col_grip_pressed(self) -> None:
        self.activated.emit()
        self._drag_armed = False

    def _on_col_grip_moved(self, global_x: float) -> None:
        if not self._drag_armed:
            self._drag_armed = True
            self._arm_drag()
        try:
            self.reorder_drag_moved.emit(float(global_x))
        except Exception:
            pass

    def _on_col_grip_released(self, global_x: float) -> None:
        if not self._drag_armed:
            return
        try:
            self.reorder_requested.emit(float(global_x))
        except Exception:
            pass
        self._disarm_drag(emit_finished=False)
        try:
            self.reorder_drag_finished.emit()
        except Exception:
            pass

    def _on_col_grip_cancelled(self) -> None:
        was = self._drag_armed
        self._disarm_drag(emit_finished=False)
        if was:
            try:
                self.reorder_drag_finished.emit()
            except Exception:
                pass

    def _arm_drag(self) -> None:
        self._drag_armed = True
        handle = getattr(self, "_col_drag_handle", None)
        if handle is not None:
            handle.setCursor(Qt.CursorShape.SizeAllCursor)
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            if getattr(self, "_reorder_opacity_effect", None) is None:
                eff = QGraphicsOpacityEffect(self)
                self._reorder_opacity_effect = eff
                self.setGraphicsEffect(eff)
            self._reorder_opacity_effect.setOpacity(0.85)
        except Exception:
            pass
        try:
            self._reorder_prev_stylesheet = self.styleSheet() or ""
            self.setStyleSheet(
                (self._reorder_prev_stylesheet + "\n" if self._reorder_prev_stylesheet else "")
                + "AccountColumn { border: 2px solid #1d9bf0; border-radius: 6px; background-color: rgba(29,155,240,0.06); }"
            )
        except Exception:
            self._reorder_prev_stylesheet = ""

    def _disarm_drag(self, emit_finished: bool = True) -> None:
        was_armed = self._drag_armed
        self._drag_armed = False
        self._drag_timer.stop()
        handle = getattr(self, "_col_drag_handle", None)
        if handle is not None:
            try:
                if handle.mouseGrabber() is handle:
                    handle.releaseMouse()
            except Exception:
                try:
                    handle.releaseMouse()
                except Exception:
                    pass
            handle.setCursor(Qt.CursorShape.SizeAllCursor)
        try:
            if getattr(self, "_reorder_opacity_effect", None) is not None:
                self._reorder_opacity_effect.setOpacity(1.0)
                self.setGraphicsEffect(None)
                self._reorder_opacity_effect = None
        except Exception:
            pass
        try:
            prev = getattr(self, "_reorder_prev_stylesheet", None)
            if prev is not None:
                self.setStyleSheet(prev)
                self._reorder_prev_stylesheet = None
        except Exception:
            pass
        if was_armed and emit_finished:
            try:
                self.reorder_drag_finished.emit()
            except Exception:
                pass

    def eventFilter(self, obj, event: QEvent) -> bool:
        if not self.is_individually_stowed():
            return False
        win = self.window()
        if win is not None and getattr(win, "_boundary_dragging", False):
            return False
        btn = getattr(self, "_stowed_restore_btn", None)
        h = getattr(self, "_resize_handle", None)
        et = event.type()
        if btn is not None and obj is btn:
            if et == QEvent.Type.Leave:
                QTimer.singleShot(0, self._maybe_release_stowed_hover)
            elif et == QEvent.Type.Enter:
                self._hide_other_stowed_restore_btns()
                self._show_stowed_restore_btn()
                self._show_stowed_name_label()
            return False
        if h is not None and obj is h:
            # 収納スロット全体がハンドル → 個別展開↔を中継
            # 共有UIはハンドル enterEvent の _ensure_stowed_shared_ui
            if et == QEvent.Type.Enter:
                self._hide_other_stowed_restore_btns()
                self._show_stowed_restore_btn()
                self._show_stowed_name_label()
            elif et == QEvent.Type.Leave:
                QTimer.singleShot(0, self._maybe_release_stowed_hover)
            return False
        return False

    def _position_resize_handles(self) -> None:
        h = self._resize_handle
        if not h.isVisible():
            return
        if self.is_individually_stowed():
            # 太い収納領域全体 = resize 可能 → SizeHor（カーソル判定 = resize 判定）
            w = max(1, int(self.width()) or self.STOWED_WIDTH)
            h.setFixedWidth(w)
            h.setGeometry(0, 0, w, max(1, int(self.height())))
            h.setCursor(Qt.CursorShape.SizeHorCursor)
            h._position_bar()
            h.raise_()
            return
        # 通常境界: visual / resize / cursor はすべて 2px ハンドル
        h.setFixedWidth(self.RESIZE_HANDLE_WIDTH)
        h.setCursor(Qt.CursorShape.SizeHorCursor)
        h._position_bar()
        self._position_shared_ui_hover_strip()

    def _position_shared_ui_hover_strip(self) -> None:
        """共有UI用の透明帯を 2px 境界中心に配置（描画なし・resize ではない）。"""
        strip = getattr(self, "_shared_ui_hover_strip", None)
        h = getattr(self, "_resize_handle", None)
        body = getattr(self, "_body", None)
        if strip is None or h is None or body is None:
            return
        if self.is_individually_stowed() or not h.isVisible():
            strip.hide()
            return
        try:
            hg = h.geometry()
            cx = int(hg.x() + hg.width() / 2)
            w = int(_SharedUiHoverStrip.WIDTH)
            strip.setGeometry(
                max(0, cx - w // 2),
                0,
                w,
                max(1, int(body.height())),
            )
            strip.show()
            strip.raise_()
            h.raise_()
        except Exception:
            pass

    def set_boundary_enabled(self, enabled: bool) -> None:
        h = self._resize_handle
        strip = getattr(self, "_shared_ui_hover_strip", None)
        if self.is_individually_stowed():
            if strip is not None:
                strip.hide()
            if enabled:
                if h.parentWidget() is not self:
                    body = getattr(self, "_body", None)
                    if body is not None:
                        lay = body.layout()
                        if lay is not None:
                            lay.removeWidget(h)
                    h.setParent(self)
                h.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                h.installEventFilter(self)
                h.show()
                self._position_resize_handles()
            else:
                h.hide()
            return
        body = getattr(self, "_body", None)
        if body is not None and h.parentWidget() is not body:
            h.setParent(body)
            lay = body.layout()
            if lay is not None:
                lay.addWidget(h, 0)
        h.setVisible(enabled)
        if strip is not None:
            if not enabled:
                strip.hide()
        if enabled:
            h.setFixedWidth(self.RESIZE_HANDLE_WIDTH)
            h.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            if body is not None:
                lay = body.layout()
                if lay is not None:
                    lay.activate()
            self._position_resize_handles()

    def _toggle_enabled(self) -> None:
        self._enabled = not self._enabled
        self._maybe_load_initial()
        self.enabled_changed.emit(self._enabled)

    def _maybe_load_initial(self) -> None:
        if not self._enabled or self._loaded_once:
            return
        if self._column_type == "profile":
            self._bootstrap_profile()
            return
        if self._column_type == "lists":
            self._bootstrap_lists()
            return
        if self._initial_url:
            self._webview.load_url(self._initial_url)

    def _on_lists_home_for_retry(self, ok: bool = True) -> None:
        if not getattr(self, "_lists_retry_after_home", False):
            return
        self._lists_retry_after_home = False
        try:
            wv = self.current_webview()
            if wv is not None:
                wv.loadFinished.disconnect(self._on_lists_home_for_retry)
        except Exception:
            pass
        if getattr(self, "_nav_target_lock", "") == "lists" and self._profile_state == "RESOLVED":
            return
        self._session_resolve_target = "lists"
        self._profile_resolve_attempted = False
        self._lists_cookie_retry_phase = True
        self._profile_resolve_retries = 0
        started = False
        try:
            started = bool(self._try_resolve_profile_from_cookies())
        except Exception:
            started = False
        QTimer.singleShot(800, lambda: self._try_resolve_profile_from_session(force=False))
        QTimer.singleShot(2000, lambda: self._try_resolve_profile_from_session(force=False))
        if not started:
            QTimer.singleShot(3500, self._lists_session_resolve_timeout)

    def _lists_cookie_retry_timeout(self) -> None:
        if self._profile_state == "RESOLVED":
            return
        if getattr(self, "_profile_waiting_self_redirect", False):
            return
        if self._profile_state == "RESOLVING":
            return

    def _lists_session_resolve_timeout(self) -> None:
        if self._profile_state == "RESOLVED":
            return
        if getattr(self, "_profile_waiting_self_redirect", False):
            return
        if self._profile_state != "FAILED":
            self._lists_show_failed_hub()

    def _lists_show_failed_hub(self) -> None:
        self._profile_resolve_attempted = True
        self._profile_state = "FAILED"
        self._profile_waiting_self_redirect = False
        try:
            self._url_bar.setText("現在のリストを確認できませんでした")
            self._url_bar.setToolTip(
                "ログイン中のXアカウントから本人のリストURLを解決できませんでした"
            )
        except Exception:
            pass

    def _bootstrap_lists(self) -> None:
        if getattr(self, "_lists_bootstrap_started", False):
            return
        if getattr(self, "_profile_resolve_attempted", False) and self._profile_state in ("RESOLVED", "FAILED"):
            return
        self._lists_bootstrap_started = True
        self._lists_home_attempted = False
        existing = (self._initial_url or "").strip()
        if existing.startswith("http") and "/lists" in existing and "/i/lists" not in existing:
            try:
                self._url_bar.setText(existing)
                self._url_bar.setToolTip(existing)
            except Exception:
                pass
            self._webview.load_url(existing)
            self._profile_resolve_attempted = True
            self._profile_state = "RESOLVED"
            self._nav_target_lock = "lists"
            self._lists_resolved_url = existing
            return

        self._profile_state = "RESOLVING"
        rid = self._begin_resolve_request("lists")
        self._lists_resolve_request_id = rid
        try:
            self._url_bar.setText("リストを取得中…")
            self._url_bar.setToolTip("ログイン中のXアカウントからリストを取得しています")
        except Exception:
            pass

        if self._try_resolve_profile_from_cookies():
            return

        if not getattr(self, "_lists_home_attempted", False):
            self._lists_home_attempted = True
            self._lists_retry_after_home = True
            self._profile_resolve_attempted = True
            try:
                wv = self.current_webview()
                if wv is not None:
                    wv.loadFinished.connect(self._on_lists_home_for_retry)
            except Exception:
                pass
            self._webview.load_url("https://x.com/home")
            QTimer.singleShot(2500, self._lists_cookie_retry_timeout)
            return
        self._lists_show_failed_hub()

    def _bootstrap_profile(self) -> None:
        if getattr(self, "_profile_resolve_attempted", False):
            return
        existing = (self._initial_url or "").strip()
        if existing.startswith("http") and not self._is_session_bootstrap_url(existing):
            try:
                self._url_bar.setText(existing)
                self._url_bar.setToolTip(existing)
            except Exception:
                pass
            self._webview.load_url(existing)
            self._profile_resolve_attempted = True
            self._profile_state = "RESOLVED"
            return

        self._profile_state = "RESOLVING"
        rid = self._begin_resolve_request("profile")
        self._profile_resolve_request_id = rid
        try:
            self._url_bar.setText("プロフィールを取得中…")
            self._url_bar.setToolTip("ログイン中のXアカウントからプロフィールを取得しています")
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(
                    f"[PROFILE] bootstrap column={getattr(self, '_column_id', '')} "
                    f"current={self._current_web_url!r}",
                    flush=True,
                )
        except Exception:
            pass

        if self._try_resolve_profile_from_cookies():
            return

        current = (self._current_web_url or "").strip()
        if current and ("x.com" in current or "twitter.com" in current) and "/login" not in current.lower():
            self._schedule_profile_resolve()
            return
        self._webview.load_url("https://x.com/home")
        self._schedule_profile_resolve()

    def _try_resolve_profile_from_cookies(self) -> bool:
        wv = self.current_webview()
        if wv is None:
            return False
        try:
            profile = wv.page().profile() if hasattr(wv, "page") else None
        except Exception:
            profile = None
        if profile is None:
            return False
        try:
            store = profile.cookieStore()
        except Exception:
            return False

        self._profile_cookie_uids: list[str] = []
        self._profile_cookie_done = False

        def _on_cookie(cookie) -> None:
            try:
                name = bytes(cookie.name()).decode("utf-8", "ignore")
                if name != "twid":
                    return
                val = bytes(cookie.value()).decode("utf-8", "ignore")
                from urllib.parse import unquote
                raw = unquote(val)
                uid = ""
                if raw.startswith("u=") and raw[2:].isdigit():
                    uid = raw[2:]
                else:
                    import re as _re
                    m = _re.search(r"(\d{5,})", raw)
                    if m:
                        uid = m.group(1)
                if uid and uid not in self._profile_cookie_uids:
                    self._profile_cookie_uids.append(uid)
                    try:
                        import os
                        if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                            print(f"[PROFILE] twid uid={uid}", flush=True)
                    except Exception:
                        pass
            except Exception:
                pass

        def _on_cookies_finished(final: bool = False) -> None:
            if self._profile_cookie_done:
                return
            uids = list(getattr(self, "_profile_cookie_uids", []) or [])
            if not uids and not final:
                return
            self._profile_cookie_done = True
            try:
                store.cookieAdded.disconnect(_on_cookie)
            except Exception:
                pass
            if not uids:
                try:
                    import os
                    if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                        print("[PROFILE] no twid cookie — fall back", flush=True)
                except Exception:
                    pass
                target = getattr(self, "_session_resolve_target", "profile")
                if target == "lists":
                    if getattr(self, "_lists_home_attempted", False):
                        self._lists_show_failed_hub()
                        return
                    self._lists_home_attempted = True
                    self._lists_retry_after_home = True
                    self._profile_resolve_attempted = True
                    try:
                        wv.loadFinished.connect(self._on_lists_home_for_retry)
                    except Exception:
                        pass
                    self._webview.load_url("https://x.com/home")
                    QTimer.singleShot(2500, self._lists_cookie_retry_timeout)
                    return
                self._profile_resolve_attempted = False
                current = (self._current_web_url or "").strip()
                if current and ("x.com" in current or "twitter.com" in current):
                    self._schedule_profile_resolve()
                else:
                    self._webview.load_url("https://x.com/home")
                    self._schedule_profile_resolve()
                return
            uid = uids[0]
            if getattr(self, "_nav_target_lock", "") == "lists" or (
                self._profile_state == "RESOLVED" and self._column_type == "lists"
            ):
                try:
                    import os
                    if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                        print("[LISTS] skip /i/user — already lists-locked", flush=True)
                except Exception:
                    pass
                return
            self_url = f"https://x.com/i/user/{uid}"
            self._profile_resolve_attempted = True
            self._profile_waiting_self_redirect = True
            self._cookie_resolve_request_id = int(
                getattr(self, "_resolve_request_id", 0) or 0
            )
            try:
                try:
                    wv.url_changed.disconnect(self._on_profile_self_redirect)
                except Exception:
                    pass
                wv.url_changed.connect(self._on_profile_self_redirect)
            except Exception:
                pass
            try:
                target = getattr(self, "_session_resolve_target", "profile")
                self._url_bar.setText(
                    "リストを取得中…" if target == "lists" else "プロフィールを取得中…"
                )
            except Exception:
                pass
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(f"[PROFILE] load self_url={self_url}", flush=True)
            except Exception:
                pass
            wv.load_url(self_url)

        try:
            store.cookieAdded.connect(_on_cookie)
            store.loadAllCookies()
            QTimer.singleShot(500, lambda: _on_cookies_finished(False))
            QTimer.singleShot(1600, lambda: _on_cookies_finished(True))
            return True
        except Exception:
            return False

    def _on_profile_self_redirect(self, url: str) -> None:
        if not getattr(self, "_profile_waiting_self_redirect", False):
            return
        rid = int(getattr(self, "_cookie_resolve_request_id", 0) or 0)
        target = getattr(self, "_session_resolve_target", None) or self._column_type
        if not self._resolve_request_alive(rid, target):
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(
                        f"[RESOLVE] ignore stale redirect id={rid} "
                        f"current={self._resolve_request_id} target={target} url={url!r}",
                        flush=True,
                    )
            except Exception:
                pass
            return
        if getattr(self, "_nav_target_lock", "") == "lists":
            return
        if self._profile_state == "RESOLVED" and self._column_type == "lists":
            return
        u = (url or "").strip()
        if not u.startswith("http"):
            return
        if self._is_session_bootstrap_url(u):
            return
        if "/i/user/" in u:
            return
        self._profile_waiting_self_redirect = False
        try:
            wv = self.current_webview()
            if wv is not None and hasattr(wv, "url_changed"):
                wv.url_changed.disconnect(self._on_profile_self_redirect)
        except Exception:
            pass

        final = u
        if target == "lists" or self._column_type == "lists":
            if self._is_user_lists_url(u):
                self._apply_resolved_lists_url(u, request_id=rid)
                return
            if not self._is_canonical_profile_url(u):
                try:
                    import os
                    if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                        print(f"[LISTS] reject non-profile redirect url={u!r}", flush=True)
                except Exception:
                    pass
                self._lists_show_failed_hub()
                return
            self._apply_resolved_lists_url(u.rstrip("/") + "/lists", request_id=rid)
            return

        if self._column_type != "profile":
            return
        self._profile_state = "RESOLVED"
        self._nav_target_lock = "profile"
        self._initial_url = final
        self._current_web_url = final
        try:
            self._url_bar.setText(final)
            self._url_bar.setToolTip(final)
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(f"[PROFILE] resolved via cookie/redirect url={final} target={target}", flush=True)
        except Exception:
            pass
        self._schedule_history_clear_when_on(final, rid)

    def _clear_profile_bootstrap_history(self) -> None:
        try:
            wv = self.current_webview()
            if wv is None:
                return
            page = wv.page() if hasattr(wv, "page") else None
            if page is None:
                return
            hist = page.history() if hasattr(page, "history") else None
            if hist is None:
                return
            hist.clear()
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print("[PROFILE] history cleared after resolve", flush=True)
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _normalize_nav_url(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        try:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(u)
            path = (parts.path or "").rstrip("/") or ""
            return urlunsplit((parts.scheme.lower(), (parts.netloc or "").lower(), path, "", "")).rstrip("/")
        except Exception:
            return u.rstrip("/").split("?")[0].split("#")[0].lower()

    def _begin_resolve_request(self, target: str) -> int:
        self._resolve_request_id = int(getattr(self, "_resolve_request_id", 0) or 0) + 1
        self._session_resolve_target = target
        self._nav_target_lock = ""
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(
                    f"[RESOLVE] begin id={self._resolve_request_id} "
                    f"column={getattr(self, '_column_id', '')} target={target}",
                    flush=True,
                )
        except Exception:
            pass
        return self._resolve_request_id

    def _resolve_request_alive(self, request_id: int, target: str | None = None) -> bool:
        if int(request_id) != int(getattr(self, "_resolve_request_id", 0) or 0):
            return False
        if self._profile_state == "RESOLVED":
            lock = getattr(self, "_nav_target_lock", "") or ""
            if target and lock and target != lock:
                return False
            if lock == "lists" and target == "profile":
                return False
        if target is not None:
            cur = getattr(self, "_session_resolve_target", "") or self._column_type
            if cur and target != cur and target != self._column_type:
                return False
        return True

    def _schedule_history_clear_when_on(self, expected_url: str, request_id: int) -> None:
        expected = self._normalize_nav_url(expected_url)

        def _try_clear(attempt: int = 0) -> None:
            if not self._resolve_request_alive(request_id):
                return
            cur = (self._current_web_url or "").strip()
            try:
                wv = self.current_webview()
                if wv is not None and hasattr(wv, "url") and callable(wv.url):
                    cur = wv.url().toString() or cur
            except Exception:
                pass
            if self._normalize_nav_url(cur) == expected:
                self._clear_profile_bootstrap_history()
                return
            if attempt < 8:
                QTimer.singleShot(250, lambda: _try_clear(attempt + 1))

        QTimer.singleShot(300, lambda: _try_clear(0))

    def _apply_resolved_lists_url(self, final: str, request_id: int | None = None) -> None:
        final = (final or "").strip()
        if not final.startswith("http") or "/i/lists" in final:
            self._lists_show_failed_hub()
            return
        if request_id is not None and not self._resolve_request_alive(int(request_id), "lists"):
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(f"[LISTS] skip stale apply id={request_id} url={final}", flush=True)
            except Exception:
                pass
            return
        if self._is_canonical_profile_url(final) and not self._is_user_lists_url(final):
            final = final.rstrip("/") + "/lists"
        if not self._is_user_lists_url(final):
            self._lists_show_failed_hub()
            return
        norm_final = self._normalize_nav_url(final)
        if self._profile_state == "RESOLVED" and getattr(self, "_nav_target_lock", "") == "lists":
            if self._normalize_nav_url(getattr(self, "_lists_resolved_url", "") or self._initial_url or "") == norm_final:
                return
            if self._is_user_lists_url(getattr(self, "_lists_resolved_url", "") or ""):
                return

        already_there = False
        try:
            candidates = []
            cur = (self._current_web_url or "").strip()
            if cur:
                candidates.append(cur)
            wv0 = self.current_webview()
            if wv0 is not None:
                try:
                    if hasattr(wv0, "url") and callable(wv0.url):
                        candidates.append(wv0.url().toString() or "")
                except Exception:
                    pass
                try:
                    if hasattr(wv0, "get_current_url"):
                        candidates.append(wv0.get_current_url() or "")
                except Exception:
                    pass
            for c in candidates:
                if c and self._normalize_nav_url(c) == norm_final:
                    already_there = True
                    break
        except Exception:
            already_there = False

        self._profile_state = "RESOLVED"
        self._nav_target_lock = "lists"
        self._session_resolve_target = "lists"
        self._profile_resolve_attempted = True
        self._profile_waiting_self_redirect = False
        self._lists_bootstrap_started = True
        self._lists_resolved_url = final
        self._initial_url = final
        self._current_web_url = final
        self._cookie_resolve_request_id = -1
        try:
            wv = self.current_webview()
            if wv is not None and hasattr(wv, "url_changed"):
                try:
                    wv.url_changed.disconnect(self._on_profile_self_redirect)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._url_bar.setText(final)
            self._url_bar.setToolTip(final)
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(
                    f"[LISTS] resolved url={final} already_there={already_there} "
                    f"lock=lists id={getattr(self, '_resolve_request_id', 0)}",
                    flush=True,
                )
        except Exception:
            pass
        if already_there:
            QTimer.singleShot(200, self._clear_profile_bootstrap_history)
            return
        try:
            wv = self.current_webview()
            if wv is not None:
                wv.load_url(final)
        except Exception:
            pass
        QTimer.singleShot(400, self._clear_profile_bootstrap_history)

    @staticmethod
    def _is_user_lists_url(url: str) -> bool:
        u = (url or "").strip()
        if not u.startswith("http") or "/i/lists" in u:
            return False
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(u)
        except Exception:
            return False
        host = (parts.hostname or "").lower()
        if host not in ("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            return False
        segs = [s for s in (parts.path or "").strip("/").split("/") if s]
        if len(segs) != 2 or segs[1].lower() != "lists":
            return False
        handle = segs[0].lower()
        reserved = {
            "home", "explore", "search", "notifications", "messages", "i",
            "settings", "compose", "login", "logout", "signup", "intent",
            "hashtag", "share", "tos", "privacy",
        }
        return handle not in reserved

    @staticmethod
    def _is_session_bootstrap_url(url: str) -> bool:
        u = (url or "").strip().rstrip("/").lower()
        if not u:
            return True
        if u in ("https://x.com", "https://twitter.com", "http://x.com", "http://twitter.com"):
            return True
        if u.endswith("/home") or "/home?" in (url or "").lower():
            return True
        if "/settings/" in u or "/i/flow/" in u or "/login" in u or "/i/user/" in u:
            return True
        if u.endswith("/i/lists") or "/i/lists?" in u or u.endswith("/i/lists/"):
            return True
        if "/status/" in u:
            return True
        return False

    @staticmethod
    def _is_canonical_profile_url(url: str) -> bool:
        u = (url or "").strip()
        if not u.startswith("http"):
            return False
        if AccountColumn._is_session_bootstrap_url(u):
            return False
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(u)
        except Exception:
            return False
        host = (parts.hostname or "").lower()
        if host not in ("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            return False
        path = (parts.path or "").strip("/")
        if not path:
            return False
        segs = [s for s in path.split("/") if s]
        if len(segs) != 1:
            return False
        handle = segs[0].lower()
        reserved = {
            "home", "explore", "search", "notifications", "messages", "i",
            "settings", "compose", "login", "logout", "signup", "intent",
            "hashtag", "share", "tos", "privacy",
        }
        if handle in reserved:
            return False
        return True

    def _schedule_profile_resolve(self) -> None:
        if getattr(self, "_profile_resolve_attempted", False) and self._profile_resolve_retries > 0:
            return
        self._profile_resolve_attempted = True
        wv = self.current_webview()
        if wv is not None and hasattr(wv, "loadFinished"):
            try:
                wv.loadFinished.connect(self._on_profile_bootstrap_load_finished)
            except Exception:
                pass
        QTimer.singleShot(1200, lambda: self._try_resolve_profile_from_session(force=False))

    def _on_profile_bootstrap_load_finished(self, ok: bool) -> None:
        wv = self.current_webview()
        if wv is not None and hasattr(wv, "loadFinished"):
            try:
                wv.loadFinished.disconnect(self._on_profile_bootstrap_load_finished)
            except Exception:
                pass
        if self._column_type != "profile":
            return
        QTimer.singleShot(600, lambda: self._try_resolve_profile_from_session(force=False))

    def _try_resolve_profile_from_session(self, force: bool = False) -> None:
        if self._column_type not in ("profile", "lists"):
            return
        if self._profile_state == "RESOLVED":
            return
        if self._column_type == "lists" and getattr(self, "_lists_resolved_url", ""):
            return
        cur = (self._current_web_url or self._initial_url or "").strip()
        if cur.startswith("http") and not self._is_session_bootstrap_url(cur):
            if self._column_type == "lists":
                if self._is_canonical_profile_url(cur):
                    final = cur.rstrip("/") + "/lists"
                    self._apply_resolved_lists_url(final)
                    return
                if "/lists" in cur and "/i/lists" not in cur and self._is_user_lists_url(cur):
                    self._apply_resolved_lists_url(cur)
                    return
            else:
                try:
                    self._url_bar.setText(cur)
                    self._url_bar.setToolTip(cur)
                except Exception:
                    pass
                self._profile_state = "RESOLVED"
                return
        wv = self.current_webview()
        if wv is None:
            self._set_profile_failed("FAILED")
            return
        try:
            eng = wv.page() if hasattr(wv, "page") else None
        except Exception:
            eng = None
        if eng is None:
            self._set_profile_failed("FAILED")
            return
        js = r"""
        (function() {
          function clean(h) {
            if (!h) return '';
            try { h = String(h); } catch (e) { return ''; }
            h = h.split('?')[0].split('#')[0];
            return h;
          }
          function absHref(node) {
            if (!node) return '';
            try {
              // Prefer DOM property (resolved absolute URL) over attribute.
              var h = node.href || '';
              if (!h) h = node.getAttribute('href') || '';
              return clean(h);
            } catch (e) { return ''; }
          }
          function isReserved(pathUser) {
            var u = (pathUser || '').toLowerCase();
            var reserved = {
              home:1, explore:1, notifications:1, messages:1, i:1, settings:1,
              compose:1, search:1, login:1, logout:1, jobs:1, premium:1, tos:1,
              privacy:1, signup:1, intent:1, share:1, hashtag:1, following:1,
              followers:1, lists:1, bookmarks:1, communities:1, about:1,
              download:1, more:1, display:1, connect:1
            };
            return !!reserved[u];
          }
          function profileUrlFromHref(h) {
            h = clean(h);
            if (!h) return '';
            // Absolute
            var m = h.match(/^https?:\/\/(?:www\.)?(?:x|twitter)\.com\/@?([A-Za-z0-9_]{1,40})\/?$/i);
            if (m && !isReserved(m[1])) return 'https://x.com/' + m[1];
            // Site-relative
            m = h.match(/^\/@?([A-Za-z0-9_]{1,40})\/?$/i);
            if (m && !isReserved(m[1])) return 'https://x.com/' + m[1];
            return '';
          }
          function pack(status, url) {
            return JSON.stringify({status: status, url: url || ''});
          }
          try {
            var path = (location.pathname || '').toLowerCase();
            if (path.indexOf('/login') >= 0 || path.indexOf('/i/flow/login') >= 0) {
              return pack('not_logged_in');
            }

            var probes = [
              'a[data-testid="AppTabBar_Profile_Link"]',
              '[data-testid="AppTabBar_Profile_Link"]',
              '[data-testid="AppTabBar_Profile_Link"] a',
              'a[data-testid="AppTabBar_Profile_Link"][href]',
              'a[aria-label="Profile"]',
              'a[aria-label="プロフィール"]',
              'a[aria-label*="Profile"][href]',
              'a[aria-label*="プロフィール"][href]'
            ];
            for (var i = 0; i < probes.length; i++) {
              var n = document.querySelector(probes[i]);
              if (!n) continue;
              // element itself may be the anchor or a wrapper
              var candidates = [n];
              if (n.tagName !== 'A') {
                var inner = n.querySelector('a[href]');
                if (inner) candidates.push(inner);
                if (n.closest) {
                  var outer = n.closest('a[href]');
                  if (outer) candidates.push(outer);
                }
              }
              for (var c = 0; c < candidates.length; c++) {
                var pu = profileUrlFromHref(absHref(candidates[c]));
                if (pu) return pack('ok', pu);
              }
            }

            // Explicit user Lists links: /{handle}/lists (never /i/lists)
            function listsUrlFromHref(h) {
              h = clean(h);
              if (!h) return '';
              var m = h.match(/^https?:\/\/(?:www\.)?(?:x|twitter)\.com\/@?([A-Za-z0-9_]{1,40})\/lists\/?$/i);
              if (m && !isReserved(m[1])) return 'https://x.com/' + m[1] + '/lists';
              m = h.match(/^\/@?([A-Za-z0-9_]{1,40})\/lists\/?$/i);
              if (m && !isReserved(m[1])) return 'https://x.com/' + m[1] + '/lists';
              return '';
            }
            var allAnchors = document.querySelectorAll('a[href]');
            for (var li = 0; li < allAnchors.length; li++) {
              var lu = listsUrlFromHref(absHref(allAnchors[li]));
              if (lu) return pack('ok', lu);
            }

            // Account switcher button: only accept a real nested profile anchor href
            var switcher = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
            if (switcher) {
              var a = switcher.querySelector('a[href]');
              var pu2 = profileUrlFromHref(absHref(a));
              if (pu2) return pack('ok', pu2);
            }

            // Nav / header / bottom bar anchors with real href
            var roots = document.querySelectorAll(
              'nav a[href], header a[href], [role="navigation"] a[href], [data-testid="Sidebar"] a[href], [data-testid="BottomBar"] a[href], [data-testid="primaryColumn"] a[href]'
            );
            for (var j = 0; j < roots.length; j++) {
              var pu3 = profileUrlFromHref(absHref(roots[j]));
              if (pu3) return pack('ok', pu3);
            }

            // Logged-out login CTA without app chrome
            if (document.querySelector('a[href*="/login"]') || document.querySelector('[data-testid="login"]')) {
              var hasApp = document.querySelector(
                'a[data-testid="AppTabBar_Home_Link"], a[data-testid="AppTabBar_Profile_Link"], [data-testid="AppTabBar_Home_Link"]'
              );
              if (!hasApp) return pack('not_logged_in');
            }
          } catch (e) {
            return pack('failed');
          }
          return pack('failed');
        })();
        """

        def _done(result):
            status = "failed"
            url = ""
            raw = result
            if isinstance(result, dict):
                status = str(result.get("status") or "failed")
                url = str(result.get("url") or "").strip()
            elif isinstance(result, str):
                s = result.strip()
                if s.startswith("{"):
                    try:
                        import json
                        obj = json.loads(s)
                        status = str(obj.get("status") or "failed")
                        url = str(obj.get("url") or "").strip()
                    except Exception:
                        if s.startswith("http"):
                            status, url = "ok", s
                elif s.startswith("http"):
                    status, url = "ok", s
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(f"[PROFILE] js_raw={raw!r} status={status} url={url!r}", flush=True)
            except Exception:
                pass

            if status == "ok" and url.startswith("http") and not self._is_session_bootstrap_url(url):
                if self._column_type == "lists":
                    if getattr(self, "_nav_target_lock", "") == "lists" and self._profile_state == "RESOLVED":
                        return
                    if not self._resolve_request_alive(js_request_id, "lists"):
                        return
                    if self._is_user_lists_url(url):
                        final = url
                    elif self._is_canonical_profile_url(url):
                        final = url.rstrip("/") + "/lists"
                    else:
                        final = ""
                    if final:
                        self._apply_resolved_lists_url(final, request_id=js_request_id)
                        return
                else:
                    if not self._resolve_request_alive(js_request_id, "profile"):
                        return
                    if getattr(self, "_nav_target_lock", "") == "lists":
                        return
                    self._profile_state = "RESOLVED"
                    self._nav_target_lock = "profile"
                    self._initial_url = url
                    try:
                        self._url_bar.setText(url)
                        self._url_bar.setToolTip(url)
                    except Exception:
                        pass
                    self._current_web_url = url
                    try:
                        wv.load_url(url)
                    except Exception:
                        pass
                    QTimer.singleShot(400, self._clear_profile_bootstrap_history)
                    return

            if status == "not_logged_in":
                if self._column_type == "lists":
                    self._lists_show_failed_hub()
                    try:
                        self._url_bar.setText("Xにログインしてください")
                    except Exception:
                        pass
                else:
                    self._set_profile_failed("NOT_LOGGED_IN")
                return

            self._profile_resolve_retries = getattr(self, "_profile_resolve_retries", 0) + 1
            max_retries = 8 if self._column_type == "lists" else 12
            if self._profile_resolve_retries < max_retries:
                QTimer.singleShot(600, lambda: self._try_resolve_profile_from_session(force=False))
            else:
                if self._column_type == "lists":
                    self._lists_show_failed_hub()
                else:
                    self._set_profile_failed("FAILED")

        js_request_id = int(getattr(self, "_resolve_request_id", 0) or 0)
        try:
            eng.runJavaScript(js, _done)
        except Exception:
            self._set_profile_failed("FAILED")

    def _set_profile_failed(self, state: str = "FAILED") -> None:
        self._profile_state = state
        if state == "NOT_LOGGED_IN":
            msg = "Xにログインしてください"
        else:
            msg = "現在のXアカウントを確認できませんでした"
        try:
            self._url_bar.setText(msg)
            self._url_bar.setToolTip(msg)
        except Exception:
            pass
        cur = (self._current_web_url or "").lower()
        if "/settings/" in cur:
            try:
                self.current_webview().load_url("https://x.com/home")
            except Exception:
                pass

    def _on_close(self) -> None:
        self.closed.emit()

    def _on_stow_self_clicked(self, _checked: bool = False) -> None:
        if self.is_individually_stowed():
            return
        # 最後の通常カラムは収納しない（MainWindow 側でも再チェック）
        win = self.window()
        cols = getattr(win, "_columns", None) if win is not None else None
        if cols:
            normals = 0
            for c in cols:
                try:
                    if c.isVisible() and not getattr(c, "is_individually_stowed", lambda: False)():
                        normals += 1
                except Exception:
                    pass
            if normals <= 1:
                return
        self.stow_self_requested.emit(self)

    def _on_restore_self_clicked(self, _checked: bool = False) -> None:
        if not self.is_individually_stowed():
            return
        self.restore_self_requested.emit(self)

    def is_individually_stowed(self) -> bool:
        return bool(getattr(self, "_individually_stowed", False))

    def set_individually_stowed(self, stowed: bool) -> None:
        stowed = bool(stowed)
        if stowed == bool(getattr(self, "_individually_stowed", False)):
            return
        self._individually_stowed = stowed
        if stowed:
            self._enter_individual_stow()
        else:
            self._exit_individual_stow()

    def _enter_individual_stow(self) -> None:
        # 復帰用幅。MainWindow が preferred を先に入れていればそれを優先する
        # （個別収納中の一時再配分幅で上書きしない）
        existing = int(getattr(self, "_width_before_individual_stow", 0) or 0)
        live = int(getattr(self, "_current_width", 0) or self.width() or 0)
        if existing >= self.MIN_WIDTH:
            self._width_before_individual_stow = existing
        else:
            self._width_before_individual_stow = max(self.MIN_WIDTH, live)
        # 中間状態を描画しない（全幅の暗い背景が一瞬出るのを防ぐ）
        self.setUpdatesEnabled(False)
        try:
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self.setStyleSheet("background-color: #141820;")
            except Exception:
                pass
            # 先にスロット幅へ固定してから中身を隠す
            # （先に hide すると全幅の暗い矩形が1フレーム描画される）
            self._current_width = self.STOWED_WIDTH
            self.setMinimumWidth(self.STOWED_WIDTH)
            self.setMaximumWidth(self.STOWED_WIDTH)
            self.setFixedWidth(self.STOWED_WIDTH)
            for tab in list(getattr(self, "_tabs", None) or []):
                try:
                    tab.hide()
                except Exception:
                    pass
            try:
                self._body.hide()
            except Exception:
                pass
            try:
                nf = getattr(self, "_nav_frame", None)
                if nf is not None:
                    nf.hide()
            except Exception:
                pass
            for w in (
                self._back_btn,
                self._forward_btn,
                self._reload_btn,
                self._home_btn,
                self._col_drag_handle,
                self._stow_btn,
                self._url_bar,
                self._close_btn,
            ):
                try:
                    w.hide()
                except Exception:
                    pass
            btn = getattr(self, "_stowed_restore_btn", None)
            if btn is None:
                btn = QToolButton(self)
                btn.setObjectName("stowed_restore_btn")
                btn.setIcon(make_expand_h_icon("#c5d0e6", 14))
                btn.setIconSize(QSize(14, 14))
                btn.setFixedSize(22, 22)
                # ネイティブ ToolTip「カラムを復帰」は不要（↔ボタン自体は維持）
                btn.setToolTip("")
                btn.setAutoRaise(False)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(self._on_restore_self_clicked)
                btn.setStyleSheet(
                    "QToolButton#stowed_restore_btn {"
                    " background-color: #252b38;"
                    " border: 1px solid #3d465c;"
                    " border-radius: 11px;"
                    "}"
                    "QToolButton#stowed_restore_btn:hover {"
                    " background-color: #2a3348;"
                    " border: 1px solid #6a8ab8;"
                    "}"
                    "QToolButton#stowed_restore_btn:pressed {"
                    " background-color: #1a2740;"
                    "}"
                )
                btn.installEventFilter(self)
                self._stowed_restore_btn = btn
            btn.hide()
            self.setMouseTracking(True)
            self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.updateGeometry()
        finally:
            self.setUpdatesEnabled(True)

    def _exit_individual_stow(self) -> None:
        # 最終幅は MainWindow._fit_columns が決める。
        # body/WebView はまだ出さない（10px のまま show すると surface が一度小さいサイズで作られる）。
        self.setUpdatesEnabled(False)
        try:
            btn = getattr(self, "_stowed_restore_btn", None)
            if btn is not None:
                anim = getattr(self, "_stowed_restore_anim", None)
                if anim is not None:
                    try:
                        anim.stop()
                    except Exception:
                        pass
                btn.hide()
            try:
                self._hide_stowed_name_label_now()
            except Exception:
                pass
            self.setMinimumWidth(self.MIN_WIDTH)
            self.setMaximumWidth(16777215)
            try:
                self.setStyleSheet("")
            except Exception:
                pass
            try:
                nf = getattr(self, "_nav_frame", None)
                if nf is not None:
                    nf.show()
            except Exception:
                pass
            for wdg in (
                self._back_btn,
                self._forward_btn,
                self._reload_btn,
                self._home_btn,
                self._col_drag_handle,
                self._stow_btn,
                self._url_bar,
                self._close_btn,
            ):
                try:
                    wdg.show()
                except Exception:
                    pass
            self.updateGeometry()
        finally:
            self.setUpdatesEnabled(True)

    def reveal_after_restore(self) -> None:
        # fit で最終幅が付いたあとで body/WebView を出す
        try:
            self._body.show()
        except Exception:
            pass
        try:
            self._enforce_single_visible_tab()
        except Exception:
            try:
                idx = int(getattr(self, "_current_tab", 0) or 0)
                tabs = list(getattr(self, "_tabs", None) or [])
                for i, tab in enumerate(tabs):
                    if i == idx:
                        tab.show()
                    else:
                        tab.hide()
            except Exception:
                pass

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        win = self.window()
        if win is not None and getattr(win, "_boundary_dragging", False):
            return
        if self.is_individually_stowed():
            # 境界有効なら収納群全体が resize 可能 → SizeHor
            h = getattr(self, "_resize_handle", None)
            if h is not None and h.isVisible():
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                h.setCursor(Qt.CursorShape.SizeHorCursor)
            # 個別展開↔のみ（共有UIはハンドル側で領域単位管理）
            self._hide_other_stowed_restore_btns()
            self._show_stowed_restore_btn()
            self._show_stowed_name_label()

    def mouseMoveEvent(self, event) -> None:
        win = self.window()
        if win is not None and getattr(win, "_boundary_dragging", False):
            super().mouseMoveEvent(event)
            return
        if self.is_individually_stowed():
            h = getattr(self, "_resize_handle", None)
            if h is not None and h.isVisible():
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                h.setCursor(Qt.CursorShape.SizeHorCursor)
            # すでに表示中なら毎移動で再表示しない
            btn = getattr(self, "_stowed_restore_btn", None)
            if btn is None or not btn.isVisible():
                self._hide_other_stowed_restore_btns()
                self._show_stowed_restore_btn()
                self._show_stowed_name_label()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        # Widget 境界跨ぎで一瞬 Arrow にしない（ウィンドウ側で SizeHor 維持）
        win = self.window()
        sync = getattr(win, "_sync_column_resize_cursor", None) if win is not None else None
        if callable(sync):
            try:
                sync()
            except Exception:
                pass
        super().leaveEvent(event)
        if not self.is_individually_stowed():
            return
        if self._cursor_over_stowed_restore_btn() or self._cursor_over_stowed_column():
            QTimer.singleShot(0, self._maybe_release_stowed_hover)
            return
        self._fade_stowed_restore_btn(False)
        self._fade_stowed_name_label(False)
        QTimer.singleShot(0, self._maybe_release_stowed_hover)

    def _cursor_over_stowed_restore_btn(self) -> bool:
        btn = getattr(self, "_stowed_restore_btn", None)
        if btn is None or not btn.isVisible():
            return False
        try:
            from PySide6.QtGui import QCursor
            return btn.rect().contains(btn.mapFromGlobal(QCursor.pos()))
        except Exception:
            return False

    def _cursor_over_stowed_column(self) -> bool:
        try:
            from PySide6.QtGui import QCursor
            return self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        except Exception:
            return False

    def _left_normal_neighbor(self):
        win = self.window()
        cols = list(getattr(win, "_columns", None) or [])
        try:
            idx = cols.index(self)
        except ValueError:
            return None
        for j in range(idx - 1, -1, -1):
            c = cols[j]
            try:
                if not c.isVisible():
                    continue
                if getattr(c, "is_individually_stowed", lambda: False)():
                    continue
            except Exception:
                continue
            return c
        return None

    def _maybe_release_stowed_hover(self) -> None:
        if not self.is_individually_stowed():
            return
        if self._cursor_over_stowed_column() or self._cursor_over_stowed_restore_btn():
            return
        self._fade_stowed_restore_btn(False)
        self._fade_stowed_name_label(False)

    def _hide_stowed_restore_btn_now(self) -> None:
        btn = getattr(self, "_stowed_restore_btn", None)
        if btn is None:
            return
        anim = getattr(self, "_stowed_restore_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
        eff = getattr(self, "_stowed_restore_effect", None)
        if eff is not None:
            try:
                eff.setOpacity(0.0)
            except Exception:
                pass
        try:
            btn.hide()
        except Exception:
            pass

    def _hide_other_stowed_restore_btns(self) -> None:
        """他の個別収納の↔・名前を消す（自分だけ表示）。"""
        win = self.window()
        cols = getattr(win, "_columns", None) if win is not None else None
        if not cols:
            return
        for c in cols:
            if c is self:
                continue
            try:
                if not getattr(c, "is_individually_stowed", lambda: False)():
                    continue
                # 即 clear で A→B 移動時の重なり残留を防ぐ（fade は自分の leave で）
                c._hide_stowed_restore_btn_now()
                c._hide_stowed_name_label_now()
            except Exception:
                pass

    def _stowed_profile_label_text(self) -> str:
        name = ""
        try:
            name = (self.get_display_name() or "").strip()
        except Exception:
            name = ""
        if not name:
            try:
                name = (self.get_title() or "").strip()
            except Exception:
                name = ""
        if not name:
            name = (getattr(self, "_account_id", "") or "").strip() or "カラム"
        return name

    def _ensure_stowed_name_label(self):
        lbl = getattr(self, "_stowed_name_lbl", None)
        if lbl is not None:
            return lbl
        host = self.parentWidget() or self
        lbl = QLabel(host)
        lbl.setObjectName("stowed_name_hover_lbl")
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont(lbl.font())
        try:
            f.setPointSize(max(8, int(f.pointSize()) - 1))
        except Exception:
            pass
        lbl.setFont(f)
        # 黒文字禁止。既存 UI の淡いテキスト色に合わせる
        lbl.setStyleSheet(
            "QLabel#stowed_name_hover_lbl {"
            " color: #c5d0e6;"
            " background-color: rgba(18, 24, 36, 0.94);"
            " border: 1px solid #3d465c;"
            " border-radius: 6px;"
            " padding: 2px 7px;"
            "}"
        )
        eff = QGraphicsOpacityEffect(lbl)
        eff.setOpacity(0.0)
        lbl.setGraphicsEffect(eff)
        self._stowed_name_effect = eff
        anim = QVariantAnimation(self)
        anim.setDuration(140)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_stowed_name_anim_value)
        anim.finished.connect(self._on_stowed_name_anim_finished)
        self._stowed_name_anim = anim
        self._stowed_name_lbl = lbl
        self._stowed_name_base_pos = QPoint(0, 0)
        lbl.hide()
        return lbl

    def _on_stowed_name_anim_value(self, value) -> None:
        try:
            t = float(value)
        except (TypeError, ValueError):
            t = 0.0
        eff = getattr(self, "_stowed_name_effect", None)
        if eff is not None:
            try:
                eff.setOpacity(max(0.0, min(1.0, t)))
            except Exception:
                pass
        lbl = getattr(self, "_stowed_name_lbl", None)
        base = getattr(self, "_stowed_name_base_pos", None)
        if lbl is not None and base is not None:
            # わずかな浮上: 開始は +4px 下、t=1 で base
            lift = int(round(4 * (1.0 - t)))
            try:
                lbl.move(base.x(), base.y() + lift)
            except Exception:
                pass

    def _on_stowed_name_anim_finished(self) -> None:
        lbl = getattr(self, "_stowed_name_lbl", None)
        eff = getattr(self, "_stowed_name_effect", None)
        if lbl is None or eff is None:
            return
        try:
            if float(eff.opacity()) < 0.05:
                lbl.hide()
        except Exception:
            pass

    def _place_stowed_name_label(self) -> None:
        """個別収納 geometry 基準で固定配置（cursor 座標には追従しない）。"""
        lbl = self._ensure_stowed_name_label()
        host = lbl.parentWidget() or self.parentWidget() or self
        if lbl.parentWidget() is not host:
            lbl.setParent(host)
        raw = self._stowed_profile_label_text()
        fm = QFontMetrics(lbl.font())
        max_w = 120
        elided = fm.elidedText(raw, Qt.TextElideMode.ElideRight, max_w)
        lbl.setText(elided)
        tw = min(max_w + 14, fm.horizontalAdvance(elided) + 16)
        th = max(18, fm.height() + 6)
        lbl.setFixedSize(tw, th)
        # カラム中心 X・上寄り固定 Y（カーソル Y は使わない）
        top_left = self.mapTo(host, QPoint(0, 0))
        x = int(top_left.x() + (self.width() - tw) / 2)
        y = int(top_left.y() + max(8, (self.height() // 2) - th - 28))
        try:
            x = max(2, min(x, max(2, host.width() - tw - 2)))
            y = max(2, min(y, max(2, host.height() - th - 2)))
        except Exception:
            pass
        self._stowed_name_base_pos = QPoint(x, y)
        # 既に表示中なら位置を動かさない（mouseMove での再配置を防ぐ）
        try:
            eff = getattr(self, "_stowed_name_effect", None)
            if eff is not None and float(eff.opacity()) > 0.15 and lbl.isVisible():
                return
        except Exception:
            pass
        lbl.move(x, y + 4)

    def _fade_stowed_name_label(self, show: bool) -> None:
        """プロフィール名の fade-in / fade-out。現在 opacity から目標へ遷移。"""
        if show and not self.is_individually_stowed():
            return
        lbl = self._ensure_stowed_name_label()
        anim = self._stowed_name_anim
        eff = self._stowed_name_effect
        if show:
            self._place_stowed_name_label()
            lbl.show()
            lbl.raise_()
            win = self.window()
            cols = getattr(win, "_columns", None) if win is not None else None
            if cols:
                for c in cols:
                    if c is self:
                        continue
                    try:
                        c._hide_stowed_name_label_now()
                    except Exception:
                        pass
        try:
            cur = float(eff.opacity())
        except Exception:
            cur = 0.0
        target = 1.0 if show else 0.0
        if abs(cur - target) < 0.02:
            try:
                eff.setOpacity(target)
            except Exception:
                pass
            if not show:
                try:
                    lbl.hide()
                except Exception:
                    pass
            return
        # 途中の opacity から再開（半透明で止まらない）
        anim.stop()
        anim.setStartValue(cur)
        anim.setEndValue(target)
        anim.start()

    def _show_stowed_name_label(self) -> None:
        # 既に表示中なら再配置・再アニメしない（位置固定・点滅防止）
        try:
            eff = getattr(self, "_stowed_name_effect", None)
            if (
                eff is not None
                and float(eff.opacity()) > 0.95
                and getattr(self, "_stowed_name_lbl", None) is not None
                and self._stowed_name_lbl.isVisible()
            ):
                return
        except Exception:
            pass
        self._fade_stowed_name_label(True)

    def _hide_stowed_name_label_now(self) -> None:
        """プロフィール名 hover を即座に非表示（グループ切替時の残留防止）。"""
        lbl = getattr(self, "_stowed_name_lbl", None)
        if lbl is None:
            return
        anim = getattr(self, "_stowed_name_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
        eff = getattr(self, "_stowed_name_effect", None)
        if eff is not None:
            try:
                eff.setOpacity(0.0)
            except Exception:
                pass
        try:
            lbl.hide()
        except Exception:
            pass

    def _ensure_stowed_restore_anim(self) -> None:
        btn = getattr(self, "_stowed_restore_btn", None)
        if btn is None:
            return
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        if getattr(self, "_stowed_restore_effect", None) is None:
            eff = QGraphicsOpacityEffect(btn)
            eff.setOpacity(0.0)
            btn.setGraphicsEffect(eff)
            self._stowed_restore_effect = eff
        if getattr(self, "_stowed_restore_anim", None) is None:
            anim = QVariantAnimation(self)
            anim.setDuration(180)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(self._on_stowed_restore_opacity)
            anim.finished.connect(self._on_stowed_restore_anim_finished)
            self._stowed_restore_anim = anim

    def _on_stowed_restore_opacity(self, value) -> None:
        eff = getattr(self, "_stowed_restore_effect", None)
        if eff is not None:
            try:
                eff.setOpacity(float(value))
            except Exception:
                pass

    def _on_stowed_restore_anim_finished(self) -> None:
        btn = getattr(self, "_stowed_restore_btn", None)
        eff = getattr(self, "_stowed_restore_effect", None)
        if btn is None or eff is None:
            return
        try:
            if float(eff.opacity()) < 0.05:
                btn.hide()
        except Exception:
            pass

    def _fade_stowed_restore_btn(self, show: bool) -> None:
        btn = getattr(self, "_stowed_restore_btn", None)
        if btn is None:
            return
        self._ensure_stowed_restore_anim()
        anim = self._stowed_restore_anim
        eff = self._stowed_restore_effect
        try:
            cur = float(eff.opacity())
        except Exception:
            cur = 0.0
        target = 1.0 if show else 0.0
        if show:
            host = self.parentWidget() or self
            if btn.parentWidget() is not host:
                btn.setParent(host)
            self._place_stowed_restore_btn()
            btn.show()
            btn.raise_()
        if abs(cur - target) < 0.02:
            try:
                eff.setOpacity(target)
            except Exception:
                pass
            if not show:
                btn.hide()
            return
        anim.stop()
        anim.setStartValue(cur)
        anim.setEndValue(target)
        anim.start()

    def _show_stowed_restore_btn(self) -> None:
        self._fade_stowed_restore_btn(True)

    def _place_stowed_restore_btn(self) -> None:
        btn = getattr(self, "_stowed_restore_btn", None)
        if btn is None:
            return
        host = btn.parentWidget()
        if host is None:
            host = self.parentWidget() or self
            btn.setParent(host)
        center = self.mapTo(host, self.rect().center())
        bw = int(btn.width())
        x = int(center.x() - bw / 2)
        y = int(center.y() - btn.height() / 2)
        # 見切れるときだけ最小限補正（host は window の子孫なので mapFrom を使う）
        win = self.window()
        if win is not None and host is not win:
            left = int(host.mapFrom(win, QPoint(0, 0)).x())
            right = int(host.mapFrom(win, QPoint(win.width(), 0)).x())
            if x < left:
                x = left
            if x + bw > right:
                x = right - bw
            # 端に接しているときだけ中央側へ 1px
            if x <= left:
                x = left + 1
            elif x + bw >= right:
                x = right - bw - 1
        elif win is not None:
            if x < 0:
                x = 0
            if x + bw > win.width():
                x = win.width() - bw
            if x <= 0:
                x = 1
            elif x + bw >= win.width():
                x = win.width() - bw - 1
        btn.move(x, y)

    def _on_back(self) -> None:
        self.current_webview().go_back()
        QTimer.singleShot(0, self._update_nav_history_buttons)

    def _on_forward(self) -> None:
        self.current_webview().go_forward()
        QTimer.singleShot(0, self._update_nav_history_buttons)

    def _on_reload(self) -> None:
        self.reload_page()

    def reload_page(self) -> None:
        if self._enabled:
            self.current_webview().reload_page()

    def go_home(self) -> bool:
        if not self._enabled:
            return False
        url = self._initial_url or "https://x.com/"
        self.current_webview().load_url(url)
        return True

    def _on_url_changed(self, url: str) -> None:
        try:
            self._update_nav_history_buttons()
        except Exception:
            pass
        if not url:
            return
        self._loaded_once = True
        if (
            self._column_type == "lists"
            and getattr(self, "_nav_target_lock", "") == "lists"
            and self._profile_state == "RESOLVED"
        ):
            lists_url = (getattr(self, "_lists_resolved_url", "") or self._initial_url or "").strip()
            if lists_url and self._is_user_lists_url(lists_url):
                if self._is_canonical_profile_url(url) or (
                    self._is_session_bootstrap_url(url) and "/lists" not in (url or "")
                ):
                    try:
                        import os
                        if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                            print(
                                f"[LISTS] bounce late nav {url!r} → {lists_url!r}",
                                flush=True,
                            )
                    except Exception:
                        pass
                    if self._normalize_nav_url(url) != self._normalize_nav_url(lists_url):
                        self._current_web_url = lists_url
                        self._url_bar.setText(lists_url)
                        try:
                            wv = self.current_webview()
                            if wv is not None:
                                wv.load_url(lists_url)
                        except Exception:
                            pass
                    return
        self._current_web_url = url
        self._url_bar.setText(url)

    def _on_webview_url_changed(self, webview, url: str) -> None:
        if webview is self._tabs[self._current_tab]:
            self._on_url_changed(url)
        else:
            if url:
                self._loaded_once = True

    def get_account_id(self) -> str:
        return self._account_id

    def get_column_id(self) -> str:
        return self._column_id

    def get_column_type(self) -> str:
        return self._column_type

    def get_title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        self._title = title

    def get_display_name(self) -> str:
        return self._display_name

    def get_initial_url(self) -> str:
        return self._initial_url

    def set_display_name(self, name: str) -> None:
        self._display_name = (name or "").strip()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self._enabled:
            self._enabled = enabled
            if enabled:
                self._maybe_load_initial()
            self.enabled_changed.emit(enabled)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mousePressEvent(event)

    def set_width(self, width: int, emit_signal: bool = True) -> None:
        # 個別収納中はスロット幅を維持（通常幅へ上書きしない）
        if self.is_individually_stowed():
            self._current_width = self.STOWED_WIDTH
            self.setMinimumWidth(self.STOWED_WIDTH)
            self.setMaximumWidth(self.STOWED_WIDTH)
            self.setFixedWidth(self.STOWED_WIDTH)
            self.updateGeometry()
            return
        self._current_width = max(self.MIN_WIDTH, int(width))
        # fit_columns と同じ契約: min=max=確定幅。layout が余白を作らない。
        # （旧: min=MIN_WIDTH, max=tw → Preferred+stretch0 で client 未充填の黒帯）
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumWidth(self._current_width)
        self.setMaximumWidth(self._current_width)
        self.resize(self._current_width, self.height() if self.height() > 0 else 100)
        self.updateGeometry()
        if emit_signal:
            self.resized.emit(self._current_width)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        h = self.minimumHeight() if self.minimumHeight() > 0 else 400
        if self.is_individually_stowed():
            return QSize(self.STOWED_WIDTH, h)
        return QSize(self._current_width, h)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        if self.is_individually_stowed():
            return QSize(self.STOWED_WIDTH, 100)
        # min=max 契約と一致させ、layout が MIN_WIDTH へ戻さない
        w = max(self.MIN_WIDTH, int(getattr(self, "_current_width", 0) or self.MIN_WIDTH))
        return QSize(w, 100)

    def get_width(self) -> int:
        return self._current_width

    def showEvent(self, event: QEvent) -> None:
        self._position_resize_handles()
        self._enforce_single_visible_tab()
        super().showEvent(event)

    def _left_stowed_neighbor(self):
        win = self.window()
        cols = getattr(win, "_columns", None) if win is not None else None
        if not cols:
            return None
        ordered = [c for c in cols if c.isVisible()]
        try:
            idx = ordered.index(self)
        except ValueError:
            return None
        if idx <= 0:
            return None
        left = ordered[idx - 1]
        if getattr(left, "is_individually_stowed", lambda: False)():
            return left
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        # 収納同士の境界だけ常時 1px（hover/resize 用ではない）
        if not self.is_individually_stowed():
            return
        if self._left_stowed_neighbor() is None:
            return
        p = QPainter(self)
        p.fillRect(0, 0, 1, max(1, self.height()), QColor("#2a3140"))
        p.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._position_resize_handles()
        if self.is_individually_stowed():
            self._place_stowed_restore_btn()
        super().resizeEvent(event)
