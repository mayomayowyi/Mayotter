
from __future__ import annotations
from src.core.i18n import tr

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
from uuid import uuid4
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.paths import APP_BASE_DIR, DATA_DIR, IS_INSTALLED
from src.core.version import APP_VERSION, is_newer, normalize_version

OFFICIAL_GITHUB_REPO = "mayomayowyi/Mayotter"
UPDATE_TMP_DIR = (DATA_DIR if IS_INSTALLED else APP_BASE_DIR) / "update_tmp"
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7A299DDE-FA63-4A6C-A257-C9EF9894F35C}_is1'

_SHA256_RE = re.compile(
    r"(?i)(?:sha[-_]?256|checksum)\s*[:=\s]\s*([0-9a-f]{64})\b"
)

@dataclass
class ReleaseInfo:
    version: str
    name: str
    body: str
    html_url: str
    download_url: str | None
    sha256: str | None = None

def _is_dev_edition() -> bool:
    try:
        from src.core.edition import is_development
        return is_development()
    except Exception:
        return False

def _github_repo_env() -> str:
    return (os.environ.get("MAYOTTER_GITHUB_REPO") or "").strip()

def resolve_github_repo(settings_repo: str = "") -> str:
    if not _is_dev_edition():
        return OFFICIAL_GITHUB_REPO
    return (settings_repo or "").strip() or _github_repo_env() or OFFICIAL_GITHUB_REPO

def _extract_sha256_from_text(text: str) -> str | None:
    if not text:
        return None
    m = _SHA256_RE.search(text)
    if m:
        return m.group(1).lower()
    return None

def fetch_latest_release(
    *,
    github_repo: str = "",
    timeout: float = 15.0,
) -> ReleaseInfo | None:
    if _is_dev_edition():
        manifest = (os.environ.get("MAYOTTER_UPDATE_MANIFEST") or "").strip()
        if manifest:
            return _from_local_manifest(Path(manifest))

    repo = resolve_github_repo(github_repo)
    if not repo or "/" not in repo:
        return None

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Mayotter/{APP_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    tag = normalize_version(str(data.get("tag_name") or data.get("name") or ""))
    if not tag:
        return None
    body = str(data.get("body") or "")
    asset_url = _pick_asset_url(data)
    assets = [item for item in (data.get('assets') or []) if isinstance(item, dict)]
    asset = next((item for item in assets if item.get('browser_download_url') == asset_url), {})
    digest = str(asset.get('digest') or '')
    sha = digest[7:].lower() if re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest) else None
    if not sha and asset_url:
        filename = asset_url.rsplit('/', 1)[-1]
        line = next((line for line in body.splitlines() if filename in line), '')
        match = re.search(r'\b[0-9a-fA-F]{64}\b', line)
        sha = match.group(0).lower() if match else None
    single_asset = len([a for a in assets if str(a.get('name', '')).lower().endswith(('.zip', '.exe'))]) <= 1
    if not sha and single_asset:
        sha = _extract_sha256_from_text(body)
    if not sha and single_asset:
        sha = _extract_sha256_from_text(str(data.get("name") or ""))
    if not sha and asset_url:
        sums = next((a for a in assets if a.get('name') == 'SHA256SUMS.txt'), None)
        if sums:
            try:
                request = urllib.request.Request(sums['browser_download_url'], headers={'User-Agent': f'Mayotter/{APP_VERSION}'})
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    lines = response.read(65537)
                if len(lines) <= 65536:
                    for line in lines.decode('utf-8-sig').splitlines():
                        match = re.fullmatch(r'([0-9a-fA-F]{64})  (.+)', line)
                        if match and match[2] == str(asset.get('name')):
                            sha = match[1].lower()
            except (OSError, ValueError, KeyError, UnicodeError):
                pass
    return ReleaseInfo(
        version=tag,
        name=str(data.get("name") or tag),
        body=body,
        html_url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        download_url=asset_url,
        sha256=sha,
    )

