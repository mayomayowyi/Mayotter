
from __future__ import annotations

import os
import sys

PERSONAL = "personal"
DEVELOPMENT = "development"
DISTRIBUTION = "distribution"

_ALIASES = {
    "personal": PERSONAL,
    "p": PERSONAL,
    "dev": DEVELOPMENT,
    "development": DEVELOPMENT,
    "dist": DISTRIBUTION,
    "distribution": DISTRIBUTION,
}

def get_edition() -> str:
    raw = (os.environ.get("MAYOTTER_EDITION") or "").strip().lower()
    if raw in _ALIASES:
        return _ALIASES[raw]
    if getattr(sys, "frozen", False):
        return DISTRIBUTION
    return PERSONAL

def is_development() -> bool:
    return get_edition() == DEVELOPMENT

