"""HTTPS fail-closed defaults for Mayotter's embedded QtWebEngine.

This module intentionally does not claim to replace Chromium's certificate
verifier or its revocation/CT updates. A certificateError signal is emitted
only for certificates the engine has *already* considered invalid.
"""

from __future__ import annotations

import re
import shlex


# Options which bypass the browser's TLS or origin protections. Refuse to
# launch with these rather than silently altering an externally supplied
# Chromium configuration. Do not log environment values: other flags can
# contain user-specific file paths or tokens.
_UNSAFE_FLAGS = frozenset({
    "--ignore-certificate-errors",
    "--ignore-certificate-errors-spki-list",
    "--allow-insecure-localhost",
    "--disable-web-security",
    "--allow-running-insecure-content",
    "--unsafely-treat-insecure-origin-as-secure",
    "--disable-site-isolation-trials",
    "--disable-features",
})
# When a feature list is supplied, only reject known protection disabling
# names; Chromium feature lists also carry unrelated performance switches.
_UNSAFE_FEATURE_NAMES = frozenset({
    "certificatetransparencyenforcement",
    "certificatetransparency",
    "certificateverifierbuiltinfeature",
    "certificateverifierbuiltin",
    "chrome-root-store-used",
})


def find_unsafe_chromium_flags(flags: str) -> tuple[str, ...]:
    """Return risky switch *names*, never their potentially sensitive values."""
    try:
        arguments = shlex.split(flags or "", posix=False)
    except ValueError:
        # Invalid quoting is not safe to silently reinterpret.
        return ("malformed Chromium flags",)
    unsafe = set()
    for arg in arguments:
        if not arg.startswith("--"):
            continue
        switch, _, value = arg.partition("=")
        name = switch.casefold()
        if name in _UNSAFE_FLAGS - {"--disable-features"}:
            unsafe.add(name)
        if name == "--disable-features":
            features = re.split(r"[,\s]+", value.casefold())
            if any(feat.split("<", 1)[0] in _UNSAFE_FEATURE_NAMES for feat in features):
                unsafe.add(name)
    return tuple(sorted(unsafe))


def require_safe_chromium_flags(flags: str) -> None:
    """Fail before creating QApplication if TLS bypass switches are present."""
    unsafe = find_unsafe_chromium_flags(flags)
    if unsafe:
        raise RuntimeError(
            "Mayotter refused unsafe Chromium startup options: "
            + ", ".join(unsafe)
        )


def reject_certificate_error(error) -> None:
    """Never expose an 'ignore HTTPS certificate error' escape hatch."""
    error.rejectCertificate()


def enforce_certificate_error_rejection(page) -> None:
    """Connect the fail-closed handler to every Mayotter-owned WebEngine page."""
    page.certificateError.connect(reject_certificate_error)
