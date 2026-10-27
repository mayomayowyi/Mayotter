"""Start the source edition with visible diagnostics when a GUI startup fails."""

from __future__ import annotations
from src.core.i18n import tr

import ctypes
import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path


def _log_file() -> Path | None:
    base = Path(__file__).resolve().parents[2]
    edition = (os.environ.get("MAYOTTER_EDITION") or "personal").strip().lower()
    folder = "data_dev" if edition == "development" else "data"
    candidates = [
        base / folder / "logs" / "startup.log",
        Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "Mayotter" / "startup.log",
    ]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8"):
                pass
            return path
        except OSError:
            continue
    return None


def _show_failure(path: Path | None, detail: str) -> None:
    from src.core.i18n import set_language
    from src.core.settings import SettingsManager
    set_language(SettingsManager().get_ui_language())
    message = (
        tr('Mayotterの起動に失敗しました。\n\n')
        + (tr('エラーログ: {v0}\n\n', v0=path) if path else tr('ログファイルを作成できませんでした。\n\n'))
        + detail[-500:]
    )
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, tr('Mayotter 起動エラー'), 0x10 | 0x40000)
            return
        except Exception:
            pass
    print(message, file=sys.__stderr__ or sys.stderr)


def main() -> int:
    path = _log_file()
    if path is None:
        try:
            from src.app.main import main as run
            return int(run())
        except Exception:
            detail = traceback.format_exc()
            _show_failure(None, detail)
            return 1

    # pythonw has no console. Keep the log open for Python exceptions and native
    # failures reported by faulthandler, without changing existing application data.
    with path.open("a", encoding="utf-8", buffering=1) as log:
        previous_out, previous_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = log
        try:
            import faulthandler
            faulthandler.enable(file=log, all_threads=True)
        except Exception:
            pass
        try:
            print(f"[{datetime.now().isoformat(timespec='seconds')}] start: {sys.executable} ({sys.version.split()[0]})", flush=True)
            try:
                from importlib.metadata import PackageNotFoundError, version
                for name in ("PySide6", "PySide6-Addons", "shiboken6"):
                    try:
                        print(f"[Mayotter] {name}={version(name)}", flush=True)
                    except PackageNotFoundError:
                        print(f"[Mayotter] {name}=not installed", flush=True)
            except Exception:
                pass
            print(f"[Mayotter] native_filter_disabled={os.environ.get('MAYOTTER_DISABLE_NATIVE_FILTER') == '1'}", flush=True)
            from src.app.main import main as run
            code = int(run())
            print(f"[{datetime.now().isoformat(timespec='seconds')}] exit: {code}", flush=True)
            return code
        except Exception:
            detail = traceback.format_exc()
            print(detail, file=log, flush=True)
            _show_failure(path, detail)
            return 1
        finally:
            sys.stdout, sys.stderr = previous_out, previous_err
            try:
                faulthandler.disable()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
