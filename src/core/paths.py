
from __future__ import annotations

import sys
from pathlib import Path

def _get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]

def _edition_name() -> str:
    try:
        from src.core.edition import get_edition
        return get_edition()
    except Exception:
        return "personal"

def _data_dir_for_edition(base: Path, edition: str) -> Path:
    if edition == "development":
        return base / "data_dev"
    return base / "data"

def _audio_visual_for_edition(base: Path, edition: str) -> Path:
    if edition == "development":
        return base / "audio_visual_dev"
    return base / "audio_visual"

APP_BASE_DIR = _get_app_base_dir()
_EDITION = _edition_name()
DATA_DIR = _data_dir_for_edition(APP_BASE_DIR, _EDITION)
PROFILES_DIR = DATA_DIR / "profiles"
CONFIG_DIR = DATA_DIR / "config"
CACHE_DIR = DATA_DIR / "cache"
TEMP_DIR = DATA_DIR / "temp"
MEDIA_TEMP_DIR = TEMP_DIR / "media"
LOGS_DIR = DATA_DIR / "logs"
RECORDINGS_DIR = DATA_DIR / "recordings"
AUDIO_VISUAL_DIR = _audio_visual_for_edition(APP_BASE_DIR, _EDITION)
SETTINGS_FILE = CONFIG_DIR / "app.json"
UPDATE_TMP_DIR = APP_BASE_DIR / "update_tmp"

def default_recordings_dir() -> Path:
    return RECORDINGS_DIR

def default_audio_visual_dir() -> Path:
    return AUDIO_VISUAL_DIR

def ensure_directories() -> None:
    for d in (
        PROFILES_DIR,
        CONFIG_DIR,
        CACHE_DIR,
        MEDIA_TEMP_DIR,
        LOGS_DIR,
        RECORDINGS_DIR,
        AUDIO_VISUAL_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)

def default_downloads_dir() -> Path:
    import os
    home = Path.home()
    user_profile = os.environ.get("USERPROFILE") or str(home)
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            fid = GUID(
                0x374DE290, 0x123F, 0x4565,
                (wintypes.BYTE * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
            )
            path_ptr = ctypes.c_wchar_p()
            hr = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(path_ptr)
            )
            if hr == 0 and path_ptr.value:
                p = Path(path_ptr.value)
                try:
                    ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                except Exception:
                    pass
                return p
    except Exception:
        pass
    candidate = Path(user_profile) / "Downloads"
    if candidate.is_dir():
        return candidate
    xdg = os.environ.get("XDG_DOWNLOAD_DIR")
    if xdg:
        return Path(xdg)
    return home / "Downloads"
