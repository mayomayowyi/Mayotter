from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QThread,
    QTimer,
    QVariantAnimation,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
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
        RADIUS_MD,
    )
except Exception:
    POPOVER_OPEN_MS, POPOVER_CLOSE_MS = 170, 120
    SURFACE, BORDER, TEXT = "#12151c", "#2b3242", "#f1f3f7"
    ACCENT, SURFACE_RAISED = "#4a7ec7", "#1d2230"
    RADIUS_MD = 8


class _DownloadWorker(QThread):
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


class UpdateDialog(QDialog):
    busyChanged = Signal(bool)
    finishedClosing = Signal()

    def __init__(
        self,
        parent=None,
        *,
        github_repo: str = "",
        on_apply_success: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._github_repo = github_repo
        self._on_apply_success = on_apply_success
        self._state: dict = {
            "busy": False,
            "info": None,
            "worker": None,
            "closing": False,
        }
        self._anim_state: dict = {
            "display": 0.0,
            "target": 0,
            "complete_hold": False,
        }

        self.setObjectName("mayotter_update_dialog")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        try:
            from src.ui.window_polish import prepare_popup_chrome
            self._native_rounding = prepare_popup_chrome(
                self, background=SURFACE, border_color=BORDER, corner="round"
            )
        except Exception:
            self._native_rounding = False
        if not self._native_rounding:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            f"QDialog#mayotter_update_dialog {{"
            f" background:{SURFACE if self._native_rounding else 'transparent'}; border:none; }}"
        )
        self.setMinimumWidth(360)

        self._build_ui()
        self._secondary_btn.clicked.connect(self._fade_close)

    def _build_ui(self) -> None:
        btn_ss = (
            "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
            " border-radius:6px; padding:4px 12px; }"
            "QToolButton:hover { background:#232a38; border:1px solid #394255; color:#f1f3f7; }"
            "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
            "QToolButton:disabled { color:#5a6270; background:#151820; border:1px solid #2b3242; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        surface = QWidget(self)
        surface.setObjectName("mayotter_update_surface")
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        surface.setStyleSheet(
            f"QWidget#mayotter_update_surface {{"
            f" background:{SURFACE if SURFACE != '#12151c' else '#12151c'};"
            f" border:{'none' if self._native_rounding else f'1px solid {BORDER}'};"
            f" border-radius:{0 if self._native_rounding else RADIUS_MD}px; }}"
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
        self._body = QLabel("確認しています…")
        self._body.setWordWrap(True)
        self._body.setStyleSheet(f"color:{TEXT}; font-size:12px; background:transparent;")
        v.addWidget(self._body)

        prog_row = QHBoxLayout()
        prog_row.setContentsMargins(0, 2, 0, 0)
        prog_row.setSpacing(10)
        self._progress = QProgressBar()
        self._progress.setObjectName("mayotter_update_progress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(12)
        self._progress.setMinimumWidth(180)
        self._progress.setStyleSheet(
            f"QProgressBar#mayotter_update_progress {{"
            f" background:{SURFACE_RAISED}; border:1px solid {BORDER};"
            f" border-radius:6px; text-align:center; }}"
            f"QProgressBar#mayotter_update_progress::chunk {{"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f"  stop:0 #3d6aa8, stop:0.45 {ACCENT}, stop:1 #6a9be0);"
            f" border-radius:5px; margin:1px; }}"
        )
        self._progress.hide()
        self._pct_lbl = QLabel("")
        self._pct_lbl.setObjectName("mayotter_update_pct")
        self._pct_lbl.hide()
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self._pct_lbl.setStyleSheet(
            f"QLabel#mayotter_update_pct {{"
            f" color:{TEXT}; font-size:12px; font-weight:600;"
            f" background:transparent; min-width:40px; }}"
        )
        prog_row.addWidget(self._progress, 1)
        prog_row.addWidget(self._pct_lbl, 0)
        v.addLayout(prog_row)

        self._prog_anim = QVariantAnimation(self)
        self._prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._prog_anim.valueChanged.connect(self._apply_display_value)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self._primary_btn = QToolButton()
        self._primary_btn.setText("はい")
        self._primary_btn.setStyleSheet(btn_ss)
        self._primary_btn.hide()
        self._secondary_btn = QToolButton()
        self._secondary_btn.setText("いいえ")
        self._secondary_btn.setStyleSheet(btn_ss)
        self._secondary_btn.setText("閉じる")
        btn_row.addWidget(self._primary_btn)
        btn_row.addWidget(self._secondary_btn)
        v.addLayout(btn_row)

    def show_centered(self) -> None:
        try:
            self.adjustSize()
            parent = self.parentWidget()
            if parent is not None:
                geo = parent.frameGeometry()
                dg = self.frameGeometry()
                self.move(
                    geo.center().x() - dg.width() // 2,
                    geo.center().y() - dg.height() // 2,
                )
        except Exception:
            pass

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

        QTimer.singleShot(30, self._run_check)

    def _relayout(self):
        try:
            self.adjustSize()
        except Exception:
            pass

    def _set_busy(self, busy: bool) -> None:
        self._state["busy"] = bool(busy)
        self.busyChanged.emit(bool(busy))

    def _finish_close(self):
        if self._state.get("closing_done"):
            return
        self._state["closing_done"] = True
        self.busyChanged.emit(False)
        try:
            w = self._state.get("worker")
            if w is not None:
                try:
                    if w.isRunning():
                        w.requestInterruption()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.hide()
            self.deleteLater()
        except Exception:
            pass
        self.finishedClosing.emit()

    def _fade_close(self):
        if self._state.get("closing"):
            return
        self._state["closing"] = True
        try:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(int(POPOVER_CLOSE_MS))
            anim.setStartValue(float(self.windowOpacity() or 1.0))
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.InCubic)
            anim.finished.connect(self._finish_close)
            anim.start()
            self._mayotter_fade_anim = anim
            QTimer.singleShot(int(POPOVER_CLOSE_MS) + 100, self._finish_close)
        except Exception:
            self._finish_close()

    def _show_message(self, msg: str, *, closable: bool = True):
        try:
            self._prog_anim.stop()
        except Exception:
            pass
        self._body.setText(msg)
        self._progress.hide()
        self._pct_lbl.hide()
        self._primary_btn.hide()
        self._secondary_btn.setText("閉じる")
        self._secondary_btn.setEnabled(True)
        self._secondary_btn.show()
        try:
            self._secondary_btn.clicked.disconnect()
        except Exception:
            pass
        self._secondary_btn.clicked.connect(self._fade_close)
        self._relayout()

    def _apply_display_value(self, v) -> None:
        try:
            iv = int(round(float(v)))
            iv = max(0, min(100, iv))
            self._anim_state["display"] = float(iv)
            self._progress.setValue(iv)
            self._pct_lbl.setText(f"{iv}%")
        except Exception:
            pass

    def _animate_to(self, target: int, *, duration_ms: int | None = None) -> None:
        target = max(0, min(100, int(target)))
        self._anim_state["target"] = target
        try:
            cur = int(round(float(self._anim_state.get("display", self._progress.value()))))
        except Exception:
            cur = self._progress.value()
        if abs(target - cur) < 1 and target < 100:
            self._apply_display_value(target)
            return
        try:
            self._prog_anim.stop()
        except Exception:
            pass
        self._prog_anim.setStartValue(float(cur))
        self._prog_anim.setEndValue(float(target))
        if duration_ms is None:
            duration_ms = max(140, min(420, abs(target - cur) * 9))
        self._prog_anim.setDuration(int(duration_ms))
        self._prog_anim.start()

    def _on_progress(self, received: int, total):
        try:
            self._progress.setRange(0, 100)
            self._progress.show()
            self._pct_lbl.show()
            if total and total > 0:
                pct = max(0, min(100, int(received * 100 / total)))
                self._animate_to(pct)
            else:
                self._progress.setRange(0, 0)
                mb = received / (1024 * 1024)
                self._pct_lbl.setText(f"{mb:.1f} MB")
                self._pct_lbl.setStyleSheet(
                    f"QLabel#mayotter_update_pct {{"
                    f" color:{TEXT}; font-size:12px; font-weight:600;"
                    f" background:transparent; min-width:56px; }}"
                )
        except Exception:
            pass

    def _start_download(self):
        info = self._state.get("info")
        if info is None or self._state.get("busy"):
            return
        if not getattr(info, "download_url", None):
            self._show_message("アップデートファイルを取得できませんでした。")
            return
        self._set_busy(True)
        self._body.setText("ダウンロード中…")
        self._progress.setRange(0, 100)
        self._anim_state["display"] = 0.0
        self._anim_state["target"] = 0
        self._anim_state["complete_hold"] = False
        try:
            self._prog_anim.stop()
        except Exception:
            pass
        self._progress.setValue(0)
        self._pct_lbl.setText("0%")
        self._pct_lbl.setStyleSheet(
            f"QLabel#mayotter_update_pct {{"
            f" color:{TEXT}; font-size:12px; font-weight:600;"
            f" background:transparent; min-width:40px; }}"
        )
        self._progress.show()
        self._pct_lbl.show()
        self._primary_btn.hide()
        self._secondary_btn.hide()
        self._relayout()

        worker = _DownloadWorker(
            info.download_url,
            getattr(info, "sha256", None),
        )
        self._state["worker"] = worker

        worker.progress.connect(self._on_progress)
        worker.ok.connect(self._on_ok)
        worker.err.connect(self._on_err)
        worker.start()

    def _proceed_after_complete(self, path_str: str):
        try:
            from src.core.updater import (
                mark_download_complete,
                prepare_and_launch_self_update,
            )
            import sys

            info = self._state.get("info")
            mark_download_complete(Path(path_str), info)
            frozen = bool(getattr(sys, "frozen", False))
            if frozen and sys.platform.startswith("win"):
                self._body.setText("更新を適用しています…")
                self._apply_display_value(100)
                ok, msg = prepare_and_launch_self_update(Path(path_str))
                if not ok:
                    self._set_busy(False)
                    self._show_message(msg or "更新の適用に失敗しました。")
                    return
                self._body.setText(msg)
                self._progress.hide()
                self._pct_lbl.hide()
                self._primary_btn.hide()
                self._secondary_btn.hide()
                self._relayout()
                if self._on_apply_success is not None:
                    QTimer.singleShot(400, self._on_apply_success)
            else:
                self._set_busy(False)
                self._show_message(
                    "ダウンロードが完了しました。\n"
                    "（開発実行中は自動置換を行いません。"
                    "配布版では再起動して更新が適用されます）"
                )
        except Exception as exc:
            self._set_busy(False)
            self._show_message(f"更新処理に失敗しました。\n{exc}")

    def _on_ok(self, path_str: str):
        try:
            self._anim_state["complete_hold"] = True
            self._animate_to(100, duration_ms=220)

            def _after_anim():
                if self._state.get("closing"):
                    return
                self._proceed_after_complete(path_str)

            QTimer.singleShot(280, _after_anim)
        except Exception:
            self._proceed_after_complete(path_str)

    def _on_err(self, msg: str):
        self._set_busy(False)
        self._show_message(msg)

    def _on_yes(self):
        self._start_download()

    def _on_no(self):
        if self._state.get("busy"):
            return
        self._fade_close()

    def _run_check(self):
        try:
            from src.core.updater import check_for_update

            info = check_for_update(github_repo=self._github_repo)
            if info is None:
                self._show_message("新しいバージョンはありません。")
                return
            self._state["info"] = info
            self._body.setText(
                f"最新版を確認しました（{info.version}）。\n今すぐ更新しますか？"
            )
            self._progress.hide()
            self._pct_lbl.hide()
            self._secondary_btn.setText("いいえ")
            self._secondary_btn.setEnabled(True)
            self._primary_btn.setText("はい")
            self._primary_btn.show()
            self._primary_btn.setEnabled(True)
            try:
                self._primary_btn.clicked.disconnect()
            except Exception:
                pass
            try:
                self._secondary_btn.clicked.disconnect()
            except Exception:
                pass
            self._primary_btn.clicked.connect(self._on_yes)
            self._secondary_btn.clicked.connect(self._on_no)
            self._relayout()
        except Exception:
            self._show_message("アップデートの確認中にエラーが発生しました。")

    def refresh_theme(self) -> None:
        try:
            from src.ui.theme import color
            self.setStyleSheet(
                f"QDialog#mayotter_update_dialog {{"
                f" background:{color('SURFACE') if getattr(self, '_native_rounding', False) else 'transparent'}; border:none; }}"
            )
            surface = self.findChild(QWidget, "mayotter_update_surface")
            if surface:
                surface.setStyleSheet(
                    "QWidget#mayotter_update_surface {"
                    f" background:{color('SURFACE') if color('SURFACE') != '#12151c' else '#12151c'};"
                    f" border:{'none' if getattr(self, '_native_rounding', False) else '1px solid ' + color('BORDER')};"
                    f" border-radius:{0 if getattr(self, '_native_rounding', False) else 8}px; }}"
                )
            for lbl in self.findChildren(QLabel):
                if lbl.objectName() in ("mayotter_update_surface", "mayotter_update_progress", "mayotter_update_pct"):
                    continue
                lbl.setStyleSheet(f"color:{color('TEXT')}; font-size:12px; background:transparent;")
            prog = self.findChild(QProgressBar, "mayotter_update_progress")
            if prog:
                prog.setStyleSheet(
                    f"QProgressBar#mayotter_update_progress {{"
                    f" background:{color('SURFACE_RAISED')}; border:1px solid {color('BORDER')};"
                    f" border-radius:6px; text-align:center; }}"
                    f"QProgressBar#mayotter_update_progress::chunk {{"
                    f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                    f"  stop:0 {color('BORDER_ACCENT')}, stop:0.45 {color('ACCENT')}, stop:1 {color('ACCENT_STRONG')});"
                    f" border-radius:5px; margin:1px; }}"
                )
            for btn in self.findChildren(QToolButton):
                if btn.objectName() in ("primary_btn", "secondary_btn"):
                    btn.setStyleSheet(
                        f"QToolButton {{ color:{color('TEXT')}; background:{color('SURFACE_HOVER')}; border:1px solid {color('BORDER')};"
                        " border-radius:6px; padding:4px 12px; }"
                        f"QToolButton:hover {{ background:{color('SURFACE_HOVER')}; border:1px solid {color('BORDER_STRONG')}; color:{color('TEXT')}; }}"
                        f"QToolButton:pressed {{ background:{color('SURFACE_SUNKEN')}; border:1px solid {color('BORDER')}; }}"
                        f"QToolButton:disabled {{ color:{color('TEXT_MUTED')}; background:{color('SURFACE_SUNKEN')}; border:1px solid {color('BORDER')}; }}"
                    )
            self.update()
        except Exception:
            pass
