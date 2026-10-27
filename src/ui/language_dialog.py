from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.i18n import LANGUAGES, set_language, tr
from src.ui.fonts import language_font
from src.ui.theme import apply_overlay_theme, popover_hide, popover_show
from src.ui.url_overlay import AccountComboBox


class LanguageComboBox(AccountComboBox):
    """言語の選択肢を、その言語の字形に合うフォントで表示するコンボ。

    「日本語」「English」は既定フォント、「简体中文」は同梱 Noto Sans SC。
    閉じた状態は選択中の言語、展開した選択肢は各言語の字形で描く。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.currentIndexChanged.connect(self._apply_closed_font)

    def _apply_closed_font(self) -> None:
        # 見た目だけの変更。言語の確定・保存は元の設定画面の処理に任せる
        self.setFont(language_font(self.currentData() or 'ja'))

    def _popup_item_font(self, index: int) -> QFont | None:
        return language_font(self.itemData(index) or 'ja')


class LanguageDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setObjectName('mayotter_settings_dialog')
        self.setWindowTitle('言語 / Language / 语言')
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(QLabel(self.windowTitle()))
        self.instruction = QLabel(tr('表示言語を選択してください。', language='ja'))
        self.instruction.setWordWrap(True)
        layout.addWidget(self.instruction)
        self.language = AccountComboBox(self)
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setMinimumWidth(260)
        layout.addWidget(self.language)
        # ドロップダウンはダイアログ内に重ねて表示されるため、3項目の一覧が見切れない高さを確保する
        layout.addStretch(1)
        self.setMinimumHeight(250)
        row = QHBoxLayout()
        row.addStretch(1)
        self.ok = QPushButton(tr('OK', language='ja'))
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok)
        layout.addLayout(row)
        self._closing = False
        self.language.currentIndexChanged.connect(self._selection_changed)
        apply_overlay_theme(self)

    def _selection_changed(self):
        language = self.language.currentData()
        # 選択中の言語の字形で見せる。アプリ全体のフォントは確定後に main で設定する。
        # QSS を持つダイアログでは setFont が既存の子へ伝わらないため、子にも設定する
        font = language_font(language)
        for widget in (self, *self.findChildren(QWidget)):
            widget.setFont(font)
        self.instruction.setText(tr('表示言語を選択してください。', language=language))
        self.ok.setText(tr('OK', language=language))

    def accept(self):
        self._close_with_result(QDialog.DialogCode.Accepted)

    def reject(self):
        self._close_with_result(QDialog.DialogCode.Rejected)

    def _close_with_result(self, result):
        if self._closing:
            return
        self._closing = True
        self.ok.setEnabled(False)
        self.language.setEnabled(False)
        self.language.hidePopup()
        popover_hide(self, on_finished=lambda: self.done(result))


class LanguageRestartDialog(QDialog):
    def __init__(self, parent, language: str):
        super().__init__(parent)
        self.setObjectName('mayotter_settings_dialog')
        self.setWindowTitle(tr('言語の変更', language=language))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 文面は変更先の言語なので、フォントも変更先に合わせる
        self.setFont(language_font(language))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        title = QLabel(self.windowTitle())
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        message = QLabel(tr('言語の変更を反映するため、Mayotterを再起動しますか？', language=language))
        message.setWordWrap(True)
        layout.addWidget(message)
        row = QHBoxLayout()
        row.addStretch(1)
        self.later = QPushButton(tr('後で', language=language))
        self.restart = QPushButton(tr('再起動', language=language))
        self.later.setDefault(True)
        self.later.clicked.connect(self.reject)
        self.restart.clicked.connect(self.accept)
        row.addWidget(self.later)
        row.addWidget(self.restart)
        layout.addLayout(row)
        self._closing = False
        apply_overlay_theme(self)

    def accept(self):
        self._close_with_result(QDialog.DialogCode.Accepted)

    def reject(self):
        self._close_with_result(QDialog.DialogCode.Rejected)

    def closeEvent(self, event):
        event.ignore()
        self.reject()

    def _close_with_result(self, result):
        if self._closing:
            return
        self._closing = True
        self.later.setEnabled(False)
        self.restart.setEnabled(False)
        popover_hide(self, on_finished=lambda: self.done(result))

    def confirm(self) -> bool:
        available = self.parentWidget().screen().availableGeometry()
        self.setMinimumWidth(min(440, available.width() - 32))
        self.setMaximumWidth(available.width() - 32)
        self.adjustSize()
        position = self.parentWidget().frameGeometry().center() - self.rect().center()
        position.setX(max(available.left(), min(position.x(), available.right() - self.width() + 1)))
        position.setY(max(available.top(), min(position.y(), available.bottom() - self.height() + 1)))
        self.move(position)
        self.setWindowOpacity(0.0)
        popover_show(self)
        try:
            return self.exec() == QDialog.DialogCode.Accepted
        finally:
            self.deleteLater()


def choose_first_language(settings) -> bool:
    dialog = LanguageDialog()
    dialog.setWindowOpacity(0.0)
    popover_show(dialog)
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        language = dialog.language.currentData()
        settings.save_ui_language(language)
        set_language(language)
        return True
    finally:
        dialog.deleteLater()
