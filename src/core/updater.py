
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.paths import APP_BASE_DIR
from src.core.version import APP_VERSION, is_newer, normalize_version

OFFICIAL_GITHUB_REPO = "mayomayowyi/Mayotter"

# update_tmp のみ
UPDATE_TMP_DIR = APP_BASE_DIR / "update_tmp"

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
    sha = _extract_sha256_from_text(body)
    if not sha:
        sha = _extract_sha256_from_text(str(data.get("name") or ""))
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
    preferred = []
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").lower()
        url = a.get("browser_download_url")
        if not url:
            continue
        if name.endswith(".zip") or "mayotter" in name:
            preferred.append(str(url))
    if preferred:
        return preferred[0]
    for a in assets:
        if isinstance(a, dict) and a.get("browser_download_url"):
            return str(a["browser_download_url"])
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

def ensure_update_tmp() -> Path:
    UPDATE_TMP_DIR.mkdir(parents=True, exist_ok=True)
    return UPDATE_TMP_DIR

def clear_update_tmp() -> None:
    if not UPDATE_TMP_DIR.exists():
        return
    try:
        resolved = UPDATE_TMP_DIR.resolve()
        base = APP_BASE_DIR.resolve()
        if resolved.name != "update_tmp":
            return
        if base not in resolved.parents and resolved != base / "update_tmp":
            if resolved.parent != base:
                return
        shutil.rmtree(resolved, ignore_errors=True)
    except Exception:
        pass

def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def download_release_asset(
    url: str,
    dest_name: str | None = None,
    progress_callback=None,
    expected_sha256: str | None = None,
) -> Path | None:
    ensure_update_tmp()
    name = dest_name or url.rsplit("/", 1)[-1] or "update.bin"
    if "?" in name:
        name = name.split("?", 1)[0]
    dest = UPDATE_TMP_DIR / name

    require_hash = not _is_dev_edition()
    if require_hash and not (expected_sha256 and str(expected_sha256).strip()):
        return None

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"Mayotter/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
            total = None
            try:
                cl = resp.headers.get("Content-Length")
                if cl is not None:
                    total = int(cl)
            except Exception:
                total = None
            received = 0
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                if progress_callback is not None:
                    try:
                        progress_callback(received, total)
                    except Exception:
                        pass
            if progress_callback is not None:
                try:
                    progress_callback(received, total if total is not None else received)
                except Exception:
                    pass

        if expected_sha256 and str(expected_sha256).strip():
            expect = str(expected_sha256).strip().lower()
            try:
                got = compute_file_sha256(dest)
            except Exception:
                try:
                    if dest.exists():
                        dest.unlink()
                except Exception:
                    pass
                return None
            if got != expect:
                try:
                    if dest.exists():
                        dest.unlink()
                except Exception:
                    pass
                return None
        elif require_hash:
            try:
                if dest.exists():
                    dest.unlink()
            except Exception:
                pass
            return None

        return dest
    except Exception:
        try:
            if dest.exists():
                dest.unlink()
        except Exception:
            pass
        return None

def mark_download_complete(path: Path, release: ReleaseInfo) -> Path:
    ensure_update_tmp()
    marker = UPDATE_TMP_DIR / "download_complete.json"
    payload = {
        "version": release.version,
        "file": str(path),
        "html_url": release.html_url,
        "note": "Apply manually or via future updater; data/ was not modified.",
    }
    if release.sha256:
        payload["sha256"] = release.sha256
    marker.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return marker

_SKIP_DIR_NAMES = frozenset(
    {
        "data",
        "data_dev",
        "update_tmp",
        ".git",
        "__pycache__",
        "profiles",
    }
)

def extract_release_zip(zip_path: Path, dest_dir: Path | None = None) -> Path | None:
    import zipfile

    ensure_update_tmp()
    if dest_dir is None:
        dest_dir = UPDATE_TMP_DIR / "extract"
    try:
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            dest_resolved = dest_dir.resolve()
            for info in zf.infolist():
                target = (dest_dir / info.filename).resolve()
                if dest_resolved not in target.parents and target != dest_resolved:
                    return None
            zf.extractall(dest_dir)
        return dest_dir
    except Exception:
        try:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
        except Exception:
            pass
        return None

def find_staged_app_root(extract_dir: Path) -> Path | None:
    if not extract_dir or not extract_dir.is_dir():
        return None
    for name in ("Mayotter.exe", "Mayotter"):
        if (extract_dir / name).is_file():
            return extract_dir
    try:
        for child in extract_dir.iterdir():
            if not child.is_dir():
                continue
            if (child / "Mayotter.exe").is_file() or (child / "Mayotter").is_file():
                return child
    except Exception:
        pass
    try:
        for p in extract_dir.rglob("Mayotter.exe"):
            return p.parent
    except Exception:
        pass
    return None

def install_dir_for_running_app() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(APP_BASE_DIR).resolve()


def write_windows_apply_script(
    *,
    parent_pid: int,
    staged_root: Path,
    install_dir: Path,
    exe_name: str = "Mayotter.exe",
) -> Path | None:
    ensure_update_tmp()
    script = UPDATE_TMP_DIR / "apply_update.bat"
    src = str(staged_root.resolve())
    dst = str(install_dir.resolve())
    exe = str((install_dir / exe_name).resolve())
    content = f"""@echo off
setlocal EnableExtensions
set "PID={int(parent_pid)}"
set "SRC={src}"
set "DST={dst}"
set "EXE={exe}"
echo [Mayotter updater] waiting for PID %PID% ...
:waitloop
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:"%PID%" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto waitloop
)
echo [Mayotter updater] applying files ...
if not exist "%SRC%" (
  echo [Mayotter updater] missing staged source
  exit /b 1
)
rem /XD excludes user data and staging dirs
robocopy "%SRC%" "%DST%" /E /XD data data_dev update_tmp /R:2 /W:1 /NFL /NDL /NJH /NJS /NC /NS
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo [Mayotter updater] robocopy failed RC=%RC%
  exit /b 1
)
if exist "%EXE%" (
  start "" "%EXE%"
) else (
  echo [Mayotter updater] exe missing: %EXE%
  exit /b 1
)
endlocal
exit /b 0
"""
    try:
        script.write_text(content, encoding="utf-8")
        return script
    except Exception:
        return None


def launch_apply_helper(script_path: Path) -> bool:
    import sys
    import subprocess

    if not script_path or not Path(script_path).is_file():
        return False
    try:
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(
                ["cmd.exe", "/c", str(Path(script_path).resolve())],
                cwd=str(Path(script_path).resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
            return True
        return False
    except Exception:
        return False


def prepare_and_launch_self_update(
    zip_path: Path,
    *,
    parent_pid: int | None = None,
    exe_name: str = "Mayotter.exe",
) -> tuple[bool, str]:
    import os

    if parent_pid is None:
        parent_pid = os.getpid()
    extracted = extract_release_zip(Path(zip_path))
    if extracted is None:
        return False, "ZIPの展開に失敗しました。"
    staged = find_staged_app_root(extracted)
    if staged is None:
        return False, "更新パッケージにMayotter本体が見つかりません。"
    install = install_dir_for_running_app()
    script = write_windows_apply_script(
        parent_pid=int(parent_pid),
        staged_root=staged,
        install_dir=install,
        exe_name=exe_name,
    )
    if script is None:
        return False, "更新ヘルパーの作成に失敗しました。"
    if not launch_apply_helper(script):
        return False, "更新ヘルパーの起動に失敗しました。"
    return True, "更新を適用しています。アプリを再起動します…"