def _from_local_manifest(path: Path) -> ReleaseInfo | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    ver = normalize_version(str(data.get("version") or data.get("tag_name") or ""))
    if not ver:
        return None
    raw_sha = data.get("sha256") or data.get("sha256_hex") or data.get("checksum")
    sha = None
    if raw_sha:
        s = str(raw_sha).strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", s):
            sha = s
    return ReleaseInfo(
        version=ver,
        name=str(data.get("name") or ver),
        body=str(data.get("body") or data.get("notes") or ""),
        html_url=str(data.get("html_url") or ""),
        download_url=(str(data["download_url"]) if data.get("download_url") else None),
        sha256=sha,
    )

def _pick_asset_url(release: dict[str, Any]) -> str | None:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").lower()
        url = a.get("browser_download_url")
        if not url:
            continue
        pattern = r'mayotter_setup_v[0-9][\w.\-]*_windows_x64\.exe' if IS_INSTALLED else r'mayotter_v[0-9][\w.\-]*_windows_x64\.zip'
        if re.fullmatch(pattern, name):
            return str(url)
    return None

def check_for_update(
    *,
    current_version: str | None = None,
    github_repo: str = "",
) -> ReleaseInfo | None:
    cur = current_version or APP_VERSION
    info = fetch_latest_release(github_repo=github_repo)
    if info is None:
        return None
    if is_newer(info.version, cur):
        return info
    return None

def _reject_links(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'Linked path is not allowed: {item}')


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def update_in_progress() -> bool:
    lock = UPDATE_TMP_DIR / 'active.json'
    if not lock.exists():
        return False
    try:
        _reject_links(lock)
        return _process_alive(int(json.loads(lock.read_text(encoding='utf-8-sig'))['pid']))
    except (OSError, ValueError, KeyError, TypeError):
        return True


def _owned_job(job: Path) -> dict:
    _reject_links(job)
    if job.absolute().parent != UPDATE_TMP_DIR.absolute() or not re.fullmatch(r'job-[0-9a-f]{32}', job.name):
        raise ValueError('Not an update session')
    owner = json.loads((job / 'owner.json').read_text(encoding='utf-8-sig'))
    if owner.get('token') != job.name[4:] or owner.get('application') != 'Mayotter':
        raise ValueError('Update ownership mismatch')
    return owner


def ensure_update_tmp() -> Path:
    _reject_links(UPDATE_TMP_DIR)
    UPDATE_TMP_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    job = UPDATE_TMP_DIR / ('job-' + token)
    job.mkdir()
    owner = {'application': 'Mayotter', 'token': token, 'pid': os.getpid()}
    (job / 'owner.json').write_text(json.dumps(owner), encoding='utf-8')
    return job


def discard_update(job: Path) -> None:
    owner = _owned_job(job)
    if owner['pid'] != os.getpid() and _process_alive(int(owner['pid'])):
        raise ValueError('Update session is in use')
    # ジャンクションを削除対象の中にも許可しない。
    for folder, dirs, files in os.walk(job, followlinks=False):
        for name in dirs + files:
            _reject_links(Path(folder) / name)
    lock = UPDATE_TMP_DIR / 'active.json'
    if lock.exists():
        _reject_links(lock)
        active = json.loads(lock.read_text(encoding='utf-8-sig'))
        if active.get('token') == owner['token']:
            if int(active['pid']) != os.getpid() and _process_alive(int(active['pid'])):
                raise ValueError('Update helper is in use')
            lock.unlink()
    shutil.rmtree(job)


