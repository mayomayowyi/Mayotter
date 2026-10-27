from __future__ import annotations

"""ページ内 JavaScript ダイアログの統一表示。

Qt 既定だと alert/confirm/prompt がネイティブの英語ダイアログ
("Javascript Confirm - <url>" 等) になるため、他の確認ダイアログと
同じフレームレス表示・日本語ボタンに置き換える。
Cookie・ログインには触れない。confirm/prompt の判断は呼び出し側へ返す。
"""
from src.core.i18n import tr

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.icons import make_close_icon, _COLOR_TEXT_SECONDARY
from src.ui.animated_choice import AnimatedCheckBox as QCheckBox

try:
    from src.ui.theme import apply_overlay_theme, color as theme_color
except Exception:
    theme_color = lambda role: {  # noqa: E731
        "SURFACE": "#181c26",
        "SURFACE_HOVER": "#232a38",
        "BORDER": "#2b3242",
        "TEXT": "#f1f3f7",
    }.get(role, "#f1f3f7")

    def apply_overlay_theme(w):
        pass


_BTN_SS = (
    "QToolButton { color:#f1f3f7; background:#1d2230; border:1px solid #2b3242;"
    " border-radius:6px; padding:6px 12px; }"
    "QToolButton:hover { background:#232a38; border:1px solid #394255; }"
    "QToolButton:pressed { background:#181c26; border:1px solid #2b3242; }"
)

_SKIP_LEAVE_PAGE_CONFIRM = "skip_leave_page_confirm"


def _is_leave_page_message(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        key in lowered
        for key in (
            "leave this page",
            "leave site",
            "reload this page",
            "may not be saved",
            "not be saved",
            "unsaved",
        )
    )


def _make_dialog(parent, object_name: str, title: str) -> tuple[QDialog, QVBoxLayout]:
    dlg = QDialog(parent)
    dlg.setObjectName(object_name)
    dlg.setModal(True)
    dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    try:
        from src.ui.window_polish import prepare_popup_chrome

        native = bool(
            prepare_popup_chrome(
                dlg,
                background=theme_color("SURFACE"),
                border_color=theme_color("BORDER"),
                corner="round",
            )
        )
    except Exception:
        native = False
    if not native:
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    try:
        apply_overlay_theme(dlg)
    except Exception:
        pass
    dlg.setStyleSheet(
        f"QDialog#{object_name} {{"
        f" background:{theme_color('SURFACE') if native else 'transparent'};"
        " border:none; }}"
    )
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    surface = QWidget(dlg)
    surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    surface.setStyleSheet(
        "QWidget {"
        f" background:{theme_color('SURFACE')};"
        f" border:{'none' if native else '1px solid ' + theme_color('BORDER')};"
        " border-radius:8px; }"
    )
    outer.addWidget(surface)
    lay = QVBoxLayout(surface)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(
        f"color:{theme_color('TEXT')}; font-size:14px; font-weight:600;"
        " background:transparent;"
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
        f"QToolButton:hover {{ background:{theme_color('SURFACE_HOVER')}; }}"
    )
    close_tb.clicked.connect(dlg.reject)
    title_row.addWidget(close_tb)
    lay.addLayout(title_row)
    return dlg, lay


def _add_message(lay: QVBoxLayout, message: str) -> None:
    body = QLabel(message or "")
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setStyleSheet(
        f"color:{theme_color('TEXT')}; font-size:12px; background:transparent;"
    )
    lay.addWidget(body)


def _button_row(lay: QVBoxLayout, dlg: QDialog, picked: dict, labels: tuple[str, ...]) -> list:
    row = QHBoxLayout()
    row.setContentsMargins(0, 6, 0, 0)
    row.setSpacing(6)
    row.addStretch(1)
    created = []
    for label in labels:
        btn = QToolButton()
        btn.setText(label)
        btn.setStyleSheet(_BTN_SS)
        btn.clicked.connect(
            lambda _=False, v=label: (picked.__setitem__("v", v), dlg.accept())
        )
        row.addWidget(btn)
        created.append(btn)
    lay.addLayout(row)
    return created


def _add_skip_checkbox(dlg: QDialog, lay: QVBoxLayout) -> QCheckBox:
    """ボタン行の先頭に「今後ダイアログを表示しない」を差し込む。"""
    checkbox = QCheckBox(tr('今後ダイアログを表示しない'), dlg)
    checkbox.setStyleSheet(
        f"QCheckBox {{ color:{theme_color('TEXT')}; background:transparent;"
        " border:none; font-size:12px; spacing:6px; }"
        "QCheckBox::indicator { width:14px; height:14px; border-radius:3px;"
        f" border:1px solid {theme_color('BORDER')}; background:{theme_color('SURFACE')}; }}"
        f"QCheckBox::indicator:checked {{ background:{theme_color('ACCENT')};"
        f" border-color:{theme_color('ACCENT')}; }}"
    )
    row = lay.itemAt(lay.count() - 1).layout()
    row.insertWidget(0, checkbox)
    return checkbox


