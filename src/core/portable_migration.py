from __future__ import annotations

from src.core.i18n import tr

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from threading import Event
from uuid import uuid4


STATE_FILE = '.portable-migration.json'
PROFILE_CACHES = {'cache', 'code cache', 'gpucache', 'shadercache', 'dawncache', 'cachestorage'}


class MigrationError(Exception):
    pass


class MigrationCancelled(Exception):
    pass


def read_state(destination: Path) -> dict:
    path = destination / STATE_FILE
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('status') not in {
            'skipped', 'pending', 'failed', 'copying', 'committing', 'complete'}:
        raise MigrationError(tr('移行記録を読み取れません。'))
    return value


def write_state(destination: Path, value: dict) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / STATE_FILE
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _linked(path: Path) -> bool:
    return path.is_symlink() or (path.exists() and bool(
        getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def destination_has_data(destination: Path) -> bool:
    if not destination.exists():
        return False
    for entry in destination.iterdir():
        if _linked(entry):
            return True
        if entry.name in {STATE_FILE, '.mayotter.lock', 'logs', 'cache', 'temp'}:
            continue
        if entry.name == 'config':
            if not entry.is_dir() or any(_linked(p) or (p.is_file() and p.name != 'app.json') for p in entry.rglob('*')):
                return True
            path = entry / 'app.json'
            if path.exists():
                value = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(value, dict) or value.get('accounts'):
                    return True
                workspaces = value.get('workspaces') or {}
                if not isinstance(workspaces, dict) or any(not isinstance(w, dict) for w in workspaces.values()):
                    return True
                states = [value] + [w.get('state', {}) for w in workspaces.values()]
                if len(value.get('workspaces') or {}) > 1:
                    return True
                if any(not isinstance(s, dict) or s.get('columns') or
                       not isinstance(s.get('columns_by_mode', {}), dict) or
                       any(s.get('columns_by_mode', {}).values()) for s in states):
                    return True
        elif entry.is_file() or any(p.is_file() or _linked(p) for p in entry.rglob('*')):
            return True
    return False


def should_offer(destination: Path) -> bool:
    state = read_state(destination)
    return (state.get('status') not in {'skipped', 'complete'}
            and not (destination / 'config/app.json').exists()
            and not destination_has_data(destination))


class SourceInUse(MigrationError):
    """旧ZIP版が実際に起動している。終了すれば再実行できる一時的な理由。"""


def diagnose(destination: Path, event: str, **details) -> None:
    """診断ログ（移行先の logs/migration.log）。パス・PID・エラー種別だけを記録し、Cookie等の内容は記録しない。"""
    try:
        import time
        directory = Path(destination) / 'logs'
        directory.mkdir(parents=True, exist_ok=True)
        fields = ' '.join(f'{key}={value}' for key, value in details.items())
        with (directory / 'migration.log').open('a', encoding='utf-8') as stream:
            stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {event} {fields}\n")
    except OSError:
        pass


def friendly_error(exc: BaseException) -> str:
    """失敗の実際の理由を、利用者に分かる文にする。"""
    if isinstance(exc, MigrationError):
        return tr(str(exc))
    if isinstance(exc, OSError):
        code = getattr(exc, 'winerror', None) or exc.errno
        name = Path(exc.filename).name if getattr(exc, 'filename', None) else ''
        if code in (32, 33):
            return tr('他のプログラムがファイルを使用中です。Mayotterなどを終了してから、もう一度実行してください。\n{v0}', v0=name)
        if code in (5, 13, 1):
            return tr('ファイルにアクセスできません（権限がありません）。\n{v0}', v0=name)
        if code in (2, 3, 21, 53, 67):
            return tr('移行元のファイルまたはフォルダが見つかりません。ドライブが接続されているか確認してください。\n{v0}', v0=name)
        if code in (112, 28):
            return tr('移行先の空き容量が不足しています。')
        if code in (123, 161, 206):
            return tr('パスが正しくありません。\n{v0}', v0=name)
        return tr('ファイル操作でエラーが発生しました（コード {v0}）。\n{v1}', v0=code, v1=name)
    return tr('予期しないエラーが発生しました。')


def log_failure(destination: Path, source: Path, exc: BaseException) -> None:
    """移行の失敗理由を診断ログへ。例外の種類・コード・ファイル名だけで、ファイルの内容は記録しない。"""
    details = {'source': source, 'error': type(exc).__name__}
    if isinstance(exc, OSError):
        details['code'] = getattr(exc, 'winerror', None) or exc.errno
        if getattr(exc, 'filename', None):
            details['file'] = Path(exc.filename).name
    elif isinstance(exc, MigrationError):
        details['reason'] = str(exc).replace('\n', ' ')
    diagnose(destination, 'import_failed', **details)


def _process_image(pid: int):
    """PID のプロセスの実行ファイル。実行中でなければ None、実行中だが調べられなければ ''。"""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None if ctypes.get_last_error() == 87 else ''
    try:
        code = wintypes.DWORD()
        if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        return buffer.value if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)) else ''
    finally:
        kernel.CloseHandle(handle)