def clear_update_tmp() -> None:
    if not UPDATE_TMP_DIR.exists():
        return
    _reject_links(UPDATE_TMP_DIR)
    for job in UPDATE_TMP_DIR.glob('job-*'):
        try:
            if not any(job.iterdir()) and time.time() - job.stat().st_mtime > 60:
                # 終了時の後始末で中身だけ消えた空ジョブ。所有確認はできないが、
                # 中身がなく作成から1分以上経過していれば、失敗した残骸だけを回収する。
                shutil.rmtree(job)
                continue
            owner = _owned_job(job)
            if (job / 'needs-recovery').exists():
                continue
            if not _process_alive(int(owner['pid'])):
                discard_update(job)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # 所有を確認できないフォルダには触れない。


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download_release_asset(url: str, dest_name: str | None = None,
                           progress_callback=None, expected_sha256: str | None = None) -> Path | None:
    from urllib.parse import urlsplit, unquote
    name = dest_name or unquote(urlsplit(url).path.rsplit('/', 1)[-1])
    if not name or name in {'.', '..'} or any(c in name for c in '/\\:'):
        return None
    if not expected_sha256 or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
        return None
    if not _is_dev_edition() and urlsplit(url).scheme != 'https':
        return None
    clear_update_tmp()
    if update_in_progress() or any(UPDATE_TMP_DIR.glob('job-*/needs-recovery')):
        return None
    job = ensure_update_tmp()
    owner = _owned_job(job)
    lock = UPDATE_TMP_DIR / 'active.json'
    try:
        with lock.open('x', encoding='utf-8') as stream:
            json.dump(owner, stream)
    except FileExistsError:
        discard_update(job)
        return None
    dest = job / name
    try:
        request = urllib.request.Request(url, headers={'User-Agent': f'Mayotter/{APP_VERSION}'})
        with urllib.request.urlopen(request, timeout=120) as response, dest.open('xb') as output:
            if not _is_dev_edition() and urlsplit(response.geturl()).scheme != 'https':
                raise ValueError('Insecure redirect')
            total = int(response.headers.get('Content-Length', 0)) or None
            received = 0
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                received += len(chunk)
                if progress_callback:
                    progress_callback(received, total)
            if total is not None and received != total:
                raise ValueError('Incomplete download')
        if compute_file_sha256(dest) != expected_sha256.lower():
            raise ValueError('Download hash mismatch')
        (job / 'download.json').write_text(json.dumps({'file': name, 'sha256': expected_sha256.lower()}), encoding='utf-8')
        return dest
    except (OSError, ValueError, urllib.error.URLError):
        discard_update(job)
        return None


def mark_download_complete(path: Path, release: ReleaseInfo) -> Path:
    _owned_job(path.parent)
    marker = path.parent / 'release.json'
    marker.write_text(json.dumps({'version': release.version, 'sha256': release.sha256}, ensure_ascii=False), encoding='utf-8')
    return marker


_SKIP_DIR_NAMES = frozenset({'data', 'data_dev', 'update_tmp', '.git', '__pycache__',
                            'profiles', 'recordings', 'audio_visual', 'audio_visual_dev', 'cache', 'logs', 'tests',
                            'mayotter-installed.ini', 'unins000.exe', 'unins000.dat'})


def _safe_relative(name: str) -> Path:
    from pathlib import PureWindowsPath
    parts = name.replace('\\', '/').split('/')
    path = PureWindowsPath(name)
    if path.is_absolute() or path.drive or not parts or any(
            part in {'', '.', '..'} or ':' in part or part.endswith(('.', ' ')) or
            part.lower() in _SKIP_DIR_NAMES or re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', part) or
            re.search(r'[<>"|?*\x00-\x1f]', part) for part in parts):
        raise ValueError(f'Unsafe program path: {name}')
    return Path(*parts)


def extract_release_zip(zip_path: Path, dest_dir: Path | None = None) -> Path | None:
    import zipfile
    try:
        _owned_job(zip_path.parent)
        dest_dir = dest_dir or zip_path.parent / 'extract'
        if dest_dir.parent != zip_path.parent or dest_dir.exists():
            raise ValueError('Extraction target is not empty')
        with zipfile.ZipFile(zip_path) as archive:
            names = set()
            for info in archive.infolist():
                relative = _safe_relative(info.filename.rstrip('/'))
                key = str(relative).casefold()
                if key in names or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('Duplicate or linked ZIP entry')
                names.add(key)
            dest_dir.mkdir()
            for info in archive.infolist():
                target = dest_dir / _safe_relative(info.filename.rstrip('/'))
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open('xb') as output:
                        shutil.copyfileobj(source, output)
        return dest_dir
    except (OSError, ValueError, zipfile.BadZipFile):
        return None