def _finish(dlg: QDialog) -> None:
    try:
        dlg.resize(420, 200)
    except Exception:
        pass
    try:
        dlg.adjustSize()
    except Exception:
        pass
    parent = dlg.parentWidget()
    if parent is not None:
        try:
            pg = parent.frameGeometry()
            dlg.adjustSize()
            x = pg.x() + max(0, (pg.width() - dlg.width()) // 2)
            y = pg.y() + max(0, (pg.height() - dlg.height()) // 2)
            dlg.move(x, y)
        except Exception:
            pass
    dlg.exec()


def show_js_alert(parent, message: str) -> None:
    """alert() 用の通知。閉じるまで待つ。"""
    dlg, lay = _make_dialog(parent, "mayotter_js_alert_dialog", tr('メッセージ'))
    _add_message(lay, message)
    _button_row(lay, dlg, {"v": ""}, (tr('閉じる'),))
    _finish(dlg)


def show_js_confirm(parent, message: str) -> bool:
    """confirm()/beforeunload 用。離脱確認は日本語の専用文言にする。"""
    if _is_leave_page_message(message):
        return _show_leave_page_confirm(parent)
    dlg, lay = _make_dialog(parent, "mayotter_js_confirm_dialog", tr('確認'))
    _add_message(lay, message)
    picked = {"v": ""}
    _button_row(lay, dlg, picked, (tr('キャンセル'), "OK"))
    _finish(dlg)
    return str(picked.get("v") or "") == "OK"


def show_choice(parent, title: str, message: str, labels: tuple[str, ...]) -> str:
    """任意のボタンで選ばせる確認。押したボタンの文言を返す（閉じたら空文字）。"""
    dlg, lay = _make_dialog(parent, "mayotter_js_confirm_dialog", title)
    _add_message(lay, message)
    picked = {"v": ""}
    buttons = _button_row(lay, dlg, picked, tuple(labels))
    try:
        if buttons:
            buttons[-1].setFocus()
    except Exception:
        pass
    _finish(dlg)
    return str(picked.get("v") or "")


def _show_leave_page_confirm(parent) -> bool:
    """beforeunload の離脱確認。「今後表示しない」を尊重する。"""
    from src.ui.theme import remap_stylesheet

    settings = None
    try:
        from src.core.settings import SettingsManager

        settings = SettingsManager()
        if settings.get(_SKIP_LEAVE_PAGE_CONFIRM, False):
            return True
    except Exception:
        settings = None

    dlg, lay = _make_dialog(parent, "mayotter_js_confirm_dialog", tr('ページを離れる確認'))
    _add_message(
        lay,
        tr('入力中の内容があります。このページを離れますか？\n変更内容は保存されない可能性があります。'),
    )
    picked: dict = {"v": ""}
    buttons = _button_row(lay, dlg, picked, (tr('はい'), tr('いいえ')))
    for button in buttons:
        button.setStyleSheet(remap_stylesheet(_BTN_SS))
    for label in dlg.findChildren(QLabel):
        label.setStyleSheet(label.styleSheet() + " border:none;")
    checkbox = _add_skip_checkbox(dlg, lay)
    try:
        if len(buttons) > 1:
            buttons[1].setFocus()
    except Exception:
        pass
    _finish(dlg)

    allow = str(picked.get("v") or "") == tr('はい')
    if allow and checkbox.isChecked() and settings is not None:
        try:
            settings.save({_SKIP_LEAVE_PAGE_CONFIRM: True})
        except Exception:
            pass
    return allow


def show_workspace_switch_confirm(parent) -> tuple[bool, bool]:
    from src.ui.theme import remap_stylesheet
    dlg, lay = _make_dialog(parent, "mayotter_workspace_confirm_dialog", tr('確認'))
    dlg.setMinimumWidth(420)
    _add_message(lay, tr('Workを切り替えます。\n未送信の入力内容は保存を保証できません。\n切り替えますか？'))
    picked = {"v": ""}
    buttons = _button_row(lay, dlg, picked, (tr('はい'), tr('いいえ')))
    for button in buttons:
        button.setStyleSheet(remap_stylesheet(_BTN_SS))
    for label in dlg.findChildren(QLabel):
        label.setStyleSheet(label.styleSheet() + " border:none;")
    checkbox = _add_skip_checkbox(dlg, lay)
    buttons[1].setFocus()
    _finish(dlg)
    return picked["v"] == tr('はい'), checkbox.isChecked()


def show_js_prompt(parent, message: str, default_text: str = "") -> tuple[bool, str]:
    """prompt() 用。(OKか, 入力文字列) を返す。"""
    dlg, lay = _make_dialog(parent, "mayotter_js_prompt_dialog", tr('入力'))
    _add_message(lay, message)
    edit = QLineEdit(dlg)
    try:
        edit.setText(str(default_text or ""))
    except Exception:
        pass
    try:
        from src.ui.url_overlay import install_dark_lineedit_menu

        install_dark_lineedit_menu(edit)
    except Exception:
        pass
    lay.addWidget(edit)
    picked: dict = {"v": ""}
    _button_row(lay, dlg, picked, (tr('キャンセル'), "OK"))
    try:
        edit.setFocus()
        edit.selectAll()
    except Exception:
        pass
    _finish(dlg)
    if str(picked.get("v") or "") != "OK":
        return (False, "")
    try:
        return (True, str(edit.text()))
    except Exception:
        return (True, "")