def _lock_is_live(lock: Path) -> int | None:
    """data/.mayotter.lock の持ち主が今も起動していればその PID。異常終了で残った古いロックなら None。
    ロックファイルは読み取るだけで、作成・更新・削除はしない。"""
    import socket
    from PySide6.QtCore import QLockFile
    try:
        pid, host, application = QLockFile(str(lock)).getLockInfo()   # 持ち主が分からないときは pid=0
    except Exception:
        pid, host, application = 0, '', ''
    if pid <= 0:
        # 内容を読めない（空・壊れている）ロックは、持ち主を特定できないので古いものとして扱う
        return None
    if host and host.lower() != socket.gethostname().lower():
        return None          # 別のPCで作られたロック。このPCでは起動中かどうかを確認できず、PID も無関係
    if os.name != 'nt':
        return pid
    image = _process_image(int(pid))
    if image is None:
        return None
    # PID の使い回し対策: 実行中のプロセスがロックの作成者（アプリ名）と同じ実行ファイルのときだけ起動中とみなす
    if image and application and Path(image).stem.lower() != str(application).lower().removesuffix('.exe'):
        return None
    return int(pid)


def _source_closed(root: Path, destination: Path | None = None) -> None:
    lock = root / 'data/.mayotter.lock'
    if lock.exists():
        owner = _lock_is_live(lock)
        if owner is not None:
            if destination is not None:
                diagnose(destination, 'source_in_use', reason='live_lock', pid=owner, source=root)
            raise SourceInUse(tr('ZIP版Mayotterが起動中です（プロセス {v0}）。通常終了してから、もう一度実行してください。', v0=owner))
        if destination is not None:
            diagnose(destination, 'stale_lock_ignored', source=root,
                     note='the lock owner is not running (abnormal exit); the source was not modified')
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t), ('module', wintypes.DWORD),
                    ('threads', wintypes.DWORD), ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                    ('flags', wintypes.DWORD), ('exe', wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.exe.lower() == 'mayotter.exe':
                image = _process_image(int(entry.pid))
                # 実行ファイルを調べられない他ユーザーのプロセスは、この移行元のものと確認できないので対象外にする
                if image and Path(image).resolve().parent == root:
                    if destination is not None:
                        diagnose(destination, 'source_in_use', reason='running_process', pid=entry.pid, source=root)
                    raise SourceInUse(tr('ZIP版Mayotterが起動中です（プロセス {v0}）。通常終了してから、もう一度実行してください。', v0=entry.pid))
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)


