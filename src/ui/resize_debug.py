from __future__ import annotations

import os
import sys
from typing import Any

_ENABLED: bool | None = None

def enabled() -> bool:
    global _ENABLED
    if _ENABLED is None:
        v = os.environ.get("MAYOTTER_RESIZE_DEBUG", "").strip().lower()
        _ENABLED = v in ("1", "true", "yes", "on")
    return _ENABLED

def log(tag: str, **fields: Any) -> None:
    if not enabled():
        return
    parts = [f"[RESIZE DEBUG] {tag}"]
    for k, v in fields.items():
        parts.append(f"{k}={v!r}")
    print(" ".join(parts), file=sys.stderr, flush=True)
