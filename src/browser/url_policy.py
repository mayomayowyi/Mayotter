
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, parse_qs, unquote

POLICY_DEFAULT_BROWSER = "default_browser"
POLICY_IN_APP = "in_app"
POLICY_ASK = "ask"
POLICY_VALUES = frozenset({POLICY_DEFAULT_BROWSER, POLICY_IN_APP, POLICY_ASK})
DEFAULT_EXTERNAL_SITE_POLICY = POLICY_DEFAULT_BROWSER

X_ALLOWED_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }
)

_BLOCKED_SCHEMES = frozenset(
    {
        "file",
        "javascript",
        "data",
        "blob",
        "chrome",
        "chrome-extension",
        "devtools",
        "qrc",
        "about",
    }
)

UrlKind = Literal["x", "external", "unsupported"]
NavAction = Literal["in_app", "external_browser", "ask", "block"]

_current_policy: str = DEFAULT_EXTERNAL_SITE_POLICY
_allowed_external_new_tab: bool = True
_user_allowed_external: list[dict] = []

def set_external_site_policy(policy: str) -> None:
    global _current_policy
    if policy not in POLICY_VALUES:
        policy = DEFAULT_EXTERNAL_SITE_POLICY
    _current_policy = policy

def get_external_site_policy() -> str:
    return _current_policy

def set_allowed_external_new_tab(enabled: bool) -> None:
    global _allowed_external_new_tab
    _allowed_external_new_tab = bool(enabled)

def get_allowed_external_new_tab() -> bool:
    return bool(_allowed_external_new_tab)