def _settings(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or not value:
        raise MigrationError(tr('Mayotterの設定があるZIP版フォルダを選択してください。'))
    from src.core.settings import SettingsManager
    if 'workspaces' in value:
        SettingsManager._validate_workspaces(value)
    accounts = value.get('accounts', [])
    if not isinstance(accounts, list):
        raise MigrationError(tr('アカウントの保存形式が不正です。'))
    ids = [a.get('account_id') if isinstance(a, dict) else None for a in accounts]
    if any(not isinstance(a, str) or not a or Path(a).name != a or a in {'.', '..'}
           or ':' in a or '/' in a or '\\' in a for a in ids) or len({a.casefold() for a in ids}) != len(ids):
        raise MigrationError(tr('アカウントの保存形式が不正です。'))
    return value


def scan_source(root: Path, destination: Path, include_cache=False, cancel: Event | None = None) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if (root / 'mayotter-installed.ini').exists() or not (root / 'data/config/app.json').is_file():
        raise MigrationError(tr('Mayotterの設定があるZIP版フォルダを選択してください。'))
    if root == destination or root in destination.parents or destination in root.parents:
        raise MigrationError(tr('移行元と移行先には別のフォルダを指定してください。'))
    _source_closed(root, destination)
    settings = _settings(root / 'data/config/app.json')
    files, directories, skipped = {}, set(), []

    def collect(directory, relative=Path()):
        if _linked(directory):
            raise MigrationError(tr('リンクやジャンクションを含むフォルダは移行できません。'))
        if relative.parts:
            directories.add(relative.as_posix())
        for path in directory.iterdir():
            if cancel is not None and cancel.is_set():
                raise MigrationCancelled()
            target = relative / path.name
            parts = [p.lower() for p in target.parts]
            if parts[0] in {'logs', 'temp', 'update_tmp', STATE_FILE, '.mayotter.lock'}:
                skipped.append(path)
                continue
            if path.name in {'SingletonLock', 'SingletonCookie', 'SingletonSocket', 'LOCK', 'LOG', 'LOG.old'}:
                skipped.append(path)
                continue
            if not include_cache and (parts[0] == 'cache' or
                    (parts[0] == 'profiles' and any(p in PROFILE_CACHES for p in parts[2:]))):
                skipped.append(path)
                continue
            if _linked(path):
                raise MigrationError(tr('リンクやジャンクションを含むフォルダは移行できません。'))
            if path.is_dir():
                collect(path, target)
            elif path.is_file():
                stat = path.stat()
                files[target.as_posix()] = (path, stat.st_size, stat.st_mtime_ns)
            else:
                raise MigrationError(tr('通常のファイル以外は移行できません。'))

    collect(root / 'data')
    for account in settings.get('accounts', []):
        aid = account['account_id']
        canonical = root / 'data/profiles' / aid
        if not canonical.is_dir():
            legacy = account.get('legacy_profile_path') or account.get('profile_path')
            if legacy is not None and not isinstance(legacy, str):
                raise MigrationError(tr('アカウントの保存形式が不正です。'))
            path = Path(legacy) if legacy else canonical
            if not path.is_absolute():
                path = root / path
            if (not path.is_dir() or path.name != aid or path.resolve() == destination
                    or destination in path.resolve().parents or path.resolve() in destination.parents):
                raise MigrationError(tr('アカウントの保存プロファイルが見つかりません。'))
            collect(path, Path('profiles') / aid)
    if (root / 'audio_visual').exists():
        if any(name.startswith('audio_visual/') for name in files):
            raise MigrationError(tr('音声画像の保存先が重複しています。'))
        collect(root / 'audio_visual', Path('audio_visual'))
    if not {'accounts', 'workspaces', 'columns', 'ui_language', 'ui_theme'}.intersection(settings):
        raise MigrationError(tr('Mayotterの設定があるZIP版フォルダを選択してください。'))
    return {'root': root, 'settings': settings, 'files': files, 'directories': directories, 'skipped': skipped,
            'size': sum(value[1] for value in files.values()), 'accounts': len(settings.get('accounts', []))}


def _stage_path(destination: Path, name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(re.escape('.' + destination.name + '-migration-') + '[0-9a-f]{32}', name):
        raise MigrationError(tr('移行記録を読み取れません。'))
    path = destination.parent / name
    if _linked(path):
        raise MigrationError(tr('移行記録を読み取れません。'))
    return path


def recover_migration(destination: Path) -> None:
    state = read_state(destination)
    if state.get('status') not in {'copying', 'committing'}:
        return
    stage = _stage_path(destination, state.get('stage'))
    if not stage.is_dir() or not (stage / 'payload').is_dir() or not (stage / 'backup').is_dir():
        raise MigrationError(tr('移行の一時領域が見つかりません。自動復旧できないため起動を中止します。'))
    if state['status'] == 'committing':
        if not isinstance(state.get('names'), list) or not isinstance(state.get('original'), list):
            raise MigrationError(tr('移行記録を読み取れません。'))
        for name in state['names']:
            if not isinstance(name, str) or Path(name).name != name or name in {'.', '..', STATE_FILE, '.mayotter.lock'} or ':' in name or '\\' in name:
                raise MigrationError(tr('移行記録を読み取れません。'))
            target, backup = destination / name, stage / 'backup' / name
            if backup.exists():
                if target.exists():
                    target.rename(stage / 'payload' / name)
                backup.rename(target)
            elif name not in state['original'] and not (stage / 'payload' / name).exists() and target.exists():
                target.rename(stage / 'payload' / name)
    if stage.exists():
        shutil.rmtree(stage)
    write_state(destination, {'status': 'failed'})


def _convert_paths(settings: dict, root: Path, destination: Path) -> dict:
    mapping = [(root / 'data', destination), (root / 'audio_visual', destination / 'audio_visual')]
    keys = {'recorded_audio_dir', 'cropped_visual_dir', 'audio_visual_image', 'audio_visual_image_original',
            'download_dir', 'profile_path', 'legacy_profile_path', 'path'}

    def convert(value, key=''):
        if isinstance(value, dict):
            result = {k: convert(v, k) for k, v in value.items()}
            if value.get('account_id'):
                for field in ('profile_path', 'legacy_profile_path'):
                    if field in result:
                        result[field] = str(destination / 'profiles' / value['account_id'])
            return result
        if isinstance(value, list):
            return [convert(v, key) for v in value]
        if key in keys and isinstance(value, str) and value and Path(value).is_absolute():
            path = Path(os.path.normpath(value))
            for old, new in mapping:
                if path == old or old in path.parents:
                    return str(new / path.relative_to(old))
        return value

    return convert(settings)


def migrate(root: Path, destination: Path, *, include_cache=False, replace_settings=False,
            cancel: Event | None = None, progress=lambda done, total: None) -> dict:
    destination = destination.resolve()
    cancel = cancel or Event()
    recover_migration(destination)
    if destination_has_data(destination):
        raise MigrationError(tr('移行先にユーザーデータがあります。上書きや統合は行いません。'))
    if (destination / 'config/app.json').exists() and not replace_settings:
        raise MigrationError(tr('移行先の設定の置き換えには同意が必要です。'))
    settings_path = destination / 'config/app.json'
    initial_settings = settings_path.read_bytes() if settings_path.exists() else None
    plan = scan_source(root, destination, include_cache, cancel)
    if shutil.disk_usage(destination.parent).free < plan['size'] + 64 * 1024 * 1024:
        raise MigrationError(tr('移行先の空き容量が不足しています。'))
    stage = _stage_path(destination, '.' + destination.name + '-migration-' + uuid4().hex)
    payload = stage / 'payload'
    payload.mkdir(parents=True)
    (stage / 'backup').mkdir()
    write_state(destination, {'status': 'copying', 'stage': stage.name})
    try:
        done, hashes = 0, {}
        for name in plan['directories']:
            (payload / name).mkdir(parents=True, exist_ok=True)
        for name, (source, size, mtime) in plan['files'].items():
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    if cancel.is_set():
                        raise MigrationCancelled()
                    outgoing.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done, plan['size'] * 2)
            if target.stat().st_size != size:
                raise MigrationError(tr('コピー中に移行元が変更されました。もう一度実行してください。'))
            with target.open('rb') as stream:
                copied = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    if cancel.is_set():
                        raise MigrationCancelled()
                    copied.update(chunk)
                if copied.hexdigest() != digest.hexdigest():
                    raise MigrationError(tr('コピー結果の検証に失敗しました。'))
            hashes[name] = digest.hexdigest()
        again = scan_source(plan['root'], destination, include_cache, cancel)
        if plan['files'] != again['files'] or plan['directories'] != again['directories']:
            raise MigrationError(tr('コピー中に移行元が変更されました。もう一度実行してください。'))
        for name, (source, size, _) in plan['files'].items():
            digest = hashlib.sha256()
            with source.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    if cancel.is_set():
                        raise MigrationCancelled()
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done, plan['size'] * 2)
            if digest.hexdigest() != hashes[name]:
                raise MigrationError(tr('コピー中に移行元が変更されました。もう一度実行してください。'))
        converted = _convert_paths(plan['settings'], plan['root'], destination)
        (payload / 'config/app.json').write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding='utf-8')
        if cancel.is_set():
            raise MigrationCancelled()
        _source_closed(plan['root'], destination)
        if destination_has_data(destination):
            raise MigrationError(tr('移行先にユーザーデータがあります。上書きや統合は行いません。'))
        if (settings_path.read_bytes() if settings_path.exists() else None) != initial_settings:
            raise MigrationError(tr('コピー中に移行先の設定が変更されました。もう一度実行してください。'))
        names = [p.name for p in payload.iterdir()]
        original = [name for name in names if (destination / name).exists()]
        write_state(destination, {'status': 'committing', 'stage': stage.name, 'names': names, 'original': original})
        for name in names:
            if name in original:
                (destination / name).rename(stage / 'backup' / name)
            (payload / name).rename(destination / name)
        result = {'status': 'complete', 'files': len(hashes), 'bytes': plan['size'], 'backup': str(stage / 'backup')}
        # 旧ZIP版の削除可否の判定用。何をどこから、どの内容でコピーしたかを残す
        record = {**result, 'source': str(plan['root']), 'include_cache': bool(include_cache),
                  'accounts_migrated': [a['account_id'] for a in plan['settings'].get('accounts', [])],
                  'migrated': {name: {'sha256': hashes[name], 'source': str(plan['files'][name][0])}
                               for name in hashes}}
        write_state(destination, record)
        return result
    except (OSError, ValueError, MigrationError, MigrationCancelled):
        recover_migration(destination)
        raise



