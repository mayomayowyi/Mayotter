"""PyInstaller entry for Mayotter (onedir).

Keeps import path rooted at the project so `src.*` resolves the same as
`python -m src.app.main`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare() -> None:
    # Frozen: PyInstaller sets sys.frozen; edition defaults to distribution.
    if getattr(sys, "frozen", False):
        os.environ.setdefault("MAYOTTER_EDITION", "distribution")
        # PyInstaller 6 onedir usually puts QtWebEngineProcess under _internal/.
        base = Path(sys.executable).resolve().parent
        for cand in (
            base / "QtWebEngineProcess.exe",
            base / "_internal" / "QtWebEngineProcess.exe",
            base / "PySide6" / "QtWebEngineProcess.exe",
            base / "_internal" / "PySide6" / "QtWebEngineProcess.exe",
        ):
            if cand.is_file():
                os.environ["QTWEBENGINEPROCESS_PATH"] = str(cand)
                break
    else:
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))


_prepare()

# AI ノイズ除去の別プロセス（本体が音声投稿の変換時だけ起動する）。Qt を読み込む前に分岐する
if len(sys.argv) > 1 and sys.argv[1] == "--mayotter-denoise":
    from src.media.denoise import cli_main  # noqa: E402

    raise SystemExit(cli_main(sys.argv[2:]))

# 配布物の自己診断（同梱の FFmpeg / AI ノイズ除去で変換できるか）。利用者のデータには触れない
if len(sys.argv) > 1 and sys.argv[1] == "--mayotter-selftest":
    from src.media.selftest import cli_main as selftest_main  # noqa: E402

    raise SystemExit(selftest_main(sys.argv[2:]))

from src.app.main import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
