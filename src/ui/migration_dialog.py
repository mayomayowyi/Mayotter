from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from src.core import portable_migration as migration
from src.core.i18n import tr
from src.ui.progress import SmoothProgressBar
from src.ui.theme import apply_overlay_theme, popover_hide, popover_show


class _MigrationWorker(QThread):
    progress = Signal(object, object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, root, destination, include_cache, replace_settings, preview, parent):
        super().__init__(parent)
        self.root, self.destination = root, destination
        self.include_cache, self.replace_settings, self.preview = include_cache, replace_settings, preview
        self.cancel = Event()

    def run(self):
        try:
            if self.preview:
                result = migration.scan_source(self.root, self.destination, self.include_cache, self.cancel)
            else:
                result = migration.migrate(self.root, self.destination, include_cache=self.include_cache,
                                           replace_settings=self.replace_settings, cancel=self.cancel,
                                           progress=self.progress.emit)
            self.completed.emit(result)
        except migration.MigrationCancelled:
            self.failed.emit(tr('移行を中断しました。移行元は変更していません。'))
        except (OSError, ValueError, migration.MigrationError) as exc:
            migration.log_failure(self.destination, self.root, exc)
            self.failed.emit(tr('移行できませんでした。移行元は変更していません。\n{v0}', v0=migration.friendly_error(exc)))