class RemovalBlocked(MigrationError):
    """条件が恒久的に満たせない（リンク、開発フォルダ、移行後の変更など）。再確認しても変わらない。"""


# 旧ZIP版で Mayotter 自身が作る、配布物の外のファイル・フォルダ
_LEGACY_APP_ENTRIES = {'update_tmp', 'last_audio_dnd.log'}
_DEV_MARKERS = ('.git', 'pyproject.toml', 'src', 'tests', 'data_dev', 'audio_visual_dev')


def legacy_removal_pending(destination: Path) -> bool:
    """移行が完了していて、旧ZIP版の削除についてまだ利用者の判断がない。"""
    state = read_state(destination)
    return (state.get('status') == 'complete' and bool(state.get('source'))
            and isinstance(state.get('migrated'), dict) and 'cleanup' not in state)


def _sha256(path: Path, cancel: Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise MigrationCancelled()
            digest.update(chunk)
    return digest.hexdigest()


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _program_manifest(root: Path) -> dict[str, str]:
    files = {}
    for line in (root / 'program-files.sha256').read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'([a-fA-F0-9]{64})  (.+)', line)
        if not match:
            raise RemovalBlocked(tr('旧ZIP版のファイル一覧を読み取れません。'))
        relative = Path(match[2].replace('\\', '/'))
        if relative.is_absolute() or ':' in match[2] or '..' in relative.parts or not relative.parts:
            raise RemovalBlocked(tr('旧ZIP版のファイル一覧を読み取れません。'))
        files[relative.as_posix()] = match[1].lower()
    if 'Mayotter.exe' not in files:
        raise RemovalBlocked(tr('旧ZIP版のファイル一覧を読み取れません。'))
    return files


