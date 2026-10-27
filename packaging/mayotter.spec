# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for Mayotter (Windows).
# Build from repo root via packaging\build_distribution.bat

import os
import sys
from pathlib import Path


SPECDIR = Path(SPECPATH).resolve()
ROOT = SPECDIR.parent
ENTRY = SPECDIR / "entry_mayotter.py"
# build_release.py が元ロゴから作ったマルチサイズ ICO（単体実行時は同梱の ICO）
ICON = Path(os.environ.get("MAYOTTER_ICON") or SPECDIR / "assets" / "mayotter.ico")

datas = []
binaries = []
hiddenimports = [
    "src",
    "src.app",
    "src.app.main",
    "src.core",
    "src.core.edition",
    "src.core.paths",
    "src.core.settings",
    "src.core.i18n",
    "src.core.translations_en",
    "src.core.translations_zh_cn",
    "src.ui.language_dialog",
    "src.ui.migration_dialog",
    "src.core.portable_migration",
    "src.app.restart",
    "src.core.updater",
    "src.core.version",
    "src.core.models",
    "src.core.single_instance",
    "src.browser",
    "src.browser.webview",
    "src.browser.profile_manager",
    "src.browser.url_policy",
    "src.browser.content_filter",
    "src.ui",
    "src.ui.main_window",
    "src.ui.account_column",
    "src.ui.theme",
    "src.ui.icons",
    "src.ui.edge_dock",
    "src.ui.url_overlay",
    "src.media",
    "src.media.ffmpeg_util",
    "src.media.media_converter",
    "src.media.recorder",
    "src.media.visual",
    "src.media.denoise",
    "src.media.selftest",
]

# Qt の公式 PyInstaller hooks が使用モジュールと WebEngine の依存だけを収集する。

# AI noise reduction runtime (onnxruntime + numpy). Pinned runtime wheels are staged
# through packaging/requirements-dist.txt. DeepFilterNet3 model and FFmpeg are
# installed beside the executable by packaging/stage_third_party.py.
PYDEPS = os.environ.get("MAYOTTER_PYDEPS", "").strip()
pathex = [str(ROOT)]
if PYDEPS:
    pathex.insert(0, PYDEPS)
    sys.path.insert(0, PYDEPS)
for _pkg in ("onnxruntime", "numpy"):
    try:
        _mod = __import__(_pkg)
        print(f"[spec] {_pkg} {getattr(_mod, '__version__', '?')} from {Path(_mod.__file__).parent}")
        hiddenimports.append(_pkg)
    except Exception as exc:
        if os.environ.get("MAYOTTER_REQUIRE_DENOISE") == "1":
            raise SystemExit(f"[spec] ERROR: {_pkg} is required for AI noise reduction: {exc}")
        print(f"[spec] WARNING: {_pkg} not available, AI noise reduction will be unavailable: {exc}")

# UI assets (spin buttons etc.)
ui_assets = ROOT / "src" / "ui" / "assets"
if ui_assets.is_dir():
    datas.append((str(ui_assets), "src/ui/assets"))
datas.append((str(ROOT / 'src/core/update_helper.ps1'), 'src/core'))

# App icon next to EXE for runtime QIcon as well
if ICON.is_file():
    datas.append((str(ICON), "."))

a = Analysis(
    [str(ENTRY)],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # CPU InferenceSession のみ使用。実験・学習用の PyTorch 連鎖は同梱しない。
        "onnxruntime.experimental",
        "onnxruntime.transformers",
        "onnxruntime.training",
        "pytest",
        "pytest_qt",
        "tkinter",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mayotter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ICON) if ICON.is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Mayotter",
)
