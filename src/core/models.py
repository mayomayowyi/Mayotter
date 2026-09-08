
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote, urlparse
from uuid import uuid4

GROK_HOME_URL = "https://grok.com/"

SOURCE_TYPE_HOME = "home"
SOURCE_TYPE_NOTIFICATIONS = "notifications"
SOURCE_TYPE_FAVORITES = "favorites"
SOURCE_TYPE_SAVED = "saved"
SOURCE_TYPE_PROFILE = "profile"
SOURCE_TYPE_LISTS = "lists"
SOURCE_TYPE_SEARCH = "search"
SOURCE_TYPE_DIRECT_MESSAGES = "direct_messages"
SOURCE_TYPE_GROK = "grok"

SOURCE_TYPE_URL = "url"
SOURCE_TYPE_LIST = "list"
SOURCE_TYPE_USER = "user"
SOURCE_TYPE_BOOKMARKS = "bookmarks"
SOURCE_TYPE_MENTIONS = "mentions"
SOURCE_TYPE_LIKES = "likes"

COLUMN_PRESETS: tuple[str, ...] = (
    SOURCE_TYPE_HOME,
    SOURCE_TYPE_NOTIFICATIONS,
    SOURCE_TYPE_FAVORITES,
    SOURCE_TYPE_PROFILE,
    SOURCE_TYPE_LISTS,
    SOURCE_TYPE_SEARCH,
    SOURCE_TYPE_DIRECT_MESSAGES,
    SOURCE_TYPE_GROK,
)

COLUMN_PRESET_LABELS: dict[str, str] = {
    SOURCE_TYPE_HOME: "ホーム",
    SOURCE_TYPE_NOTIFICATIONS: "通知",
    SOURCE_TYPE_FAVORITES: "お気に入り",
    SOURCE_TYPE_SAVED: "お気に入り",
    SOURCE_TYPE_PROFILE: "プロフィール",
    SOURCE_TYPE_LISTS: "リスト",
    SOURCE_TYPE_SEARCH: "検索",
    SOURCE_TYPE_DIRECT_MESSAGES: "ダイレクトメッセージ",
    SOURCE_TYPE_GROK: "Grok",
}

_SOURCE_TYPES_NEEDING_INPUT = frozenset({
    SOURCE_TYPE_SEARCH,
})

FAVORITES_ENTRY_URL = "https://x.com/i/bookmarks"
SAVED_ENTRY_URL = FAVORITES_ENTRY_URL

LISTS_ENTRY_URL = "https://x.com/i/lists"
DM_ENTRY_URL = "https://x.com/messages"
X_GROK_ENTRY_URL = "https://x.com/i/grok"

_COLUMN_TYPE_MIGRATION: dict[str, str] = {
    "likes": SOURCE_TYPE_FAVORITES,
    "bookmarks": SOURCE_TYPE_FAVORITES,
    "saved": SOURCE_TYPE_FAVORITES,
    "mentions": SOURCE_TYPE_NOTIFICATIONS,
    "list": SOURCE_TYPE_LISTS,
    "user": SOURCE_TYPE_PROFILE,
}

def migrate_column_type(column_type: str) -> str:
    if not column_type:
        return SOURCE_TYPE_HOME
    return _COLUMN_TYPE_MIGRATION.get(column_type, column_type)

def _is_grok_url(url: str) -> bool:
    return "grok.com" in (url or "")