def _walk_files(root: Path) -> tuple[list[Path], list[Path]]:
    files, directories = [], []

    def walk(directory):
        for entry in directory.iterdir():
            if _linked(entry):
                raise RemovalBlocked(tr('リンクやジャンクションを含むフォルダは削除できません。'))
            if entry.is_dir():
                directories.append(entry)
                walk(entry)
            elif entry.is_file():
                files.append(entry)
            else:
                raise RemovalBlocked(tr('通常のファイル以外を含むため削除できません。'))

    walk(root)
    return files, directories


def plan_legacy_removal(destination: Path, *, protect=(), cancel: Event | None = None) -> dict:
    """削除してよいものだけを列挙する。1つでも安全が確認できなければ例外にし、何も削除しない。"""
    state = read_state(destination)
    if state.get('status') != 'complete' or not state.get('source') or not isinstance(state.get('migrated'), dict):
        raise RemovalBlocked(tr('移行の記録がないため、旧ZIP版は削除できません。'))
    source = Path(state['source'])
    if not source.is_dir():
        raise RemovalBlocked(tr('旧ZIP版のフォルダが見つかりません。'))
    if _linked(source):
        raise RemovalBlocked(tr('リンクやジャンクションを含むフォルダは削除できません。'))
    root, destination = source.resolve(), destination.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise RemovalBlocked(tr('削除対象が広すぎるため実行できません。'))
    for other in (destination, *[Path(p).resolve() for p in protect]):
        if _under(other, root) or _under(root, other):
            raise RemovalBlocked(tr('移行先やSetup版の本体と場所が重なっているため削除できません。'))
    if any((parent / '.git').exists() for parent in (root, *root.parents)) or any((root / m).exists() for m in _DEV_MARKERS):
        raise RemovalBlocked(tr('Gitリポジトリや開発用フォルダは削除できません。'))
    if (root / 'mayotter-installed.ini').exists() or not (root / 'Mayotter.exe').is_file() \
            or not (root / 'program-files.sha256').is_file():
        raise RemovalBlocked(tr('旧ZIP版のMayotterフォルダとして確認できないため削除できません。'))
    _source_closed(root)

    # 移行先の確認: 移行したファイルとアカウントのプロファイルが、Setup版の保存先にある
    migrated = state['migrated']
    for name in migrated:
        if not (destination / name).is_file():
            raise RemovalBlocked(tr('移行先に移行済みのファイルが見つからないため削除できません。'))
    try:
        accounts = {a.get('account_id') for a in json.loads(
            (destination / 'config/app.json').read_text(encoding='utf-8-sig')).get('accounts', [])}
    except (OSError, ValueError, AttributeError):
        raise RemovalBlocked(tr('移行先の設定を読み取れないため削除できません。'))
    for account in state.get('accounts_migrated', []):
        if account not in accounts or not (destination / 'profiles' / account).is_dir():
            raise RemovalBlocked(tr('移行先にアカウントのデータが見つからないため削除できません。'))

    all_files, directories = _walk_files(root)

    # 移行後に旧ZIP版のデータが変わっていない（コピーした内容のまま）
    current = scan_source(root, destination, bool(state.get('include_cache')), cancel)
    if set(current['files']) != set(migrated):
        raise RemovalBlocked(tr('移行後に旧ZIP版のデータが変更されているため削除できません。'))
    data_files = []
    for name, (path, size, mtime) in current['files'].items():
        if _sha256(path, cancel) != migrated[name]['sha256']:
            raise RemovalBlocked(tr('移行後に旧ZIP版のデータが変更されているため削除できません。'))
        if _under(path.resolve(), root):
            data_files.append(path)

    # 旧ZIP版の本体: 配布時のファイル一覧とハッシュが一致するものだけ
    program = _program_manifest(root)
    program_files = []
    for relative, expected in program.items():
        path = root / relative
        if path.is_file() and _sha256(path, cancel) == expected:
            program_files.append(path)
    program_files.append(root / 'program-files.sha256')

    # ログ・一時・キャッシュなど移行しなかった Mayotter 専用の項目
    skipped = []
    for entry in current['skipped']:
        if _under(entry.resolve(), root):
            skipped.extend(p for p in ([entry] if entry.is_file() else entry.rglob('*')) if p.is_file())
    for name in _LEGACY_APP_ENTRIES:
        entry = root / name
        if entry.is_file():
            skipped.append(entry)
        elif entry.is_dir():
            skipped.extend(p for p in entry.rglob('*') if p.is_file())

    planned = {*data_files, *program_files, *skipped}
    unknown = sorted(p for p in all_files if p not in planned)
    sizes = {p: p.stat().st_size for p in planned}
    return {'root': root, 'destination': destination, 'data_files': data_files, 'program_files': program_files,
            'other_files': skipped, 'unknown': unknown, 'directories': directories, 'sizes': sizes,
            'bytes': sum(sizes.values()), 'count': len(planned)}