def find_staged_app_root(extract_dir: Path) -> Path | None:
    if (extract_dir / 'Mayotter.exe').is_file():
        return extract_dir
    children = list(extract_dir.iterdir())
    if len(children) == 1 and children[0].is_dir() and (children[0] / 'Mayotter.exe').is_file():
        return children[0]
    return None


def verify_program_manifest(root: Path) -> dict[str, str]:
    _reject_links(root)
    files = {}
    for line in (root / 'program-files.sha256').read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'([a-fA-F0-9]{64})  (.+)', line)
        if not match:
            raise ValueError('Invalid program manifest')
        relative = _safe_relative(match[2])
        key = relative.as_posix()
        if key.casefold() in {name.casefold() for name in files}:
            raise ValueError('Duplicate manifest entry')
        target = root / relative
        _reject_links(target)
        if compute_file_sha256(target) != match[1].lower():
            raise ValueError(f'Program hash mismatch: {key}')
        files[key] = match[1].lower()
    if 'Mayotter.exe' not in files:
        raise ValueError('Missing Mayotter.exe in manifest')
    return files


def running_app_location() -> tuple[Path, str]:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).absolute().parent, Path(sys.executable).name
    return Path(APP_BASE_DIR).absolute(), 'Mayotter.exe'


def install_dir_for_running_app() -> Path:
    return running_app_location()[0]


def validate_update_target(target: Path, *, installed: bool) -> None:
    _reject_links(target)
    target = target.absolute()
    if target == Path(target.anchor) or not (target / 'Mayotter.exe').is_file():
        raise ValueError('Not a Mayotter program directory')
    for parent in (target, *target.parents):
        if (parent / '.git').exists() or (parent / 'pyproject.toml').exists():
            raise ValueError('Development workspace cannot be updated')
        if parent.name.lower() in {'data', 'data_dev', 'profiles', 'recordings', 'audio_visual', 'audio_visual_dev'}:
            raise ValueError('User data directory cannot be updated')
    if (target / 'src').exists() or (target / 'data_dev').exists():
        raise ValueError('Development directory cannot be updated')
    for variable in ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'):
        base = os.environ.get(variable)
        if base and target.is_relative_to(Path(base).absolute()):
            raise ValueError('System directory cannot be updated')
    local = os.environ.get('LOCALAPPDATA')
    if local and target.is_relative_to(Path(local) / 'Mayotter'):
        raise ValueError('Program and user data must be separate')
    profile = os.environ.get('USERPROFILE')
    if profile and target == Path(profile) / 'Documents/Mayotter':
        raise ValueError('Protected workspace path')
    for file in target.iterdir():
        _reject_links(file)
        if file.suffix.lower() == '.exe' and file.name.lower() not in {'mayotter.exe', 'unins000.exe'}:
            raise ValueError('Another application is present')
    if installed:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            location = winreg.QueryValueEx(key, 'InstallLocation')[0]
        if Path(location).resolve() != target.resolve() or not (target / 'mayotter-installed.ini').is_file():
            raise ValueError('Installed location differs from registration')
    elif (target / 'mayotter-installed.ini').exists():
        raise ValueError('Installed edition requires Setup')


def write_windows_apply_script(*, parent_pid: int, staged_root: Path,
                               install_dir: Path, exe_name: str = 'Mayotter.exe') -> Path:
    job = staged_root
    _owned_job(job)
    script = job / 'apply_update.ps1'
    template = Path(__file__).with_name('update_helper.ps1')
    shutil.copyfile(template, script)
    return script