def normalize_policy_domain(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        if text.startswith("//"):
            text = "https:" + text
        else:
            text = "https://" + text
    try:
        parsed = urlsplit(text)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return ""
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return ""
    except ValueError:
        pass
    except Exception:
        return ""
    if "." not in host:
        return ""
    return host

def set_user_allowed_external(entries: list) -> None:
    global _user_allowed_external
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        domain = normalize_policy_domain(str(item.get("domain") or ""))
        if not domain or domain in seen:
            continue
        if is_google_official_host(domain) or is_grok_official_host(domain):
            continue
        seen.add(domain)
        name = str(item.get("name") or domain).strip() or domain
        cleaned.append({"name": name, "domain": domain})
    _user_allowed_external = cleaned

def get_user_allowed_external() -> list[dict]:
    return [dict(x) for x in _user_allowed_external]

def builtin_allowed_external_groups() -> list[tuple[str, list[str]]]:
    google = sorted(_GOOGLE_REGISTRABLE)
    grok_bases = sorted({h.removeprefix("www.") for h in _GROK_REGISTRABLE})
    return [
        ("Google関連", google),
        ("Grok", grok_bases),
    ]

def is_user_allowed_external_host(host: str) -> bool:
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    for entry in _user_allowed_external:
        base = (entry.get("domain") or "").lower().rstrip(".")
        if not base:
            continue
        if h == base or h.endswith("." + base):
            return True
    return False

def is_allowed_external_url(url) -> bool:
    text = normalize_url_string(url)
    if not text:
        return False
    try:
        parsed = urlsplit(text)
    except Exception:
        return False
    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    except Exception:
        pass
    return is_allowed_in_app_external_host(host)

def should_open_in_new_tab(url, is_link_click: bool = True) -> bool:
    kind = classify_url(url)
    if kind == "x":
        return bool(is_link_click)
    if is_allowed_external_url(url):
        return bool(_allowed_external_new_tab)
    return False

def _to_string(url) -> str:
    if url is None:
        return ""
    if isinstance(url, str):
        return url.strip()
    to_s = getattr(url, "toString", None)
    if callable(to_s):
        try:
            return str(to_s()).strip()
        except Exception:
            pass
    return str(url).strip()

def normalize_url_string(url) -> str:
    text = _to_string(url)
    if not text:
        return ""
    lower = text.lower()
    if "://" not in text:
        for blocked in ("javascript:", "data:", "blob:", "about:", "mailto:", "magnet:"):
            if lower.startswith(blocked):
                return text
        if text.startswith("//"):
            text = "https:" + text
        else:
            text = "https://" + text
    return text

_GOOGLE_REGISTRABLE = frozenset(
    {
        "google.com",
        "google.co.jp",
        "googleusercontent.com",
        "gstatic.com",
        "googleapis.com",
        "ggpht.com",
    }
)

def is_google_official_host(host: str) -> bool:
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    if h in _GOOGLE_REGISTRABLE:
        return True
    for base in _GOOGLE_REGISTRABLE:
        if h.endswith("." + base):
            return True
    return False

_GROK_REGISTRABLE = frozenset(
    {
        "grok.com",
        "www.grok.com",
        "x.ai",
        "www.x.ai",
    }
)

def is_grok_official_host(host: str) -> bool:
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    if h in _GROK_REGISTRABLE:
        return True
    for base in ("grok.com", "x.ai"):
        if h == base or h.endswith("." + base):
            return True
    return False

def is_allowed_in_app_external_host(host: str) -> bool:
    return (
        is_google_official_host(host)
        or is_grok_official_host(host)
        or is_user_allowed_external_host(host)
    )

def classify_url(url) -> UrlKind:
    text = normalize_url_string(url)
    if not text:
        return "unsupported"
    try:
        parsed = urlsplit(text)
    except Exception:
        return "unsupported"

    scheme = (parsed.scheme or "").lower()
    if not scheme:
        return "unsupported"
    if scheme in _BLOCKED_SCHEMES:
        return "unsupported"
    if scheme not in ("http", "https"):
        return "unsupported"

    host = (parsed.hostname or "").lower()
    if not host:
        return "unsupported"
    if host in X_ALLOWED_HOSTS:
        return "x"
    return "external"

def is_google_click_redirector(url) -> bool:
    text = normalize_url_string(url)
    if not text:
        return False
    try:
        parsed = urlsplit(text)
    except Exception:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not is_google_official_host(host):
        return False
    path = (parsed.path or "").lower()
    if path in ("/url", "/goto", "/aclk", "/imgres"):
        return True
    if path.startswith("/url") or path.startswith("/goto"):
        return True
    return False

def extract_google_redirect_target(url) -> str:
    text = normalize_url_string(url)
    if not text or not is_google_click_redirector(text):
        return ""
    try:
        parsed = urlsplit(text)
        qs = parse_qs(parsed.query)
    except Exception:
        return ""
    for key in ("q", "url", "imgurl", "adurl"):
        vals = qs.get(key) or []
        if not vals:
            continue
        cand = unquote(vals[0]).strip()
        if cand.startswith("https://") or cand.startswith("http://"):
            if is_google_click_redirector(cand):
                nested = extract_google_redirect_target(cand)
                return nested or cand
            return cand
    return ""

def decide_navigation(url, policy: str | None = None) -> NavAction:
    kind = classify_url(url)
    if kind == "unsupported":
        return "block"
    if kind == "x":
        return "in_app"

    if is_allowed_external_url(url) and get_allowed_external_new_tab():
        return "in_app"

    pol = policy if policy in POLICY_VALUES else get_external_site_policy()
    if pol == POLICY_IN_APP:
        return "in_app"
    if pol == POLICY_ASK:
        return "ask"
    return "external_browser"

def open_in_default_browser(url) -> bool:
    text = normalize_url_string(url)
    if not text:
        return False
    kind = classify_url(text)
    if kind == "unsupported":
        return False
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
    except Exception:
        return False
    q = QUrl(text)
    if not q.isValid():
        q = QUrl.fromUserInput(text)
    if not q.isValid():
        return False
    scheme = q.scheme().lower()
    if scheme not in ("http", "https"):
        return False
    return bool(QDesktopServices.openUrl(q))

def apply_webengine_security_settings(page_or_view) -> None:
    try:
        from PySide6.QtWebEngineCore import QWebEngineSettings
    except Exception:
        return
    try:
        settings = page_or_view.settings()
    except Exception:
        return
    if settings is None:
        return

    def _set(attr, value: bool) -> None:
        try:
            settings.setAttribute(attr, value)
        except Exception:
            pass

    if hasattr(QWebEngineSettings, "JavascriptEnabled"):
        _set(QWebEngineSettings.JavascriptEnabled, True)
    if hasattr(QWebEngineSettings, "LocalStorageEnabled"):
        _set(QWebEngineSettings.LocalStorageEnabled, True)
    if hasattr(QWebEngineSettings, "FullScreenSupportEnabled"):
        _set(QWebEngineSettings.FullScreenSupportEnabled, True)

    for name, value in (
        ("LocalContentCanAccessFileUrls", False),
        ("LocalContentCanAccessRemoteUrls", False),
        ("AllowRunningInsecureContent", False),
        ("NavigateOnDropEnabled", False),
        ("JavascriptCanAccessClipboard", True),
        ("JavascriptCanPaste", False),
        ("ErrorPageEnabled", True),
    ):
        if hasattr(QWebEngineSettings, name):
            _set(getattr(QWebEngineSettings, name), value)

    try:
        if hasattr(QWebEngineSettings, "UnknownUrlSchemePolicy") and hasattr(
            QWebEngineSettings, "DisallowUnknownUrlSchemes"
        ):
            settings.setUnknownUrlSchemePolicy(
                QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes
            )
    except Exception:
        pass