def remove_legacy(plan: dict, *, cancel: Event | None = None, progress=lambda done, total: None) -> dict:
    """plan_legacy_removal の結果だけを削除する。親フォルダは削除しない。未知のファイルが残れば本体フォルダも残す。"""
    root, destination = plan['root'], plan['destination']
    _source_closed(root)
    ordered = [*plan['data_files'], *plan['other_files'], *plan['program_files']]
    done = 0
    try:
        for path in ordered:
            if cancel is not None and cancel.is_set():
                raise MigrationCancelled()
            if _linked(path) or not path.is_file() or path.stat().st_size != plan['sizes'][path]:
                raise MigrationError(tr('削除の直前にファイルが変更されました。'))
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
            path.unlink()
            done += 1
            progress(done, len(ordered))
    except (OSError, MigrationError, MigrationCancelled) as exc:
        state = read_state(destination)
        write_state(destination, {**state, 'cleanup': 'failed', 'cleanup_removed': done})
        raise MigrationError(tr('削除を途中で中止しました。Setup版のデータは影響を受けていません。\n{v0}', v0=str(exc)))
    for directory in sorted(plan['directories'], key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
    state = read_state(destination)
    write_state(destination, {**state, 'cleanup': 'removed', 'cleanup_removed': done,
                              'cleanup_left': [str(p) for p in plan['unknown']][:50]})
    return {'removed': done, 'left': len(plan['unknown']), 'root_removed': not root.exists()}


def decline_legacy_removal(destination: Path, reason: str = 'kept') -> None:
    state = read_state(destination)
    write_state(destination, {**state, 'cleanup': reason})
