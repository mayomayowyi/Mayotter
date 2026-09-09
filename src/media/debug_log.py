
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

def media_debug_enabled() -> bool:
    return bool(
        os.environ.get("MAYOTTER_MEDIA_DEBUG")
        or os.environ.get("MAYOTTER_COLUMN_DEBUG")
    )

def media_log_dir() -> Path:
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        p = Path(local) / "Mayotter" / "logs"
    else:
        home = Path.home()
        p = home / ".local" / "share" / "Mayotter" / "logs"
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return p
    except Exception:
        pass
    import tempfile

    p = Path(tempfile.gettempdir()) / "Mayotter" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p

def media_log_path() -> Path:
    return media_log_dir() / "media.log"

def media_debug(tag: str, message: str, *, force: bool = False) -> None:
    always_file = force or tag in ("ATTACH", "ATTACH_TIMING", "DT_POC", "CDP_POC", "MEDIA", "REC")
    if not media_debug_enabled() and not always_file:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{tag}] {message}"
    if media_debug_enabled():
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:
            pass
    if always_file or media_debug_enabled():
        try:
            path = media_log_path()
            with path.open("a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        except Exception:
            pass