class MigrationDialog(QDialog):
    def __init__(self, destination: Path, parent=None, *, deferred=False, source=None, include_cache=False):
        super().__init__(parent)
        self.destination = destination
        self.deferred = deferred
        self.worker = None
        self.plan = None
        self.migrated = False
        self.abort_startup = False
        self._closing = False
        self.setObjectName('mayotter_settings_dialog')
        self.setWindowTitle(tr('ZIP版から引き継ぐ'))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(520)
        self.setMaximumWidth(680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        title = QLabel(self.windowTitle())
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        note = QLabel(tr('ZIP版のMayotterフォルダを選択してください。移行元は変更・削除しません。'))
        note.setWordWrap(True)
        layout.addWidget(note)
        if deferred:
            note = QLabel(tr('移行は次回起動時に行います。録音や編集中の作業を終え、Mayotterを通常終了してください。'))
            note.setWordWrap(True)
            layout.addWidget(note)
        row = QHBoxLayout()
        self.folder = QLineEdit(str(source or ''))
        self.folder.setPlaceholderText(tr('ZIP版のMayotterフォルダ'))
        self.browse = QPushButton(tr('参照'))
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.cache = QCheckBox(tr('キャッシュも引き継ぐ（通常は不要）'))
        self.cache.setChecked(include_cache)
        layout.addWidget(self.cache)
        self.consent = QCheckBox(tr('移行先の設定の置き換えに同意する（元の設定は退避）'))
        self.consent.setVisible((destination / 'config/app.json').exists())
        layout.addWidget(self.consent)
        warning = QLabel(tr('※ログイン状態の引き継ぎはキャッシュとは無関係です。Cookieやブラウザのバージョン差により、再ログインが必要になる場合があります。'))
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.status = QLabel(tr('ZIP版Mayotterを終了してから実行してください。'))
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.progress = SmoothProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.secondary = QPushButton(tr('閉じる') if deferred else tr('スキップ'))
        self.primary = QPushButton(tr('移行内容を確認'))
        self.secondary.clicked.connect(self.reject)
        self.primary.clicked.connect(self._primary)
        row.addWidget(self.secondary)
        row.addWidget(self.primary)
        layout.addLayout(row)
        self.folder.textChanged.connect(self._invalidate)
        self.cache.toggled.connect(self._invalidate)
        apply_overlay_theme(self)

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, tr('ZIP版のMayotterフォルダ'), self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def _invalidate(self):
        self.plan = None
        self.primary.setText(tr('移行内容を確認'))

    def _primary(self):
        try:
            self._start()
        except (OSError, ValueError, migration.MigrationError) as exc:
            migration.log_failure(self.destination, Path(self.folder.text()), exc)
            self.status.setText(tr('移行できませんでした。移行元は変更していません。\n{v0}', v0=migration.friendly_error(exc)))

    def _start(self):
        if self.migrated:
            self.accept()
            return
        if self.worker is not None:
            return
        if not self.folder.text().strip():
            self.status.setText(tr('ZIP版のMayotterフォルダを選択してください。'))
            return
        if migration.destination_has_data(self.destination):
            self.status.setText(tr('移行先にユーザーデータがあります。上書きや統合は行いません。'))
            return
        if self.plan is not None and (self.destination / 'config/app.json').exists() and not self.consent.isChecked():
            self.status.setText(tr('移行先の設定の置き換えには同意が必要です。'))
            return
        if self.plan is not None and self.deferred:
            migration.write_state(self.destination, {'status': 'pending', 'source': str(self.plan['root']),
                                  'include_cache': self.cache.isChecked()})
            self.status.setText(tr('移行を予約しました。次回起動時に、内容を確認してから引き継ぎます。'))
            self.migrated = True
            self.primary.setText(tr('閉じる'))
            self.secondary.setText(tr('閉じる'))
            for widget in (self.folder, self.browse, self.cache, self.consent):
                widget.setEnabled(False)
            return
        preview = self.plan is None
        self.worker = _MigrationWorker(Path(self.folder.text()), self.destination, self.cache.isChecked(),
                                       self.consent.isChecked(), preview, self)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.primary.setEnabled(False)
        for widget in (self.folder, self.browse, self.cache, self.consent):
            widget.setEnabled(False)
        self.secondary.setText(tr('キャンセル'))
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText(tr('移行内容を確認しています…') if preview else tr('コピーと検証を行っています…'))
        self.worker.start()

    def _progress(self, done, total):
        self.progress.setRange(0, 1000)
        self.progress.setValue(int(done * 1000 / max(total, 1)))

    def _completed(self, result):
        if self.worker.preview:
            self.plan = result
            self.status.setText(tr('アカウント: {v0} / ファイル: {v1} / 容量: {v2} MB\n設定・Work・プロファイル・録音・音声画像を引き継ぎます。',
                                   v0=result['accounts'], v1=len(result['files']), v2=f"{result['size'] / 1048576:.1f}"))
            self.primary.setText(tr('次回起動時に移行する') if self.deferred else tr('引き継ぐ'))
        else:
            self.migrated = True
            self.progress.setRange(0, 1000)
            self.progress.setValue(1000)
            self.status.setText(tr('移行が完了しました。移行元はそのまま使用できます。\n設定の退避先: {v0}', v0=result['backup']))
            self.primary.setText(tr('続ける'))

    def _failed(self, message):
        self.plan = None
        self.progress.hide()
        self.status.setText(message)
        self.primary.setText(tr('移行内容を確認'))

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.primary.setEnabled(True)
        for widget in (self.folder, self.browse, self.cache, self.consent):
            widget.setEnabled(not self.migrated)
        self.secondary.setText(tr('閉じる') if self.migrated or self.deferred else tr('スキップ'))
        if not self.migrated:
            self.progress.hide()

    def accept(self):
        self._close(QDialog.DialogCode.Accepted)

    def reject(self):
        if self.worker is not None:
            self.worker.cancel.set()
            self.status.setText(tr('中断しています…'))
            return
        if not self.deferred and not self.migrated:
            try:
                if not self.abort_startup:
                    state = migration.read_state(self.destination)
                    if state.get('status') not in {'copying', 'committing'}:
                        migration.write_state(self.destination, {'status': 'skipped'})
            except (OSError, ValueError, migration.MigrationError) as exc:
                self.status.setText(tr(str(exc)))
                self.abort_startup = True
                return
        self._close(QDialog.DialogCode.Accepted if self.migrated else QDialog.DialogCode.Rejected)

    def _close(self, result):
        if self.worker is not None or self._closing:
            return
        self._closing = True
        popover_hide(self, on_finished=lambda: self.done(result))

    def closeEvent(self, event):
        event.ignore()
        self.reject()

    def confirm(self):
        self.adjustSize()
        screen = self.screen().availableGeometry()
        self.setMinimumWidth(min(520, screen.width() - 32))
        self.setMaximumWidth(min(680, screen.width() - 32))
        self.adjustSize()
        center = self.parentWidget().frameGeometry().center() if self.parentWidget() else screen.center()
        self.move(center - self.rect().center())
        self.setWindowOpacity(0.0)
        popover_show(self)
        try:
            return self.exec()
        finally:
            self.deleteLater()


def run_startup_migration(destination: Path) -> bool:
    try:
        migration.recover_migration(destination)
        state = migration.read_state(destination)
        if state.get('status') == 'pending' or migration.should_offer(destination):
            MigrationDialog(destination, source=state.get('source'), include_cache=state.get('include_cache', False)).confirm()
        return migration.read_state(destination).get('status') not in {'copying', 'committing'}
    except (OSError, ValueError, migration.MigrationError) as exc:
        dialog = MigrationDialog(destination)
        dialog.abort_startup = True
        dialog.primary.hide()
        dialog.secondary.setText(tr('閉じる'))
        dialog.status.setText(tr('移行の復旧に失敗しました。データは上書きせず起動を中止します。\n{v0}', v0=tr(str(exc))))
        dialog.confirm()
        return False


class _RemovalWorker(QThread):
    progress = Signal(object, object)
    completed = Signal(object)
    failed = Signal(str, bool)

    def __init__(self, destination, protect, plan, parent):
        super().__init__(parent)
        self.destination, self.protect, self.plan = destination, protect, plan
        self.cancel = Event()

    def run(self):
        try:
            if self.plan is None:
                result = migration.plan_legacy_removal(self.destination, protect=self.protect, cancel=self.cancel)
            else:
                result = migration.remove_legacy(self.plan, cancel=self.cancel, progress=self.progress.emit)
            self.completed.emit(result)
        except migration.MigrationCancelled:
            self.failed.emit(tr('中断しました。旧ZIP版もSetup版のデータも変更していません。'), False)
        except migration.RemovalBlocked as exc:
            self.failed.emit(tr(str(exc)), True)
        except (OSError, ValueError, migration.MigrationError) as exc:
            self.failed.emit(tr(str(exc)), False)


class LegacyRemovalDialog(QDialog):
    """移行完了後に、旧ZIP版を削除するかを確認する。承認しない限り何も削除しない。"""

    def __init__(self, destination: Path, parent=None, protect=()):
        super().__init__(parent)
        self.destination, self.protect = destination, protect
        self.worker = None
        self.plan = None
        self.stage = 'planning'
        self.removed = False
        self._closing = False
        self.setObjectName('mayotter_settings_dialog')
        self.setWindowTitle(tr('旧ZIP版の削除'))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(520)
        self.setMaximumWidth(680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        title = QLabel(self.windowTitle())
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        self.status = QLabel(tr('旧ZIP版を確認しています…'))
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.progress = SmoothProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.secondary = QPushButton(tr('残す'))
        self.primary = QPushButton(tr('旧ZIP版を削除…'))
        self.primary.setEnabled(False)
        self.secondary.clicked.connect(self._secondary)
        self.primary.clicked.connect(self._primary)
        row.addWidget(self.secondary)
        row.addWidget(self.primary)
        layout.addLayout(row)
        apply_overlay_theme(self)

    def start(self):
        self._run(None)

    def _run(self, plan):
        self.worker = _RemovalWorker(self.destination, self.protect, plan, self)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _progress(self, done, total):
        self.progress.setRange(0, 1000)
        self.progress.setValue(int(done * 1000 / max(total, 1)))

    def _summary(self):
        plan = self.plan
        text = tr('移行は完了し、Setup版でデータを読み込めました。\n旧ZIP版の場所: {v0}\n削除する内容: Mayotter本体とdataなど {v1} 個 / {v2} MB',
                  v0=plan['root'], v1=plan['count'], v2=f"{plan['bytes'] / 1048576:.1f}")
        if plan['unknown']:
            names = '\n'.join(str(p.relative_to(plan['root'])) for p in plan['unknown'][:5])
            text += '\n' + tr('Mayotterのものと確認できない {v0} 個のファイルは削除せず残します。\n{v1}', v0=len(plan['unknown']), v1=names)
        return text + '\n' + tr('Setup版のデータは削除されません。')

    def _completed(self, result):
        self.progress.hide()
        if self.stage == 'planning':
            self.plan, self.stage = result, 'ready'
            self.status.setText(self._summary())
            self.primary.setEnabled(True)
        else:
            self.removed, self.stage = True, 'done'
            text = tr('旧ZIP版を削除しました。') if result['root_removed'] else tr('旧ZIP版を削除しました。確認できないファイルがあるため、フォルダは残しています。')
            self.status.setText(text)
            self.primary.hide()
            self.secondary.setText(tr('閉じる'))
            self.secondary.setEnabled(True)

    def _failed(self, message, permanent):
        self.progress.hide()
        self.stage = 'blocked'
        if permanent:
            try:
                migration.decline_legacy_removal(self.destination, 'blocked')
            except (OSError, ValueError, migration.MigrationError):
                pass
        self.status.setText(tr('旧ZIP版は削除しませんでした。\n{v0}', v0=message))
        self.primary.hide()
        self.secondary.setText(tr('閉じる'))
        self.secondary.setEnabled(True)

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()

    def _primary(self):
        if self.worker is not None:
            return
        if self.stage == 'ready':
            # 削除の前に最終確認を挟む
            self.stage = 'confirm'
            self.status.setText(tr('最終確認: {v0} のMayotter本体と移行済みのdataを完全に削除します。この操作は元に戻せません。', v0=self.plan['root']))
            self.primary.setText(tr('完全に削除する'))
            self.secondary.setText(tr('戻る'))
        elif self.stage == 'confirm':
            self.stage = 'removing'
            self.primary.setEnabled(False)
            self.secondary.setEnabled(False)
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
            self.progress.show()
            self.status.setText(tr('旧ZIP版を削除しています…'))
            self._run(self.plan)

    def _secondary(self):
        if self.worker is not None:
            return
        if self.stage == 'confirm':
            self.stage = 'ready'
            self.status.setText(self._summary())
            self.primary.setText(tr('旧ZIP版を削除…'))
            self.secondary.setText(tr('残す'))
        elif self.stage in {'ready', 'planning'}:
            try:
                migration.decline_legacy_removal(self.destination, 'kept')
            except (OSError, ValueError, migration.MigrationError):
                pass
            self._close(QDialog.DialogCode.Rejected)
        else:
            self._close(QDialog.DialogCode.Accepted if self.removed else QDialog.DialogCode.Rejected)

    def _close(self, result):
        if self.worker is not None or self._closing:
            return
        self._closing = True
        popover_hide(self, on_finished=lambda: self.done(result))

    def reject(self):
        self._secondary()

    def closeEvent(self, event):
        event.ignore()
        self.reject()

    def confirm(self):
        self.adjustSize()
        screen = self.screen().availableGeometry()
        self.setMinimumWidth(min(520, screen.width() - 32))
        self.setMaximumWidth(min(680, screen.width() - 32))
        self.adjustSize()
        center = self.parentWidget().frameGeometry().center() if self.parentWidget() else screen.center()
        self.move(center - self.rect().center())
        self.setWindowOpacity(0.0)
        popover_show(self)
        self.start()
        try:
            return self.exec()
        finally:
            self.deleteLater()


def offer_legacy_removal(destination: Path, loaded_accounts, parent=None, protect=()) -> bool:
    """Setup版が起動し、移行したアカウントを読み込めている場合だけ、旧ZIP版の削除を提案する。"""
    try:
        if not migration.legacy_removal_pending(destination):
            return False
        if not set(migration.read_state(destination).get('accounts_migrated', [])) <= set(loaded_accounts):
            return False
    except (OSError, ValueError, migration.MigrationError):
        return False
    LegacyRemovalDialog(destination, parent, protect).confirm()
    return True