def launch_apply_helper(script_path: Path, env_extra: dict[str, str] | None = None) -> bool:
    import subprocess
    if sys.platform != 'win32':
        return False
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        process = subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                                    'Bypass', '-File', str(script_path)], cwd=script_path.parent,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW,
                                   env={**os.environ, **(env_extra or {})})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            if (script_path.parent / 'ready').exists():
                return True
            time.sleep(0.05)
        return False
    except OSError:
        return False



def _notice_style() -> dict:
    """更新中の進行ウィンドウをアプリの見た目（現在のテーマ色・UIフォント）に合わせるための値。"""
    try:
        from src.core.i18n import get_language
        from src.ui.theme import color
        # 簡体字は日本語フォントでは字形が変わるため、OS標準の中国語UIフォントを使う
        family = 'Microsoft YaHei UI' if get_language() == 'zh-CN' else 'Yu Gothic UI'
        return {'notice_bg': color('SURFACE'), 'notice_border': color('BORDER'), 'notice_fg': color('TEXT'),
                'notice_muted': color('TEXT_SECONDARY'), 'notice_accent': color('ACCENT_STRONG'),
                'notice_font': family}
    except Exception:
        return {}

def prepare_and_launch_self_update(zip_path: Path, *, parent_pid: int | None = None,
                                   exe_name: str | None = None) -> tuple[bool, str]:
    job = Path(zip_path).absolute().parent
    try:
        owner = _owned_job(job)
        download = json.loads((job / 'download.json').read_text(encoding='utf-8'))
        release = json.loads((job / 'release.json').read_text(encoding='utf-8'))
        if download['file'] != zip_path.name or compute_file_sha256(zip_path) != download['sha256']:
            raise ValueError('Downloaded package hash mismatch')
        install, running_exe = running_app_location()
        validate_update_target(install, installed=IS_INSTALLED)
        if (exe_name or running_exe) != 'Mayotter.exe':
            raise ValueError('Unexpected executable name')
        staged = None
        if IS_INSTALLED:
            if zip_path.suffix.lower() != '.exe':
                raise ValueError('Setup EXE required')
        else:
            extracted = extract_release_zip(zip_path)
            staged = find_staged_app_root(extracted) if extracted else None
            if staged is None:
                raise ValueError('Missing staged Mayotter')
            files = verify_program_manifest(staged)
            actual = {p.relative_to(staged).as_posix() for p in staged.rglob('*') if p.is_file()}
            if actual != set(files) | {'program-files.sha256'}:
                raise ValueError('Unmanifested program files')
        config = {**owner, 'parent_pid': parent_pid or os.getpid(), 'target': str(install),
                  'package': str(zip_path), 'sha256': download['sha256'], 'version': release['version'],
                  'installed': IS_INSTALLED, 'stage': str(staged) if staged else None,
                  'registry': UNINSTALL_KEY, 'restart': True,
                  # アプリ終了後も再起動まで表示する進行ウィンドウの文言（更新中だと分かるように）
                  'notice_title': tr('Mayotterを更新しています'),
                  'notice_text': tr('更新を適用しています。完了すると自動的に再起動します。\nそのままお待ちください（数分かかる場合があります）。'),
                  **_notice_style()}
        (job / 'apply.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        script = write_windows_apply_script(parent_pid=config['parent_pid'], staged_root=job, install_dir=install)
        if not launch_apply_helper(script):
            if update_in_progress() and json.loads((UPDATE_TMP_DIR / 'active.json').read_text(encoding='utf-8-sig')).get('pid') != os.getpid():
                return False, tr('更新ヘルパーの起動に失敗しました。')
            raise ValueError('Update helper failed to start')
        return True, tr('更新を適用しています。アプリを再起動します…')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        try:
            discard_update(job)
        except (OSError, ValueError, KeyError):
            pass
        return False, tr('更新処理に失敗しました。\n{v0}', v0=str(exc))