def resolve_source_url(column_type: str, account_initial_url: str = "", source_url: str = "") -> str:
    column_type = migrate_column_type(column_type)

    if _is_grok_url(account_initial_url):
        if column_type == SOURCE_TYPE_URL and source_url:
            return source_url
        return account_initial_url or GROK_HOME_URL

    base = "https://x.com"

    if column_type == SOURCE_TYPE_HOME:
        return f"{base}/"
    if column_type == SOURCE_TYPE_URL and source_url:
        return source_url
    if column_type == SOURCE_TYPE_SEARCH and source_url:
        return f"{base}/search?q={quote(source_url)}"
    if column_type == SOURCE_TYPE_NOTIFICATIONS:
        return f"{base}/notifications"
    if column_type == SOURCE_TYPE_LISTS:
        if source_url:
            if source_url.startswith("http"):
                if source_url.rstrip("/").endswith("/lists") or "/i/lists" in source_url:
                    return source_url
                return source_url.rstrip("/") + "/lists"
            if source_url.isdigit():
                return f"{base}/i/lists/{source_url}"
            if "/lists" in source_url:
                return f"{base}/{source_url.lstrip('/')}"
            return f"{base}/{source_url.strip('/')}/lists"
        return ""
    if column_type in (SOURCE_TYPE_FAVORITES, SOURCE_TYPE_SAVED, SOURCE_TYPE_LIKES, SOURCE_TYPE_BOOKMARKS):
        if source_url and source_url.startswith("http"):
            return source_url
        return FAVORITES_ENTRY_URL
    if column_type == SOURCE_TYPE_DIRECT_MESSAGES:
        if source_url and source_url.startswith("http"):
            return source_url
        return DM_ENTRY_URL
    if column_type == SOURCE_TYPE_GROK:
        if source_url and source_url.startswith("http") and "x.com" in source_url:
            return source_url
        return X_GROK_ENTRY_URL
    if column_type == SOURCE_TYPE_PROFILE:
        handle = (source_url or "").strip()
        if handle.startswith("http"):
            return handle
        if handle.startswith("@"):
            handle = handle[1:]
        if handle and " " not in handle and "/" not in handle and len(handle) <= 40:
            return f"{base}/{handle}"
        return ""

    if column_type == SOURCE_TYPE_BOOKMARKS:
        return SAVED_ENTRY_URL
    if column_type == SOURCE_TYPE_LIKES:
        return SAVED_ENTRY_URL
    if column_type == SOURCE_TYPE_MENTIONS:
        return f"{base}/notifications"
    if column_type == SOURCE_TYPE_LIST and source_url:
        if source_url.startswith("http"):
            return source_url
        return f"{base}/i/lists/{source_url}"
    if column_type == SOURCE_TYPE_USER and source_url:
        username = source_url.lstrip("@").rstrip("/")
        if username.startswith("http"):
            parsed = urlparse(username)
            parts = parsed.path.strip("/").split("/")
            if parts:
                username = parts[0]
        return f"{base}/{username}" if username else ""

    return account_initial_url or f"{base}/"

def default_column_title(column_type: str, account_display_name: str = "", source_url: str = "") -> str:
    column_type = migrate_column_type(column_type)
    if column_type == SOURCE_TYPE_HOME:
        return f"{account_display_name} ホーム" if account_display_name else "ホーム"
    if column_type == SOURCE_TYPE_URL:
        if source_url:
            parsed = urlparse(source_url)
            return parsed.netloc or source_url[:30]
        return "URL"
    if column_type == SOURCE_TYPE_SEARCH:
        return f"検索: {source_url}" if source_url else "検索"
    if column_type == SOURCE_TYPE_NOTIFICATIONS:
        return "通知"
    if column_type == SOURCE_TYPE_DIRECT_MESSAGES:
        return "ダイレクトメッセージ"
    if column_type == SOURCE_TYPE_GROK:
        return "Grok"
    if column_type == SOURCE_TYPE_LISTS:
        if source_url and not source_url.startswith("http"):
            return f"リスト {source_url}"
        return "リスト"
    if column_type in (SOURCE_TYPE_FAVORITES, SOURCE_TYPE_SAVED):
        return "お気に入り"
    if column_type == SOURCE_TYPE_PROFILE:
        return "プロフィール"
    if column_type == SOURCE_TYPE_BOOKMARKS:
        return "お気に入り"
    if column_type == SOURCE_TYPE_LIKES:
        return "お気に入り"
    if column_type == SOURCE_TYPE_MENTIONS:
        return "通知"
    if column_type == SOURCE_TYPE_USER:
        if source_url:
            username = source_url.lstrip("@").rstrip("/")
            if username.startswith("http"):
                parsed = urlparse(username)
                parts = parsed.path.strip("/").split("/")
                username = parts[-1] if parts else source_url
            return f"@{username}"
        return "プロフィール"
    return column_type

def source_type_needs_input(column_type: str) -> bool:
    return migrate_column_type(column_type) in _SOURCE_TYPES_NEEDING_INPUT

@dataclass(frozen=True)
class Account:

    account_id: str = ""
    display_name: str = ""
    profile_path: str = ""
    initial_url: str = "https://x.com/"

    def __post_init__(self) -> None:
        if not self.account_id:
            object.__setattr__(self, "account_id", str(uuid4()))

@dataclass
class Column:

    column_id: str = field(default_factory=lambda: str(uuid4()))
    column_type: str = SOURCE_TYPE_HOME
    source_account_id: str = ""
    source_url: str = ""
    title: str = ""
    position: int = 0
    width: int = 320

    def __post_init__(self) -> None:
        self.column_type = migrate_column_type(self.column_type)
