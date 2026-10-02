from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui import theme as _theme
from src.ui.theme import apply_overlay_theme, popover_hide, popover_show


class MultiPostDialog(QWidget):
    """同じ本文を複数アカウントの投稿画面へ流し込むポップアップ。

    投稿そのものは行わない。各アカウントのカラムに投稿画面（下書き入り）を開き、
    最後の「投稿」は利用者が各画面で押す。
    他のポップアップと同様に、フェードで開閉し、外側のクリックで閉じ、
    メインウィンドウの移動に追従する（追従は MainWindow 側の浮遊ポップアップ一覧で行う）。
    """

    closed = Signal()

    def __init__(self, accounts: dict[str, dict], submit_cb, parent=None, trigger: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self._submit_cb = submit_cb
        self._trigger = trigger
        self._checks: dict[str, QCheckBox] = {}
        self._closing = False
        # テーマ切替後も現在の色を使うため、生成時にモジュール属性から読む
        SURFACE, BORDER, TEXT = _theme.SURFACE, _theme.BORDER, _theme.TEXT
        TEXT_MUTED, TEXT_SECONDARY = _theme.TEXT_MUTED, _theme.TEXT_SECONDARY
        RADIUS_MD = _theme.RADIUS_MD

        self.setObjectName("mayotter_multi_post_dialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        try:
            apply_overlay_theme(self)
        except Exception:
            pass
        self.setStyleSheet(
            f"QWidget#mayotter_multi_post_dialog {{ background:{SURFACE};"
            f" border:1px solid {BORDER}; border-radius:{RADIUS_MD}px; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)

        title = QLabel("まとめて投稿")
        title.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600; background:transparent;")
        v.addWidget(title)

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("投稿する内容")
        self._edit.setFixedHeight(110)
        self._edit.setStyleSheet(
            f"QPlainTextEdit {{ color:{TEXT}; background:{BORDER}; border:1px solid {BORDER};"
            f" border-radius:6px; padding:4px; font-size:12px; }}"
        )
        v.addWidget(self._edit)

        lab = QLabel("投稿するアカウント")
        lab.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11px; background:transparent;")
        v.addWidget(lab)
        for aid, info in accounts.items():
            cb = QCheckBox(str(info.get("display_name") or aid))
            cb.setChecked(True)
            cb.setStyleSheet(f"color:{TEXT}; font-size:12px; background:transparent;")
            self._checks[aid] = cb
            v.addWidget(cb)

        note = QLabel("各アカウントのカラムに投稿画面が開きます。最後の「投稿」は各画面で押してください。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px; background:transparent;")
        v.addWidget(note)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#f4212e; font-size:11px; background:transparent;")
        self._status.hide()
        v.addWidget(self._status)

        btn_ss = (
            f"QToolButton {{ color:{TEXT}; background:{SURFACE}; border:1px solid {BORDER};"
            " border-radius:6px; padding:6px 12px; }"
            f"QToolButton:hover {{ background:{BORDER}; }}"
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        ok = QToolButton()
        ok.setText("画面を開く")
        ok.setStyleSheet(btn_ss)
        ok.clicked.connect(self._on_ok)
        cancel = QToolButton()
        cancel.setText("キャンセル")
        cancel.setStyleSheet(btn_ss)
        cancel.clicked.connect(self.close_popup)
        row.addWidget(ok)
        row.addWidget(cancel)
        v.addLayout(row)

        self.setFixedWidth(380)
        self.adjustSize()

    def open_below(self, anchor: QWidget) -> None:
        """anchor の直下へ置いてフェードインする。"""
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        x, y = pos.x(), pos.y() + 4
        win = self.parentWidget()
        if win is not None:
            right = win.geometry().right() - 8
            x = max(win.geometry().left() + 8, min(x, right - self.width()))
        self.move(x, y)
        popover_show(self)
        self.raise_()
        self.activateWindow()
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.instance().installEventFilter(self)

    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def close_popup(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        popover_hide(self, on_finished=self._finish_close)

    def _finish_close(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape and self.isActiveWindow():
                self.close_popup()
                return True
        elif etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton and not self._closing:
                gp = event.globalPosition().toPoint()
                if not self.frameGeometry().contains(gp) and not self._on_trigger(gp):
                    self.close_popup()
        return False

    def _on_trigger(self, gp) -> bool:
        # 開いたボタン自身の押下は、ボタン側の開閉処理に任せる
        t = self._trigger
        if t is None or not t.isVisible():
            return False
        return t.rect().contains(t.mapFromGlobal(gp))

    def _on_ok(self) -> None:
        text = self._edit.toPlainText().strip()
        ids = [aid for aid, cb in self._checks.items() if cb.isChecked()]
        if not text or not ids:
            self._status.setText("本文とアカウントを選んでください。")
            self._status.show()
            self.adjustSize()
            return
        missing = self._submit_cb(text, ids)
        if missing:
            self._status.setText("カラムが無いアカウント: " + "、".join(missing))
            self._status.show()
            self.adjustSize()
            return
        self.close_popup()
