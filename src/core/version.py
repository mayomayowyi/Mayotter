
from __future__ import annotations

import os

# 正式版。Build / 通常起動はこの値を使う
APP_VERSION = "1.0.5"

# 開発用 bat が MAYOTTER_APP_VERSION=1.0.0 を渡したときだけ実行時に上書き
_dev_ver = (os.environ.get("MAYOTTER_APP_VERSION") or "").strip().strip('"').strip("'")
if _dev_ver == "1.0.0":
    APP_VERSION = "1.0.0"

def normalize_version(text: str) -> str:
    s = (text or "").strip()
    if s.lower().startswith("v"):
        s = s[1:]
    if "+" in s:
        s = s.split("+", 1)[0]
    return s.strip()

def parse_version_tuple(text: str) -> tuple[int, ...]:
    s = normalize_version(text)
    parts: list[int] = []
    for chunk in s.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while parts and parts[-1] == 0 and len(parts) > 1:
        parts.pop()
    return tuple(parts) if parts else (0,)

def is_newer(candidate: str, current: str) -> bool:
    try:
        return parse_version_tuple(candidate) > parse_version_tuple(current)
    except Exception:
        return False
